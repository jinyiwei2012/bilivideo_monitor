"""
数据对比界面（重构版）
- 标签1「趋势图」：折线图，多视频对比，支持 8 种指标切换
- 标签2「快照对比」：柱状图，任意选视频 × 任意选时间点，7 种指标，里程碑数据也可叠加
"""
import tkinter as tk
from tkinter import ttk, messagebox, LEFT, RIGHT, BOTH, X, Y, TOP, BOTTOM
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import math

from core.database import db
from ui.main_gui import C

# ── 颜色表 ────────────────────────────────────────────────────────────────────
PALETTE = [
    "#fb7299",  # bilibili 粉
    "#23ade5",  # 蓝
    "#42b983",  # 绿
    "#f5a623",  # 橙
    "#9b59b6",  # 紫
    "#e74c3c",  # 红
    "#1abc9c",  # 青绿
    "#e67e22",  # 棕橙
    "#3498db",  # 浅蓝
    "#2ecc71",  # 亮绿
]

PALETTE_LIGHT = [
    "#ff8db5", "#4bbfea", "#66cba0", "#f7b84e",
    "#b07cc6", "#e57878", "#45d1b8", "#f0a35a",
    "#5aaee8", "#5ddda2",
]

# ── 指标定义 ──────────────────────────────────────────────────────────────────
METRICS = [
    ("view_count",     "播放量"),
    ("like_count",     "点赞"),
    ("coin_count",     "硬币"),
    ("favorite_count", "收藏"),
    ("share_count",    "分享"),
    ("danmaku_count",  "弹幕"),
    ("reply_count",    "评论"),
    ("like_view_ratio","点赞率(%)"),
]

# 图表边距
_ML, _MR, _MT, _MB = 76, 20, 36, 48
_BAR_ML, _BAR_MR, _BAR_MT, _BAR_MB = 76, 20, 36, 60


def _fmt(n):
    """格式化大数字"""
    if n is None:
        return "N/A"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "N/A"
    if n >= 1e8:
        return f"{n/1e8:.2f}亿"
    if n >= 1e4:
        return f"{n/1e4:.1f}万"
    return str(int(n))


# ══════════════════════════════════════════════════════════════════════════════
class DataComparisonWindow:
    """数据对比窗口（趋势折线图 + 快照柱状图）"""

    def __init__(self, parent=None,
                 monitored_videos: Optional[List[Dict]] = None,
                 history_data: Optional[Dict] = None,
                 video_dbs: Optional[Dict] = None,
                 on_add_monitor=None):
        self.window = tk.Toplevel(parent)
        self.window.title("数据对比")
        self.window.geometry("1100x780")
        self.window.minsize(850, 600)
        self.window.transient(parent)

        self.monitored_videos = monitored_videos or []
        self.history_data     = history_data or {}
        self.video_dbs        = video_dbs    or {}
        self.on_add_monitor   = on_add_monitor

        # 状态
        self._trend_selected: List[Dict] = []
        self._snap_selected:  List[Dict] = []
        self._snap_points:    Dict[str, List] = {}   # bvid -> sorted records
        self._snap_chosen_ts: Dict[str, List[str]] = {}  # bvid -> [ts_str, ...]
        self._snap_ts_avail:  List[str] = []          # 当前可用时间点列表

        self._trend_metric = tk.StringVar(value="view_count")
        self._snap_metric  = tk.StringVar(value="view_count")

        self._setup_ui()

    # ══════════════════════════════════════════════════════════════════════════
    # ── 整体布局 ──────────────────────────────────────────────────────────────
    def _setup_ui(self):
        nb = ttk.Notebook(self.window)
        nb.pack(fill=BOTH, expand=True, padx=8, pady=8)

        self._tab_trend = tk.Frame(nb)
        self._tab_snap  = tk.Frame(nb)
        self._tab_entry = tk.Frame(nb)

        nb.add(self._tab_trend, text="  📈  趋势图  ")
        nb.add(self._tab_snap,  text="  📊  快照对比  ")
        nb.add(self._tab_entry, text="  📥  数据录入  ")

        self._build_trend_tab()
        self._build_snap_tab()
        self._build_entry_tab()

    # ══════════════════════════════════════════════════════════════════════════
    # ── 标签1：趋势图 ─────────────────────────────────────────────────────────
    def _build_trend_tab(self):
        f = self._tab_trend

        # 顶栏
        top = tk.Frame(f)
        top.pack(fill=X, padx=10, pady=(8, 4))

        # 左：视频列表
        left = tk.LabelFrame(top, text="选择视频（可多选）", padx=6, pady=4)
        left.pack(side=LEFT, fill=BOTH, expand=True)

        lf = tk.Frame(left)
        lf.pack(fill=BOTH, expand=True)
        self._trend_listbox = tk.Listbox(lf, selectmode=tk.MULTIPLE,
                                         height=4, exportselection=False,
                                         bg=C.get("entry_bg","#1e2330"),
                                         fg=C.get("text_1","#e6edf3"),
                                         selectbackground=C.get("accent","#fb7299"),
                                         font=("Microsoft YaHei UI", 9))
        sb = ttk.Scrollbar(lf, orient="vertical",
                           command=self._trend_listbox.yview)
        self._trend_listbox.config(yscrollcommand=sb.set)
        self._trend_listbox.pack(side=LEFT, fill=BOTH, expand=True)
        sb.pack(side=RIGHT, fill=Y)
        for v in self.monitored_videos:
            title = v.get("title","未知")[:35]
            self._trend_listbox.insert(tk.END, f"  {v.get('bvid','')}  {title}")

        # 右：指标 + 按钮
        right = tk.Frame(top)
        right.pack(side=RIGHT, padx=(10,0), fill=Y)

        tk.Label(right, text="对比指标", font=("Microsoft YaHei UI",9,"bold")).pack(anchor="w")
        for key, label in METRICS:
            ttk.Radiobutton(right, text=label, variable=self._trend_metric,
                            value=key, command=self._trend_draw).pack(anchor="w")

        ttk.Button(right, text="开始对比", command=self._trend_start).pack(
            pady=(10,0), fill=X)

        # 图表
        mid = tk.Frame(f)
        mid.pack(fill=BOTH, expand=True, padx=10, pady=4)

        self._trend_canvas = tk.Canvas(mid, bg=C.get("canvas_bg","#0d1117"),
                                       highlightthickness=0)
        self._trend_canvas.pack(fill=BOTH, expand=True)
        self._trend_canvas.bind("<Configure>", lambda e: self._trend_draw())

        # 图例
        self._trend_legend = tk.Frame(f)
        self._trend_legend.pack(fill=X, padx=14, pady=(0,6))

        # 初始提示
        self._trend_canvas.after(100, lambda: self._trend_canvas.create_text(
            self._trend_canvas.winfo_width()//2 or 400,
            120, text="请在上方选择视频后点击「开始对比」",
            fill=C.get("text_2","#8b949e"),
            font=("Microsoft YaHei UI",12)))

    # ── 趋势图：开始 ──────────────────────────────────────────────────────────
    def _trend_start(self):
        sel = self._trend_listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请至少选择 1 个视频", parent=self.window)
            return
        if len(sel) > 8:
            messagebox.showwarning("提示", "最多对比 8 个视频", parent=self.window)
            return

        self._trend_selected = [self.monitored_videos[i]
                                 for i in sel if i < len(self.monitored_videos)]

        # 加载历史数据
        metric = self._trend_metric.get()
        for video in self._trend_selected:
            bvid = video.get("bvid","")
            if bvid in self.video_dbs:
                try:
                    records = self.video_dbs[bvid].get_all_records()
                    if records:
                        self.history_data[bvid] = records
                except Exception:
                    pass

        self._trend_draw()

    # ── 趋势图：绘制 ──────────────────────────────────────────────────────────
    def _trend_draw(self):
        c = self._trend_canvas
        c.delete("all")
        for w in self._trend_legend.winfo_children():
            w.destroy()

        if not self._trend_selected:
            c.create_text(c.winfo_width()//2 or 400, 100,
                          text="请选择视频后点击「开始对比」",
                          fill=C.get("text_2","#8b949e"),
                          font=("Microsoft YaHei UI",12))
            return

        W, H = c.winfo_width(), c.winfo_height()
        if W < 100 or H < 100:
            return

        metric = self._trend_metric.get()
        metric_label = next((lb for k,lb in METRICS if k==metric), metric)

        cw = W - _ML - _MR
        ch = H - _MT - _MB

        # 收集数据
        series_map = {}
        all_vals, all_ts = [], []

        for video in self._trend_selected:
            bvid = video.get("bvid","")
            raw  = self.history_data.get(bvid, [])
            pts  = []
            for item in raw:
                # item 可能是 (ts, view) 旧格式，也可能是 dict
                if isinstance(item, dict):
                    ts  = item.get("timestamp","")
                    val = item.get(metric, 0) or 0
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    ts  = item[0]
                    val = item[1] if metric == "view_count" else 0
                else:
                    continue

                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts)
                    except Exception:
                        continue
                if not isinstance(ts, datetime):
                    try:
                        ts = datetime.fromtimestamp(float(ts))
                    except Exception:
                        continue

                try:
                    val = float(val) if val is not None else 0
                except (TypeError, ValueError):
                    val = 0

                pts.append((ts, val))
                all_vals.append(val)
                all_ts.append(ts)

            if pts:
                pts.sort(key=lambda p: p[0])
                series_map[bvid] = pts

        valid = [v for v in self._trend_selected if v.get("bvid","") in series_map]
        if not valid:
            c.create_text(W//2, H//2,
                          text=f"所选视频暂无「{metric_label}」历史数据",
                          fill=C.get("text_2","#8b949e"),
                          font=("Microsoft YaHei UI",12))
            return

        # 坐标范围
        min_ts  = min(all_ts)
        max_ts  = max(all_ts)
        max_val = max(all_vals) if all_vals else 1
        min_val = 0
        if max_val == min_val:
            max_val = min_val + 1

        ts_span = (max_ts - min_ts).total_seconds() or 1

        def to_x(ts):
            return _ML + (ts - min_ts).total_seconds() / ts_span * cw

        def to_y(v):
            return _MT + ch - (v - min_val) / (max_val - min_val) * ch

        # 标题
        c.create_text(W//2, _MT//2,
                      text=f"对比指标：{metric_label}",
                      fill=C.get("text_1","#e6edf3"),
                      font=("Microsoft YaHei UI", 11, "bold"))

        # 网格
        for i in range(5):
            ratio = i / 4
            y   = _MT + ch * (1 - ratio)
            val = min_val + (max_val - min_val) * ratio
            c.create_line(_ML, y, W - _MR, y,
                          fill=C.get("grid_line","#21262d"), dash=(2, 4))
            c.create_text(_ML - 6, y, text=_fmt(val), anchor="e",
                          fill=C.get("text_2","#8b949e"),
                          font=("Consolas", 9))

        # X 轴
        n_ticks = min(6, max(2, cw // 100))
        for i in range(n_ticks):
            ratio = i / (n_ticks - 1) if n_ticks > 1 else 0
            ts = min_ts + timedelta(seconds=ts_span * ratio)
            x  = _ML + cw * ratio
            label = ts.strftime("%m-%d %H:%M") if ts_span < 86400*7 \
                    else ts.strftime("%m-%d")
            c.create_text(x, H - _MB + 16, text=label,
                          fill=C.get("text_2","#8b949e"),
                          font=("Consolas", 8))

        # 绘线
        for idx, video in enumerate(valid):
            bvid  = video.get("bvid","")
            title = video.get("title", bvid)[:18]
            pts   = series_map.get(bvid,[])
            if not pts:
                continue

            color       = PALETTE[idx % len(PALETTE)]
            color_light = PALETTE_LIGHT[idx % len(PALETTE_LIGHT)]

            coords = []
            for ts, val in pts:
                coords.extend([to_x(ts), to_y(val)])

            if len(coords) >= 4:
                c.create_line(*coords, fill=color, width=2.2, smooth=True)

            if len(pts) >= 2:
                area = list(coords)
                area.extend([coords[-2], _MT+ch, coords[0], _MT+ch])
                c.create_polygon(*area, fill=color_light,
                                 outline="", stipple="gray25")

            last_ts, last_v = pts[-1]
            lx, ly = to_x(last_ts), to_y(last_v)
            c.create_oval(lx-4, ly-4, lx+4, ly+4,
                          fill=color, outline=C.get("bg_base","#0d1117"), width=1)
            c.create_text(lx+8, ly-10, text=_fmt(last_v),
                          anchor="w", fill=color,
                          font=("Consolas", 9, "bold"))

            # 图例
            leg = tk.Frame(self._trend_legend)
            leg.pack(side=tk.LEFT, padx=10)
            tk.Canvas(leg, width=14, height=14, bg=color,
                      highlightthickness=0).pack(side=LEFT, padx=(0,3))
            tk.Label(leg, text=f"{title} ({bvid})",
                     font=("Microsoft YaHei UI",9),
                     fg=C.get("text_1","#e6edf3"),
                     bg=C.get("bg_base","#0d1117")).pack(side=LEFT)

    # ══════════════════════════════════════════════════════════════════════════
    # ── 标签2：快照对比 ───────────────────────────────────────────────────────
    def _build_snap_tab(self):
        f = self._tab_snap

        # ── 顶部控制区 ──
        ctrl = tk.Frame(f)
        ctrl.pack(fill=X, padx=10, pady=(8,4))

        # 左1：视频选择
        vbox = tk.LabelFrame(ctrl, text="选择视频（可多选）", padx=6, pady=4)
        vbox.pack(side=LEFT, fill=BOTH, expand=True)

        vf = tk.Frame(vbox)
        vf.pack(fill=BOTH, expand=True)
        self._snap_listbox = tk.Listbox(vf, selectmode=tk.MULTIPLE,
                                        height=4, exportselection=False,
                                        bg=C.get("entry_bg","#1e2330"),
                                        fg=C.get("text_1","#e6edf3"),
                                        selectbackground=C.get("accent","#fb7299"),
                                        font=("Microsoft YaHei UI",9))
        sb2 = ttk.Scrollbar(vf, orient="vertical",
                             command=self._snap_listbox.yview)
        self._snap_listbox.config(yscrollcommand=sb2.set)
        self._snap_listbox.pack(side=LEFT, fill=BOTH, expand=True)
        sb2.pack(side=RIGHT, fill=Y)
        for v in self.monitored_videos:
            title = v.get("title","未知")[:32]
            self._snap_listbox.insert(tk.END,
                f"  {v.get('bvid','')}  {title}")
        self._snap_listbox.bind("<<ListboxSelect>>", self._snap_on_video_select)

        # 左2：时间点选择
        tbox = tk.LabelFrame(ctrl, text="选择时间点（可多选）", padx=6, pady=4)
        tbox.pack(side=LEFT, fill=BOTH, expand=True, padx=(8,0))

        tf = tk.Frame(tbox)
        tf.pack(fill=BOTH, expand=True)
        self._snap_ts_listbox = tk.Listbox(tf, selectmode=tk.MULTIPLE,
                                           height=4, exportselection=False,
                                           bg=C.get("entry_bg","#1e2330"),
                                           fg=C.get("text_1","#e6edf3"),
                                           selectbackground=C.get("accent","#23ade5"),
                                           font=("Consolas",9))
        sb3 = ttk.Scrollbar(tf, orient="vertical",
                             command=self._snap_ts_listbox.yview)
        self._snap_ts_listbox.config(yscrollcommand=sb3.set)
        self._snap_ts_listbox.pack(side=LEFT, fill=BOTH, expand=True)
        sb3.pack(side=RIGHT, fill=Y)

        tip = tk.Label(tbox,
                       text="↑ 选视频后自动加载；也可同时选多视频叠加",
                       font=("Microsoft YaHei UI",8),
                       fg=C.get("text_2","#8b949e"))
        tip.pack(anchor="w")

        # 右：指标 + 按钮
        rbox = tk.Frame(ctrl)
        rbox.pack(side=RIGHT, padx=(10,0), fill=Y)

        tk.Label(rbox, text="对比指标",
                 font=("Microsoft YaHei UI",9,"bold")).pack(anchor="w")
        for key, label in METRICS:
            ttk.Radiobutton(rbox, text=label, variable=self._snap_metric,
                            value=key, command=self._snap_draw).pack(anchor="w")

        # 里程碑来源选项
        self._snap_use_milestone = tk.BooleanVar(value=True)
        ttk.Checkbutton(rbox, text="叠加里程碑数据",
                        variable=self._snap_use_milestone,
                        command=self._snap_draw).pack(anchor="w", pady=(4,0))

        ttk.Button(rbox, text="生成对比图",
                   command=self._snap_compare).pack(pady=(10,4), fill=X)
        ttk.Button(rbox, text="清空选择",
                   command=self._snap_clear).pack(fill=X)

        # ── 图表区 ──
        chart_area = tk.Frame(f)
        chart_area.pack(fill=BOTH, expand=True, padx=10, pady=4)

        # 横向滚动
        h_scroll = ttk.Scrollbar(chart_area, orient="horizontal")
        h_scroll.pack(side=BOTTOM, fill=X)

        self._snap_canvas = tk.Canvas(chart_area,
                                      bg=C.get("canvas_bg","#0d1117"),
                                      highlightthickness=0,
                                      xscrollcommand=h_scroll.set)
        self._snap_canvas.pack(fill=BOTH, expand=True)
        h_scroll.config(command=self._snap_canvas.xview)
        self._snap_canvas.bind("<Configure>", lambda e: self._snap_draw())

        # 图例区
        self._snap_legend = tk.Frame(f)
        self._snap_legend.pack(fill=X, padx=14, pady=(0,6))

        # 状态标签
        self._snap_status = tk.Label(f, text="", font=("Microsoft YaHei UI",9),
                                     fg=C.get("text_2","#8b949e"))
        self._snap_status.pack(anchor="w", padx=14, pady=(0,4))

    # ── 快照：视频选中回调 ────────────────────────────────────────────────────
    def _snap_on_video_select(self, event=None):
        """选中视频后，加载历史时间点到下拉列表"""
        sel = self._snap_listbox.curselection()
        if not sel:
            return

        # 加载所有被选视频的历史记录
        all_ts_set = set()
        for i in sel:
            if i >= len(self.monitored_videos):
                continue
            bvid = self.monitored_videos[i].get("bvid","")
            if bvid not in self._snap_points:
                self._load_snap_records(bvid)
            for rec in self._snap_points.get(bvid, []):
                ts = rec.get("timestamp","")
                if ts:
                    all_ts_set.add(str(ts)[:16])

        # 更新时间点 listbox（保留原有选中）
        prev_sel_vals = set()
        for idx in self._snap_ts_listbox.curselection():
            prev_sel_vals.add(self._snap_ts_listbox.get(idx))

        ts_list = sorted(all_ts_set, reverse=True)   # 最新在上
        self._snap_ts_listbox.delete(0, tk.END)
        self._snap_ts_avail = ts_list   # 保存可用时间点列表

        for ts in ts_list:
            self._snap_ts_listbox.insert(tk.END, ts)
            if ts in prev_sel_vals:
                self._snap_ts_listbox.selection_set(tk.END)

        # 默认选中最新5个
        if not prev_sel_vals and ts_list:
            for i in range(min(5, len(ts_list))):
                self._snap_ts_listbox.selection_set(i)

    def _load_snap_records(self, bvid: str):
        """从 video_dbs 加载某视频的完整历史，存入 _snap_points"""
        if bvid in self.video_dbs:
            try:
                records = self.video_dbs[bvid].get_all_records()
                if records:
                    self._snap_points[bvid] = sorted(
                        [dict(r) for r in records],
                        key=lambda r: r.get("timestamp","")
                    )
                    return
            except Exception:
                pass
        self._snap_points[bvid] = []

    # ── 快照：生成对比图 ──────────────────────────────────────────────────────
    def _snap_compare(self):
        sel_v  = self._snap_listbox.curselection()
        sel_ts = self._snap_ts_listbox.curselection()

        if not sel_v:
            messagebox.showwarning("提示", "请选择至少 1 个视频", parent=self.window)
            return
        if not sel_ts:
            messagebox.showwarning("提示", "请选择至少 1 个时间点", parent=self.window)
            return

        chosen_videos = [self.monitored_videos[i]
                         for i in sel_v if i < len(self.monitored_videos)]
        chosen_ts = [self._snap_ts_listbox.get(i) for i in sel_ts]

        self._snap_selected   = chosen_videos
        self._snap_chosen_ts  = {v.get("bvid",""): chosen_ts for v in chosen_videos}

        self._snap_draw()

    # ── 快照：清空 ────────────────────────────────────────────────────────────
    def _snap_clear(self):
        self._snap_selected  = []
        self._snap_chosen_ts = {}
        self._snap_ts_listbox.selection_clear(0, tk.END)
        self._snap_listbox.selection_clear(0, tk.END)
        self._snap_draw()

    # ── 快照：绘图 ────────────────────────────────────────────────────────────
    def _snap_draw(self):
        c = self._snap_canvas
        c.delete("all")
        for w in self._snap_legend.winfo_children():
            w.destroy()
        self._snap_status.config(text="")

        if not self._snap_selected:
            cw = c.winfo_width() or 500
            c.create_text(cw//2, 120,
                          text="请选择视频和时间点后点击「生成对比图」",
                          fill=C.get("text_2","#8b949e"),
                          font=("Microsoft YaHei UI",12))
            return

        metric = self._snap_metric.get()
        metric_label = next((lb for k,lb in METRICS if k==metric), metric)

        # ── 构建数据矩阵 ──
        # bars: [{label, bvid, ts, value, color}]
        # 组织方式：按视频分组，每组内按时间点排列
        # 柱标签格式："视频短名 | 时间" 或 仅时间（单视频时）

        groups = []   # [ {bvid, title, bars:[{ts, value}]} ]
        use_milestone = self._snap_use_milestone.get()
        milestone_data = db.get_all_milestones_grouped() if use_milestone else {}
        period_map = {"1周": "1周", "1月": "1月", "1年": "1年"}

        for video in self._snap_selected:
            bvid  = video.get("bvid","")
            title = video.get("title", bvid)[:14]
            recs  = self._snap_points.get(bvid, [])
            chosen_ts = self._snap_chosen_ts.get(bvid, [])

            bars = []
            for ts_str in sorted(chosen_ts):
                # 找最近匹配的记录（前缀匹配 YYYY-MM-DD HH:MM）
                val = None
                best_rec = None
                for rec in recs:
                    rec_ts = str(rec.get("timestamp",""))[:16]
                    if rec_ts == ts_str[:16]:
                        best_rec = rec
                        break
                if best_rec is None:
                    # 容忍1分钟内的误差
                    target_dt = _parse_dt(ts_str)
                    if target_dt:
                        best = None
                        best_diff = float("inf")
                        for rec in recs:
                            rdt = _parse_dt(str(rec.get("timestamp","")))
                            if rdt:
                                diff = abs((rdt - target_dt).total_seconds())
                                if diff < best_diff:
                                    best_diff = diff
                                    best = rec
                        if best and best_diff < 300:
                            best_rec = best

                if best_rec is not None:
                    raw_val = best_rec.get(metric, None)
                    try:
                        val = float(raw_val) if raw_val is not None else 0
                    except (TypeError, ValueError):
                        val = 0
                    bars.append({"ts": ts_str, "value": val, "source": "history"})

            # 叠加里程碑
            if use_milestone and bvid in milestone_data:
                for period, row in milestone_data[bvid].items():
                    raw_val = row.get(metric, None)
                    try:
                        val = float(raw_val) if raw_val is not None else 0
                    except (TypeError, ValueError):
                        val = 0
                    if val and val > 0:
                        bars.append({"ts": f"里程碑·{period}", "value": val,
                                     "source": "milestone"})

            if bars:
                groups.append({"bvid": bvid, "title": title, "bars": bars})

        if not groups:
            c.create_text((c.winfo_width() or 500)//2, 120,
                          text=f"所选视频/时间点下无「{metric_label}」数据",
                          fill=C.get("text_2","#8b949e"),
                          font=("Microsoft YaHei UI",12))
            return

        # ── 计算尺寸 ──
        total_bars = sum(len(g["bars"]) for g in groups)
        n_groups   = len(groups)

        BAR_W    = max(30, min(60, 800 // max(total_bars,1)))
        GROUP_GAP = max(BAR_W, 24)
        inner_gap = max(2, BAR_W // 6)
        LEFT_PAD  = _BAR_ML
        RIGHT_PAD = _BAR_MR + 20
        TOP_PAD   = _BAR_MT
        BOT_PAD   = _BAR_MB

        # 各组宽度
        group_widths = [len(g["bars"]) * (BAR_W + inner_gap) - inner_gap
                        for g in groups]
        total_W = LEFT_PAD + sum(group_widths) + GROUP_GAP*(n_groups-1) + RIGHT_PAD + GROUP_GAP
        canvas_H = c.winfo_height() or 400
        if canvas_H < 150:
            canvas_H = 400

        chart_H = canvas_H - TOP_PAD - BOT_PAD
        if chart_H < 80:
            chart_H = 80

        # 配置滚动区域
        real_W = max(total_W, c.winfo_width() or total_W)
        c.config(scrollregion=(0, 0, real_W, canvas_H))

        # 最大值
        all_vals = [b["value"] for g in groups for b in g["bars"] if b["value"] is not None]
        if not all_vals:
            return
        max_val = max(all_vals) * 1.12 or 1

        def val_to_y(v):
            return TOP_PAD + chart_H - max(0, v) / max_val * chart_H

        # 网格
        n_grid = 5
        for i in range(n_grid + 1):
            ratio = i / n_grid
            y   = TOP_PAD + chart_H * (1 - ratio)
            val = max_val * ratio
            c.create_line(LEFT_PAD, y, real_W - RIGHT_PAD, y,
                          fill=C.get("grid_line","#21262d"), dash=(2,4))
            c.create_text(LEFT_PAD - 6, y, text=_fmt(val), anchor="e",
                          fill=C.get("text_2","#8b949e"), font=("Consolas",9))

        # 标题
        c.create_text(real_W//2, TOP_PAD//2,
                      text=f"快照对比 — {metric_label}",
                      fill=C.get("text_1","#e6edf3"),
                      font=("Microsoft YaHei UI",11,"bold"))

        # X 轴线
        c.create_line(LEFT_PAD, TOP_PAD + chart_H,
                      real_W - RIGHT_PAD, TOP_PAD + chart_H,
                      fill=C.get("text_2","#8b949e"))

        # 绘柱
        x_cursor = LEFT_PAD + GROUP_GAP // 2
        legend_added = set()

        for g_idx, group in enumerate(groups):
            bvid  = group["bvid"]
            title = group["title"]
            bars  = group["bars"]

            g_color = PALETTE[g_idx % len(PALETTE)]

            # 组标签（视频名）
            g_center = x_cursor + (len(bars)*(BAR_W+inner_gap) - inner_gap) // 2
            c.create_text(g_center, canvas_H - BOT_PAD + 30,
                          text=f"{title}", fill=g_color,
                          font=("Microsoft YaHei UI",9,"bold"))

            for b_idx, bar in enumerate(bars):
                val    = bar["value"] or 0
                ts_lbl = bar["ts"]
                source = bar["source"]

                # 里程碑用不同色系（加深）
                if source == "milestone":
                    bar_color = _darken(g_color, 0.75)
                    bar_color2 = _darken(g_color, 0.55)
                else:
                    # 同一组内按时间点用渐变色
                    ratio = b_idx / max(len(bars)-1,1)
                    bar_color  = _blend(g_color, "#ffffff", 0.15 + ratio*0.2)
                    bar_color2 = g_color

                x0 = x_cursor
                x1 = x0 + BAR_W
                y0 = val_to_y(val)
                y1 = TOP_PAD + chart_H

                # 柱体
                _draw_bar(c, x0, y0, x1, y1, bar_color, bar_color2)

                # 数值标签
                if val > 0:
                    c.create_text((x0+x1)//2, max(y0 - 6, TOP_PAD + 8),
                                  text=_fmt(val), anchor="s",
                                  fill=C.get("text_1","#e6edf3"),
                                  font=("Consolas",8,"bold"))

                # X 轴标签（时间点）
                short_ts = ts_lbl[-5:] if len(ts_lbl) > 5 else ts_lbl
                # 里程碑显示周期
                if source == "milestone":
                    short_ts = ts_lbl.replace("里程碑·","")
                c.create_text((x0+x1)//2, TOP_PAD + chart_H + 10,
                              text=short_ts, fill=C.get("text_2","#8b949e"),
                              font=("Consolas",8))

                x_cursor += BAR_W + inner_gap

            x_cursor += GROUP_GAP

            # 图例
            if bvid not in legend_added:
                legend_added.add(bvid)
                leg = tk.Frame(self._snap_legend)
                leg.pack(side=LEFT, padx=10)
                tk.Canvas(leg, width=14, height=14, bg=g_color,
                          highlightthickness=0).pack(side=LEFT, padx=(0,3))
                tk.Label(leg, text=f"{title} ({bvid})",
                         font=("Microsoft YaHei UI",9),
                         fg=C.get("text_1","#e6edf3"),
                         bg=C.get("bg_base","#0d1117")).pack(side=LEFT)

        # 里程碑图例
        if use_milestone:
            leg2 = tk.Frame(self._snap_legend)
            leg2.pack(side=LEFT, padx=10)
            tk.Canvas(leg2, width=14, height=14, bg="#888888",
                      highlightthickness=0).pack(side=LEFT, padx=(0,3))
            tk.Label(leg2, text="里程碑数据（深色柱）",
                     font=("Microsoft YaHei UI",9),
                     fg=C.get("text_2","#8b949e"),
                     bg=C.get("bg_base","#0d1117")).pack(side=LEFT)

        self._snap_status.config(
            text=f"共 {n_groups} 个视频，{total_bars} 根柱，指标：{metric_label}")

    # ══════════════════════════════════════════════════════════════════════════
    # ── 标签3：数据录入 ───────────────────────────────────────────────────────
    def _build_entry_tab(self):
        f = self._tab_entry

        # 录入模式切换
        mode_bar = tk.Frame(f)
        mode_bar.pack(fill=X, padx=10, pady=(8, 4))

        tk.Label(mode_bar, text="录入模式：",
                 font=("Microsoft YaHei UI", 9, "bold")).pack(side=LEFT)
        self._entry_mode = tk.StringVar(value="milestone")
        ttk.Radiobutton(mode_bar, text="里程碑（一周/月/年）",
                        variable=self._entry_mode, value="milestone",
                        command=self._entry_switch_mode).pack(side=LEFT, padx=(8, 16))
        ttk.Radiobutton(mode_bar, text="历史快照（指定时间点）",
                        variable=self._entry_mode, value="snapshot",
                        command=self._entry_switch_mode).pack(side=LEFT)

        # ── 上半：输入区 ──
        input_area = tk.Frame(f)
        input_area.pack(fill=BOTH, expand=True, padx=10, pady=4)

        # 左列：BV号输入
        bv_frame = tk.LabelFrame(input_area, text="BV号（每行一个，可批量）",
                                  padx=6, pady=6)
        bv_frame.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 8))

        self._entry_bvid_text = tk.Text(
            bv_frame, width=24, height=8,
            bg=C.get("entry_bg", "#1e2330"), fg=C.get("text_1", "#e6edf3"),
            insertbackground=C.get("text_1", "#e6edf3"),
            font=("Consolas", 9), relief="flat", bd=1,
            highlightthickness=1,
            highlightcolor=C.get("accent", "#fb7299"),
            highlightbackground=C.get("border", "#30363d"))
        self._entry_bvid_text.pack(fill=BOTH, expand=True)

        # 从监控列表批量添加按钮
        ttk.Button(bv_frame, text="从监控列表添加全部",
                   command=self._entry_add_all_monitored).pack(fill=X, pady=(4, 0))

        # 中列：模式参数区（里程碑用周期勾选 / 快照用日期选择）
        self._entry_param_frame = tk.LabelFrame(input_area, text="参数",
                                                  padx=6, pady=6)
        self._entry_param_frame.pack(side=LEFT, fill=Y, padx=(0, 8))

        # 里程碑参数（周期勾选）
        self._entry_ms_frame = tk.Frame(self._entry_param_frame)
        self._entry_ms_vars: Dict[str, tk.BooleanVar] = {}
        tk.Label(self._entry_ms_frame, text="统计周期",
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        for p in db.MILESTONE_PERIODS:
            var = tk.BooleanVar(value=True)
            self._entry_ms_vars[p] = var
            tk.Checkbutton(self._entry_ms_frame, text=p, variable=var).pack(anchor="w")

        # 快照参数（日期选择）
        self._entry_snap_frame = tk.Frame(self._entry_param_frame)
        tk.Label(self._entry_snap_frame, text="选择日期时间",
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        self._entry_snap_dt = tk.StringVar(value="")
        dt_entry = tk.Entry(self._entry_snap_frame, textvariable=self._entry_snap_dt,
                            width=18, font=("Consolas", 9))
        dt_entry.pack(anchor="w", pady=2)
        tk.Label(self._entry_snap_frame, text="格式：2026-04-22 12:00",
                 font=("Microsoft YaHei UI", 8),
                 fg=C.get("text_2", "#8b949e")).pack(anchor="w")
        tk.Label(self._entry_snap_frame, text="\n或从下拉选已有时间点：",
                 font=("Microsoft YaHei UI", 8),
                 fg=C.get("text_2", "#8b949e")).pack(anchor="w")
        self._entry_snap_combo = ttk.Combobox(self._entry_snap_frame, width=18,
                                               state="readonly")
        self._entry_snap_combo.pack(anchor="w", pady=2)
        self._entry_snap_combo.bind("<<ComboboxSelected>>", self._on_snap_combo_select)

        # 右列：操作按钮
        btn_frame = tk.Frame(input_area)
        btn_frame.pack(side=LEFT, fill=Y)

        ttk.Button(btn_frame, text="生成输入表",
                   command=self._entry_generate_rows).pack(fill=X, pady=3, ipady=2)
        ttk.Button(btn_frame, text="💾 保存全部",
                   command=self._entry_save_all).pack(fill=X, pady=3, ipady=2)

        # ── 下半：可滚动的输入行 + 已有数据表格 ──
        bottom = tk.Frame(f)
        bottom.pack(fill=BOTH, expand=True, padx=10, pady=(4, 4))

        # Notebook 嵌套：输入行 / 已有数据
        inner_nb = ttk.Notebook(bottom)
        inner_nb.pack(fill=BOTH, expand=True)

        tab_input = tk.Frame(inner_nb)
        tab_table = tk.Frame(inner_nb)
        inner_nb.add(tab_input, text="  输入行  ")
        inner_nb.add(tab_table,  text="  已录入数据  ")

        # 输入行区域
        self._entry_canvas = tk.Canvas(tab_input,
                                        bg=C.get("bg_base", "#0d1117"),
                                        highlightthickness=0)
        vsb = ttk.Scrollbar(tab_input, orient="vertical",
                             command=self._entry_canvas.yview)
        self._entry_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=RIGHT, fill=Y)
        self._entry_canvas.pack(fill=BOTH, expand=True)

        self._entry_container = tk.Frame(self._entry_canvas)
        self._entry_canvas.create_window((0, 0), window=self._entry_container,
                                          anchor="nw", tags="inner")
        self._entry_container.bind("<Configure>",
            lambda e: self._entry_canvas.configure(
                scrollregion=self._entry_canvas.bbox("all")))
        self._entry_canvas.bind("<MouseWheel>",
            lambda e: self._entry_canvas.yview_scroll(
                -1 * (e.delta // 120), "units"))

        # 已录入数据表格
        cols = ("bvid", "type", "time_key", "播放量", "点赞", "硬币",
                "收藏", "分享", "弹幕", "评论", "记录时间")
        self._entry_tbl = ttk.Treeview(tab_table, columns=cols, show="headings",
                                        height=8)
        tbl_sb = ttk.Scrollbar(tab_table, orient="vertical",
                                command=self._entry_tbl.yview)
        self._entry_tbl.configure(yscrollcommand=tbl_sb.set)
        tbl_sb.pack(side=RIGHT, fill=Y)
        self._entry_tbl.pack(fill=BOTH, expand=True)

        widths = [110, 70, 130, 80, 60, 60, 60, 60, 60, 60, 120]
        for col, w in zip(cols, widths):
            self._entry_tbl.heading(col, text=col)
            self._entry_tbl.column(col, width=w, minwidth=40, anchor="center")

        # 右键删除
        self._entry_tbl_menu = tk.Menu(self.window, tearoff=0)
        self._entry_tbl_menu.add_command(label="删除选中行",
                                          command=self._entry_delete_selected)
        self._entry_tbl.bind("<Button-3>",
            lambda e: self._entry_tbl_menu.tk_popup(e.x_root, e.y_root))

        # 状态栏
        self._entry_status = tk.Label(f, text="选择录入模式，输入 BV 号后点击「生成输入表」",
                                       font=("Microsoft YaHei UI", 9),
                                       fg=C.get("text_2", "#8b949e"), anchor="w")
        self._entry_status.pack(fill=X, padx=12, pady=(0, 6))

        # 内部状态
        self._entry_rows: List[dict] = []   # [{bvid, period_or_ts, vars:{field: StringVar}}, ...]
        self._monitored_set = {v.get("bvid", "") for v in self.monitored_videos}

        # 初始显示里程碑参数
        self._entry_switch_mode()
        # 加载已有数据
        self._entry_reload_table()

    # ── 录入模式切换 ──────────────────────────────────────────────────────────
    def _entry_switch_mode(self):
        mode = self._entry_mode.get()
        # 切换参数面板
        self._entry_ms_frame.pack_forget()
        self._entry_snap_frame.pack_forget()
        if mode == "milestone":
            self._entry_ms_frame.pack(fill=X)
            self._entry_param_frame.config(text="统计周期")
        else:
            self._entry_snap_frame.pack(fill=X)
            self._entry_param_frame.config(text="日期时间")
            self._refresh_snap_combo()

    def _refresh_snap_combo(self):
        """刷新快照模式下拉时间点列表。"""
        ts_set = set()
        for bvid in self.video_dbs:
            try:
                for rec in self.video_dbs[bvid].get_all_records():
                    ts = str(rec.get("timestamp", ""))[:16]
                    if ts:
                        ts_set.add(ts)
            except Exception:
                pass
        ts_list = sorted(ts_set, reverse=True)
        self._entry_snap_combo["values"] = ts_list[:200]

    def _on_snap_combo_select(self, event=None):
        val = self._entry_snap_combo.get()
        if val:
            self._entry_snap_dt.set(val)

    # ── 从监控列表添加全部 ────────────────────────────────────────────────────
    def _entry_add_all_monitored(self):
        text = self._entry_bvid_text
        text.delete("1.0", tk.END)
        for v in self.monitored_videos:
            bvid = v.get("bvid", "")
            if bvid:
                text.insert(tk.END, bvid + "\n")

    # ── BV号验证 ──────────────────────────────────────────────────────────────
    @staticmethod
    def _is_valid_bvid(s: str) -> bool:
        import re
        return bool(re.match(r'^BV[A-Za-z0-9]{10}$', s.strip()))

    # ── 生成输入行 ────────────────────────────────────────────────────────────
    def _entry_generate_rows(self):
        import re as _re
        raw = self._entry_bvid_text.get("1.0", tk.END).strip()
        if not raw:
            messagebox.showwarning("提示", "请先输入 BV 号", parent=self.window)
            return

        bvids, invalid = [], []
        for line in raw.splitlines():
            bv = line.strip()
            if not bv:
                continue
            if self._is_valid_bvid(bv):
                if bv not in bvids:
                    bvids.append(bv)
            else:
                invalid.append(bv)

        if invalid:
            messagebox.showwarning("格式错误",
                f"以下格式不合法已跳过：\n" + "\n".join(invalid[:10]),
                parent=self.window)

        if not bvids:
            return

        # 不在监控列表的提示
        not_monitored = [b for b in bvids if b not in self._monitored_set]
        if not_monitored:
            msg = (f"以下 BV 号不在监控列表：\n"
                   + "\n".join(not_monitored[:10])
                   + "\n\n是否加入监控？")
            if messagebox.askyesno("加入监控", msg, parent=self.window):
                for bv in not_monitored:
                    if self.on_add_monitor:
                        self.on_add_monitor(bv)
                    self._monitored_set.add(bv)

        mode = self._entry_mode.get()

        # 生成行标签
        row_labels = []
        if mode == "milestone":
            periods = [p for p, v in self._entry_ms_vars.items() if v.get()]
            if not periods:
                messagebox.showwarning("提示", "请至少选择一个周期", parent=self.window)
                return
            for bv in bvids:
                for p in periods:
                    row_labels.append((bv, p))
        else:
            dt_str = self._entry_snap_dt.get().strip()
            if not dt_str:
                messagebox.showwarning("提示", "请填写日期时间或从下拉选择",
                                       parent=self.window)
                return
            # 验证格式
            dt = _parse_dt(dt_str)
            if dt is None:
                messagebox.showwarning("格式错误",
                    "日期格式不正确，请使用 2026-04-22 12:00 格式",
                    parent=self.window)
                return
            for bv in bvids:
                row_labels.append((bv, dt_str[:16]))

        # 清空旧行
        for w in self._entry_container.winfo_children():
            w.destroy()
        self._entry_rows.clear()

        # 加载已有数据做预填
        existing_ms = {}
        for row in db.get_milestones():
            existing_ms[(row["bvid"], row["period"])] = row

        # 快照已有数据
        existing_snap = {}
        if mode == "snapshot":
            for bvid in bvids:
                if bvid in self.video_dbs:
                    try:
                        for rec in self.video_dbs[bvid].get_all_records():
                            rec_ts = str(rec.get("timestamp", ""))[:16]
                            if rec_ts == dt_str[:16]:
                                existing_snap[bvid] = dict(rec)
                                break
                    except Exception:
                        pass

        # 字段定义
        fields = [
            ("view_count", "播放量*", True),
            ("like_count", "点赞", False),
            ("coin_count", "硬币", False),
            ("share_count", "分享", False),
            ("favorite_count", "收藏", False),
            ("danmaku_count", "弹幕", False),
            ("reply_count", "评论", False),
            ("note", "备注", False),
        ]

        for bv, key in row_labels:
            row_frame = tk.Frame(self._entry_container, padx=4, pady=2)
            row_frame.pack(fill=tk.X)

            # BV号 + key 标签
            tk.Label(row_frame, text=bv, font=("Consolas", 9),
                     fg=C.get("accent", "#fb7299"),
                     bg=C.get("bg_base", "#0d1117"),
                     width=14, anchor="w").grid(row=0, column=0, padx=(0,4))

            tk.Label(row_frame, text=key, font=("Microsoft YaHei UI", 9, "bold"),
                     fg=C.get("text_1", "#e6edf3"),
                     bg=C.get("bg_base", "#0d1117"),
                     width=16, anchor="w").grid(row=0, column=1, padx=(0,8))

            vars_dict = {}
            col = 2
            for fkey, flabel, required in fields:
                tk.Label(row_frame,
                         text=flabel + ("*" if required else ""),
                         font=("Microsoft YaHei UI", 8),
                         fg=C.get("danger", "#f85149") if required
                            else C.get("text_2", "#8b949e"),
                         bg=C.get("bg_base", "#0d1117"),
                         anchor="e", width=6).grid(row=0, column=col, padx=(2,1))

                var = tk.StringVar()
                # 预填
                if mode == "milestone":
                    existing = existing_ms.get((bv, key))
                    if existing and existing.get(fkey) is not None:
                        var.set(str(existing[fkey]))
                else:
                    existing = existing_snap.get(bv)
                    if existing and existing.get(fkey) is not None:
                        var.set(str(existing[fkey]))

                vars_dict[fkey] = var
                w = 18 if fkey == "note" else 8
                ent = tk.Entry(row_frame, textvariable=var,
                               font=("Consolas", 9), width=w,
                               bg=C.get("entry_bg", "#1e2330"),
                               fg=C.get("text_1", "#e6edf3"),
                               insertbackground=C.get("text_1", "#e6edf3"),
                               relief="flat", bd=1,
                               highlightthickness=1,
                               highlightcolor=C.get("accent", "#fb7299"),
                               highlightbackground=C.get("border", "#30363d"))
                ent.grid(row=0, column=col+1, padx=(0,4))
                col += 2

            self._entry_rows.append({
                "bvid": bv,
                "key": key,
                "vars": vars_dict,
                "mode": mode,
            })

        n = len(self._entry_rows)
        self._entry_status.config(
            text=f"已生成 {n} 行输入（{len(bvids)} 视频 × "
                 + (f"{len(periods)} 周期" if mode == "milestone" else "1 时间点")
                 + f"），填写后点击「保存全部」")

    # ── 保存全部 ──────────────────────────────────────────────────────────────
    def _entry_save_all(self):
        if not self._entry_rows:
            messagebox.showwarning("提示", "请先生成输入表", parent=self.window)
            return

        saved = skipped = errors = 0
        for row in self._entry_rows:
            vars_d = row["vars"]
            raw_view = vars_d["view_count"].get().strip().replace(",", "")
            if not raw_view:
                skipped += 1
                continue
            try:
                view_val = int(float(raw_view))
            except ValueError:
                errors += 1
                continue

            data = {"view_count": view_val}
            for fkey in ["like_count", "coin_count", "share_count",
                         "favorite_count", "danmaku_count", "reply_count"]:
                val = vars_d[fkey].get().strip()
                if val:
                    try:
                        data[fkey] = int(float(val.replace(",", "")))
                    except ValueError:
                        pass
            note = vars_d["note"].get().strip()
            if note:
                data["note"] = note

            mode = row["mode"]
            bvid = row["bvid"]

            if mode == "milestone":
                ok = db.upsert_milestone(bvid, row["key"], data)
            else:
                # 快照模式：写入 video_dbs 对应的历史表
                ok = self._save_snapshot_record(bvid, row["key"], data)

            if ok:
                saved += 1
            else:
                errors += 1

        msg = f"✅ 已保存 {saved} 条"
        if skipped:
            msg += f"，跳过 {skipped} 条（播放量为空）"
        if errors:
            msg += f"，失败 {errors} 条"
        self._entry_status.config(
            text=msg,
            fg=C.get("success", "#3fb950") if not errors else C.get("warning", "#d29922"))

        if saved:
            self._entry_reload_table()
            messagebox.showinfo("保存完成", msg, parent=self.window)

    def _save_snapshot_record(self, bvid: str, ts_str: str, data: dict) -> bool:
        """将快照数据写入视频的历史记录表。"""
        if bvid not in self.video_dbs:
            return False
        try:
            video_db = self.video_dbs[bvid]
            dt = _parse_dt(ts_str)
            if dt is None:
                return False
            ts_str_full = dt.strftime("%Y-%m-%d %H:%M:%S")

            # 构造 MonitorRecord 并写入
            from core.database import MonitorRecord
            record = MonitorRecord(
                bvid=bvid,
                timestamp=ts_str_full,
                view_count=data.get("view_count", 0),
                like_count=data.get("like_count", 0),
                coin_count=data.get("coin_count", 0),
                share_count=data.get("share_count", 0),
                favorite_count=data.get("favorite_count", 0),
                danmaku_count=data.get("danmaku_count", 0),
                reply_count=data.get("reply_count", 0),
            )
            video_db.add_monitor_record(record)
            return True
        except Exception as e:
            print(f"快照写入失败 [{bvid}]: {e}")
            return False

    # ── 刷新已有数据表格 ──────────────────────────────────────────────────────
    def _entry_reload_table(self):
        for item in self._entry_tbl.get_children():
            self._entry_tbl.delete(item)

        # 里程碑数据
        for row in db.get_milestones():
            self._entry_tbl.insert("", tk.END, values=(
                row.get("bvid", ""),
                "里程碑",
                row.get("period", ""),
                _fmt(row.get("view_count")),
                _fmt(row.get("like_count")),
                _fmt(row.get("coin_count")),
                _fmt(row.get("favorite_count")),
                _fmt(row.get("share_count")),
                _fmt(row.get("danmaku_count")),
                _fmt(row.get("reply_count")),
                str(row.get("recorded_at", ""))[:16],
            ))

        # 快照数据（手动录入的标记 tricky，显示所有里程碑即可；快照已录入历史表
        # 不在里程碑表中，这里主要显示里程碑）

    def _entry_delete_selected(self):
        selected = self._entry_tbl.selection()
        if not selected:
            return
        if not messagebox.askyesno("确认", f"删除选中的 {len(selected)} 条记录？",
                                    parent=self.window):
            return
        for iid in selected:
            values = self._entry_tbl.item(iid, "values")
            if not values:
                continue
            bvid = values[0]
            entry_type = values[1]
            time_key = values[2]
            if entry_type == "里程碑":
                db.delete_milestone(bvid, time_key)
        self._entry_reload_table()


# ══════════════════════════════════════════════════════════════════════════════
# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:len(fmt)].strip(), fmt)
        except Exception:
            pass
    return None


def _hex_to_rgb(hex_color: str) -> Tuple[int,int,int]:
    h = hex_color.lstrip("#")
    return int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{min(255,max(0,r)):02x}{min(255,max(0,g)):02x}{min(255,max(0,b)):02x}"


def _blend(c1: str, c2: str, t: float) -> str:
    """t=0 → c1, t=1 → c2"""
    r1,g1,b1 = _hex_to_rgb(c1)
    r2,g2,b2 = _hex_to_rgb(c2)
    return _rgb_to_hex(int(r1+(r2-r1)*t), int(g1+(g2-g1)*t), int(b1+(b2-b1)*t))


def _darken(c1: str, factor: float) -> str:
    """factor < 1 → 变暗"""
    r,g,b = _hex_to_rgb(c1)
    return _rgb_to_hex(int(r*factor), int(g*factor), int(b*factor))


def _draw_bar(canvas: tk.Canvas, x0, y0, x1, y1, color_top, color_body):
    """绘制一根带顶部高亮的矩形柱"""
    if y0 >= y1:
        return
    # 主体
    canvas.create_rectangle(x0, y0, x1, y1, fill=color_body, outline="", width=0)
    # 顶部高亮条
    top_h = max(3, (y1 - y0) * 0.06)
    canvas.create_rectangle(x0, y0, x1, y0 + top_h,
                             fill=color_top, outline="", width=0)
    # 右侧阴影
    shadow_w = max(2, (x1-x0)*0.08)
    canvas.create_rectangle(x1-shadow_w, y0, x1, y1,
                             fill=_darken(color_body, 0.75), outline="", width=0)
