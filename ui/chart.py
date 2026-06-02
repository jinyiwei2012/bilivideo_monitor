"""
图表绘制模块 — Canvas 播放量趋势图

本模块提供基于 Tkinter Canvas 的播放量趋势图表绘制功能。支持三种渲染模式：

1. step（新增模式）：每个数据点 = v[i] - v[i-1]，显示播放量增量变化
   - 正值用绿色圆点，负值用红色圆点
   - 包含 0 基准线
   
2. delta（增量模式）：以第一条记录为基准，显示相对增长量
   - 折线图 + 面积填充 + 阈值虚线标注

3. full（全量模式）：显示完整播放量绝对值
   - 折线图 + 面积填充 + 阈值虚线标注

每种模式均支持：
- 预测投影（虚线延伸到预测值）
- 固定间隔数据点标注
- 最新值高亮标注框
- X 轴时间标签
- 图例
"""

from datetime import datetime
from ui.theme import C                                     # 颜色主题常量
from ui.helpers import fmt_num, abbrev, THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS  # UI 辅助

# ── 预测投影专用颜色（高亮蓝，与粉色折线形成对比） ──
_PRED_COLOR = "#0969da"                                    # 预测主色
_PRED_LIGHT = "#58a6ff"                                    # 预测亮色
_PRED_BG = "#ddf4ff"                                       # 预测背景色

# 增量绘制缓存：{canvas_id: {"struct_fp": (W,H,mode,pt_count), "series": {...}}}
_draw_cache = {}


def draw_chart_placeholder(canvas, text=None):
    """
    绘制空状态占位提示文本

    :param canvas: Tkinter Canvas 对象
    :param text: 提示文本，默认为「选择视频后显示播放量趋势图」
    """
    canvas.delete("all")
    w = canvas.winfo_width() or 600
    h = canvas.winfo_height() or 300
    canvas.create_text(
        w // 2, h // 2, text=text or "选择视频后显示播放量趋势图", fill=C["text_3"], font=("Microsoft YaHei UI", 11)
    )


def compute_chart_scale(views_list, history, ML, MR, MT, cw, ch):
    """
    计算图表数据范围及坐标转换函数

    :param views_list: 播放量列表
    :param history: 历史数据 [(timestamp, views), ...]
    :param ML: 左边距
    :param MR: 右边距
    :param MT: 上边距
    :param cw: 图表有效宽度
    :param ch: 图表有效高度
    :return: (min_v, max_v, span, px, py)
       - px(i): 第 i 个数据点的 X 坐标
       - py(v): 值 v 对应的 Y 坐标
    """
    min_v = min(views_list)
    max_v = max(views_list)
    span = max_v - min_v if max_v != min_v else max(1, max_v * 0.01)
    # 上下各留 5% 边距
    min_v = max(0, min_v - span * 0.05)
    max_v = max_v + span * 0.05
    span = max_v - min_v

    def px(i):
        """X 坐标：按索引比例映射到图表宽度"""
        return ML + (i / (len(history) - 1)) * cw

    def py(v):
        """Y 坐标：将值映射到图表高度（注意 Y 轴反转，值越大越靠上）"""
        return MT + ch - ((v - min_v) / span) * ch

    return min_v, max_v, span, px, py


def draw_threshold_lines(c, min_v, max_v, py, W, ML, MR, base_v=0):
    """
    绘制阈值虚线及标注

    在增量模式下，阈值会转换为相对位置后绘制（阈值 - 基准播放量）。

    :param c: Canvas 对象
    :param min_v: 图表 Y 轴最小值
    :param max_v: 图表 Y 轴最大值
    :param py: Y 坐标转换函数
    :param W: Canvas 总宽度
    :param ML: 左边距
    :param MR: 右边距
    :param base_v: 基准播放量（增量模式）
    """
    for thr, col in zip(THRESHOLDS, THRESH_COLORS):
        rel_thr = thr - base_v                              # 相对阈值（增量模式）
        if rel_thr <= 0:
            continue                                        # 低于基准的阈值不显示
        if min_v <= rel_thr <= max_v * 1.05:
            ty = py(rel_thr)
            c.create_line(ML, ty, W - MR, ty, fill=col, width=1, dash=(6, 4), tags="_thresh")
            c.create_text(W - MR + 2, ty, text=fmt_num(thr), anchor="w", fill=col, font=("Consolas", 8), tags="_thresh")


def _pick_dot_indices(n, max_points):
    """
    固定间隔选取数据点索引，确保首尾始终包含

    :param n: 数据点总数
    :param max_points: 最大显示点数
    :return: 选中的索引集合
    """
    num = max(2, min(n, max_points))
    step = (n - 1) / (num - 1)
    return sorted(set(min(n - 1, int(round(i * step))) for i in range(num)))


def draw_chart_series(c, history, px, py, ML, MT, W, MR, ch, views_list, max_points=20):
    """
    绘制面积填充 + 折线 + 固定间隔数据点

    :param c: Canvas 对象
    :param history: 历史数据
    :param px: X 坐标函数
    :param py: Y 坐标函数
    :param ML, MT, W, MR, ch: 图表边距和尺寸
    :param views_list: 播放量列表
    :param max_points: 最大数据点数
    """
    # 面积填充：从底部到每个数据点再回到底部，形成闭合多边形
    pts_area = [ML, MT + ch]
    for i, (_, v) in enumerate(history):
        pts_area += [px(i), py(v)]
    pts_area += [W - MR, MT + ch]
    area_id = c.create_polygon(pts_area, fill=C["chart_area"], outline="")

    # 折线
    pts_line = []
    for i, (_, v) in enumerate(history):
        pts_line += [px(i), py(v)]
    line_id = c.create_line(pts_line, fill=C["chart_line"], width=2.5, smooth=True, joinstyle="round", capstyle="round")

    # 固定间隔数据点（白色描边圆形标记）
    dot_ids = []
    for i in _pick_dot_indices(len(history), max_points):
        x, y = px(i), py(views_list[i])
        oid = c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=C["chart_dot"], outline=C["bg_base"], width=2)
        dot_ids.append((oid, i))
    return {"area": area_id, "line": line_id, "dots": dot_ids}


def _draw_projection(c, start_x, start_y, end_x, end_y, pred_val=0, is_step=False, base_v=0, raw_pred=0):
    """
    绘制预测虚拟点：虚线连接线 + 标准圆点 + 预测标签

    :param c: Canvas 对象
    :param start_x, start_y: 起始坐标（最后一个实际数据点）
    :param end_x, end_y: 终止坐标（预测点）
    :param pred_val: 预测值
    :param is_step: 是否为新增模式
    :param base_v: 基准值（增量模式）
    :param raw_pred: 原始预测值（未减基准）
    """
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
    """
    绘制最新值标注 + X 轴时间标签 + 图例 + 预测点

    :param c: Canvas 对象
    :param history: 历史数据
    :param views_list: 播放量列表
    :param px, py: 坐标转换函数
    :param W, H: Canvas 尺寸
    :param ML, MR, MB: 边距
    :param base_v: 基准值（增量模式）
    :param prediction: 预测结果字典（含 prediction 和 rate_per_sec）
    """
    # ── 最新值标注框（粉红色背景，数字靠左显示） ──
    lx = px(len(history) - 1)
    lv = py(views_list[-1])
    cur_val = views_list[-1]
    c.create_rectangle(lx - 32, lv - 22, lx + 32, lv - 6, fill=C["bilibili"], outline="", tags="_annot")
    label_text = f"+{fmt_num(cur_val)}" if cur_val > 0 and base_v else fmt_num(cur_val)
    c.create_text(lx, lv - 14, text=label_text, fill="#ffffff", font=("Consolas", 8, "bold"), tags="_annot")

    # ── 预测投影线 ──
    if prediction:
        w_pred = prediction.get("prediction", 0)
        pred_val = w_pred - base_v if base_v > 0 else w_pred
        if pred_val > 0:
            last_x = lx
            last_y = lv
            spacing = (W - ML - MR) / (len(history) - 1) if len(history) > 1 else 30
            proj_x = min(last_x + spacing, W - MR - 10)    # 不超过绘图区右侧
            proj_y = py(pred_val)
            _draw_projection(c, last_x, last_y, proj_x, proj_y, pred_val, is_step=False, base_v=base_v, raw_pred=w_pred)

    # ── X 轴时间标签（均匀分布，最多 6 个） ──
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
            c.create_text(px(i), H - MB + 6, text=t_str, fill=C["text_3"], font=("Consolas", 8), tags="_label")

    # ── 图例（左上角） ──
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
        c.create_rectangle(lx0, 8, lx0 + 8, 16, fill=col, outline="", tags="_annot")
        c.create_text(lx0 + 10, 12, text=label, anchor="w", fill=C["text_2"], font=("Consolas", 8), tags="_annot")
        lx0 += len(label) * 7 + 22


def draw_chart_grid(c, W, H, ML, MR, MT, MB, cw, ch, min_v, max_v, is_delta=False):
    """
    画坐标轴 + 网格线 + Y 轴标签

    :param c: Canvas 对象
    :param W, H: Canvas 尺寸
    :param ML, MR, MT, MB: 边距
    :param cw, ch: 绘图区宽高
    :param min_v, max_v: Y 轴范围
    :param is_delta: 是否为增量模式（标签加 + 号）
    """
    # Y 轴和 X 轴线
    c.create_line(ML, MT, ML, MT + ch, fill=C["border"], width=1)
    c.create_line(ML, MT + ch, W - MR, MT + ch, fill=C["border"], width=1)

    # 水平网格线 + Y 轴标签（等分 5 段）
    rows = 5
    for i in range(rows + 1):
        y = MT + i * ch // rows
        c.create_line(ML, y, W - MR, y, fill=C["border_sub"], dash=(3, 5))
        frac = 1 - i / rows
        val = min_v + frac * (max_v - min_v)
        label = f"+{abbrev(val)}" if is_delta and val > 0 else abbrev(val)
        c.create_text(ML - 4, y, text=label, anchor="e", fill=C["text_3"], font=("Consolas", 8), tags="_grid_label")


def draw_chart(canvas, history_data, bvid, video, FONT, mode="step", max_points=20, prediction=None):
    """
    主入口：根据 mode 选择图表渲染方式

    内置指纹缓存 + 增量更新机制：
      - 数据完全未变 → 跳过全部绘制
      - 结构未变（同尺寸/模式/点数）仅数据值变化 → 快速增量更新（coords 移动）
      - 结构变化（resize/切模式/点数增减） → delete("all") 全量重绘

    :param canvas: Tkinter Canvas 对象
    :param history_data: 历史数据字典 {bvid: [(timestamp, views), ...]}
    :param bvid: 当前选中的 BV 号
    :param video: 视频信息字典
    :param FONT: 字体元组
    :param mode: 渲染模式 ("step" / "delta" / "full")
    :param max_points: 最大显示数据点数
    :param prediction: 预测结果字典
    """
    history = history_data.get(bvid, [])
    pred_val = prediction.get("prediction", 0) if prediction else 0
    rate_val = prediction.get("rate_per_sec", 0) if prediction else 0

    c = canvas
    W = c.winfo_width() or 600
    H = c.winfo_height() or 300
    if W < 100 or H < 60:
        return

    # 指纹缓存：数据完全未变时跳过重绘
    fp = (bvid, mode, max_points, len(history), history[-1][1] if history else 0, pred_val, rate_val, W, H)
    if getattr(draw_chart, "_last_fp", None) == fp:
        return
    draw_chart._last_fp = fp

    # 边距
    ML, MR, MT, MB = 58, 20, 28, 36
    cw = W - ML - MR
    ch = H - MT - MB
    has_data = len(history) >= 2

    # 结构性指纹：尺寸 + 模式 + 数据点数 → 决定是否走快速更新路径
    struct_fp = (W, H, mode, len(history))
    cid = str(id(c))
    cache = _draw_cache.get(cid, {})

    if cache.get("struct_fp") == struct_fp and has_data and cache.get("series"):
        # 快速路径：结构未变，仅数据值变化 → 通过 coords() 增量更新
        if mode == "step":
            _fast_update_step(c, history, W, H, ML, MR, MT, MB, cw, ch, FONT, max_points, prediction, cache)
        else:
            _fast_update_delta_full(c, history, W, H, ML, MR, MT, MB, cw, ch, FONT, max_points, prediction, mode, cache)
        return

    # 全量重绘
    c.delete("all")
    _draw_cache.pop(cid, None)

    if not has_data:
        draw_chart_grid(c, W, H, ML, MR, MT, MB, cw, ch, 0, 1)
        c.create_text(W // 2, H // 2, text="数据点不足（需要至少2条记录）", fill=C["text_3"], font=FONT)
        _draw_cache[cid] = {"struct_fp": struct_fp}
        return

    if mode == "step":
        series = _draw_step_chart(c, history, W, H, ML, MR, MT, MB, cw, ch, FONT, max_points, prediction)
    else:
        series = _draw_delta_or_full_chart(c, history, W, H, ML, MR, MT, MB, cw, ch, FONT, max_points, prediction, mode)

    _draw_cache[cid] = {"struct_fp": struct_fp, "series": series, "mode": mode}


def _draw_delta_or_full_chart(c, history, W, H, ML, MR, MT, MB, cw, ch, FONT, max_points, prediction, mode):
    """
    绘制增量/全量模式图表

    增量模式下每个数据点减去起始值，预测值也相应调整。

    :param mode: "delta" 或 "full"
    """
    is_delta = mode == "delta" and history[0][1] > 0
    base_v = history[0][1] if is_delta else 0

    if is_delta:
        # 增量模式下每个数据点减去起始值，以第一条记录为 0 基准
        history = [(ts, v - base_v) for ts, v in history]

    views_list = [v for _, v in history]

    # 计算预测值（也需减去基准）
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
    series_ids = draw_chart_series(c, history, px, py, ML, MT, W, MR, ch, views_list, max_points)
    draw_chart_annotations(c, history, views_list, px, py, W, H, ML, MR, MB, base_v, prediction)

    # 右上角模式标签
    mode_name = "增量" if is_delta else "全量"
    shown = min(len(history), max_points)
    c.create_text(
        W - MR - 2,
        12,
        text=f"{mode_name} | {shown}/{len(history)} 点",
        anchor="e",
        fill=C["text_3"],
        font=("Consolas", 8),
        tags="_label",
    )
    if base_v:
        c.create_text(
            W - MR - 2, 24, text=f"起始 {fmt_num(base_v)}", anchor="e", fill=C["text_3"], font=("Consolas", 7),
            tags="_label",
        )
    return series_ids


def _step_compute_scale(values, ch, MT):
    """
    计算 step 图 Y 轴范围并返回 py(v) 转换函数

    step 模式下 Y 轴以 0 为中心，正负值各留 10% 边距。

    :param values: 增量值列表
    :param ch: 图表有效高度
    :param MT: 上边距
    :return: (v_min, v_max, span, py)
    """
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
    """
    画 step 图的网格、Y 轴标签、0 基准线

    step 模式特别绘制一条 0 基准线作为视觉参考。
    """
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
        c.create_text(ML - 4, y, text=f"{sign}{abbrev(val)}", anchor="e", fill=C["text_3"], font=("Consolas", 8), tags="_grid_label")
    # 0 基准线
    if v_min <= 0 <= v_max:
        zy = py(0)
        c.create_line(ML, zy, W - MR, zy, fill=C["text_3"], width=1)


def _step_draw_series(c, deltas, values, px, py, W, H, MR, MB, ML, pred_delta=None):
    """
    画 step 图的折线、数据点、最新值标注、X 轴时间标签 + 预测投影

    数据点颜色：正值=绿色(success), 负值=红色(danger)
    返回 {"line": line_id, "dots": [(oid, i), ...]} 供增量更新使用
    """
    # 折线
    pts = []
    for i, (_, v) in enumerate(deltas):
        pts += [px(i), py(v)]
    line_id = None
    if len(pts) >= 4:
        line_id = c.create_line(pts, fill=C["chart_line"], width=2.5, smooth=True, joinstyle="round", capstyle="round")

    # 数据点（正值绿色，负值红色）
    dot_ids = []
    for i, (_, v) in enumerate(deltas):
        x, y = px(i), py(v)
        dot_col = C["success"] if v >= 0 else C["danger"]
        oid = c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=dot_col, outline=C["bg_base"], width=2)
        dot_ids.append((oid, i))

    # 最新值标注
    last_v = values[-1]
    last_idx = len(deltas) - 1
    lx = px(last_idx)
    ly = py(last_v)
    label_text = f"+{fmt_num(last_v)}" if last_v >= 0 else fmt_num(last_v)
    c.create_rectangle(lx - 34, ly - 22, lx + 34, ly - 6, fill=C["chart_line"], outline="", tags="_annot")
    c.create_text(lx, ly - 14, text=label_text, fill="#ffffff", font=("Consolas", 8, "bold"), tags="_annot")

    # ── 预测投影（step 模式） ──
    if pred_delta is not None:
        spacing = (W - ML - MR) / (len(deltas) - 1) if len(deltas) > 1 else 30
        proj_x = min(lx + spacing, W - MR - 10)
        proj_y = py(pred_delta)
        _draw_projection(c, lx, ly, proj_x, proj_y, pred_delta, is_step=True)

    # X 轴时间标签
    step = max(1, len(deltas) // 6)
    for i, (ts, _) in enumerate(deltas):
        if i % step == 0 or i == len(deltas) - 1:
            try:
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts)
                t_str = ts.strftime("%m-%d %H:%M") if isinstance(ts, datetime) else str(ts)
            except Exception:
                t_str = ""
            c.create_text(px(i), H - MB + 6, text=t_str, fill=C["text_3"], font=("Consolas", 8), tags="_label")

    return {"line": line_id, "dots": dot_ids}


def _draw_step_chart(c, history, W, H, ML, MR, MT, MB, cw, ch, FONT, max_points, prediction=None):
    """
    绘制"新增"折线图 — 每个点是 v[i] - v[i-1]

    - 取尾部 N+1 条以产生 N 个差值
    - 0 基准线将正负值分隔
    - 支持预测下一个增量（利用 rate_per_sec × 平均时间间隔）
    - 底部显示统计信息（总增量、平均增量、预测增量）
    """
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
                pred_delta = rate * avg_interval             # 预测增量 = 速率 × 平均间隔

    # 将预测增量纳入 Y 轴范围
    values_for_scale = values + ([pred_delta] if pred_delta is not None else [])
    v_min, v_max, _, py = _step_compute_scale(values_for_scale, ch, MT)

    def px(i):
        """X 坐标（step 模式的索引映射）"""
        if len(deltas) == 1:
            return ML + cw / 2
        return ML + (i / (len(deltas) - 1)) * cw

    _step_draw_grid(c, W, H, ML, MR, MT, MB, ch, v_min, v_max, py)
    series_ids = _step_draw_series(c, deltas, values, px, py, W, H, MR, MB, ML, pred_delta)

    # 底部统计信息
    total = sum(values)
    avg = total / len(values) if values else 0
    info = f"新增 | {len(deltas)} 点 | 总+{fmt_num(total)} | 均+{fmt_num(avg)}"
    if pred_delta is not None:
        sign = "+" if pred_delta >= 0 else ""
        info += f" | 预测 {sign}{fmt_num(int(pred_delta))}"
    c.create_text(W - MR - 2, 12, text=info, anchor="e", fill=C["text_3"], font=("Consolas", 8), tags="_label")
    return series_ids


def _fast_update_delta_full(c, history, W, H, ML, MR, MT, MB, cw, ch, FONT, max_points, prediction, mode, cache):
    """快速增量更新路径（delta/full 模式）：仅数据值变化，结构不变。
    通过 coords() 移动系列元素，delete+redraw 标注层。"""
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

    series = cache.get("series", {})

    # ── 更新面积多边形坐标 ──
    area_id = series.get("area")
    if area_id:
        pts_area = [ML, MT + ch]
        for i, (_, v) in enumerate(history):
            pts_area += [px(i), py(v)]
        pts_area += [W - MR, MT + ch]
        c.coords(area_id, *pts_area)

    # ── 更新折线坐标 ──
    line_id = series.get("line")
    if line_id:
        pts_line = []
        for i, (_, v) in enumerate(history):
            pts_line += [px(i), py(v)]
        c.coords(line_id, *pts_line)

    # ── 更新数据点坐标 ──
    for oid, idx in series.get("dots", []):
        x, y = px(idx), py(views_list[idx])
        c.coords(oid, x - 4, y - 4, x + 4, y + 4)

    # ── 删除并重建所有标注层（网格标签、阈值线、最新值框、图例等） ──
    _redraw_delta_full_annotations(c, history, views_list, px, py, W, H, ML, MR, MT, MB, cw, ch,
                                   min_v, max_v, is_delta, base_v, prediction, FONT,
                                   mode, max_points)


def _redraw_delta_full_annotations(c, history, views_list, px, py, W, H, ML, MR, MT, MB, cw, ch,
                                   min_v, max_v, is_delta, base_v, prediction, FONT,
                                   mode, max_points):
    """重绘增量/全量模式的标注层（网格标签、阈值、标注）。"""
    # 删除旧标注（保留系列元素）
    for tag in ("_annot", "_grid_label", "_thresh", "_label"):
        c.delete(tag)

    # 网格 Y 轴标签
    rows = 5
    for i in range(rows + 1):
        y = MT + i * ch // rows
        frac = 1 - i / rows
        val = min_v + frac * (max_v - min_v)
        label = f"+{abbrev(val)}" if is_delta and val > 0 else abbrev(val)
        c.create_text(ML - 4, y, text=label, anchor="e", fill=C["text_3"], font=("Consolas", 8), tags="_grid_label")

    # 阈值线
    for thr, col in zip(THRESHOLDS, THRESH_COLORS):
        rel_thr = thr - base_v
        if rel_thr <= 0:
            continue
        if min_v <= rel_thr <= max_v * 1.05:
            ty = py(rel_thr)
            c.create_line(ML, ty, W - MR, ty, fill=col, width=1, dash=(6, 4), tags="_thresh")
            c.create_text(W - MR + 2, ty, text=fmt_num(thr), anchor="w", fill=col, font=("Consolas", 8), tags="_thresh")

    # 最新值标注框
    lx = px(len(history) - 1)
    lv = py(views_list[-1])
    cur_val = views_list[-1]
    c.create_rectangle(lx - 32, lv - 22, lx + 32, lv - 6, fill=C["bilibili"], outline="", tags="_annot")
    label_text = f"+{fmt_num(cur_val)}" if cur_val > 0 and base_v else fmt_num(cur_val)
    c.create_text(lx, lv - 14, text=label_text, fill="#ffffff", font=("Consolas", 8, "bold"), tags="_annot")

    # 预测投影
    if prediction:
        w_pred = prediction.get("prediction", 0)
        pv = w_pred - base_v if base_v > 0 else w_pred
        if pv > 0:
            last_x = lx
            last_y = lv
            spacing = (W - ML - MR) / (len(history) - 1) if len(history) > 1 else 30
            proj_x = min(last_x + spacing, W - MR - 10)
            proj_y = py(pv)
            _draw_projection(c, last_x, last_y, proj_x, proj_y, pv, is_step=False, base_v=base_v, raw_pred=w_pred)

    # X 轴时间标签
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
            c.create_text(px(i), H - MB + 6, text=t_str, fill=C["text_3"], font=("Consolas", 8), tags="_label")

    # 图例
    items = [("播放" + ("增长" if base_v else "量"), C["bilibili"])] + [
        (THRESHOLD_NAMES[i] + "阈值", THRESH_COLORS[i]) for i in range(3)
    ]
    if prediction:
        w_pred = prediction.get("prediction", 0)
        pv = w_pred - base_v if base_v > 0 else w_pred
        if pv > 0:
            items.append(("预测", _PRED_COLOR))
    lx0 = ML + 4
    for label, col in items:
        c.create_rectangle(lx0, 8, lx0 + 8, 16, fill=col, outline="", tags="_annot")
        c.create_text(lx0 + 10, 12, text=label, anchor="w", fill=C["text_2"], font=("Consolas", 8), tags="_annot")
        lx0 += len(label) * 7 + 22

    # 右上角模式标签
    mode_name = "增量" if is_delta else "全量"
    shown = min(len(history), max_points)
    c.create_text(W - MR - 2, 12, text=f"{mode_name} | {shown}/{len(history)} 点",
                  anchor="e", fill=C["text_3"], font=("Consolas", 8), tags="_label")
    if base_v:
        c.create_text(W - MR - 2, 24, text=f"起始 {fmt_num(base_v)}", anchor="e", fill=C["text_3"],
                      font=("Consolas", 7), tags="_label")


def _fast_update_step(c, history, W, H, ML, MR, MT, MB, cw, ch, FONT, max_points, prediction, cache):
    """快速增量更新路径（step 模式）：仅数据值变化，结构不变。
    通过 coords() 移动系列元素，delete+redraw 标注层。"""
    n_keep = min(len(history), max(2, max_points) + 1)
    tail = history[-n_keep:]
    deltas = [(tail[i][0], tail[i][1] - tail[i - 1][1]) for i in range(1, len(tail))]
    if not deltas:
        return
    values = [v for _, v in deltas]

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

    values_for_scale = values + ([pred_delta] if pred_delta is not None else [])
    v_min, v_max, _, py = _step_compute_scale(values_for_scale, ch, MT)

    def px(i):
        if len(deltas) == 1:
            return ML + cw / 2
        return ML + (i / (len(deltas) - 1)) * cw

    series = cache.get("series", {})

    # ── 更新折线坐标 ──
    line_id = series.get("line")
    if line_id:
        pts = []
        for i, (_, v) in enumerate(deltas):
            pts += [px(i), py(v)]
        if len(pts) >= 4:
            c.coords(line_id, *pts)

    # ── 更新数据点坐标和颜色 ──
    for oid, idx in series.get("dots", []):
        v = deltas[idx][1]
        x, y = px(idx), py(v)
        dot_col = C["success"] if v >= 0 else C["danger"]
        c.coords(oid, x - 4, y - 4, x + 4, y + 4)
        c.itemconfigure(oid, fill=dot_col)

    # ── 删除并重建标注层 ──
    for tag in ("_annot", "_grid_label", "_label"):
        c.delete(tag)

    # 网格 Y 轴标签
    rows = 5
    span = v_max - v_min
    for i in range(rows + 1):
        y = MT + i * ch // rows
        frac = 1 - i / rows
        val = v_min + frac * span
        sign = "+" if val > 0 else ""
        c.create_text(ML - 4, y, text=f"{sign}{abbrev(val)}", anchor="e", fill=C["text_3"],
                      font=("Consolas", 8), tags="_grid_label")

    # 最新值标注
    last_v = values[-1]
    last_idx = len(deltas) - 1
    lx = px(last_idx)
    ly = py(last_v)
    label_text = f"+{fmt_num(last_v)}" if last_v >= 0 else fmt_num(last_v)
    c.create_rectangle(lx - 34, ly - 22, lx + 34, ly - 6, fill=C["chart_line"], outline="", tags="_annot")
    c.create_text(lx, ly - 14, text=label_text, fill="#ffffff", font=("Consolas", 8, "bold"), tags="_annot")

    # 预测投影
    if pred_delta is not None:
        spacing = (W - ML - MR) / (len(deltas) - 1) if len(deltas) > 1 else 30
        proj_x = min(lx + spacing, W - MR - 10)
        proj_y = py(pred_delta)
        # _draw_projection creates items without tags; they'll be cleaned on next full redraw only
        _draw_projection(c, lx, ly, proj_x, proj_y, pred_delta, is_step=True)

    # X 轴时间标签
    step = max(1, len(deltas) // 6)
    for i, (ts, _) in enumerate(deltas):
        if i % step == 0 or i == len(deltas) - 1:
            try:
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts)
                t_str = ts.strftime("%m-%d %H:%M") if isinstance(ts, datetime) else str(ts)
            except Exception:
                t_str = ""
            c.create_text(px(i), H - MB + 6, text=t_str, fill=C["text_3"], font=("Consolas", 8), tags="_label")

    # 底部统计信息
    total = sum(values)
    avg = total / len(values) if values else 0
    info = f"新增 | {len(deltas)} 点 | 总+{fmt_num(total)} | 均+{fmt_num(avg)}"
    if pred_delta is not None:
        sign = "+" if pred_delta >= 0 else ""
        info += f" | 预测 {sign}{fmt_num(int(pred_delta))}"
    c.create_text(W - MR - 2, 12, text=info, anchor="e", fill=C["text_3"], font=("Consolas", 8), tags="_label")
