"""
趋势图标签页 - 多视频折线图对比 (PyQt6 版)
"""

import logging
from typing import List, Dict
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QRadioButton, QFrame,
    QScrollBar, QSizePolicy,
)
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QFont, QBrush, QFontMetrics,
)

from ui.theme import C
from .data_comparison import _fmt, PALETTE, PALETTE_LIGHT, METRICS, _ML, _MR, _MT, _MB

logger = logging.getLogger(__name__)


class TrendChart(QWidget):
    """自定义趋势折线图控件 — 使用 QPainter 绘制"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._series_map: Dict[str, list] = {}
        self._valid_videos: List[Dict] = []
        self._metric_label = ""
        self._min_ts = None
        self._max_ts = None
        self._max_val = 1.0
        self._min_val = 0.0
        self._placeholder = "先在上方选好视频,再点「开始对比」,天依就画给你看 ♪"

    def set_data(self, series_map, valid_videos, metric_label, min_ts, max_ts, max_val):
        self._series_map = series_map
        self._valid_videos = valid_videos
        self._metric_label = metric_label
        self._min_ts = min_ts
        self._max_ts = max_ts
        self._min_val = 0.0
        self._max_val = max(max_val, 1)
        self._placeholder = ""
        self.update()

    def set_placeholder(self, text: str):
        self._placeholder = text
        self._series_map.clear()
        self._valid_videos.clear()
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
            text_w = metrics.horizontalAdvance(self._placeholder)
            painter.drawText((W - text_w) // 2, H // 2, self._placeholder)
            painter.end()
            return

        if not self._series_map or not self._min_ts or not self._max_ts:
            painter.end()
            return

        cw = W - _ML - _MR
        ch = H - _MT - _MB
        if cw < 20 or ch < 20:
            painter.end()
            return

        ts_span = (self._max_ts - self._min_ts).total_seconds() or 1
        val_range = self._max_val - self._min_val or 1

        def to_x(ts):
            return _ML + (ts - self._min_ts).total_seconds() / ts_span * cw

        def to_y(v):
            return _MT + ch - (v - self._min_val) / val_range * ch

        # 标题
        painter.setPen(QColor(C.get("text_1", "#e6edf3")))
        title_font = QFont("Microsoft YaHei UI", 11)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(_ML, _MT // 2 + 4, f"对比指标: {self._metric_label} ♪")

        # 网格
        grid_pen = QPen(QColor(C.get("grid_line", "#21262d")))
        grid_pen.setDashPattern([2, 4])
        n_grid = 5
        for i in range(n_grid + 1):
            ratio = i / n_grid
            y = _MT + ch * (1 - ratio)
            val = self._max_val * ratio
            painter.setPen(grid_pen)
            painter.drawLine(int(_ML), int(y), int(W - _MR), int(y))
            painter.setPen(QColor(C.get("text_2", "#8b949e")))
            label_font = QFont("Consolas", 9)
            painter.setFont(label_font)
            painter.drawText(0, int(y - 6), int(_ML - 4), 14, Qt.AlignmentFlag.AlignRight.value, _fmt(val))

        # X 轴时间刻度
        n_ticks = min(6, max(2, cw // 100))
        tick_font = QFont("Consolas", 8)
        for i in range(n_ticks):
            ratio = i / (n_ticks - 1) if n_ticks > 1 else 0
            ts = self._min_ts + timedelta(seconds=ts_span * ratio)
            x = int(_ML + cw * ratio)
            label = (
                ts.strftime("%m-%d %H:%M") if ts_span < 86400 * 7 else ts.strftime("%m-%d")
            )
            painter.setPen(QColor(C.get("text_2", "#8b949e")))
            painter.setFont(tick_font)
            painter.drawText(int(x - 30), int(H - _MB + 6), 60, 16, Qt.AlignmentFlag.AlignCenter.value, label)

        # 绘制所有折线
        line_pen = QPen()
        line_pen.setWidth(2)
        for idx, video in enumerate(self._valid_videos):
            bvid = video.get("bvid", "")
            pts = self._series_map.get(bvid, [])
            if not pts:
                continue

            color = QColor(PALETTE[idx % len(PALETTE)])
            color_light = QColor(PALETTE_LIGHT[idx % len(PALETTE_LIGHT)])

            # 构建折线坐标
            coords = []
            for ts, val in pts:
                coords.append((int(to_x(ts)), int(to_y(val))))

            # 面积填充
            if len(coords) >= 2:
                path = []
                for x, y in coords:
                    path.append((x, y))
                path.append((coords[-1][0], _MT + ch))
                path.append((coords[0][0], _MT + ch))

                poly = []
                for x, y in path:
                    poly.append(x)
                    poly.append(y)

                # Draw filled area using a semi-transparent brush
                alpha_color = QColor(color_light)
                alpha_color.setAlpha(80)
                painter.setBrush(QBrush(alpha_color))
                painter.setPen(Qt.PenStyle.NoPen)

                # Need to use drawPolygon
                from PyQt6.QtGui import QPolygon
                from PyQt6.QtCore import QPoint
                points = [QPoint(x, y) for x, y in path]
                painter.drawPolygon(QPolygon(points))

            # 折线
            line_pen.setColor(color)
            painter.setPen(line_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(1, len(coords)):
                painter.drawLine(coords[i - 1][0], coords[i - 1][1], coords[i][0], coords[i][1])

            # 最后一个数据点 + 标注
            lx, ly = coords[-1]
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(QColor(C.get("bg_base", "#0d1117")), 1))
            painter.drawEllipse(lx - 4, ly - 4, 8, 8)

            painter.setPen(QPen(color))
            val_font = QFont("Consolas", 9)
            val_font.setBold(True)
            painter.setFont(val_font)
            painter.drawText(lx + 8, ly - 14, _fmt(pts[-1][1]))

        painter.end()


class TrendTab(QWidget):
    """趋势折线图标签页 — 多视频数据对比 (PyQt6 版)"""

    def __init__(self, parent, monitored_videos, history_data, video_dbs):
        super().__init__(parent)
        self._monitored_videos = monitored_videos
        self._history_data = history_data
        self._video_dbs = video_dbs

        self._selected: List[Dict] = []
        self._metric_key = "view_count"
        self._listbox: QListWidget = QListWidget()  # replaced in _build
        self._chart: TrendChart = TrendChart()  # replaced in _build
        self._valid_videos_cache: List[Dict] = []

        self._build()

    # ── 构建UI ──────────────────────────────────────────────────────────────────
    def _build(self):
        """构建趋势图页面的 UI 布局"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        # 顶栏（视频列表 + 指标选择）
        top = QWidget()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 4)

        # 左：视频列表
        left_frame = QFrame()
        left_frame.setFrameShape(QFrame.Shape.StyledPanel)
        left_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {C['bg_surface']};
                border: 1px solid {C['border']};
                border-radius: {C['radius_sm']}px;
            }}
        """)
        left_inner = QVBoxLayout(left_frame)
        left_inner.setContentsMargins(8, 8, 8, 8)

        left_label = QLabel("  ◉ 选择视频（可多选）  ")
        left_label.setStyleSheet(f"color: {C['accent']}; font-weight: bold; background: transparent;")
        left_inner.addWidget(left_label)

        self._listbox = QListWidget()
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
            QListWidget::item:hover {{
                background-color: {C['bg_hover']};
            }}
        """)
        for v in self._monitored_videos:
            title = v.get("title", "未知")[:35]
            item = QListWidgetItem(f"  {v.get('bvid', '')}  {title}")
            self._listbox.addItem(item)
        left_inner.addWidget(self._listbox)

        top_layout.addWidget(left_frame, 3)

        # 右：指标选择
        right_frame = QFrame()
        right_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {C['bg_surface']};
                border: 1px solid {C['border']};
                border-radius: {C['radius_sm']}px;
            }}
        """)
        right_inner = QVBoxLayout(right_frame)
        right_inner.setContentsMargins(10, 8, 10, 8)

        metric_label = QLabel("对比指标")
        metric_label.setStyleSheet(f"color: {C['accent']}; font-weight: bold; background: transparent;")
        right_inner.addWidget(metric_label)

        self._metric_buttons = {}
        for key, label in METRICS:
            rb = QRadioButton(label)
            rb.setStyleSheet(f"""
                QRadioButton {{
                    color: {C['text_1']}; background: transparent;
                    spacing: 6px;
                }}
                QRadioButton::indicator {{
                    width: 16px; height: 16px;
                    border: 1px solid {C['border']};
                    border-radius: 8px;
                    background-color: {C['bg_base']};
                }}
                QRadioButton::indicator:checked {{
                    background-color: {C['accent']};
                    border-color: {C['accent']};
                }}
            """)
            if key == self._metric_key:
                rb.setChecked(True)
            rb.toggled.connect(lambda checked, k=key: self._on_metric_changed(k) if checked else None)
            right_inner.addWidget(rb)
            self._metric_buttons[key] = rb

        right_inner.addStretch()

        start_btn = QPushButton("开始对比 ♪")
        start_btn.setProperty("primary", True)
        start_btn.clicked.connect(self._start)
        right_inner.addWidget(start_btn)

        top_layout.addWidget(right_frame, 1)

        layout.addWidget(top)

        # 图表区
        self._chart = TrendChart()
        self._chart.setStyleSheet(f"""
            background-color: {C['canvas_bg']};
            border: 1px solid {C['border']};
            border-radius: {C['radius_sm']}px;
        """)
        layout.addWidget(self._chart, 1)

        # 图例区
        self._legend = QWidget()
        self._legend.setStyleSheet(f"background-color: {C['bg_surface']};")
        self._legend_layout = QHBoxLayout(self._legend)
        self._legend_layout.setContentsMargins(10, 4, 10, 4)
        layout.addWidget(self._legend)

    def _on_metric_changed(self, key: str):
        """指标选择变更"""
        self._metric_key = key

    # ── 开始 ────────────────────────────────────────────────────────────────────
    def _start(self):
        """开始对比：选择视频 → 加载历史数据 → 绘图"""
        sel = self._listbox.selectedItems()
        if not sel:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "♪ 提示", "至少选 1 个视频哦,不然天依不知道唱哪首 ♪")
            return
        if len(sel) > 8:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "♪ 提示", "一次最多对比 8 个视频呢,天依的耳朵也要歇一歇 ♪")
            return

        selected_indices = [self._listbox.row(item) for item in sel]
        self._selected = [self._monitored_videos[i] for i in selected_indices if i < len(self._monitored_videos)]

        # 加载选中视频的历史数据
        for video in self._selected:
            bvid = video.get("bvid", "")
            if bvid in self._video_dbs:
                try:
                    records = self._video_dbs[bvid].get_all_records()
                    if records:
                        self._history_data[bvid] = [dict(row) for row in records]
                except Exception as e:
                    logger.warning("加载 %s 历史数据失败: %s", bvid, e)

        self._draw()

    # ── 绘制 ────────────────────────────────────────────────────────────────────
    def _draw(self):
        """主绘图函数 - 委托 TrendChart 绘制"""
        # 清空图例
        for i in reversed(range(self._legend_layout.count())):
            item = self._legend_layout.itemAt(i)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()

        # 检查前置条件
        if not self._selected:
            self._chart.set_placeholder("选好视频后点「开始对比」,天依为你唱出折线 ♪")
            return

        # 收集数据
        result = self._collect_data()
        if result is None:
            return
        series_map, all_vals, all_ts = result

        # 计算布局参数
        if not all_vals or not all_ts:
            return
        min_ts = min(all_ts)
        max_ts = max(all_ts)
        max_val = max(all_vals) if all_vals else 1

        metric_label = next((lb for k, lb in METRICS if k == self._metric_key), self._metric_key)

        # 传递数据给图表
        self._chart.set_data(series_map, self._valid_videos_cache, metric_label, min_ts, max_ts, max_val)

        # 构建图例
        valid = self._valid_videos_cache or []
        for idx, video in enumerate(valid):
            bvid = video.get("bvid", "")
            title = video.get("title", bvid)[:18]
            color = PALETTE[idx % len(PALETTE)]
            leg_item = QLabel(f"  {title} ({bvid})")
            leg_item.setStyleSheet(f"""
                color: {color}; background: transparent;
                padding: 2px 6px; border-left: 3px solid {color};
            """)
            self._legend_layout.addWidget(leg_item)

        self._legend_layout.addStretch()

    def _collect_data(self):
        """收集选中视频在指定指标下的数据，按 bvid 分组"""
        metric = self._metric_key
        series_map = {}
        all_vals, all_ts = [], []

        for video in self._selected:
            bvid = video.get("bvid", "")
            pts = []
            for item in self._history_data.get(bvid, []):
                parsed = self._parse_raw_item(item, metric)
                if parsed:
                    pts.append(parsed)
                    all_vals.append(parsed[1])
                    all_ts.append(parsed[0])

            if pts:
                pts.sort(key=lambda p: p[0])
                series_map[bvid] = pts

        valid = [v for v in self._selected if v.get("bvid", "") in series_map]
        if not valid:
            metric_label = next((lb for k, lb in METRICS if k == metric), metric)
            self._chart.set_placeholder(f"呜…这些视频还没有「{metric_label}」的历史数据呢,天依先记在心里,等数据来了再画 ♪")
            return None

        self._valid_videos_cache = valid
        return series_map, all_vals, all_ts

    @staticmethod
    def _normalize_timestamp(ts):
        """将时间戳统一标准化为 datetime 对象"""
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts)
            except Exception as e:
                logger.debug("趋势ISO时间解析失败: %s", e)
                return None
        if isinstance(ts, (int, float)):
            try:
                return datetime.fromtimestamp(float(ts))
            except Exception as e:
                logger.debug("时间戳解析失败: %s", e)
                return None
        return ts if isinstance(ts, datetime) else None

    @staticmethod
    def _normalize_value(val):
        """将数值标准化为 float"""
        try:
            return float(val) if val is not None else 0
        except (TypeError, ValueError):
            return 0

    def _parse_raw_item(self, item, metric):
        """解析单条历史记录，返回 (时间, 数值) 元组"""
        if isinstance(item, dict):
            ts = self._normalize_timestamp(item.get("timestamp", ""))
            val = self._normalize_value(item.get(metric, 0))
        else:
            return None
        return None if ts is None else (ts, val)
