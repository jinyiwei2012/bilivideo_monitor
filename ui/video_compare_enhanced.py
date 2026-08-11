"""
视频对比增强面板

三个标签页：同期对比、增速排名、预测一致性
"""
import logging
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QFrame, QComboBox,
)
from PyQt6.QtCore import Qt

from ui.theme import C
from ui.helpers import FONT, FONT_MONO, fmt_num, THRESHOLDS, THRESHOLD_NAMES
from ui.dialog_base import DialogBase
from utils.time_utils import safe_timestamp

logger = logging.getLogger(__name__)


class VideoCompareEnhanced:
    """视频对比增强面板"""

    def __init__(self, parent, gui):
        self.gui = gui
        self.dlg = DialogBase(parent, "视频对比增强", "1000x700")
        self._build_ui()
        self._refresh_all()

    def _build_ui(self):
        content = self.dlg.content_area()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{ background-color: {C['bg_base']}; border: none; }}
            QTabBar::tab {{ background-color: {C['bg_surface']}; color: {C['text_2']};
                padding: 8px 14px; border: none; font-size: 10pt; }}
            QTabBar::tab:selected {{ color: {C['bilibili']}; border-bottom: 2px solid {C['bilibili']}; }}
        """)

        self._build_peer_tab()
        self._build_velocity_tab()
        self._build_consistency_tab()

        layout.addWidget(self._tabs)

    # ── 同期对比 ──
    def _build_peer_tab(self):
        tab = QWidget()
        ol = QVBoxLayout(tab)
        ol.setContentsMargins(16, 12, 16, 12)
        ol.setSpacing(8)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("天数:"))
        self._peer_days = QComboBox()
        self._peer_days.addItems(["1天", "3天", "7天", "14天", "30天"])
        self._peer_days.setCurrentIndex(2)
        self._peer_days.currentIndexChanged.connect(self._refresh_peer)
        ctrl.addWidget(self._peer_days)
        ctrl.addStretch()
        self._peer_btn = QPushButton("⟳ 刷新")
        self._peer_btn.clicked.connect(self._refresh_peer)
        ctrl.addWidget(self._peer_btn)
        ol.addLayout(ctrl)

        self._peer_table = QTableWidget()
        self._peer_table.setColumnCount(4)
        self._peer_table.setHorizontalHeaderLabels(["视频", "当前播放量", "同期增量", "日均增速"])
        self._peer_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        ol.addWidget(self._peer_table, 1)

        self._tabs.addTab(tab, "◧ 同期对比")

    def _refresh_peer(self):
        days_map = {"1天": 1, "3天": 3, "7天": 7, "14天": 14, "30天": 30}
        days = days_map.get(self._peer_days.currentText(), 7)
        cutoff = datetime.now() - timedelta(days=days)
        rows = []

        for v in self.gui.monitored_videos:
            bvid = v.get("bvid", "")
            title = v.get("title", bvid)[:30]
            views = v.get("view_count", 0)
            history = self.gui.history_data.get(bvid, [])
            # 找最接近 cutoff 的历史记录
            base_views = views
            for ts, vc in reversed(history):
                t = safe_timestamp(ts)
                if isinstance(t, (int, float)):
                    t = datetime.fromtimestamp(t)
                if t < cutoff:
                    base_views = vc
                    break
            delta = max(0, views - base_views) if isinstance(base_views, (int, float)) else 0
            daily = delta / days if days > 0 else 0
            rows.append((bvid, title, views, delta, daily))

        rows.sort(key=lambda r: r[3], reverse=True)
        self._peer_table.setRowCount(len(rows))
        for i, (bvid, title, views, delta, daily) in enumerate(rows):
            items = [
                (f"{bvid} {title}", C["text_1"]),
                (fmt_num(views), C["bilibili"]),
                (fmt_num(delta), C["success"] if delta > 0 else C["text_2"]),
                (fmt_num(int(daily)), C["accent"]),
            ]
            for j, (text, _) in enumerate(items):
                self._peer_table.setItem(i, j, QTableWidgetItem(text))

    # ── 增速排名 ──
    def _build_velocity_tab(self):
        tab = QWidget()
        ol = QVBoxLayout(tab)
        ol.setContentsMargins(16, 12, 16, 12)
        ol.setSpacing(8)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("时间窗口:"))
        self._vel_window = QComboBox()
        self._vel_window.addItems(["1小时", "6小时", "24小时"])
        self._vel_window.setCurrentIndex(2)
        self._vel_window.currentIndexChanged.connect(self._refresh_velocity)
        ctrl.addWidget(self._vel_window)
        ctrl.addStretch()
        self._vel_btn = QPushButton("⟳ 刷新")
        self._vel_btn.clicked.connect(self._refresh_velocity)
        ctrl.addWidget(self._vel_btn)
        ol.addLayout(ctrl)

        self._vel_table = QTableWidget()
        self._vel_table.setColumnCount(5)
        self._vel_table.setHorizontalHeaderLabels(["排名", "视频", "播放量", "时段增量", "时均增量"])
        self._vel_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        ol.addWidget(self._vel_table, 1)

        self._tabs.addTab(tab, "♬ 增速排名")

    def _refresh_velocity(self):
        hours_map = {"1小时": 1, "6小时": 6, "24小时": 24}
        hours = hours_map.get(self._vel_window.currentText(), 24)
        cutoff = datetime.now() - timedelta(hours=hours)
        rows = []

        for v in self.gui.monitored_videos:
            bvid = v.get("bvid", "")
            title = v.get("title", bvid)[:30]
            views = v.get("view_count", 0)
            history = self.gui.history_data.get(bvid, [])
            base_views = views
            actual_hours = 0
            for ts, vc in reversed(history):
                t = safe_timestamp(ts)
                if isinstance(t, (int, float)):
                    t = datetime.fromtimestamp(t)
                if t < cutoff:
                    base_views = vc
                    base_t = t  # 记录 cutoff 边界处的时间点
                    if len(history) >= 2:
                        latest_t = safe_timestamp(history[-1][0])
                        if isinstance(latest_t, (int, float)):
                            latest_t = datetime.fromtimestamp(latest_t)
                        actual_hours = (latest_t - base_t).total_seconds() / 3600
                    break
            delta = max(0, views - base_views) if isinstance(base_views, (int, float)) else 0
            hourly = delta / max(actual_hours, 0.1)
            rows.append((bvid, title, views, delta, hourly))

        rows.sort(key=lambda r: r[3], reverse=True)
        self._vel_table.setRowCount(len(rows))
        for i, (bvid, title, views, delta, hourly) in enumerate(rows):
            items = [
                (f"#{i + 1}", C["text_2"]),
                (f"{bvid} {title}", C["text_1"]),
                (fmt_num(views), C["bilibili"]),
                (fmt_num(delta), C["success"]),
                (fmt_num(int(hourly)), C["accent"]),
            ]
            for j, (text, _) in enumerate(items):
                self._vel_table.setItem(i, j, QTableWidgetItem(text))

    # ── 预测一致性 ──
    def _build_consistency_tab(self):
        tab = QWidget()
        ol = QVBoxLayout(tab)
        ol.setContentsMargins(16, 12, 16, 12)
        ol.setSpacing(8)

        ctrl = QHBoxLayout()
        ctrl.addStretch()
        self._con_btn = QPushButton("⟳ 刷新")
        self._con_btn.clicked.connect(self._refresh_consistency)
        ctrl.addWidget(self._con_btn)
        ol.addLayout(ctrl)

        self._con_summary = QLabel("")
        self._con_summary.setStyleSheet(f"color: {C['text_2']}; font-size: 10pt; padding: 4px 0;")
        ol.addWidget(self._con_summary)

        self._con_table = QTableWidget()
        self._con_table.setColumnCount(4)
        self._con_table.setHorizontalHeaderLabels(["视频", "算法数", "平均预测(h)", "标准差(h)"])
        self._con_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        ol.addWidget(self._con_table, 1)

        self._tabs.addTab(tab, "◎ 预测一致性")

    def _refresh_consistency(self):
        import numpy as np
        rows = []

        for v in self.gui.monitored_videos:
            bvid = v.get("bvid", "")
            title = v.get("title", bvid)[:30]
            preds = self.gui.prediction_results.get(bvid, {})
            results = preds.get("results", [])
            if not results:
                continue
            hours_list = []
            for r in results:
                h = r.get("predicted_hours", 0)
                if h and h != float("inf") and h < 87600:  # < 10 years
                    hours_list.append(h)
            if len(hours_list) < 2:
                continue
            arr = np.array(hours_list)
            avg_h = float(np.mean(arr))
            std_h = float(np.std(arr))
            cv = std_h / max(avg_h, 1) * 100
            rows.append((bvid, title, len(hours_list), avg_h, std_h, cv))

        rows.sort(key=lambda r: r[5])  # 按变异系数排序（越小越一致）

        self._con_table.setRowCount(len(rows))
        for i, (bvid, title, count, avg_h, std_h, _) in enumerate(rows):
            items = [
                (f"{bvid} {title}", C["text_1"]),
                (str(count), C["accent"]),
                (f"{avg_h:.1f}", C["bilibili"]),
                (f"{std_h:.1f}", C["warning"]),
            ]
            for j, (text, _) in enumerate(items):
                self._con_table.setItem(i, j, QTableWidgetItem(text))

        if rows:
            best = rows[0]
            worst = rows[-1]
            self._con_summary.setText(
                f"最一致: {best[1][:15]} (CV={best[5]:.1f}%) | "
                f"最分歧: {worst[1][:15]} (CV={worst[5]:.1f}%) | "
                f"共 {len(rows)} 个视频有预测结果"
            )

    def _refresh_all(self):
        self._refresh_peer()
        self._refresh_velocity()
        self._refresh_consistency()
