"""
图表绘制模块 - Canvas 播放量趋势图
"""
import tkinter as tk
from datetime import datetime
from ui.theme import C
from ui.helpers import fmt_num, abbrev, THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS


def draw_chart_placeholder(canvas):
    """绘制空状态占位"""
    canvas.delete("all")
    w = canvas.winfo_width()  or 600
    h = canvas.winfo_height() or 300
    canvas.create_text(w//2, h//2, text="选择视频后显示播放量趋势图",
                       fill=C["text_3"], font=("Microsoft YaHei UI", 11))


def compute_chart_scale(views_list, history, ML, MR, MT, cw, ch):
    """计算图表数据范围及坐标转换函数，返回 (min_v, max_v, span, px, py)"""
    min_v = min(views_list)
    max_v = max(views_list)
    span  = max_v - min_v if max_v != min_v else max(1, max_v * 0.01)
    min_v = max(0, min_v - span * 0.05)
    max_v = max_v + span * 0.05
    span  = max_v - min_v

    def px(i):
        return ML + (i / (len(history) - 1)) * cw

    def py(v):
        return MT + ch - ((v - min_v) / span) * ch

    return min_v, max_v, span, px, py


def draw_threshold_lines(c, min_v, max_v, py, W, ML, MR):
    """绘制阈值虚线及标注"""
    for thr, col in zip(THRESHOLDS, THRESH_COLORS):
        if min_v <= thr <= max_v * 1.05:
            ty = py(thr)
            c.create_line(ML, ty, W - MR, ty, fill=col, width=1, dash=(6, 4))
            c.create_text(W - MR + 2, ty, text=fmt_num(thr),
                          anchor="w", fill=col, font=("Consolas", 8))


def draw_chart_series(c, history, px, py, ML, MT, W, MR, ch):
    """绘制面积填充 + 折线 + 数据点"""
    pts_area = [ML, MT + ch]
    for i, (_, v) in enumerate(history):
        pts_area += [px(i), py(v)]
    pts_area += [W - MR, MT + ch]
    c.create_polygon(pts_area, fill=C["chart_area"], outline="", stipple="gray25")

    pts_line = []
    for i, (_, v) in enumerate(history):
        pts_line += [px(i), py(v)]
    c.create_line(pts_line, fill=C["chart_line"], width=2.5,
                  smooth=True, joinstyle="round", capstyle="round")

    every = max(1, len(history) // 8)
    for i, (_, v) in enumerate(history):
        if i % every == 0 or i == len(history) - 1:
            x, y = px(i), py(v)
            c.create_oval(x-4, y-4, x+4, y+4,
                          fill=C["chart_dot"], outline=C["bg_base"], width=2)


def draw_chart_annotations(c, history, views_list, px, py, W, H, ML, MR, MB):
    """绘制最新值标注 + X 轴时间标签 + 图例"""
    lx = px(len(history) - 1)
    lv = py(views_list[-1])
    c.create_rectangle(lx-32, lv-22, lx+32, lv-6, fill=C["bilibili"], outline="")
    c.create_text(lx, lv-14, text=fmt_num(views_list[-1]),
                  fill="#ffffff", font=("Consolas", 8, "bold"))

    step = max(1, len(history) // 6)
    for i, (ts, _) in enumerate(history):
        if i % step == 0 or i == len(history) - 1:
            try:
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts)
                t_str = ts.strftime("%H:%M") if isinstance(ts, datetime) else str(ts)
            except Exception:
                t_str = ""
            c.create_text(px(i), H - MB + 6, text=t_str,
                          fill=C["text_3"], font=("Consolas", 8))

    items = [("播放量", C["bilibili"])] + \
            [(THRESHOLD_NAMES[i] + "阈值", THRESH_COLORS[i]) for i in range(3)]
    lx0 = ML + 4
    for label, col in items:
        c.create_rectangle(lx0, 8, lx0+8, 16, fill=col, outline="")
        c.create_text(lx0+10, 12, text=label, anchor="w",
                      fill=C["text_2"], font=("Consolas", 8))
        lx0 += len(label) * 7 + 22

    c.create_text(W - MR - 2, 12, text=f"{len(history)} 个数据点",
                  anchor="e", fill=C["text_3"], font=("Consolas", 8))


def draw_chart_grid(c, W, H, ML, MR, MT, MB, cw, ch, min_v, max_v):
    """画坐标轴 + 网格"""
    c.create_line(ML, MT, ML, MT + ch, fill=C["border"], width=1)
    c.create_line(ML, MT + ch, W - MR, MT + ch, fill=C["border"], width=1)

    rows = 5
    for i in range(rows + 1):
        y = MT + i * ch // rows
        c.create_line(ML, y, W - MR, y, fill=C["border_sub"], dash=(3, 5))
        frac = 1 - i / rows
        val  = min_v + frac * (max_v - min_v)
        c.create_text(ML - 4, y, text=abbrev(val),
                      anchor="e", fill=C["text_3"], font=("Consolas", 8))


def draw_chart(canvas, history_data, bvid, video, FONT):
    """绘制完整图表（总入口）"""
    c = canvas
    c.delete("all")

    W = c.winfo_width()  or 600
    H = c.winfo_height() or 300
    if W < 100 or H < 60:
        return

    ML, MR, MT, MB = 58, 20, 28, 36
    cw = W - ML - MR
    ch = H - MT - MB

    history = history_data.get(bvid, [])
    has_data = len(history) >= 2

    if not has_data:
        draw_chart_grid(c, W, H, ML, MR, MT, MB, cw, ch, 0, 1)
        c.create_text(W//2, H//2, text="数据点不足（需要至少2条记录）",
                      fill=C["text_3"], font=FONT)
        return

    views_list = [v for _, v in history]
    min_v, max_v, span, px, py = compute_chart_scale(
        views_list, history, ML, MR, MT, cw, ch)

    draw_chart_grid(c, W, H, ML, MR, MT, MB, cw, ch, min_v, max_v)
    draw_threshold_lines(c, min_v, max_v, py, W, ML, MR)
    draw_chart_series(c, history, px, py, ML, MT, W, MR, ch)
    draw_chart_annotations(c, history, views_list, px, py, W, H, ML, MR, MB)
