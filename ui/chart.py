"""
图表绘制模块 - Canvas 播放量趋势图（增量/全量模式 + 可配置数据点）
"""

from datetime import datetime
from ui.theme import C
from ui.helpers import fmt_num, abbrev, THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS

# 预测投影专用颜色（高亮蓝，与粉色折线形成对比）
_PRED_COLOR = "#0969da"
_PRED_LIGHT = "#58a6ff"
_PRED_BG = "#ddf4ff"


def draw_chart_placeholder(canvas, text=None):
    """绘制空状态占位"""
    canvas.delete("all")
    w = canvas.winfo_width() or 600
    h = canvas.winfo_height() or 300
    canvas.create_text(
        w // 2, h // 2, text=text or "选择视频后显示播放量趋势图", fill=C["text_3"], font=("Microsoft YaHei UI", 11)
    )


def compute_chart_scale(views_list, history, ML, MR, MT, cw, ch):
    """计算图表数据范围及坐标转换函数，返回 (min_v, max_v, span, px, py)"""
    min_v = min(views_list)
    max_v = max(views_list)
    span = max_v - min_v if max_v != min_v else max(1, max_v * 0.01)
    min_v = max(0, min_v - span * 0.05)
    max_v = max_v + span * 0.05
    span = max_v - min_v

    def px(i):
        return ML + (i / (len(history) - 1)) * cw

    def py(v):
        return MT + ch - ((v - min_v) / span) * ch

    return min_v, max_v, span, px, py


def draw_threshold_lines(c, min_v, max_v, py, W, ML, MR, base_v=0):
    """绘制阈值虚线及标注（增量模式下转换为相对位置）"""
    for thr, col in zip(THRESHOLDS, THRESH_COLORS):
        rel_thr = thr - base_v
        if rel_thr <= 0:
            continue
        if min_v <= rel_thr <= max_v * 1.05:
            ty = py(rel_thr)
            c.create_line(ML, ty, W - MR, ty, fill=col, width=1, dash=(6, 4))
            c.create_text(W - MR + 2, ty, text=fmt_num(thr), anchor="w", fill=col, font=("Consolas", 8))


def _pick_dot_indices(n, max_points):
    """固定间隔选取数据点索引"""
    num = max(2, min(n, max_points))
    step = (n - 1) / (num - 1)
    return sorted(set(min(n - 1, int(round(i * step))) for i in range(num)))


def draw_chart_series(c, history, px, py, ML, MT, W, MR, ch, views_list, max_points=20):
    """绘制面积填充 + 折线 + 固定间隔数据点"""
    pts_area = [ML, MT + ch]
    for i, (_, v) in enumerate(history):
        pts_area += [px(i), py(v)]
    pts_area += [W - MR, MT + ch]
    c.create_polygon(pts_area, fill=C["chart_area"], outline="", stipple="gray25")

    pts_line = []
    for i, (_, v) in enumerate(history):
        pts_line += [px(i), py(v)]
    c.create_line(pts_line, fill=C["chart_line"], width=2.5, smooth=True, joinstyle="round", capstyle="round")

    for i in _pick_dot_indices(len(history), max_points):
        x, y = px(i), py(views_list[i])
        c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=C["chart_dot"], outline=C["bg_base"], width=2)


def _draw_projection(c, start_x, start_y, end_x, end_y, pred_val=0, is_step=False, base_v=0, raw_pred=0):
    """绘制预测虚拟点：虚线连接线 + 标准圆点 + 预测标签"""
    # 虚线连接线（从最后一个实际点到预测点）
    c.create_line(start_x, start_y, end_x, end_y, fill=_PRED_COLOR, width=2, dash=(4, 4), capstyle="round")

    # 标准圆点（和实际数据点一致：r=4，白色描边 width=2）
    c.create_oval(end_x - 4, end_y - 4, end_x + 4, end_y + 4, fill=_PRED_COLOR, outline="#ffffff", width=2)

    # 预测标签（悬浮在圆点上方）
    if is_step:
        sign = "+" if pred_val >= 0 else ""
        label = f"预测 {sign}{fmt_num(int(pred_val))}"
    else:
        label = f"预测 {fmt_num(int(pred_val))}" if base_v else f"预测 {fmt_num(raw_pred)}"
    c.create_text(end_x, end_y - 14, text=label, anchor="s", fill=_PRED_COLOR, font=("Consolas", 8, "bold"))


def draw_chart_annotations(c, history, views_list, px, py, W, H, ML, MR, MB, base_v=0, prediction=None):
    """绘制最新值标注 + X 轴时间标签 + 图例 + 预测点"""
    lx = px(len(history) - 1)
    lv = py(views_list[-1])
    cur_val = views_list[-1]
    c.create_rectangle(lx - 32, lv - 22, lx + 32, lv - 6, fill=C["bilibili"], outline="")
    label_text = f"+{fmt_num(cur_val)}" if cur_val > 0 and base_v else fmt_num(cur_val)
    c.create_text(lx, lv - 14, text=label_text, fill="#ffffff", font=("Consolas", 8, "bold"))

    # ── 预测投影线 ─────────────────────────────────
    if prediction:
        w_pred = prediction.get("prediction", 0)
        pred_val = w_pred - base_v if base_v > 0 else w_pred
        if pred_val > 0:
            last_x = lx
            last_y = lv
            spacing = (W - ML - MR) / (len(history) - 1) if len(history) > 1 else 30
            proj_x = min(last_x + spacing, W - MR - 10)
            proj_y = py(pred_val)
            _draw_projection(c, last_x, last_y, proj_x, proj_y, pred_val, is_step=False, base_v=base_v, raw_pred=w_pred)

    # ── X 轴时间标签 ────────────────────
    _X_LABEL_COUNT = 6
    step = max(1, len(history) // _X_LABEL_COUNT)
    for i, (ts, _) in enumerate(history):
        if i % step == 0 or i == len(history) - 1:
            try:
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts)
                t_str = ts.strftime("%m-%d %H:%M") if isinstance(ts, datetime) else str(ts)
            except Exception:
                t_str = ""
            c.create_text(px(i), H - MB + 6, text=t_str, fill=C["text_3"], font=("Consolas", 8))

    items = [("播放" + ("增长" if base_v else "量"), C["bilibili"])] + [
        (THRESHOLD_NAMES[i] + "阈值", THRESH_COLORS[i]) for i in range(3)
    ]
    if prediction:
        w_pred = prediction.get("prediction", 0)
        pred_val = w_pred - base_v if base_v > 0 else w_pred
        if pred_val > 0:
            items.append(("预测", _PRED_COLOR))
    lx0 = ML + 4
    for label, col in items:
        c.create_rectangle(lx0, 8, lx0 + 8, 16, fill=col, outline="")
        c.create_text(lx0 + 10, 12, text=label, anchor="w", fill=C["text_2"], font=("Consolas", 8))
        lx0 += len(label) * 7 + 22


def draw_chart_grid(c, W, H, ML, MR, MT, MB, cw, ch, min_v, max_v, is_delta=False):
    """画坐标轴 + 网格"""
    c.create_line(ML, MT, ML, MT + ch, fill=C["border"], width=1)
    c.create_line(ML, MT + ch, W - MR, MT + ch, fill=C["border"], width=1)

    rows = 5
    for i in range(rows + 1):
        y = MT + i * ch // rows
        c.create_line(ML, y, W - MR, y, fill=C["border_sub"], dash=(3, 5))
        frac = 1 - i / rows
        val = min_v + frac * (max_v - min_v)
        label = f"+{abbrev(val)}" if is_delta and val > 0 else abbrev(val)
        c.create_text(ML - 4, y, text=label, anchor="e", fill=C["text_3"], font=("Consolas", 8))


def draw_chart(canvas, history_data, bvid, video, FONT, mode="step", max_points=20, prediction=None):
    history = history_data.get(bvid, [])
    pred_val = prediction.get("prediction", 0) if prediction else 0
    rate_val = prediction.get("rate_per_sec", 0) if prediction else 0
    fp = (bvid, mode, max_points, len(history), history[-1][1] if history else 0, pred_val, rate_val)
    if getattr(draw_chart, "_last_fp", None) == fp:
        return
    draw_chart._last_fp = fp

    c = canvas
    c.delete("all")

    W = c.winfo_width() or 600
    H = c.winfo_height() or 300
    if W < 100 or H < 60:
        return

    ML, MR, MT, MB = 58, 20, 28, 36
    cw = W - ML - MR
    ch = H - MT - MB

    has_data = len(history) >= 2

    if not has_data:
        draw_chart_grid(c, W, H, ML, MR, MT, MB, cw, ch, 0, 1)
        c.create_text(W // 2, H // 2, text="数据点不足（需要至少2条记录）", fill=C["text_3"], font=FONT)
        return

    if mode == "step":
        _draw_step_chart(c, history, W, H, ML, MR, MT, MB, cw, ch, FONT, max_points, prediction)
        return

    _draw_delta_or_full_chart(c, history, W, H, ML, MR, MT, MB, cw, ch, FONT, max_points, prediction, mode)


def _draw_delta_or_full_chart(c, history, W, H, ML, MR, MT, MB, cw, ch, FONT, max_points, prediction, mode):
    is_delta = mode == "delta" and history[0][1] > 0
    base_v = history[0][1] if is_delta else 0

    if is_delta:
        history = [(ts, v - base_v) for ts, v in history]

    views_list = [v for _, v in history]

    pred_val = None
    if prediction:
        w_pred = prediction.get("prediction", 0)
        pv = w_pred - base_v if base_v > 0 else w_pred
        if pv > 0:
            pred_val = pv
    views_for_scale = views_list + ([pred_val] if pred_val else [])
    min_v, max_v, span, px, py = compute_chart_scale(views_for_scale, history, ML, MR, MT, cw, ch)

    draw_chart_grid(c, W, H, ML, MR, MT, MB, cw, ch, min_v, max_v, is_delta=is_delta)
    draw_threshold_lines(c, min_v, max_v, py, W, ML, MR, base_v)
    draw_chart_series(c, history, px, py, ML, MT, W, MR, ch, views_list, max_points)
    draw_chart_annotations(c, history, views_list, px, py, W, H, ML, MR, MB, base_v, prediction)

    mode_name = "增量" if is_delta else "全量"
    shown = min(len(history), max_points)
    c.create_text(
        W - MR - 2,
        12,
        text=f"{mode_name} | {shown}/{len(history)} 点",
        anchor="e",
        fill=C["text_3"],
        font=("Consolas", 8),
    )
    if base_v:
        c.create_text(
            W - MR - 2, 24, text=f"起始 {fmt_num(base_v)}", anchor="e", fill=C["text_3"], font=("Consolas", 7)
        )


def _step_compute_scale(values, ch, MT):
    """计算 step 图 Y 轴范围并返回 py(v) 转换函数"""
    v_min = min(0, min(values))
    v_max = max(0, max(values))
    if v_max == v_min:
        v_max = v_min + 1
    span = v_max - v_min
    pad = span * 0.1
    v_min -= pad
    v_max += pad
    span = v_max - v_min

    def py(v):
        return MT + ch - ((v - v_min) / span) * ch

    return v_min, v_max, span, py


def _step_draw_grid(c, W, H, ML, MR, MT, MB, ch, v_min, v_max, py):
    """画 step 图的网格、Y 轴标签、0 基准线"""
    c.create_line(ML, MT, ML, MT + ch, fill=C["border"], width=1)
    c.create_line(ML, MT + ch, W - MR, MT + ch, fill=C["border"], width=1)
    rows = 5
    span = v_max - v_min
    for i in range(rows + 1):
        y = MT + i * ch // rows
        c.create_line(ML, y, W - MR, y, fill=C["border_sub"], dash=(3, 5))
        frac = 1 - i / rows
        val = v_min + frac * span
        sign = "+" if val > 0 else ""
        c.create_text(ML - 4, y, text=f"{sign}{abbrev(val)}", anchor="e", fill=C["text_3"], font=("Consolas", 8))
    if v_min <= 0 <= v_max:
        zy = py(0)
        c.create_line(ML, zy, W - MR, zy, fill=C["text_3"], width=1)


def _step_draw_series(c, deltas, values, px, py, W, H, MR, MB, ML, pred_delta=None):
    """画 step 图的折线、数据点、最新值标注、X 轴时间标签 + 预测投影"""
    pts = []
    for i, (_, v) in enumerate(deltas):
        pts += [px(i), py(v)]
    if len(pts) >= 4:
        c.create_line(pts, fill=C["chart_line"], width=2.5, smooth=True, joinstyle="round", capstyle="round")

    for i, (_, v) in enumerate(deltas):
        x, y = px(i), py(v)
        dot_col = C["success"] if v >= 0 else C["danger"]
        c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=dot_col, outline=C["bg_base"], width=2)

    last_v = values[-1]
    last_idx = len(deltas) - 1
    lx = px(last_idx)
    ly = py(last_v)
    label_text = f"+{fmt_num(last_v)}" if last_v >= 0 else fmt_num(last_v)
    c.create_rectangle(lx - 34, ly - 22, lx + 34, ly - 6, fill=C["chart_line"], outline="")
    c.create_text(lx, ly - 14, text=label_text, fill="#ffffff", font=("Consolas", 8, "bold"))

    # ── 预测投影（step 模式） ──
    if pred_delta is not None:
        spacing = (W - ML - MR) / (len(deltas) - 1) if len(deltas) > 1 else 30
        proj_x = min(lx + spacing, W - MR - 10)
        proj_y = py(pred_delta)
        _draw_projection(c, lx, ly, proj_x, proj_y, pred_delta, is_step=True)

    step = max(1, len(deltas) // 6)
    for i, (ts, _) in enumerate(deltas):
        if i % step == 0 or i == len(deltas) - 1:
            try:
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts)
                t_str = ts.strftime("%m-%d %H:%M") if isinstance(ts, datetime) else str(ts)
            except Exception:
                t_str = ""
            c.create_text(px(i), H - MB + 6, text=t_str, fill=C["text_3"], font=("Consolas", 8))


def _draw_step_chart(c, history, W, H, ML, MR, MT, MB, cw, ch, FONT, max_points, prediction=None):
    """绘制"新增"折线图 — 每个点是 v[i] - v[i-1]，0 基线，仅显示最近 N 点。"""
    # 取尾部 N+1 条以产生 N 个差值
    n_keep = min(len(history), max(2, max_points) + 1)
    tail = history[-n_keep:]
    deltas = [(tail[i][0], tail[i][1] - tail[i - 1][1]) for i in range(1, len(tail))]
    if not deltas:
        c.create_text(W // 2, H // 2, text="数据点不足（需要至少2条记录）", fill=C["text_3"], font=FONT)
        return

    values = [v for _, v in deltas]

    # ── 计算预测的下一个增量 ──
    pred_delta = None
    if prediction and len(deltas) >= 2:
        rate = prediction.get("rate_per_sec", 0)
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

    # 将预测增量纳入 Y 轴范围
    values_for_scale = values + ([pred_delta] if pred_delta is not None else [])
    v_min, v_max, _, py = _step_compute_scale(values_for_scale, ch, MT)

    def px(i):
        if len(deltas) == 1:
            return ML + cw / 2
        return ML + (i / (len(deltas) - 1)) * cw

    _step_draw_grid(c, W, H, ML, MR, MT, MB, ch, v_min, v_max, py)
    _step_draw_series(c, deltas, values, px, py, W, H, MR, MB, ML, pred_delta)

    total = sum(values)
    avg = total / len(values) if values else 0
    info = f"新增 | {len(deltas)} 点 | 总+{fmt_num(total)} | 均+{fmt_num(avg)}"
    if pred_delta is not None:
        sign = "+" if pred_delta >= 0 else ""
        info += f" | 预测 {sign}{fmt_num(int(pred_delta))}"
    c.create_text(W - MR - 2, 12, text=info, anchor="e", fill=C["text_3"], font=("Consolas", 8))
