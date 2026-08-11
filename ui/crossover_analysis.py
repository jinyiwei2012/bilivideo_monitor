"""
播放量交叉计算界面 — PyQt6 版
基于历史数据预测多个视频播放量的交会时间
"""

import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QComboBox, QListWidget, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QMessageBox,
)
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QPainter, QColor, QFont, QPen

from ui.theme import C
from algorithms.registry import AlgorithmRegistry
from utils.time_utils import safe_datetime

logger = logging.getLogger(__name__)

# 图表边距
_ML, _MR, _MT, _MB = 72, 24, 32, 40

# 折线颜色列表（每对 = 主色 + 浅色）
LINE_COLORS = [
    ("#fb7299", "#ff8db5"),
    ("#23ade5", "#4bbfea"),
    ("#42b983", "#66cba0"),
    ("#f5a623", "#f7b84e"),
    ("#9b59b6", "#b07cc6"),
]


def _fmt_num(n):
    """格式化大数字：亿/万/原始"""
    if n >= 1_0000_0000:
        return f"{n / 1_0000_0000:.2f}亿"
    if n >= 1_0000:
        return f"{n / 1_0000:.1f}万"
    return str(int(n))


def _parse_ts(ts) -> Optional[datetime]:
    """将各种时间格式统一为 datetime"""
    try:
        return safe_datetime(ts)
    except Exception as e:
        logger.debug("safe_datetime 失败: %s", e)
        return None


def _linear_fit(points: List[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    """最小二乘线性拟合，返回 (斜率k, 截距b)，x 为距第一个点的小时数"""
    n = len(points)
    if n < 2:
        return None
    sx = sy = sxx = sxy = 0
    for x, y in points:
        sx += x
        sy += y
        sxx += x * x
        sxy += x * y
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-12:
        return None
    k = (n * sxy - sx * sy) / denom
    b = (sy - k * sx) / n
    return (k, b)


def _find_crossover(
    slope_a: float, intercept_a: float, slope_b: float, intercept_b: float, offset_hours: float
) -> Optional[float]:
    """
    求两条线的交点。
    线A: y = slope_a * t + intercept_a  (t=0 对应视频A第一个数据点)
    线B: y = slope_b * (t - offset_hours) + intercept_b  (有偏移)
    返回交点距视频A第一个数据点的小时数，None 表示不相交。
    """
    denom = slope_a - slope_b
    if abs(denom) < 1e-12:
        return None
    t = (intercept_b - intercept_a - slope_b * (-offset_hours)) / denom
    if t > 0:
        return t
    return None


# ══════════════════════════════════════════════════════════════════════════════
# ── 趋势图绘制组件 ─────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


class TrendChartWidget(QWidget):
    """QPainter 绘制的播放量趋势图（实际折线 + 预测虚线 + 网格 + 数据点）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fits: Dict = {}
        self._selected: List[Dict] = []
        self.setMinimumSize(200, 120)
        self.setStyleSheet(f"background-color: {C['canvas_bg']};")

    def set_data(self, fits: Dict, selected: List[Dict]):
        self._fits = fits
        self._selected = selected
        self.update()

    def paintEvent(self, a0):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        W = self.width()
        H = self.height()
        if W < 100 or H < 100:
            painter.end()
            return

        cw = W - _ML - _MR
        ch = H - _MT - _MB
        if cw < 50 or ch < 50:
            painter.end()
            return

        series, all_pts = self._collect_trend_series()
        if not all_pts or not series:
            painter.setPen(QColor(C["text_2"]))
            title_font = QFont("Microsoft YaHei UI", 12)
            painter.setFont(title_font)
            painter.drawText(QRect(0, 0, W, H), Qt.AlignmentFlag.AlignCenter, "数据还不太够呢…像还没写完的歌词 ♪")
            painter.end()
            return

        min_ts, max_ts, max_v, min_v, ts_span, v_span = self._compute_trend_ranges(all_pts)

        def tx(ts):
            return _ML + (ts - min_ts).total_seconds() / ts_span * cw

        def ty(v):
            return _MT + ch - (v - min_v) / v_span * ch

        self._draw_grid(painter, W, H, cw, ch, min_ts, max_ts, ts_span, max_v, min_v, v_span)
        self._draw_now_line(painter, tx, W, ch)
        self._draw_series(painter, series, tx, ty, max_ts)

        painter.end()

    def _collect_trend_series(self):
        """收集趋势图所需的数据系列"""
        all_pts = []
        series = {}
        for idx, v in enumerate(self._selected):
            bvid = v.get("bvid", "")
            fit_info = self._fits.get(bvid)
            if not fit_info:
                continue
            slope, intercept, base_ts, pts = fit_info
            series[bvid] = (slope, intercept, base_ts, pts, idx)
            for p in pts:
                all_pts.append((p[0], p[1]))
        return series, all_pts

    def _compute_trend_ranges(self, all_pts):
        """计算趋势图的坐标轴范围（时间轴延长到未来 7 天）"""
        all_ts_list = [p[0] for p in all_pts]
        all_v_list = [p[1] for p in all_pts]
        min_ts = min(all_ts_list)
        max_ts = max(all_ts_list)
        max_ts = max(max_ts, max_ts + timedelta(hours=168))
        max_v = max(all_v_list) * 1.2
        min_v = 0
        ts_span = (max_ts - min_ts).total_seconds() or 1
        v_span = max_v - min_v or 1
        return min_ts, max_ts, max_v, min_v, ts_span, v_span

    def _draw_grid(self, painter, W, H, cw, ch, min_ts, max_ts, ts_span, max_v, min_v, v_span):
        """绘制趋势图的网格线和坐标轴标签"""
        grid_pen = QPen(QColor(C["grid_line"]), 1)
        grid_pen.setDashPattern([2, 4])

        # Y 轴网格线（5条水平线）
        for i in range(5):
            ratio = i / 4
            y = _MT + ch * (1 - ratio)
            val = min_v + v_span * ratio
            painter.setPen(grid_pen)
            painter.drawLine(int(_ML), int(y), int(W - _MR), int(y))
            painter.setPen(QColor(C["text_2"]))
            mono_font = QFont("Consolas", 9)
            painter.setFont(mono_font)
            painter.drawText(int(_ML - 6), int(y + 4), _fmt_num(val))

        # X 轴时间标签（5个刻度）
        for i in range(5):
            ratio = i / 4
            ts = min_ts + timedelta(seconds=ts_span * ratio)
            x = _ML + cw * ratio
            lbl = ts.strftime("%m-%d %H:%M") if ts_span < 86400 * 3 else ts.strftime("%m-%d")
            painter.setPen(QColor(C["text_2"]))
            mono_font = QFont("Consolas", 8)
            painter.setFont(mono_font)
            painter.drawText(int(x), int(H - _MB + 16), lbl)

    def _draw_now_line(self, painter, tx, W, ch):
        """绘制"现在"时间参考线"""
        now_x = tx(datetime.now())
        if _ML < now_x < W - _MR:
            warn_pen = QPen(QColor(C["warning"]), 1)
            warn_pen.setDashPattern([4, 4])
            painter.setPen(warn_pen)
            painter.drawLine(int(now_x), int(_MT), int(now_x), int(_MT + ch))
            warn_font = QFont("Microsoft YaHei UI", 8)
            painter.setFont(warn_font)
            painter.drawText(int(now_x), int(_MT - 8), "现在")

    def _draw_series(self, painter, series, tx, ty, max_ts):
        """绘制所有视频的数据系列（实际折线 + 预测虚线 + 数据点 + 图例）"""
        for bvid, (slope, intercept, base_ts, pts, idx) in series.items():
            color = LINE_COLORS[idx % len(LINE_COLORS)][0]
            title = next((v.get("title", bvid) for v in self._selected if v.get("bvid") == bvid), bvid)[:16]

            line_pen = QPen(QColor(color), 2)
            dash_pen = QPen(QColor(color), 1)
            dash_pen.setDashPattern([6, 4])

            # 实际数据折线
            real_points = []
            for p in pts:
                real_points.append((int(tx(p[0])), int(ty(p[1]))))

            if len(real_points) >= 2:
                painter.setPen(line_pen)
                for i in range(len(real_points) - 1):
                    painter.drawLine(*real_points[i], *real_points[i + 1])

            # 预测虚线：从最后一个实际数据点延长到 max_ts
            if real_points:
                future_hours = (max_ts - base_ts).total_seconds() / 3600
                future_v = slope * future_hours + intercept
                last_x, last_y = real_points[-1]
                future_x = int(tx(max_ts))
                future_y = int(ty(max(0, future_v)))
                painter.setPen(dash_pen)
                painter.drawLine(last_x, last_y, future_x, future_y)

            # 数据点
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            for p in pts:
                px, py = int(tx(p[0])), int(ty(p[1]))
                painter.drawEllipse(px - 2, py - 2, 4, 4)

            # 图例
            legend_font = QFont("Microsoft YaHei UI", 8)
            painter.setFont(legend_font)
            painter.setPen(QColor(color))
            painter.drawText(int(_ML + idx * 160), int(_MT - 12), f"━ {title}")


# ══════════════════════════════════════════════════════════════════════════════
# ── 主窗口 ────────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


class CrossoverAnalysisWindow(QDialog):
    """交叉计算窗口：选择多个视频，预测播放量交会时间"""

    def __init__(
        self,
        parent=None,
        monitored_videos: Optional[List[Dict]] = None,
        history_data: Optional[Dict] = None,
        video_dbs: Optional[Dict] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("播放量交叉计算")
        if parent:
            screen = parent.screen()
            sw, sh = (screen.geometry().width(), screen.geometry().height()) if screen else (1920, 1080)
        else:
            sw, sh = 1920, 1080
        self.resize(int(sw * 0.54), int(sh * 0.72))
        self.setMinimumSize(600, 400)

        self.monitored_videos = monitored_videos or []
        self.history_data = history_data or {}
        self.video_dbs = video_dbs or {}
        self._selected: List[Dict] = []

        self._setup_ui()

    def _setup_ui(self):
        """构建界面：视频多选列表、算法选择、趋势图表、交会结果表格"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        # ── 视频选择区 ──
        sel_group = QGroupBox("选择视频（2-5个）")
        sel_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {C['text_1']};
                border: 1px solid {C['border']};
                border-radius: 6px;
                margin-top: 10px;
                padding: 16px 8px 8px 8px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }}
        """)
        sel_layout = QVBoxLayout(sel_group)
        sel_layout.setContentsMargins(8, 4, 8, 8)

        self._listbox = QListWidget()
        self._listbox.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self._listbox.setMinimumHeight(100)
        self._listbox.setStyleSheet(f"""
            QListWidget {{
                font-family: Consolas; font-size: 9pt;
                background-color: {C['bg_base']};
                color: {C['text_1']};
                border: 1px solid {C['border_sub']};
            }}
            QListWidget::item:selected {{
                background-color: {C['accent']};
                color: #ffffff;
            }}
        """)
        for v in self.monitored_videos:
            bvid = v.get("bvid", "")
            title = v.get("title", "未知")[:40]
            self._listbox.addItem(f"{bvid}  {title}")
        sel_layout.addWidget(self._listbox)

        # 算法选择行
        algo_row = QWidget()
        algo_row_layout = QHBoxLayout(algo_row)
        algo_row_layout.setContentsMargins(0, 4, 0, 0)
        algo_lbl = QLabel("预测算法:")
        algo_lbl.setStyleSheet(f"color: {C['text_2']};")
        algo_font = QFont("Microsoft YaHei UI", 9)
        algo_lbl.setFont(algo_font)
        algo_row_layout.addWidget(algo_lbl)

        self._algo_combo = QComboBox()
        self._algo_combo.setMinimumWidth(400)
        algo_names = ["加权集成(默认)", "线性回归(原方法)"]
        try:
            algo_names.extend(AlgorithmRegistry.get_algorithm_names())
        except Exception as e:
            logger.debug("获取算法列表失败: %s", e)
        self._algo_combo.addItems(algo_names)
        self._algo_combo.setStyleSheet("font-family: Microsoft YaHei UI; font-size: 9pt; padding: 2px 4px;")
        algo_row_layout.addWidget(self._algo_combo)

        analyze_btn = QPushButton("开始分析")
        analyze_btn.clicked.connect(self._analyze)
        algo_row_layout.addWidget(analyze_btn)
        algo_row_layout.addSpacing(12)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"color: {C['text_2']}; font-size: 9pt;")
        algo_row_layout.addWidget(self._status_lbl)
        algo_row_layout.addStretch()

        sel_layout.addWidget(algo_row)
        layout.addWidget(sel_group)

        # ── 趋势图表 ──
        self._chart = TrendChartWidget()
        layout.addWidget(self._chart, 1)

        # ── 交会结果表格 ──
        result_group = QGroupBox("交会分析结果")
        result_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {C['text_1']};
                border: 1px solid {C['border']};
                border-radius: 6px;
                margin-top: 10px;
                padding: 16px 8px 8px 8px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }}
        """)
        result_layout = QVBoxLayout(result_group)
        result_layout.setContentsMargins(8, 4, 8, 8)

        cols = ("视频A", "视频B", "预计交会时间", "预计播放量", "A增长率/h", "B增长率/h", "置信度", "剩余时间")
        widths = [100, 100, 130, 110, 90, 90, 80, 90]

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(cols)
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {C['bg_elevated']};
                alternate-background-color: {C['bg_surface']};
                border: 1px solid {C['border_sub']};
                font-size: 9pt;
            }}
            QHeaderView::section {{
                background-color: {C['bg_surface']};
                color: {C['text_2']};
                border: 1px solid {C['border_sub']};
                padding: 4px 8px;
                font-weight: bold;
            }}
            QTreeWidget::item {{
                padding: 2px 4px;
            }}
        """)
        header = self._tree.header()
        if header is not None:
            for i, w in enumerate(widths):
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
                self._tree.setColumnWidth(i, w)

        result_layout.addWidget(self._tree)
        layout.addWidget(result_group)

    # ── 分析 ──────────────────────────────────────────
    def _analyze(self):
        """开始分析：校验选择、加载数据、拟合、计算交会、绘制趋势图"""
        sel_items = self._listbox.selectedItems()
        if len(sel_items) < 2:
            QMessageBox.warning(self, "提示", "至少选2个视频,天依才能算出它们的交会哦 ♪")
            return
        if len(sel_items) > 5:
            QMessageBox.warning(self, "提示", "最多选5个视频啦,太多了天依会数不过来呢 ♪")
            return

        sel_idx = [self._listbox.row(item) for item in sel_items]
        self._selected = [self.monitored_videos[i] for i in sel_idx if i < len(self.monitored_videos)]

        self._load_history()
        fits = self._fit_videos()

        # 清空旧结果
        self._tree.clear()
        self._chart.set_data({}, [])

        # 筛选出拟合成功的视频
        valid = [v for v in self._selected if fits.get(v.get("bvid", ""))]
        if len(valid) < 2:
            self._status_lbl.setText("呜…这些视频的历史数据还太少,每个至少要有2条记录才行哦 ♪")
            self._status_lbl.setStyleSheet(f"color: {C['danger']}; font-size: 9pt;")
            QMessageBox.warning(
                self,
                "数据不足",
                "呜…部分视频的历史数据还不够,天依没法算出它们的交会。\n每个视频至少需要2条历史记录哦 ♪",
            )
            return

        crossover_count = self._compute_crossovers(valid, fits)

        self._status_lbl.setText(f"分析完成啦!♪ {len(valid)} 个视频,找到了 {crossover_count} 个交会点")
        self._status_lbl.setStyleSheet(f"color: {C['success']}; font-size: 9pt;")

        self._chart.set_data(fits, self._selected)

        if crossover_count == 0 and len(valid) >= 2:
            QMessageBox.information(self, "结果", "呜…按现在的趋势,这些视频的歌声还没有相遇的时刻呢 ♪")

    def _load_history(self):
        """从视频数据库补充历史播放数据到 history_data"""
        for v in self._selected:
            bvid = v.get("bvid", "")
            if bvid in self.video_dbs:
                try:
                    records = self.video_dbs[bvid].get_all_records()
                    if records:
                        self.history_data[bvid] = [(row["timestamp"], row["view_count"]) for row in records]
                except Exception as e:
                    logger.debug("加载视频历史数据失败: %s", e)

    def _fit_videos(self) -> dict:
        """对每个视频做拟合，返回 {bvid: (slope, intercept, base_ts, points)}"""
        algo = self._algo_combo.currentText()
        if algo == "线性回归(原方法)":
            return self._fit_linear()
        return self._fit_with_algorithms(algo)

    def _fit_linear(self) -> dict:
        """原线性回归拟合方法"""
        fits = {}
        for v in self._selected:
            bvid = v.get("bvid", "")
            raw = self.history_data.get(bvid, [])
            pts_parsed = []
            for item in raw:
                ts = _parse_ts(item[0])
                views = item[1] if isinstance(item[1], (int, float)) else 0
                if ts and views >= 0:
                    pts_parsed.append((ts, views))
            if len(pts_parsed) < 2:
                fits[bvid] = None
                continue
            pts_parsed.sort(key=lambda p: p[0])
            base_ts = pts_parsed[0][0]
            hours = [(p[0] - base_ts).total_seconds() / 3600 for p in pts_parsed]
            fit_pts = list(zip(hours, [p[1] for p in pts_parsed]))
            result = _linear_fit(fit_pts)
            fits[bvid] = (*result, base_ts, pts_parsed) if result else None
        return fits

    def _fit_with_algorithms(self, algo_name: str) -> dict:
        """使用算法预测进行拟合：通过算法预测增长率，失败时回退到线性回归"""
        threshold = 100000
        fits = {}
        for v in self._selected:
            bvid = v.get("bvid", "")
            raw = self.history_data.get(bvid, [])
            pts_parsed = []
            for item in raw:
                ts = _parse_ts(item[0])
                views = item[1] if isinstance(item[1], (int, float)) else 0
                if ts and views >= 0:
                    pts_parsed.append((ts, views))
            if len(pts_parsed) < 2:
                fits[bvid] = None
                continue
            pts_parsed.sort(key=lambda p: p[0])
            base_ts = pts_parsed[0][0]
            current_views = pts_parsed[-1][1]
            history_pts = [(p[0], p[1]) for p in pts_parsed]

            growth_rate = self._get_algo_growth_rate(history_pts, current_views, algo_name, threshold)

            if growth_rate is None or growth_rate <= 0:
                hours = [(p[0] - base_ts).total_seconds() / 3600 for p in pts_parsed]
                fit_pts = list(zip(hours, [p[1] for p in pts_parsed]))
                result = _linear_fit(fit_pts)
                fits[bvid] = (*result, base_ts, pts_parsed) if result else None
            else:
                last_hours = (pts_parsed[-1][0] - base_ts).total_seconds() / 3600
                intercept = current_views - growth_rate * last_hours
                fits[bvid] = (growth_rate, intercept, base_ts, pts_parsed)
        return fits

    def _get_algo_growth_rate(self, history_pts, current_views, algo_name, threshold):
        """获取算法预测的增长率 (播放量/小时)"""
        MAX_RATE = 50000
        MIN_HOURS = 0.5
        try:
            if algo_name == "加权集成(默认)":
                results = AlgorithmRegistry.predict_all(history_pts, current_views, thresholds=[threshold])
                rates, weights = [], []
                for name, r in results.items():
                    if name == "_weighted" or r.get("weight", 0) <= 0:
                        continue
                    pred_h = r.get("metadata", {}).get("predicted_hours", None)
                    if pred_h and pred_h != float("inf") and pred_h > MIN_HOURS:
                        rate = (threshold - current_views) / pred_h
                        if 0 < rate <= MAX_RATE:
                            rates.append(rate)
                            weights.append(r["weight"] * max(r["confidence"], 0.1))
                if rates:
                    return sum(r * w for r, w in zip(rates, weights)) / sum(weights)
            else:
                algo = AlgorithmRegistry.get_algorithm(algo_name)
                if algo is None:
                    return None
                result = algo.predict(history_pts, current_views, thresholds=[threshold])
                if result:
                    pred_h = result.get("metadata", {}).get("predicted_hours", None)
                    if pred_h and pred_h != float("inf") and pred_h > MIN_HOURS:
                        rate = (threshold - current_views) / pred_h
                        if 0 < rate <= MAX_RATE:
                            return rate
        except Exception as e:
            logger.debug("计算预测速率失败: %s", e)
        return None

    def _compute_crossovers(self, valid: list, fits: dict) -> int:
        """两两配对计算交会点，返回找到的交会点总数"""
        crossover_count = 0
        now = datetime.now()

        for i in range(len(valid)):
            for j in range(i + 1, len(valid)):
                count = self._compute_pair(valid[i], valid[j], fits, now)
                if count:
                    crossover_count += count

        return crossover_count

    def _compute_pair(self, va: dict, vb: dict, fits: dict, now: datetime) -> int:
        """计算两个视频的交会点，成功则插入结果表格并返回 1"""
        ba = va.get("bvid", "")
        bb = vb.get("bvid", "")
        fa = fits.get(ba)
        fb = fits.get(bb)
        if not fa or not fb:
            return 0

        slope_a, intercept_a, base_a, pts_a = fa
        slope_b, intercept_b, base_b, pts_b = fb
        offset_h = (base_b - base_a).total_seconds() / 3600

        cross_h = _find_crossover(slope_a, intercept_a, slope_b, intercept_b, offset_h)
        if cross_h is None:
            return 0

        cross_views = slope_a * cross_h + intercept_a
        if cross_views < 0:
            return 0

        cross_time = base_a + timedelta(hours=cross_h)
        confidence = self._compute_confidence(slope_a, intercept_a, pts_a, slope_b, intercept_b, pts_b)
        time_str = cross_time.strftime("%Y-%m-%d %H:%M")
        remaining = cross_time - now
        remaining_str = ""
        if remaining.total_seconds() > 0:
            days = remaining.days
            hours = int(remaining.total_seconds() // 3600 % 24)
            remaining_str = f"{days}天{hours}小时" if days else f"{hours}小时"

        item = QTreeWidgetItem()
        item.setText(0, ba[:14])
        item.setText(1, bb[:14])
        item.setText(2, time_str)
        item.setText(3, _fmt_num(cross_views))
        item.setText(4, f"{slope_a:,.1f}")
        item.setText(5, f"{slope_b:,.1f}")
        item.setText(6, f"{confidence:.0%}")
        item.setText(7, remaining_str)
        for col in range(8):
            item.setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)

        self._tree.addTopLevelItem(item)
        return 1

    def _compute_confidence(self, slope_a, intercept_a, pts_a, slope_b, intercept_b, pts_b) -> float:
        """基于 R² 拟合优度和数据点数量计算综合置信度"""
        pts_a_fit = [((p[0] - pts_a[0][0]).total_seconds() / 3600, p[1]) for p in pts_a]
        pts_b_fit = [((p[0] - pts_b[0][0]).total_seconds() / 3600, p[1]) for p in pts_b]
        r2_a = self._r_squared(slope_a, intercept_a, pts_a_fit)
        r2_b = self._r_squared(slope_b, intercept_b, pts_b_fit)
        r2_avg = (r2_a + r2_b) / 2
        data_penalty = min(1.0, (len(pts_a) + len(pts_b)) / 20)
        return r2_avg * data_penalty

    def _r_squared(self, k: float, b: float, points) -> float:
        """计算 R² 拟合优度（决定系数）"""
        pts = list(points)
        if len(pts) < 2:
            return 0
        n = len(pts)
        y_mean = sum(p[1] for p in pts) / n
        ss_tot = sum((p[1] - y_mean) ** 2 for p in pts)
        ss_res = sum((p[1] - (k * p[0] + b)) ** 2 for p in pts)
        if ss_tot < 1e-12:
            return 1.0
        return max(0, 1 - ss_res / ss_tot)
