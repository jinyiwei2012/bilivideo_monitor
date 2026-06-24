"""
图表绘制模块 - PyQt6 QGraphicsScene 版

播放量趋势图（增量/全量/新增模式 + 可配置数据点）
使用 QGraphicsView + QGraphicsScene 替代 Tkinter Canvas。
"""

import math
from datetime import datetime
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsTextItem,
    QGraphicsLineItem, QGraphicsRectItem, QWidget, QVBoxLayout,
)
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPolygonF,
)

from ui.theme import C
from ui.helpers import fmt_num, abbrev, THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS

_PRED_COLOR = "#0969da"
_PRED_LIGHT = "#58a6ff"
_PRED_BG = "#ddf4ff"


class ChartWidget(QWidget):
    """图表控件 - 使用 QGraphicsView 绘制播放量趋势图"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history_data = {}
        self._bvid = None
        self._video = None
        self._mode = "step"
        self._max_points = 20
        self._prediction = None
        # 指纹缓存
        self._chart_fp = None

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._scene = QGraphicsScene(self)
        self._view = QGraphicsView(self._scene)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setBackgroundBrush(QBrush(QColor(C["bg_base"])))
        self._view.setStyleSheet("border: none;")
        layout.addWidget(self._view)

    def update_chart(self, history_data, bvid, video, mode="step", max_points=20, prediction=None):
        """更新图表内容"""
        self._history_data = history_data
        self._bvid = bvid
        self._video = video
        self._mode = mode
        self._max_points = max_points
        self._prediction = prediction

        history = history_data.get(bvid, [])
        pred_val = prediction.get("prediction", 0) if prediction else 0
        rate_val = prediction.get("rate_per_sec", 0) if prediction else 0

        fp = (bvid, mode, max_points, len(history),
              history[-1][1] if history else 0, pred_val, rate_val)
        if fp == self._chart_fp:
            return
        self._chart_fp = fp

        self._scene.clear()
        self._redraw()

    def _redraw(self):
        """重新绘制图表"""
        history = self._history_data.get(self._bvid, [])
        if not history:
            self._draw_placeholder("选择视频后显示播放量趋势图")
            return

        W = self._view.width() or 600
        H = self._view.height() or 300
        if W < 100 or H < 60:
            return

        ML, MR, MT, MB = 58, 20, 28, 36
        cw = W - ML - MR
        ch = H - MT - MB

        if len(history) < 2:
            self._draw_grid(W, H, ML, MR, MT, MB, cw, ch, 0, 1)
            self._draw_text(W // 2, H // 2, "数据点不足（需要至少2条记录）",
                            QColor(C["text_3"]), 11, Qt.AlignmentFlag.AlignCenter)
            return

        if self._mode == "step":
            self._draw_step_chart(history, W, H, ML, MR, MT, MB, cw, ch)
        else:
            self._draw_delta_or_full_chart(history, W, H, ML, MR, MT, MB, cw, ch)

    def _draw_placeholder(self, text):
        """绘制空状态占位"""
        W = self._view.width() or 600
        H = self._view.height() or 300
        self._draw_text(W // 2, H // 2, text, QColor(C["text_3"]), 11,
                        Qt.AlignmentFlag.AlignCenter)

    def _draw_text(self, x, y, text, color, size=8, align=Qt.AlignmentFlag.AlignCenter):
        """在场景中绘制文本"""
        item = QGraphicsTextItem(text)
        font = QFont("Microsoft YaHei UI", size)
        item.setFont(font)
        item.setDefaultTextColor(color)

        if align == Qt.AlignmentFlag.AlignCenter:
            item.setPos(x - item.boundingRect().width() / 2,
                        y - item.boundingRect().height() / 2)
        elif align == Qt.AlignmentFlag.AlignRight:
            item.setPos(x - item.boundingRect().width(), y)
        elif align == Qt.AlignmentFlag.AlignLeft:
            item.setPos(x, y)
        else:
            item.setPos(x, y)
        self._scene.addItem(item)

    def _draw_line(self, x1, y1, x2, y2, color, width=1, dash=None):
        """在场景中绘制线段"""
        pen = QPen(QColor(color), width)
        if dash:
            pen.setDashPattern(dash)
        line = self._scene.addLine(x1, y1, x2, y2, pen)
        return line

    def _draw_rect(self, x1, y1, x2, y2, fill, outline=None, width=0):
        """在场景中绘制矩形"""
        rect = QRectF(x1, y1, x2 - x1, y2 - y1)
        brush = QBrush(QColor(fill))
        pen = QPen(QColor(outline or fill), width) if outline else QPen(Qt.PenStyle.NoPen)
        r = self._scene.addRect(rect, pen, brush)
        return r

    def _draw_oval(self, x, y, r, fill, outline=None, width=1):
        """在场景中绘制圆点"""
        rect = QRectF(x - r, y - r, r * 2, r * 2)
        brush = QBrush(QColor(fill))
        pen = QPen(QColor(outline or fill), width) if outline else QPen(Qt.PenStyle.NoPen)
        o = self._scene.addEllipse(rect, pen, brush)
        return o

    def _draw_polygon(self, points, fill):
        """在场景中绘制多边形（用于面积填充）"""
        poly = QPolygonF()
        for p in points:
            poly.append(QPointF(p[0], p[1]))
        brush = QBrush(QColor(fill))
        self._scene.addPolygon(poly, QPen(Qt.PenStyle.NoPen), brush)

    def _draw_grid(self, W, H, ML, MR, MT, MB, cw, ch, min_v, max_v, is_delta=False):
        """绘制坐标轴和网格"""
        # Y 轴
        self._draw_line(ML, MT, ML, MT + ch, C["border"])
        # X 轴
        self._draw_line(ML, MT + ch, W - MR, MT + ch, C["border"])

        rows = 5
        for i in range(rows + 1):
            y = MT + i * ch // rows
            self._draw_line(ML, y, W - MR, y, C["border_sub"], dash=(3, 5))
            frac = 1 - i / rows
            val = min_v + frac * (max_v - min_v)
            label = f"+{abbrev(val)}" if is_delta and val > 0 else abbrev(val)
            self._draw_text(ML - 4, y - 6, label, QColor(C["text_3"]), 8,
                            Qt.AlignmentFlag.AlignRight)

    def _compute_scale(self, values, cw, ch, ML, MR, MT):
        """计算坐标比例"""
        min_v = min(values)
        max_v = max(values)
        span = max_v - min_v if max_v != min_v else max(1, max_v * 0.01)
        min_v = max(0, min_v - span * 0.05)
        max_v = max_v + span * 0.05
        span = max_v - min_v

        def px(i, n):
            if n <= 1:
                return ML + cw / 2
            return ML + (i / (n - 1)) * cw

        def py(v):
            return MT + ch - ((v - min_v) / span) * ch

        return min_v, max_v, span, px, py

    def _draw_threshold_lines(self, min_v, max_v, py, W, ML, MR, base_v=0):
        """绘制阈值虚线"""
        for thr, name, col in zip(THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS):
            rel_thr = thr - base_v
            if rel_thr <= 0:
                continue
            if min_v <= rel_thr <= max_v * 1.05:
                ty = py(rel_thr)
                self._draw_line(ML, ty, W - MR, ty, col, dash=(6, 4))
                self._draw_text(W - MR + 2, ty - 6, fmt_num(thr), QColor(col), 8,
                                Qt.AlignmentFlag.AlignLeft)

    def _draw_series(self, history, px, py, ML, MT, W, MR, ch, views_list):
        """绘制面积 + 折线 + 数据点"""
        n = len(history)
        if n < 2:
            return

        # 面积填充
        pts = [[ML, MT + ch]]
        for i, (_, v) in enumerate(history):
            pts.append([px(i, n), py(v)])
        pts.append([W - MR, MT + ch])
        self._draw_polygon(pts, C["chart_area"])

        # 折线
        for i in range(n - 1):
            x1, y1 = px(i, n), py(views_list[i])
            x2, y2 = px(i + 1, n), py(views_list[i + 1])
            self._draw_line(x1, y1, x2, y2, C["chart_line"], width=2)

        # 数据点（固定间隔）
        max_pts = min(self._max_points, n)
        for i in self._pick_dot_indices(n, max_pts):
            x, y = px(i, n), py(views_list[i])
            self._draw_oval(x, y, 4, C["chart_dot"], C["bg_base"], 2)

    def _pick_dot_indices(self, n, max_points):
        """固定间隔选取数据点索引"""
        num = max(2, min(n, max_points))
        step_val = (n - 1) / (num - 1)
        return sorted(set(min(n - 1, int(round(i * step_val))) for i in range(num)))

    def _draw_annotations(self, history, views_list, px, py, W, H, ML, MR, MB, base_v=0):
        """绘制标注、时间轴、图例、预测点"""
        n = len(history)
        # 最新值标注
        lx = px(n - 1, n)
        lv = py(views_list[-1])
        cur_val = views_list[-1]
        self._draw_rect(lx - 32, lv - 22, lx + 32, lv - 6,
                        C["bilibili"])
        label_text = f"+{fmt_num(cur_val)}" if cur_val > 0 and base_v else fmt_num(cur_val)
        self._draw_text(lx, lv - 14, label_text, QColor("#ffffff"), 8,
                        Qt.AlignmentFlag.AlignCenter)

        # 预测投影
        if self._prediction:
            w_pred = self._prediction.get("prediction", 0)
            pred_val = w_pred - base_v if base_v > 0 else w_pred
            if pred_val > 0:
                last_x = lx
                last_y = lv
                spacing_val = (W - ML - MR) / (n - 1) if n > 1 else 30
                proj_x = min(last_x + spacing_val, W - MR - 10)
                proj_y = py(pred_val)
                # 虚线连接
                self._draw_line(last_x, last_y, proj_x, proj_y, _PRED_COLOR, dash=(4, 4))
                # 预测点
                self._draw_oval(proj_x, proj_y, 4, _PRED_COLOR, "#ffffff", 2)
                label = f"预测 {fmt_num(int(pred_val))}" if base_v else f"预测 {fmt_num(int(w_pred))}"
                self._draw_text(proj_x, proj_y - 14, label, QColor(_PRED_COLOR), 8,
                                Qt.AlignmentFlag.AlignCenter)

        # X 轴时间标签
        step = max(1, n // 6)
        for i, (ts, _) in enumerate(history):
            if i % step == 0 or i == n - 1:
                t_str = self._fmt_ts(ts)
                if i == 0:
                    t_str = ""
                self._draw_text(px(i, n), H - MB + 6, t_str, QColor(C["text_3"]), 8,
                                Qt.AlignmentFlag.AlignCenter)

        # 图例
        items = [("播放" + ("增长" if base_v else "量"), C["bilibili"])]
        for idx in range(min(3, len(THRESHOLD_NAMES))):
            items.append((THRESHOLD_NAMES[idx] + "阈值", THRESH_COLORS[idx]))
        if self._prediction:
            w_pred = self._prediction.get("prediction", 0)
            if w_pred > 0:
                items.append(("预测", _PRED_COLOR))

        lx0 = ML + 4
        for label, col in items:
            self._draw_rect(lx0, 8, lx0 + 8, 16, col)
            self._draw_text(lx0 + 10, 12, label, QColor(C["text_2"]), 8,
                            Qt.AlignmentFlag.AlignLeft)
            lx0 += len(label) * 7 + 22

    @staticmethod
    def _fmt_ts(ts) -> str:
        """安全格式化时间戳为显示字符串。"""
        try:
            ts_dt = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
            return ts_dt.strftime("%m-%d %H:%M") if isinstance(ts_dt, datetime) else str(ts)
        except (ValueError, TypeError):
            return ""

    def _draw_delta_or_full_chart(self, history, W, H, ML, MR, MT, MB, cw, ch):
        """绘制增量/全量模式"""
        is_delta = self._mode == "delta" and history[0][1] > 0
        base_v = history[0][1] if is_delta else 0

        if is_delta:
            history = [(ts, v - base_v) for ts, v in history]

        views_list = [v for _, v in history]
        pred_val = None
        if self._prediction:
            w_pred = self._prediction.get("prediction", 0)
            pv = w_pred - base_v if base_v > 0 else w_pred
            if pv > 0:
                pred_val = pv

        views_for_scale = views_list + ([pred_val] if pred_val else [])
        min_v, max_v, span, px, py = self._compute_scale(views_for_scale, cw, ch, ML, MR, MT)

        self._draw_grid(W, H, ML, MR, MT, MB, cw, ch, min_v, max_v, is_delta=is_delta)
        self._draw_threshold_lines(min_v, max_v, py, W, ML, MR, base_v)
        self._draw_series(history, px, py, ML, MT, W, MR, ch, views_list)
        self._draw_annotations(history, views_list, px, py, W, H, ML, MR, MB, base_v)

        mode_name = "增量" if is_delta else "全量"
        shown = min(len(history), self._max_points)
        self._draw_text(W - MR - 2, 12,
                        f"{mode_name} | {shown}/{len(history)} 点",
                        QColor(C["text_3"]), 8, Qt.AlignmentFlag.AlignRight)
        if base_v:
            self._draw_text(W - MR - 2, 24, f"起始 {fmt_num(base_v)}",
                            QColor(C["text_3"]), 7, Qt.AlignmentFlag.AlignRight)

    def _draw_step_chart(self, history, W, H, ML, MR, MT, MB, cw, ch):
        """绘制新增折线图"""
        n_keep = min(len(history), max(2, self._max_points) + 1)
        tail = history[-n_keep:]
        deltas = [(tail[i][0], tail[i][1] - tail[i - 1][1]) for i in range(1, len(tail))]
        if not deltas:
            self._draw_text(W // 2, H // 2, "数据点不足", QColor(C["text_3"]), 11,
                            Qt.AlignmentFlag.AlignCenter)
            return

        values = [v for _, v in deltas]
        n = len(deltas)

        # 计算预测增量
        pred_delta = None
        if self._prediction and n >= 2:
            rate = self._prediction.get("rate_per_sec", 0)
            if rate > 0:
                intervals = []
                for i in range(1, len(tail)):
                    t1, t2 = tail[i - 1][0], tail[i][0]
                    if isinstance(t1, str):
                        t1 = datetime.fromisoformat(t1)
                    if isinstance(t2, str):
                        t2 = datetime.fromisoformat(t2)
                    if isinstance(t1, datetime) and isinstance(t2, datetime):
                        intervals.append((t2 - t1).total_seconds())
                if intervals:
                    avg_interval = sum(intervals) / len(intervals)
                    pred_delta = rate * avg_interval

        values_for_scale = values + ([pred_delta] if pred_delta is not None else [])
        v_min = min(0, min(values_for_scale))
        v_max = max(0, max(values_for_scale))
        if v_max == v_min:
            v_max = v_min + 1
        span = v_max - v_min
        pad = span * 0.1
        v_min -= pad
        v_max += pad
        span = v_max - v_min

        def py(v):
            return MT + ch - ((v - v_min) / span) * ch

        def px(i):
            if n <= 1:
                return ML + cw / 2
            return ML + (i / (n - 1)) * cw

        # 网格
        self._draw_grid(W, H, ML, MR, MT, MB, cw, ch, v_min, v_max, is_delta=True)
        # 0 基准线
        if v_min <= 0 <= v_max:
            zy = py(0)
            self._draw_line(ML, zy, W - MR, zy, C["text_3"])

        # 折线
        for i in range(n - 1):
            x1, y1 = px(i), py(values[i])
            x2, y2 = px(i + 1), py(values[i + 1])
            self._draw_line(x1, y1, x2, y2, C["chart_line"], width=2)

        # 数据点
        for i, v in enumerate(values):
            x, y = px(i), py(v)
            dot_col = C["success"] if v >= 0 else C["danger"]
            self._draw_oval(x, y, 4, dot_col, C["bg_base"], 2)

        # 最新标注
        last_v = values[-1]
        lx = px(n - 1)
        ly = py(last_v)
        label_text = f"+{fmt_num(last_v)}" if last_v >= 0 else fmt_num(last_v)
        self._draw_rect(lx - 34, ly - 22, lx + 34, ly - 6, C["chart_line"])
        self._draw_text(lx, ly - 14, label_text, QColor("#ffffff"), 8,
                        Qt.AlignmentFlag.AlignCenter)

        # 预测投影
        if pred_delta is not None:
            spacing_val = (W - ML - MR) / (n - 1) if n > 1 else 30
            proj_x = min(lx + spacing_val, W - MR - 10)
            proj_y = py(pred_delta)
            self._draw_line(lx, ly, proj_x, proj_y, _PRED_COLOR, dash=(4, 4))
            self._draw_oval(proj_x, proj_y, 4, _PRED_COLOR, "#ffffff", 2)
            sign = "+" if pred_delta >= 0 else ""
            self._draw_text(proj_x, proj_y - 14, f"预测 {sign}{fmt_num(int(pred_delta))}",
                            QColor(_PRED_COLOR), 8, Qt.AlignmentFlag.AlignCenter)

        # X 轴时间标签
        step = max(1, n // 6)
        for i, (ts, _) in enumerate(deltas):
            if i % step == 0 or i == n - 1:
                t_str = self._fmt_ts(ts)
                self._draw_text(px(i), H - MB + 6, t_str, QColor(C["text_3"]), 8,
                                Qt.AlignmentFlag.AlignCenter)

        # 统计
        total = sum(values)
        avg = total / n if n else 0
        info = f"新增 | {n} 点 | 总+{fmt_num(total)} | 均+{fmt_num(avg)}"
        if pred_delta is not None:
            sign = "+" if pred_delta >= 0 else ""
            info += f" | 预测 {sign}{fmt_num(int(pred_delta))}"
        self._draw_text(W - MR - 2, 12, info, QColor(C["text_3"]), 8,
                        Qt.AlignmentFlag.AlignRight)


def draw_chart_placeholder(canvas, text=None):
    """兼容旧接口 — 占位函数"""
    # QGraphicsScene 版通过 ChartWidget.update_chart 直接处理
    pass


def draw_chart(canvas, history_data, bvid, video, FONT, mode="step", max_points=20, prediction=None):
    """兼容旧接口 — 直接调用 ChartWidget.update_chart"""
    if isinstance(canvas, ChartWidget):
        canvas.update_chart(history_data, bvid, video, mode, max_points, prediction)
