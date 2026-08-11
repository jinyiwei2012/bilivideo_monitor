"""
时段播放模式分析面板

分析视频的周期性播放模式：按小时/星期聚合展示平均播放增量热力图。
支持多视频对比，发现各视频的最佳发布时间段。
"""
import logging
from datetime import datetime
from collections import defaultdict

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QFrame, QScrollArea,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor

from ui.theme import C
from ui.helpers import FONT, FONT_MONO, fmt_num
from ui.dialog_base import DialogBase

logger = logging.getLogger(__name__)

_HEAT_COLORS = ["#0d1117", "#0e4429", "#006d32", "#26a641", "#39d353"]


def _heat_color(ratio: float) -> str:
    """根据比率(0-1)返回热力图颜色"""
    if ratio <= 0:
        return _HEAT_COLORS[0]
    idx = min(len(_HEAT_COLORS) - 1, int(ratio * (len(_HEAT_COLORS) - 1)))
    return _HEAT_COLORS[idx]


class TimeAnalysisPanel:
    """时段分析面板 — 按小时/星期聚合展示播放增量"""

    def __init__(self, parent, gui):
        self.gui = gui
        self.dlg = DialogBase(parent, "♪ 时段播放分析", "1100x700")
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
        ch.addWidget(self._video_combo)

        ch.addWidget(QLabel("模式:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["按小时 (24h)", "按星期 (7天)", "按小时+星期 (热力图)"])
        ch.addWidget(self._mode_combo)

        self._analyze_btn = QPushButton("⌕ 分析 ♪")
        self._analyze_btn.clicked.connect(self._refresh)
        ch.addWidget(self._analyze_btn)

        ch.addStretch()

        self._summary_lbl = QLabel("")
        self._summary_lbl.setStyleSheet(f"color: {C['text_2']}; font-size: 10pt;")
        ch.addWidget(self._summary_lbl)

        layout.addWidget(ctrl)

        # 热力图表格
        self._table = QTableWidget()
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
        self._table.setAlternatingRowColors(False)
        layout.addWidget(self._table, 1)

    def _refresh(self):
        self._populate_videos()
        self._analyze()

    def _populate_videos(self):
        self._video_combo.blockSignals(True)
        self._video_combo.clear()
        for v in self.gui.monitored_videos:
            bvid = v.get("bvid", "")
            self._video_combo.addItem(f"{bvid} {v.get('title', bvid)[:25]}", bvid)
        self._video_combo.blockSignals(False)

    def _analyze(self):
        mode = self._mode_combo.currentIndex()

        if mode == 0:
            self._analyze_hourly()
        elif mode == 1:
            self._analyze_weekly()
        else:
            self._analyze_heatmap()

    def _get_history(self):
        bvid = self._video_combo.currentData()
        if not bvid:
            return None, []
        return bvid, self.gui.history_data.get(bvid, [])

    def _analyze_hourly(self):
        """按小时聚合 24 列"""
        bvid, history = self._get_history()
        if not history or len(history) < 2:
            self._summary_lbl.setText("数据还不够呢…再多攒一些,天依就能听出规律啦 ♪")
            self._table.setRowCount(0)
            return

        hourly_delta = defaultdict(float)
        hourly_count = defaultdict(int)

        for i in range(1, len(history)):
            ts = history[i][0]
            v1 = history[i - 1][1]
            v2 = history[i][1]
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                except Exception:
                    continue
            hour = ts.hour
            delta = max(0, v2 - v1) if isinstance(v1, (int, float)) and isinstance(v2, (int, float)) else 0
            hourly_delta[hour] += delta
            hourly_count[hour] += 1

        self._table.setRowCount(2)
        self._table.setColumnCount(24)
        self._table.setHorizontalHeaderLabels([f"{h}:00" for h in range(24)])
        self._table.setVerticalHeaderLabels(["平均增量", "采样数"])

        for h in range(24):
            avg = hourly_delta[h] / max(hourly_count[h], 1)
            self._table.setItem(0, h, QTableWidgetItem(fmt_num(int(avg))))
            self._table.setItem(1, h, QTableWidgetItem(str(hourly_count[h])))

        total_avg = sum(hourly_delta.values()) / max(sum(hourly_count.values()), 1)
        peak_hour = max(range(24), key=lambda h: hourly_delta[h] / max(hourly_count[h], 1))
        self._summary_lbl.setText(
            f"♪ 总采样 {len(history)} 点 | 时均增量 {fmt_num(int(total_avg))} | 高峰时段: {peak_hour}:00"
        )

    def _analyze_weekly(self):
        """按星期聚合 7 列"""
        bvid, history = self._get_history()
        if not history or len(history) < 2:
            self._summary_lbl.setText("数据还不够呢…再多攒一些,天依就能听出规律啦 ♪")
            self._table.setRowCount(0)
            return

        days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        daily_delta = defaultdict(float)
        daily_count = defaultdict(int)

        for i in range(1, len(history)):
            ts = history[i][0]
            v1 = history[i - 1][1]
            v2 = history[i][1]
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                except Exception:
                    continue
            dow = ts.weekday()
            delta = max(0, v2 - v1) if isinstance(v1, (int, float)) and isinstance(v2, (int, float)) else 0
            daily_delta[dow] += delta
            daily_count[dow] += 1

        self._table.setRowCount(2)
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(days)
        self._table.setVerticalHeaderLabels(["平均增量", "采样数"])

        for d in range(7):
            avg = daily_delta[d] / max(daily_count[d], 1)
            self._table.setItem(0, d, QTableWidgetItem(fmt_num(int(avg))))
            self._table.setItem(1, d, QTableWidgetItem(str(daily_count[d])))

        peak_day = max(range(7), key=lambda d: daily_delta[d] / max(daily_count[d], 1))
        self._summary_lbl.setText(f"♪ 高峰日: {days[peak_day]}")

    def _analyze_heatmap(self):
        """按小时×星期热力图"""
        bvid, history = self._get_history()
        if not history or len(history) < 2:
            self._summary_lbl.setText("数据还不够呢…再多攒一些,天依就能听出规律啦 ♪")
            self._table.setRowCount(0)
            return

        days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        heat_data = defaultdict(lambda: defaultdict(float))
        heat_count = defaultdict(lambda: defaultdict(int))

        for i in range(1, len(history)):
            ts = history[i][0]
            v1 = history[i - 1][1]
            v2 = history[i][1]
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                except Exception:
                    continue
            hour, dow = ts.hour, ts.weekday()
            delta = max(0, v2 - v1) if isinstance(v1, (int, float)) and isinstance(v2, (int, float)) else 0
            heat_data[dow][hour] += delta
            heat_count[dow][hour] += 1

        # 计算全局最大值用于归一化
        max_val = 0
        for dow in range(7):
            for h in range(24):
                val = heat_data[dow][h] / max(heat_count[dow][h], 1)
                if val > max_val:
                    max_val = val

        self._table.setRowCount(7)
        self._table.setColumnCount(24)
        self._table.setHorizontalHeaderLabels([f"{h}h" for h in range(24)])
        self._table.setVerticalHeaderLabels(days)
        self._table.setRowHeight(0, 40)

        for dow in range(7):
            for h in range(24):
                val = heat_data[dow][h] / max(heat_count[dow][h], 1)
                ratio = val / max(max_val, 1)
                color = _heat_color(ratio)
                item = QTableWidgetItem(fmt_num(int(val)))
                item.setBackground(QColor(color))
                if ratio > 0.5:
                    item.setForeground(QColor("#ffffff"))
                self._table.setItem(dow, h, item)

        self._summary_lbl.setText("♪ 热力图 — 颜色越亮,该时段的播放声浪越高哦")
