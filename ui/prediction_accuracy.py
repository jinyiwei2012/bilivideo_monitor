"""
预测准确率回看面板 — 对比历史预测值 vs 实际播放量

展示每个预测时间点各算法的准确率，支持按算法筛选和时间范围选择。
通过查询 monitor_records 找到预测到达时间点的实际播放量，与 target_threshold 对比计算偏差。
"""
import logging
from bisect import bisect_left
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QComboBox, QHeaderView,
    QMessageBox, QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from ui.theme import C
from ui.helpers import FONT, FONT_MONO, fmt_num
from ui.dialog_base import DialogBase

logger = logging.getLogger(__name__)


class PredictionAccuracyPanel:
    """预测准确率回看面板"""

    def __init__(self, parent, gui):
        self.gui = gui
        self.dlg = DialogBase(parent, "预测准确率回看", "1000x700")

        self._build_ui()
        self._refresh()

    def _build_ui(self):
        content = self.dlg.content_area()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 控件栏
        ctrl = QWidget()
        ctrl.setStyleSheet(f"background-color: {C['bg_base']};")
        ch = QHBoxLayout(ctrl)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(8)

        ch.addWidget(QLabel("视频:"))
        self._video_combo = QComboBox()
        self._video_combo.setMinimumWidth(200)
        self._video_combo.currentIndexChanged.connect(self._refresh)
        ch.addWidget(self._video_combo)

        ch.addWidget(QLabel("阈值:"))
        self._thresh_combo = QComboBox()
        self._thresh_combo.addItems(["10万", "100万", "1000万"])
        self._thresh_combo.currentIndexChanged.connect(self._refresh)
        ch.addWidget(self._thresh_combo)

        ch.addWidget(QLabel("天数:"))
        self._days_combo = QComboBox()
        self._days_combo.addItems(["7天", "14天", "30天", "全部"])
        self._days_combo.setCurrentIndex(0)
        self._days_combo.currentIndexChanged.connect(self._refresh)
        ch.addWidget(self._days_combo)

        ch.addStretch()

        refresh_btn = QPushButton("⟳ 刷新")
        refresh_btn.clicked.connect(self._refresh)
        ch.addWidget(refresh_btn)

        layout.addWidget(ctrl)

        # 统计摘要
        self._summary_lbl = QLabel("")
        self._summary_lbl.setStyleSheet(f"color: {C['text_2']}; font-size: 10pt; padding: 4px 0;")
        layout.addWidget(self._summary_lbl)

        # 准确率表格
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(["预测时间", "算法", "预测值", "实际值", "偏差", "准确率"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {C['bg_elevated']}; color: {C['text_1']};
                border: 1px solid {C['border']}; gridline-color: {C['border_sub']};
                font-family: Consolas; font-size: 10pt;
            }}
            QHeaderView::section {{
                background-color: {C['bg_surface']}; color: {C['text_2']};
                border: none; padding: 6px; font-size: 9pt; font-weight: bold;
            }}
        """)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table, 1)

    def _refresh(self):
        self._populate_videos()
        self._load_data()

    def _populate_videos(self):
        current = self._video_combo.currentData()
        self._video_combo.blockSignals(True)
        self._video_combo.clear()
        for v in self.gui.monitored_videos:
            bvid = v.get("bvid", "")
            title = v.get("title", bvid)[:30]
            self._video_combo.addItem(f"{bvid} {title}", bvid)
        if current:
            idx = self._video_combo.findData(current)
            if idx >= 0:
                self._video_combo.setCurrentIndex(idx)
        self._video_combo.blockSignals(False)

    def _load_data(self):
        bvid = self._video_combo.currentData()
        if not bvid:
            self._summary_lbl.setText("请选择视频")
            self._table.setRowCount(0)
            return

        thresholds = [100000, 1000000, 10000000]
        threshold = thresholds[self._thresh_combo.currentIndex()]
        days_map = {"7天": 7, "14天": 14, "30天": 30, "全部": 9999}
        days = days_map[self._days_combo.currentText()]

        vdb = self.gui.video_dbs.get(bvid)
        if not vdb:
            self._summary_lbl.setText("无数据库")
            self._table.setRowCount(0)
            return

        try:
            with vdb._get_connection() as conn:
                cursor = conn.cursor()
                if days < 9999:
                    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
                    cursor.execute(
                        """SELECT created_at, algorithm, algorithm_id, current_views,
                                  predicted_time, predicted_seconds, target_threshold
                           FROM predictions
                           WHERE target_threshold = ? AND created_at >= ?
                           ORDER BY created_at DESC""",
                        (threshold, cutoff),
                    )
                else:
                    cursor.execute(
                        """SELECT created_at, algorithm, algorithm_id, current_views,
                                  predicted_time, predicted_seconds, target_threshold
                           FROM predictions
                           WHERE target_threshold = ?
                           ORDER BY created_at DESC""",
                        (threshold,),
                    )
                rows = cursor.fetchall()
        except Exception as e:
            logger.warning("查询预测记录失败: %s", e)
            self._summary_lbl.setText(f"查询失败: {e}")
            self._table.setRowCount(0)
            return

        if not rows:
            self._summary_lbl.setText("暂无预测记录")
            self._table.setRowCount(0)
            return

        # 加载 monitor_records 用于查找预测到达时点的实际播放量
        records = vdb.get_all_records()
        if not records:
            self._summary_lbl.setText("无监控记录，无法计算准确率")
            self._table.setRowCount(0)
            return

        # 构建时间戳列表和对应的播放量（用于二分查找）
        # monitor_records timestamps 可能是 ISO 字符串或 datetime 对象
        _rec_timestamps = []
        _rec_views = []
        for r in records:
            ts = r.get("timestamp", "")
            vc = r.get("view_count", 0) or 0
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                except (ValueError, TypeError):
                    continue
            elif isinstance(ts, datetime):
                pass
            else:
                continue
            _rec_timestamps.append(ts)
            _rec_views.append(vc)
        if not _rec_timestamps:
            self._summary_lbl.setText("监控记录时间戳解析失败")
            self._table.setRowCount(0)
            return

        # 当前最新播放量（用于摘要显示）
        latest_views = _rec_views[-1] if _rec_views else 0

        # 填充表格
        self._table.setRowCount(len(rows))
        total_dev = 0.0
        count = 0
        skipped_future = 0

        for i, row in enumerate(rows):
            ts_created, algo, algo_id, current_views, predicted_time, predicted_seconds, target_threshold = row
            ts_display = ts_created[:16] if isinstance(ts_created, str) else str(ts_created)[:16]

            # 解析 prediction 创建时间
            if isinstance(ts_created, str):
                try:
                    pred_ts = datetime.fromisoformat(ts_created)
                except (ValueError, TypeError):
                    pred_ts = None
            elif isinstance(ts_created, datetime):
                pred_ts = ts_created
            else:
                pred_ts = None

            if pred_ts is None:
                dev_text = "—"
                acc_text = "时间错误"
                actual_views_display = "—"
                self._set_row(i, ts_display, algo or algo_id, fmt_num(current_views or 0),
                              actual_views_display, dev_text, acc_text, 0)
                continue

            # 预测的到达时间
            predicted_arrival = pred_ts + timedelta(seconds=(predicted_seconds or 0))

            # 二分查找 monitor_records 中最接近 predicted_arrival 的记录
            idx = bisect_left(_rec_timestamps, predicted_arrival)
            if idx >= len(_rec_timestamps):
                # 预测到达时间在所有监控记录之后 → 尚未到达
                actual_views = _rec_views[-1]
                actual_views_display = f"{fmt_num(actual_views)} (未到)"
                skipped_future += 1
            elif idx == 0:
                actual_views = _rec_views[0]
                actual_views_display = fmt_num(actual_views)
            else:
                # 选择更接近的那个记录
                before_ts = _rec_timestamps[idx - 1]
                after_ts = _rec_timestamps[idx]
                if abs((after_ts - predicted_arrival).total_seconds()) < abs(
                    (predicted_arrival - before_ts).total_seconds()
                ):
                    actual_views = _rec_views[idx]
                else:
                    actual_views = _rec_views[idx - 1]
                actual_views_display = fmt_num(actual_views)

            # 计算偏差和准确率：对比 target_threshold vs actual_views
            target = target_threshold or threshold
            if target > 0 and actual_views > 0:
                deviation = abs(actual_views - target) / target * 100
                accuracy = max(0, 100 - deviation)
                total_dev += deviation
                count += 1
                dev_text = f"{deviation:.1f}%"
                acc_text = f"{accuracy:.1f}%"
            else:
                dev_text = "—"
                acc_text = "—"

            self._set_row(i, ts_display, algo or algo_id, fmt_num(current_views or 0),
                          actual_views_display, dev_text, acc_text,
                          deviation if target > 0 and actual_views > 0 else 0)

        if count > 0:
            avg_dev = total_dev / count
            extra = f" | {skipped_future} 条预测尚未到达" if skipped_future > 0 else ""
            self._summary_lbl.setText(
                f"共 {len(rows)} 条记录 | 平均偏差: {avg_dev:.1f}% | "
                f"平均准确率: {100 - avg_dev:.1f}% | 当前播放量: {fmt_num(latest_views)}{extra}"
            )
        else:
            self._summary_lbl.setText(
                f"共 {len(rows)} 条记录 | 当前播放量: {fmt_num(latest_views)}"
                + (f" | {skipped_future} 条未到达" if skipped_future > 0 else "")
            )

    def _set_row(self, row_idx, ts_display, algo, pred_views, actual_views, dev_text, acc_text, deviation):
        """填充表格的一行"""
        items = [
            (ts_display, C["text_2"]),
            (algo, C["text_1"]),
            (pred_views, C["bilibili"]),
            (actual_views, C["text_1"]),
            (dev_text, C["danger"] if deviation > 20 else C["success"]),
            (acc_text, C["success"] if (100 - deviation) > 80 else C["warning"] if (100 - deviation) > 50 else C["danger"]),
        ]
        for j, (text, color) in enumerate(items):
            item = QTableWidgetItem(text)
            item.setForeground(Qt.GlobalColor.white)
            self._table.setItem(row_idx, j, item)
