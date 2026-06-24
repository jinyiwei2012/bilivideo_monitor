"""
预测准确率回看面板 — 对比历史预测值 vs 实际播放量

展示每个预测时间点各算法的准确率，支持按算法筛选和时间范围选择。
"""
import logging
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
                        """SELECT timestamp, algorithm, algorithm_id, current_views, predicted_time, predicted_seconds
                           FROM predictions
                           WHERE target_threshold = ? AND timestamp >= ?
                           ORDER BY timestamp DESC""",
                        (threshold, cutoff),
                    )
                else:
                    cursor.execute(
                        """SELECT timestamp, algorithm, algorithm_id, current_views, predicted_time, predicted_seconds
                           FROM predictions
                           WHERE target_threshold = ?
                           ORDER BY timestamp DESC""",
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

        # 获取最新实际播放量
        history = self.gui.history_data.get(bvid, [])
        latest_views = history[-1][1] if history else 0

        # 填充表格
        self._table.setRowCount(len(rows))
        total_dev = 0.0
        count = 0

        for i, row in enumerate(rows):
            ts_str, algo, algo_id, predicted_views, predicted_time, predicted_seconds = row
            ts_display = ts_str[:16] if isinstance(ts_str, str) else str(ts_str)[:16]
            pred_val = predicted_views or 0

            # 计算偏差和准确率
            if latest_views > 0 and pred_val > 0:
                deviation = abs(pred_val - latest_views) / latest_views * 100
                accuracy = max(0, 100 - deviation)
                total_dev += deviation
                count += 1
                dev_text = f"{deviation:.1f}%"
                acc_text = f"{accuracy:.1f}%"
            else:
                dev_text = "—"
                acc_text = "—"

            items = [
                (ts_display, C["text_2"]),
                (algo or algo_id, C["text_1"]),
                (fmt_num(pred_val), C["bilibili"]),
                (fmt_num(latest_views), C["text_1"]),
                (dev_text, C["danger"] if deviation > 20 else C["success"]),
                (acc_text, C["success"] if accuracy > 80 else C["warning"] if accuracy > 50 else C["danger"]),
            ]
            for j, (text, color) in enumerate(items):
                item = QTableWidgetItem(text)
                item.setForeground(Qt.GlobalColor.white)
                self._table.setItem(i, j, item)

        if count > 0:
            avg_dev = total_dev / count
            self._summary_lbl.setText(
                f"共 {len(rows)} 条记录 | 平均偏差: {avg_dev:.1f}% | "
                f"平均准确率: {100 - avg_dev:.1f}% | 当前播放量: {fmt_num(latest_views)}"
            )
        else:
            self._summary_lbl.setText(f"共 {len(rows)} 条记录 | 当前播放量: {fmt_num(latest_views)}")
