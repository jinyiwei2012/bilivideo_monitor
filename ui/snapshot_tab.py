"""
快照对比标签页 - 柱状图对比 (PyQt6 版)
"""

import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QCheckBox, QLineEdit,
    QFrame, QSizePolicy, QMessageBox, QScrollBar,
    QGroupBox,
)
from PyQt6.QtCore import Qt, QRect, QTimer
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QFont, QBrush, QFontMetrics,
)

from core.database import get_db
from ui.theme import C
from .data_comparison import (
    _fmt,
    _parse_dt,
    PALETTE,
    METRICS,
    _BAR_ML,
    _BAR_MR,
    _BAR_MT,
    _BAR_MB,
    _blend,
    _darken,
)

_bar_snap_logger = logging.getLogger("data_comparison.snapshot")


class SnapshotBarChart(QWidget):
    """自定义柱状图控件 — 使用 QPainter 绘制快照对比柱状图"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._data: Optional[dict] = None  # all_metric_bars after layout
        self._chosen_metrics: List[str] = []
        self._selected_videos: List[Dict] = []
        self._use_milestone = False
        self._placeholder = ""
        self._scroll_offset = 0

    def set_chart_data(
        self, all_metric_bars, chosen_metrics, selected_videos, use_milestone
    ):
        self._data = all_metric_bars
        self._chosen_metrics = chosen_metrics
        self._selected_videos = selected_videos
        self._use_milestone = use_milestone
        self._placeholder = ""
        self.update()

    def set_placeholder(self, text: str):
        self._placeholder = text
        self._data = None
        self.update()

    def paintEvent(self, a0):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        W = self.width()
        H = self.height()
        bg = QColor(C.get("canvas_bg", "#0d1117"))
        painter.fillRect(QRect(0, 0, W, H), bg)

        if self._placeholder:
            painter.setPen(QColor(C.get("text_2", "#8b949e")))
            font = QFont("Microsoft YaHei UI", 12)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            tw = metrics.horizontalAdvance(self._placeholder)
            painter.drawText((W - tw) // 2, H // 2, self._placeholder)
            painter.end()
            return

        if not self._data or not self._chosen_metrics:
            painter.end()
            return

        chosen_metrics = self._chosen_metrics
        n_metrics = len(chosen_metrics)
        if n_metrics == 0:
            painter.end()
            return

        section_H = H / n_metrics
        if section_H < 80:
            section_H = 80

        # calculate layout dimensions
        all_section_widths = []
        metric_data_map: Dict[str, dict] = {}

        bvid_order = [v.get("bvid", "") for v in self._selected_videos]

        for m_idx, metric in enumerate(chosen_metrics):
            bars = self._data.get(metric, [])
            if not isinstance(bars, list) or not bars:
                all_section_widths.append(0)
                continue

            groups = []
            seen = set()
            for bv in bvid_order:
                if bv in seen:
                    continue
                seen.add(bv)
                g_bars = [b for b in bars if b["bvid"] == bv]
                if g_bars:
                    groups.append({"bvid": bv, "title": g_bars[0]["title"], "bars": g_bars})

            total_bars = len(bars)
            BAR_W = max(20, min(50, 700 // max(total_bars, 1)))
            GROUP_GAP = max(BAR_W, 20)
            inner_gap = max(2, BAR_W // 8)

            group_widths = [len(g["bars"]) * (BAR_W + inner_gap) - inner_gap for g in groups]
            sec_W = sum(group_widths) + GROUP_GAP * (len(groups) - 1) + GROUP_GAP + _BAR_MR
            all_section_widths.append(sec_W)

            metric_data_map[metric] = {
                "groups": groups,
                "BAR_W": BAR_W,
                "GROUP_GAP": GROUP_GAP,
                "inner_gap": inner_gap,
                "group_widths": group_widths,
                "total_bars": total_bars,
            }

        max_section_W = max(all_section_widths) if all_section_widths else 500
        real_W = max(_BAR_ML + max_section_W + 10, W)

        painter.setClipRect(0, 0, W, H)

        y_offset = 0
        legend_added: set = set()

        for m_idx, metric in enumerate(chosen_metrics):
            metric_label = next((lb for k, lb in METRICS if k == metric), metric)
            data = metric_data_map.get(metric)
            if data is None:
                y_offset += section_H
                continue

            groups = data["groups"]
            BAR_W = data["BAR_W"]
            GROUP_GAP = data["GROUP_GAP"]
            inner_gap = data["inner_gap"]

            if not groups:
                y_offset += section_H
                continue

            sec_y0 = y_offset
            chart_H = section_H - _BAR_MT - _BAR_MB
            if chart_H < 60:
                chart_H = 60

            all_vals = [b["value"] for g in groups for b in g["bars"] if b["value"] is not None]
            if not all_vals:
                y_offset += section_H
                continue
            max_val = max(all_vals) * 1.12 or 1

            def val_to_y(v, _sy0=sec_y0, _ch=chart_H, _mv=max_val):
                return _sy0 + _BAR_MT + _ch - max(0, v) / _mv * _ch

            # divider
            if m_idx > 0:
                pen = QPen(QColor(C.get("border", "#30363d")))
                pen.setDashPattern([6, 4])
                painter.setPen(pen)
                painter.drawLine(_BAR_ML, int(sec_y0), int(_BAR_ML + max_section_W), int(sec_y0))

            # grid + Y axis
            n_grid = 4
            grid_pen = QPen(QColor(C.get("grid_line", "#21262d")))
            grid_pen.setDashPattern([2, 4])
            label_font = QFont("Consolas", 8)
            for i in range(n_grid + 1):
                ratio = i / n_grid
                y = sec_y0 + _BAR_MT + chart_H * (1 - ratio)
                val = max_val * ratio
                painter.setPen(grid_pen)
                painter.drawLine(_BAR_ML, int(y), int(_BAR_ML + max_section_W), int(y))
                painter.setPen(QColor(C.get("text_2", "#8b949e")))
                painter.setFont(label_font)
                painter.drawText(0, int(y - 6), int(_BAR_ML - 4), 14, Qt.AlignmentFlag.AlignRight.value, _fmt(val))

            # metric title
            title_font = QFont("Microsoft YaHei UI", 10)
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.setPen(QColor(C.get("text_1", "#e6edf3")))
            painter.drawText(int(_BAR_ML + 10), int(sec_y0 + _BAR_MT // 2 + 4), metric_label)

            # X axis line
            painter.setPen(QPen(QColor(C.get("text_2", "#8b949e"))))
            painter.drawLine(_BAR_ML, int(sec_y0 + _BAR_MT + chart_H), int(_BAR_ML + max_section_W), int(sec_y0 + _BAR_MT + chart_H))

            # draw bars
            x_cursor = _BAR_ML + GROUP_GAP // 2
            for g_idx, group in enumerate(groups):
                bvid = group["bvid"]
                title = group["title"]
                bars = group["bars"]
                g_color = QColor(PALETTE[g_idx % len(PALETTE)])

                g_center = x_cursor + (len(bars) * (BAR_W + inner_gap) - inner_gap) // 2
                painter.setPen(g_color)
                name_font = QFont("Microsoft YaHei UI", 8)
                name_font.setBold(True)
                painter.setFont(name_font)
                painter.drawText(int(g_center - 50), int(sec_y0 + section_H - _BAR_MB + 8), 100, 16, Qt.AlignmentFlag.AlignCenter.value, f"{title}")

                for b_idx, bar in enumerate(bars):
                    val = bar["value"] or 0
                    ts_lbl = bar["ts"]
                    source = bar["source"]

                    hex_color = PALETTE[g_idx % len(PALETTE)]
                    if source == "milestone":
                        bar_color = QColor(_darken(hex_color, 0.75))
                        bar_color2 = QColor(_darken(hex_color, 0.55))
                    else:
                        ratio = b_idx / max(len(bars) - 1, 1)
                        bar_color = QColor(_blend(hex_color, "#ffffff", 0.15 + ratio * 0.2))
                        bar_color2 = QColor(hex_color)

                    x0 = x_cursor
                    x1 = x0 + BAR_W
                    y0 = val_to_y(val)
                    y1 = sec_y0 + _BAR_MT + chart_H

                    # draw rounded rect bar
                    r = min(3, max(1, BAR_W * 0.15))
                    painter.setBrush(QBrush(bar_color2))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawRoundedRect(int(x0), int(y0), int(BAR_W), int(y1 - y0), int(r), int(r))

                    # highlight top
                    top_h = max(2, (y1 - y0) * 0.08)
                    painter.setBrush(QBrush(bar_color))
                    painter.drawRoundedRect(int(x0), int(y0), int(BAR_W), int(top_h + r * 2), int(r), int(r))

                    if val > 0:
                        painter.setPen(QColor(C.get("text_1", "#e6edf3")))
                        val_font = QFont("Consolas", 7)
                        val_font.setBold(True)
                        painter.setFont(val_font)
                        painter.drawText(
                            int(x0), int(max(y0 - 14, sec_y0 + _BAR_MT)),
                            int(BAR_W), 14,
                            Qt.AlignmentFlag.AlignCenter.value,
                            _fmt(val),
                        )

                    short_ts = ts_lbl[-5:] if len(ts_lbl) > 5 else ts_lbl
                    if source == "milestone":
                        short_ts = ts_lbl.replace("里程碑·", "")
                    painter.setPen(QColor(C.get("text_2", "#8b949e")))
                    ts_font = QFont("Consolas", 7)
                    painter.setFont(ts_font)
                    painter.drawText(
                        int(x0), int(sec_y0 + _BAR_MT + chart_H + 4),
                        int(BAR_W), 14,
                        Qt.AlignmentFlag.AlignCenter.value,
                        short_ts,
                    )

                    x_cursor += BAR_W + inner_gap

                x_cursor += GROUP_GAP

                # legend
                if m_idx == 0 and bvid not in legend_added:
                    legend_added.add(bvid)

            y_offset += section_H

        # milestone legend hint
        if self._use_milestone:
            painter.setPen(QColor(C.get("text_2", "#8b949e")))
            hint_font = QFont("Microsoft YaHei UI", 8)
            painter.setFont(hint_font)
            painter.drawText(int(_BAR_ML), int(y_offset + 10), "■ 里程碑（深色柱）")

        painter.end()


class SnapshotTab(QWidget):
    """快照对比标签页 (PyQt6 版)"""

    def __init__(self, parent, monitored_videos, video_dbs):
        super().__init__(parent)
        self._monitored_videos = monitored_videos
        self._video_dbs = video_dbs

        self._selected: List[Dict] = []
        self._points: Dict[str, List] = {}
        self._chosen_ts: Dict[str, List[str]] = {}
        self._ts_avail: List[str] = []
        self._ts_displayed: List[str] = []
        self._chosen_metrics_cache: Optional[List[str]] = None
        self._metric_checks: Dict[str, bool] = {key: (key == "view_count") for key, _ in METRICS}
        self._use_milestone = True

        self._listbox: QListWidget = QListWidget()
        self._ts_listbox: QListWidget = QListWidget()
        self._chart: SnapshotBarChart = SnapshotBarChart()
        self._start_entry: QLineEdit = QLineEdit()
        self._end_entry: QLineEdit = QLineEdit()
        self._status: QLabel = QLabel()
        self._quick_filter_btns: List[QLabel] = []

        self._build()
        QTimer.singleShot(50, self._on_video_select)

    # ── UI 构建 ──
    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        # ── Top control area ──
        ctrl = QWidget()
        ctrl_layout = QHBoxLayout(ctrl)
        ctrl_layout.setContentsMargins(0, 0, 0, 4)

        # Video selection
        vbox = QGroupBox("  📹 选择视频（可多选）  ")
        vbox.setStyleSheet(f"""
            QGroupBox {{
                color: {C['accent']}; font-weight: bold;
                border: 1px solid {C['border']};
                border-radius: {C['radius_sm']}px;
                margin-top: 12px;
                padding-top: 16px;
                background-color: {C['bg_surface']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
            }}
        """)
        vb_layout = QVBoxLayout(vbox)
        vb_layout.setContentsMargins(8, 8, 8, 8)

        self._listbox.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self._listbox.setStyleSheet(f"""
            QListWidget {{
                background-color: {C['bg_base']};
                color: {C['text_1']};
                border: 1px solid {C['border']};
                border-radius: {C['radius_sm']}px;
                font-size: 10pt;
            }}
            QListWidget::item:selected {{
                background-color: {C['bilibili_dim']};
                color: white;
            }}
        """)
        for v in self._monitored_videos:
            title = v.get("title", "未知")[:32]
            item = QListWidgetItem(f"  {v.get('bvid', '')}  {title}")
            self._listbox.addItem(item)
        self._listbox.itemSelectionChanged.connect(self._on_video_select)
        vb_layout.addWidget(self._listbox)

        ctrl_layout.addWidget(vbox, 2)

        # Time point selection
        tbox = QGroupBox("  🕐 选择时间点（可多选）  ")
        tbox.setStyleSheet(vbox.styleSheet())
        tb_layout = QVBoxLayout(tbox)
        tb_layout.setContentsMargins(8, 8, 8, 8)

        # Quick filter buttons
        qf = QWidget()
        qf.setStyleSheet(f"background-color: {C['bg_surface']};")
        qf_layout = QHBoxLayout(qf)
        qf_layout.setContentsMargins(0, 0, 0, 4)
        qf_layout.setSpacing(4)

        for label, key in [(" 最近1h ", "1h"), (" 今天 ", "today"), (" 最近3天 ", "3d"), (" 全部 ", "all")]:
            btn = QPushButton(label)
            btn.setFixedHeight(22)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {C['bg_elevated']};
                    color: {C['text_2']};
                    border: 1px solid {C['border_sub']};
                    border-radius: 11px;
                    padding: 0 8px;
                    font-size: 8pt;
                }}
                QPushButton:hover {{
                    background-color: {C['bg_hover']};
                    color: {C['bilibili']};
                }}
            """)
            btn.clicked.connect(lambda checked, k=key: self._quick_filter(k))
            qf_layout.addWidget(btn)

        qf_layout.addStretch()
        tb_layout.addWidget(qf)

        # Custom range input
        cf = QWidget()
        cf.setStyleSheet(f"background-color: {C['bg_surface']};")
        cf_layout = QHBoxLayout(cf)
        cf_layout.setContentsMargins(0, 2, 0, 2)

        cf_lbl = QLabel("自定义范围:")
        cf_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent; font-size: 8pt;")
        cf_layout.addWidget(cf_lbl)

        self._start_entry.setPlaceholderText("YYYY-MM-DD HH:MM")
        self._start_entry.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                border: 1px solid {C['border']};
                border-radius: {C['radius_sm']}px;
                padding: 2px 6px;
                font-family: Consolas; font-size: 9pt;
            }}
        """)
        cf_layout.addWidget(self._start_entry)

        to_lbl = QLabel("至")
        to_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent; font-size: 8pt;")
        cf_layout.addWidget(to_lbl)

        self._end_entry.setPlaceholderText("YYYY-MM-DD HH:MM")
        self._end_entry.setStyleSheet(self._start_entry.styleSheet())
        cf_layout.addWidget(self._end_entry)

        custom_btn = QPushButton("应用")
        custom_btn.setFixedWidth(50)
        custom_btn.clicked.connect(self._apply_custom_range)
        cf_layout.addWidget(custom_btn)

        tb_layout.addWidget(cf)

        self._ts_listbox.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self._ts_listbox.setStyleSheet(f"""
            QListWidget {{
                background-color: {C['bg_base']};
                color: {C['text_1']};
                border: 1px solid {C['border']};
                border-radius: {C['radius_sm']}px;
                font-family: Consolas; font-size: 10pt;
            }}
            QListWidget::item:selected {{
                background-color: {C['bilibili_dim']};
                color: white;
            }}
        """)
        tb_layout.addWidget(self._ts_listbox)

        tip = QLabel("↑ 选视频后自动加载（智能采样） | 快捷按钮可快速筛选 | 或自行输入范围筛选")
        tip.setStyleSheet(f"color: {C['text_3']}; background: transparent; font-size: 8pt;")
        tb_layout.addWidget(tip)

        ctrl_layout.addWidget(tbox, 2)

        # Right panel: metrics + buttons
        rbox = QFrame()
        rbox.setStyleSheet(f"""
            QFrame {{
                background-color: {C['bg_surface']};
                border: 1px solid {C['border']};
                border-radius: {C['radius_sm']}px;
            }}
        """)
        rb_layout = QVBoxLayout(rbox)
        rb_layout.setContentsMargins(10, 8, 10, 8)

        metric_title = QLabel("对比指标（可多选）")
        metric_title.setStyleSheet(f"color: {C['accent']}; font-weight: bold; background: transparent;")
        rb_layout.addWidget(metric_title)

        for key, label in METRICS:
            cb = QCheckBox(label)
            cb.setChecked(self._metric_checks.get(key, False))
            cb.toggled.connect(lambda checked, k=key: self._on_metric_toggle(k, checked))
            cb.setStyleSheet(f"""
                QCheckBox {{
                    color: {C['text_1']}; background: transparent;
                    spacing: 6px;
                }}
                QCheckBox::indicator {{
                    width: 16px; height: 16px;
                    border: 1px solid {C['border']};
                    border-radius: 3px;
                    background-color: {C['bg_base']};
                }}
                QCheckBox::indicator:checked {{
                    background-color: {C['accent']};
                    border-color: {C['accent']};
                }}
            """)
            rb_layout.addWidget(cb)

        ms_cb = QCheckBox("叠加里程碑数据")
        ms_cb.setChecked(True)
        ms_cb.toggled.connect(lambda checked: self._on_milestone_toggle(checked))
        ms_cb.setStyleSheet(f"""
            QCheckBox {{ color: {C['text_1']}; background: transparent; spacing: 6px; }}
            QCheckBox::indicator {{
                width: 16px; height: 16px;
                border: 1px solid {C['border']};
                border-radius: 3px;
                background-color: {C['bg_base']};
            }}
            QCheckBox::indicator:checked {{
                background-color: {C['accent']};
                border-color: {C['accent']};
            }}
        """)
        rb_layout.addWidget(ms_cb)

        rb_layout.addStretch()

        compare_btn = QPushButton("生成对比图")
        compare_btn.setProperty("primary", True)
        compare_btn.clicked.connect(self._compare)
        rb_layout.addWidget(compare_btn)

        clear_btn = QPushButton("清空选择")
        clear_btn.clicked.connect(self._clear)
        rb_layout.addWidget(clear_btn)

        ctrl_layout.addWidget(rbox, 1)

        layout.addWidget(ctrl)

        # Chart area
        self._chart.setStyleSheet(f"""
            background-color: {C['canvas_bg']};
            border: 1px solid {C['border']};
            border-radius: {C['radius_sm']}px;
        """)
        layout.addWidget(self._chart, 1)

        # Status
        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {C['text_2']}; padding: 2px 12px;")
        layout.addWidget(self._status)

    def _on_metric_toggle(self, key: str, checked: bool):
        self._metric_checks[key] = checked

    def _on_milestone_toggle(self, checked: bool):
        self._use_milestone = checked

    # ── Video selection callback ──
    def _on_video_select(self):
        selected = self._listbox.selectedItems()
        if not selected:
            return

        all_ts_set: set = set()
        for item in selected:
            row = self._listbox.row(item)
            if row >= len(self._monitored_videos):
                continue
            bvid = self._monitored_videos[row].get("bvid", "")
            if bvid not in self._points:
                self._load_records(bvid)
            for rec in self._points.get(bvid, []):
                ts = rec.get("timestamp", "")
                if ts:
                    all_ts_set.add(str(ts)[:16])

        ts_list = sorted(all_ts_set, reverse=True)

        self._ts_listbox.clear()
        self._ts_avail = ts_list

        self._ts_displayed = self._smart_sample(ts_list) if len(ts_list) > 50 else ts_list

        for ts in self._ts_displayed:
            self._ts_listbox.addItem(ts)

    # ── Quick filter ──
    def _quick_filter(self, mode: str):
        all_ts = self._ts_avail
        if not all_ts:
            return

        now = _parse_dt(all_ts[0])
        if not now:
            now = datetime.now()

        filtered: List[str] = []
        cutoff_map = {
            "1h": now - timedelta(hours=1),
            "3d": now - timedelta(days=3),
        }
        cutoff = cutoff_map.get(mode)
        if cutoff is not None:
            for ts in all_ts:
                dt = _parse_dt(ts)
                if dt is not None and dt >= cutoff:
                    filtered.append(ts)
        elif mode == "today":
            filtered = [ts for ts in all_ts if ts.startswith(now.strftime("%Y-%m-%d"))]
        else:
            filtered = self._smart_sample(all_ts) if len(all_ts) > 50 else all_ts

        if not filtered:
            return

        self._ts_listbox.clear()
        self._ts_displayed = filtered
        for ts in filtered:
            self._ts_listbox.addItem(ts)

    # ── Custom range ──
    def _apply_custom_range(self):
        all_ts = self._ts_avail
        if not all_ts:
            QMessageBox.warning(self, "提示", "请先选择视频加载时间点")
            return

        start_str = self._start_entry.text().strip()
        end_str = self._end_entry.text().strip()
        if not start_str and not end_str:
            QMessageBox.warning(self, "提示", "请输入至少一个时间范围")
            return

        if not start_str or start_str == self._start_entry.placeholderText():
            start_dt = None
        else:
            try:
                start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M")
            except ValueError:
                try:
                    start_dt = datetime.strptime(start_str, "%Y-%m-%d")
                except ValueError:
                    start_dt = None

        if not end_str or end_str == self._end_entry.placeholderText():
            end_dt = None
        else:
            try:
                end_dt = datetime.strptime(end_str, "%Y-%m-%d %H:%M")
            except ValueError:
                try:
                    end_dt = datetime.strptime(end_str, "%Y-%m-%d")
                except ValueError:
                    end_dt = None

        if start_dt is None and end_dt is None:
            QMessageBox.warning(self, "提示", "无法解析输入的时间格式")
            return

        first_ts = _parse_dt(all_ts[-1]) if all_ts else None
        last_ts = _parse_dt(all_ts[0]) if all_ts else None

        filtered = []
        for ts_str in all_ts:
            ts_dt = _parse_dt(ts_str)
            if not ts_dt:
                continue
            if start_dt and ts_dt < start_dt:
                continue
            if end_dt and ts_dt > end_dt:
                continue
            filtered.append(ts_str)

        if not filtered:
            QMessageBox.warning(self, "提示", "没有符合条件的时间点")
            return

        self._ts_listbox.clear()
        self._ts_displayed = filtered
        for ts in filtered:
            self._ts_listbox.addItem(ts)

        _bar_snap_logger.info(f"[快照-自定义范围] 筛选结果: {len(filtered)} 个时间点")

    # ── Smart sample ──
    def _smart_sample(self, ts_list, max_per_day=8):
        if len(ts_list) <= 20:
            return ts_list

        day_groups = defaultdict(list)
        for ts in ts_list:
            day = ts[:10]
            day_groups[day].append(ts)

        result = []
        for day in sorted(day_groups.keys(), reverse=True):
            day_ts = day_groups[day]
            if len(day_ts) <= max_per_day:
                result.extend(day_ts)
            else:
                step = len(day_ts) / max_per_day
                sampled = [day_ts[int(i * step)] for i in range(max_per_day)]
                if day_ts[0] not in sampled:
                    sampled[0] = day_ts[0]
                if day_ts[-1] not in sampled:
                    sampled[-1] = day_ts[-1]
                result.extend(sorted(sampled, reverse=True))

        return result

    def _load_records(self, bvid: str):
        if bvid in self._video_dbs:
            try:
                records = self._video_dbs[bvid].get_all_records()
                if records:
                    self._points[bvid] = sorted(
                        [dict(r) for r in records], key=lambda r: r.get("timestamp", "")
                    )
                    return
            except Exception as e:
                _bar_snap_logger.warning("加载 %s 历史记录失败: %s", bvid, e)
        self._points[bvid] = []

    # ── Generate comparison ──
    def _compare(self):
        sel_v = self._listbox.selectedItems()
        sel_ts = self._ts_listbox.selectedItems()

        if not sel_v:
            QMessageBox.warning(self, "提示", "请选择至少 1 个视频")
            return
        if not sel_ts:
            QMessageBox.warning(self, "提示", "请选择至少 1 个时间点")
            return

        selected_indices = [self._listbox.row(item) for item in sel_v]
        chosen_videos = [self._monitored_videos[i] for i in selected_indices if i < len(self._monitored_videos)]

        chosen_ts_list = [item.text() for item in sel_ts]

        self._selected = chosen_videos
        self._chosen_ts = {v.get("bvid", ""): chosen_ts_list for v in chosen_videos}
        self._chosen_metrics_cache = [key for key, checked in self._metric_checks.items() if checked]
        if not self._chosen_metrics_cache:
            QMessageBox.warning(self, "提示", "请至少选择一个对比指标")
            return

        self._draw()

    # ── Clear ──
    def _clear(self):
        self._selected = []
        self._chosen_ts = {}
        self._ts_listbox.clearSelection()
        self._listbox.clearSelection()
        self._chart.set_placeholder("")
        self._status.setText("")

    # ── Draw ──
    def _draw(self):
        if not self._selected:
            return

        all_metric_bars = self._collect_data()
        if not all_metric_bars:
            self._chart.set_placeholder("所选视频/时间点下无数据")
            return

        total_data = sum(len(v) for v in all_metric_bars.values())
        if total_data == 0:
            self._chart.set_placeholder("所选视频/时间点下无数据")
            return

        # Update chart widget
        self._chart.set_chart_data(
            all_metric_bars,
            self._chosen_metrics_cache or [],
            self._selected,
            self._use_milestone,
        )

        # Update status
        metric_labels = ", ".join(
            next((lb for k, lb in METRICS if k == m), m)
            for m in (self._chosen_metrics_cache or [])
        )
        self._status.setText(f"共 {len(self._selected)} 个视频，{total_data} 条数据，指标：{metric_labels}")

    def _collect_data(self) -> Dict:
        """Collect all bar data grouped by metric"""
        use_milestone = self._use_milestone
        milestone_data = get_db().get_all_milestones_grouped() if use_milestone else {}

        all_metric_bars: Dict[str, list] = {}
        chosen_metrics = self._chosen_metrics_cache or []

        for video in self._selected:
            bvid = video.get("bvid", "")
            title = video.get("title", bvid)[:14]
            recs = self._points.get(bvid, [])
            chosen_ts = self._chosen_ts.get(bvid, [])

            # History data
            for ts_str in sorted(chosen_ts):
                best_rec = self._find_best_record(recs, ts_str)
                if best_rec is not None:
                    for metric in chosen_metrics:
                        raw_val = best_rec.get(metric, None)
                        try:
                            val = float(raw_val) if raw_val is not None else 0
                        except (TypeError, ValueError):
                            val = 0
                        all_metric_bars.setdefault(metric, []).append(
                            {"bvid": bvid, "title": title, "ts": ts_str, "value": val, "source": "history"}
                        )

            # Milestone data
            if use_milestone and bvid in milestone_data:
                for period, row in milestone_data[bvid].items():
                    for metric in chosen_metrics:
                        raw_val = row.get(metric, None)
                        try:
                            val = float(raw_val) if raw_val is not None else 0
                        except (TypeError, ValueError):
                            val = 0
                        if val and val > 0:
                            all_metric_bars.setdefault(metric, []).append(
                                {"bvid": bvid, "title": title, "ts": f"里程碑·{period}", "value": val, "source": "milestone"}
                            )

        return all_metric_bars

    def _find_best_record(self, recs, ts_str):
        best_rec = None
        for rec in recs:
            rec_ts = str(rec.get("timestamp", ""))[:16]
            if rec_ts == ts_str[:16]:
                best_rec = rec
                break
        if best_rec is None:
            target_dt = _parse_dt(ts_str)
            if target_dt:
                best, best_diff = None, float("inf")
                for rec in recs:
                    rdt = _parse_dt(str(rec.get("timestamp", "")))
                    if rdt:
                        diff = abs((rdt - target_dt).total_seconds())
                        if diff < best_diff:
                            best_diff, best = diff, rec
                if best and best_diff < 300:
                    best_rec = best
        return best_rec
