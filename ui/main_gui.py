"""
主GUI界面 - 深色三栏布局
左侧视频卡片 / 中间图表详情 / 右侧预测分析
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import sys
import os
from datetime import datetime, timedelta
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# 从新模块导入
from ui.theme import C, THEMES, THEME_DARK, current_theme_name, apply_theme
from ui.helpers import (
    FONT, FONT_BOLD, FONT_SM, FONT_LG, FONT_MONO, FONT_MONO_LG,
    THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS,
    DEFAULT_INTERVAL, FAST_INTERVAL, FAST_GAP,
    fmt_num, nearest_threshold_gap, card_status_tag,
)
from ui.chart import (
    draw_chart, draw_chart_placeholder,
)
from ui.log_panel import LogPanel
from ui.monitor_service import (
    fetch_all_video_data, predict_single, merge_history,
    calc_growth_rate, auto_predict_all, load_watch_list,
)
from algorithms.registry import AlgorithmRegistry
from core import bilibili_api, db, MonitorRecord
from config import load_config, save_config
from utils.file_logger import FileLogger



# ══════════════════════════════════════════════
# 主界面
# ══════════════════════════════════════════════
class BilibiliMonitorGUI:
    """主界面 - 深色三栏布局"""

    DEFAULT_INTERVAL = DEFAULT_INTERVAL
    FAST_INTERVAL    = FAST_INTERVAL
    THRESHOLD_GAP    = FAST_GAP

    def __init__(self, root=None):
        if root is None:
            root = tk.Tk()
            root.title("B站视频监控与播放量预测系统")
            root.geometry("1400x860")
            root.minsize(1100, 700)

        self.root = root
        _cfg = load_config()
        _saved_theme = _cfg.get("ui", {}).get("theme", "dark")
        apply_theme(root, _saved_theme)
        self._initial_theme = _saved_theme

        # 状态变量
        self.refresh_interval      = self.DEFAULT_INTERVAL
        self.auto_refresh_enabled  = tk.BooleanVar(value=True)
        self.auto_refresh_job      = None
        self.countdown_job         = None
        self.seconds_remaining     = 0
        self.fast_mode             = False

        # 数据
        self.monitored_videos  = []
        self.history_data      = {}
        self.prediction_results= {}
        self.video_dbs         = {}
        self.selected_bvid     = None

        # UI 组件引用
        self._video_card_widgets = {}
        self._cover_cache      = {}
        self._photo_ref        = None

        # 文件日志
        self._file_logger = FileLogger(os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "log"))

        self.root.protocol("WM_DELETE_WINDOW", self._on_exit)
        self._build_ui()
        self._load_watch_list()
        self._start_auto_refresh()
        self._file_logger.start_midnight_checker(self.root)

    # ──────────────────────────────────────────
    # UI 构建
    # ──────────────────────────────────────────
    def _build_ui(self):
        self._build_titlebar()
        # 日志面板（独立于主三栏布局）
        self.log_panel = LogPanel(self.root, self._file_logger)
        self._build_main()
        self._build_bottom_bar()
        self._build_status_bar()

    # ── 顶部标题栏 ──────────────────────────────
    def _build_titlebar(self):
        bar = tk.Frame(self.root, bg=C["bg_surface"], height=46)
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill=tk.X)

        # Logo
        logo_f = tk.Frame(bar, bg=C["bg_surface"])
        logo_f.pack(side=tk.LEFT, padx=(14, 0))
        tk.Label(logo_f, text="📺", bg=C["bg_surface"], fg=C["bilibili"],
                 font=("Microsoft YaHei UI", 14)).pack(side=tk.LEFT)
        tk.Label(logo_f, text=" B站监控", bg=C["bg_surface"], fg=C["bilibili"],
                 font=("Microsoft YaHei UI", 11, "bold")).pack(side=tk.LEFT)

        # 导航按钮
        nav_f = tk.Frame(bar, bg=C["bg_surface"])
        nav_f.pack(side=tk.LEFT, padx=16)
        self._nav_btns = {}
        self._page_views = ["监控列表", "日志"]
        nav_items = [
            ("监控列表", None),
            ("数据对比",  self._open_data_comparison),
            ("交叉计算",  self._open_crossover_analysis),
            ("周刊分数",  self._open_weekly_score),
            ("数据库",    self._open_database_query),
            ("日志",      None),
        ]
        for label, cmd in nav_items:
            btn = tk.Label(nav_f, text=label, bg=C["bg_surface"], fg=C["text_2"],
                           font=FONT, cursor="hand2", padx=10, pady=6)
            btn.pack(side=tk.LEFT)
            is_active = label == "监控列表"
            if is_active:
                btn.config(fg=C["bilibili"])
            if label in self._page_views:
                btn.bind("<Button-1>", lambda e, n=label: self._switch_nav(n))
                btn.bind("<Enter>", lambda e, b=btn: b.config(fg=C["text_1"])
                         if b.cget("fg") != C["bilibili"] else None)
                btn.bind("<Leave>", lambda e, b=btn: b.config(fg=C["text_2"])
                         if b.cget("fg") != C["bilibili"] else None)
            elif cmd:
                btn.bind("<Button-1>", lambda e, c=cmd: c())
                btn.bind("<Enter>", lambda e, b=btn: b.config(fg=C["text_1"]))
                btn.bind("<Leave>", lambda e, b=btn: b.config(fg=C["text_2"]))
            self._nav_btns[label] = btn
        self._current_nav = "监控列表"

        # 右侧按钮区
        right_f = tk.Frame(bar, bg=C["bg_surface"])
        right_f.pack(side=tk.RIGHT, padx=14)

        # 设置下拉菜单
        self._settings_menu = tk.Menu(self.root, tearoff=0, bg=C["bg_elevated"],
                                       fg=C["text_1"], activebackground=C["bg_hover"],
                                       activeforeground=C["text_1"],
                                       font=FONT, bd=0, relief="flat")
        self._settings_menu.add_command(label="⏱  刷新间隔", command=self._open_interval_settings)
        self._settings_menu.add_command(label="📊  权重设置", command=self._open_weight_settings)
        self._settings_menu.add_command(label="🌐  网络设置", command=self._open_network_settings)
        self._settings_menu.add_separator()
        self._settings_menu.add_command(label="⚙️  系统设置", command=self._open_settings)

        gear = tk.Label(right_f, text="⚙️", bg=C["bg_elevated"], fg=C["text_2"],
                        font=("Microsoft YaHei UI", 11), cursor="hand2",
                        padx=6, pady=2, relief="flat")
        gear.pack(side=tk.RIGHT, padx=2)
        gear.bind("<Button-1>", lambda e: self._settings_menu.tk_popup(
            gear.winfo_rootx(), gear.winfo_rooty() + gear.winfo_height()))
        gear.bind("<Enter>", lambda e: gear.config(bg=C["bg_hover"], fg=C["text_1"]))
        gear.bind("<Leave>", lambda e: gear.config(bg=C["bg_elevated"], fg=C["text_2"]))

        # 搜索按钮
        search_btn = tk.Label(right_f, text="🔍", bg=C["bg_elevated"], fg=C["text_2"],
                              font=("Microsoft YaHei UI", 11), cursor="hand2",
                              padx=6, pady=2, relief="flat")
        search_btn.pack(side=tk.RIGHT, padx=2)
        search_btn.bind("<Button-1>", lambda e: self._open_video_search())
        search_btn.bind("<Enter>", lambda e: search_btn.config(bg=C["bg_hover"], fg=C["text_1"]))
        search_btn.bind("<Leave>", lambda e: search_btn.config(bg=C["bg_elevated"], fg=C["text_2"]))

        # 主题切换按钮
        self._theme_btn = tk.Label(right_f, text="🌙", bg=C["bg_elevated"], fg=C["text_2"],
                                   font=("Microsoft YaHei UI", 11), cursor="hand2",
                                   padx=6, pady=2, relief="flat")
        self._theme_btn.pack(side=tk.RIGHT, padx=2)
        self._theme_btn.bind("<Button-1>", self._toggle_theme)
        self._theme_btn.bind("<Enter>", lambda e: self._theme_btn.config(bg=C["bg_hover"], fg=C["text_1"]))
        self._theme_btn.bind("<Leave>", lambda e: self._theme_btn.config(bg=C["bg_elevated"], fg=C["text_2"]))
        self._theme_btn.config(text="☀️" if self._initial_theme == "light" else "🌙")

        # 倒计时徽章
        self._countdown_badge = tk.Label(
            right_f, text="-- s", bg=C["bg_elevated"], fg=C["accent"],
            font=FONT_MONO, padx=8, pady=2, relief="flat")
        self._countdown_badge.pack(side=tk.RIGHT, padx=6)

        # 模式状态药丸
        self._mode_pill = tk.Label(
            right_f, text="● 正常模式", bg=C["bg_surface"], fg=C["success"],
            font=("Microsoft YaHei UI", 9, "bold"))
        self._mode_pill.pack(side=tk.RIGHT, padx=6)

    # ── 主体三栏 ────────────────────────────────
    def _build_main(self):
        self._main_frame = tk.Frame(self.root, bg=C["bg_base"])
        self._main_frame.pack(fill=tk.BOTH, expand=True)

        main = tk.Frame(self._main_frame, bg=C["bg_base"])
        main.pack(fill=tk.BOTH, expand=True)

        self._left = tk.Frame(main, bg=C["bg_surface"], width=310)
        self._left.pack(side=tk.LEFT, fill=tk.Y)
        self._left.pack_propagate(False)
        tk.Frame(main, bg=C["border"], width=1).pack(side=tk.LEFT, fill=tk.Y)

        self._center = tk.Frame(main, bg=C["bg_base"])
        self._center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Frame(main, bg=C["border"], width=1).pack(side=tk.LEFT, fill=tk.Y)

        self._right = tk.Frame(main, bg=C["bg_surface"], width=290)
        self._right.pack(side=tk.LEFT, fill=tk.Y)
        self._right.pack_propagate(False)

        self._build_left_panel()
        self._build_center_panel()
        self._build_right_panel()

    # ── 左侧：视频列表 ──────────────────────────
    def _build_left_panel(self):
        p = self._left
        hdr = tk.Frame(p, bg=C["bg_surface"])
        hdr.pack(fill=tk.X, padx=12, pady=(10, 4))
        tk.Label(hdr, text="监控视频", bg=C["bg_surface"], fg=C["text_2"],
                 font=("Microsoft YaHei UI", 8, "bold")).pack(side=tk.LEFT)
        self._video_count_lbl = tk.Label(hdr, text="0", bg=C["bg_elevated"],
                                          fg=C["text_2"], font=FONT_SM, padx=6, pady=1)
        self._video_count_lbl.pack(side=tk.LEFT, padx=4)

        # 搜索框
        sf = tk.Frame(p, bg=C["bg_elevated"], bd=1, relief="flat",
                      highlightthickness=1, highlightbackground=C["border"],
                      highlightcolor=C["bilibili"])
        sf.pack(fill=tk.X, padx=10, pady=(0, 6))
        tk.Label(sf, text="🔍", bg=C["bg_elevated"], fg=C["text_3"],
                 font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(6, 0))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search)
        se = tk.Entry(sf, textvariable=self._search_var,
                      bg=C["bg_elevated"], fg=C["text_1"],
                      insertbackground=C["text_1"],
                      relief="flat", font=FONT, bd=0)
        se.pack(fill=tk.X, padx=4, pady=5)
        se.insert(0, "搜索标题或BV号…")
        se.config(fg=C["text_3"])
        def _focus_in(e):
            if se.get() == "搜索标题或BV号…":
                se.delete(0, tk.END)
                se.config(fg=C["text_1"])
        def _focus_out(e):
            if not se.get():
                se.insert(0, "搜索标题或BV号…")
                se.config(fg=C["text_3"])
        se.bind("<FocusIn>",  _focus_in)
        se.bind("<FocusOut>", _focus_out)

        # 滚动容器
        wrap = tk.Frame(p, bg=C["bg_surface"])
        wrap.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(wrap, bg=C["bg_surface"], bd=0,
                           highlightthickness=0, yscrollincrement=1)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._card_frame = tk.Frame(canvas, bg=C["bg_surface"])
        cwin = canvas.create_window((0, 0), window=self._card_frame, anchor="nw")
        def _on_cf_resize(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(cwin, width=canvas.winfo_width())
        self._card_frame.bind("<Configure>", _on_cf_resize)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cwin, width=e.width))
        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self._list_canvas = canvas
        self._video_card_widgets = {}

        # 底部操作按钮行
        bottom_f = tk.Frame(p, bg=C["bg_surface"])
        bottom_f.pack(fill=tk.X, padx=10, pady=8)
        btn = tk.Label(bottom_f, text="＋  添加监控",
                       bg=C["bg_surface"], fg=C["text_2"],
                       font=FONT, cursor="hand2", pady=6,
                       relief="flat", highlightthickness=1,
                       highlightbackground=C["border"], highlightcolor=C["bilibili"])
        btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        btn.bind("<Button-1>", lambda e: self._add_monitor())
        btn.bind("<Enter>", lambda e: btn.config(fg=C["bilibili"], highlightbackground=C["bilibili"]))
        btn.bind("<Leave>", lambda e: btn.config(fg=C["text_2"], highlightbackground=C["border"]))

        search_btn = tk.Label(bottom_f, text="🔍 搜索视频",
                              bg=C["bg_surface"], fg=C["text_2"],
                              font=FONT, cursor="hand2", pady=6, padx=8,
                              relief="flat", highlightthickness=1,
                              highlightbackground=C["border"], highlightcolor=C["accent"])
        search_btn.pack(side=tk.LEFT, padx=(3, 0))
        search_btn.bind("<Button-1>", lambda e: self._open_video_search())
        search_btn.bind("<Enter>", lambda e: search_btn.config(fg=C["accent"], highlightbackground=C["accent"]))
        search_btn.bind("<Leave>", lambda e: search_btn.config(fg=C["text_2"], highlightbackground=C["border"]))

    def _make_video_card(self, video):
        bvid   = video.get("bvid", "")
        title  = video.get("title", "未知标题")
        author = video.get("author", "未知UP主")
        views  = video.get("view_count", 0)
        gap, tidx = nearest_threshold_gap(views)

        card = tk.Frame(self._card_frame, bg=C["bg_surface"], cursor="hand2",
                        highlightthickness=1, highlightbackground=C["border_sub"])
        card.pack(fill=tk.X, padx=6, pady=2)
        inner = tk.Frame(card, bg=C["bg_surface"], padx=10, pady=8)
        inner.pack(fill=tk.X)

        top = tk.Frame(inner, bg=C["bg_surface"])
        top.pack(fill=tk.X)
        thumb = tk.Label(top, width=8, bg=C["bg_elevated"], fg=C["text_3"],
                         text="🎬", font=("Microsoft YaHei UI", 14), relief="flat")
        thumb.pack(side=tk.LEFT)
        info = tk.Frame(top, bg=C["bg_surface"])
        info.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
        title_lbl = tk.Label(info, text=title[:28] + ("…" if len(title) > 28 else ""),
                              bg=C["bg_surface"], fg=C["text_1"],
                              font=FONT, justify="left", anchor="w", wraplength=180)
        title_lbl.pack(fill=tk.X)
        author_lbl = tk.Label(info, text=author[:16], bg=C["bg_surface"],
                               fg=C["text_2"], font=FONT_SM, anchor="w")
        author_lbl.pack(fill=tk.X)

        mid = tk.Frame(inner, bg=C["bg_surface"])
        mid.pack(fill=tk.X, pady=(6, 0))
        views_lbl = tk.Label(mid, text=fmt_num(views),
                              bg=C["bg_surface"], fg=C["text_1"],
                              font=("Consolas", 12, "bold"))
        views_lbl.pack(side=tk.LEFT)
        online_total = video.get("viewers_total", 0)
        online_text = f"👁 {fmt_num(online_total)}" if online_total > 0 else ""
        online_lbl = tk.Label(mid, text=online_text, bg=C["bg_surface"],
                               fg=C["accent"], font=("Consolas", 9))
        online_lbl.pack(side=tk.LEFT, padx=(10, 0))
        stag, stag_fg = card_status_tag(gap)
        tag_lbl = tk.Label(mid, text=stag, bg=C["bg_surface"], fg=stag_fg, font=FONT_SM)
        tag_lbl.pack(side=tk.RIGHT)

        prog_f = tk.Frame(inner, bg=C["bg_surface"])
        prog_f.pack(fill=tk.X, pady=(5, 0))
        prog_bg = tk.Frame(prog_f, bg=C["bg_hover"], height=3)
        prog_bg.pack(fill=tk.X)
        prog_bg.pack_propagate(False)
        if tidx >= 0:
            thr, pct, fill_c = THRESHOLDS[tidx], min(views / THRESHOLDS[tidx], 1.0), THRESH_COLORS[tidx]
        else:
            pct, fill_c = 1.0, C["success"]
        prog_fill = tk.Frame(prog_bg, bg=fill_c, height=3)
        prog_fill.place(x=0, y=0, relwidth=pct, relheight=1)

        label_f = tk.Frame(inner, bg=C["bg_surface"])
        label_f.pack(fill=tk.X)
        if gap > 0:
            gap_text = f"距{THRESHOLD_NAMES[tidx]}：{fmt_num(gap)}"
            pct_text = f"{pct*100:.1f}%"
        else:
            gap_text, pct_text = "已全部达标 ✓", ""
        tk.Label(label_f, text=gap_text, bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM).pack(side=tk.LEFT)
        tk.Label(label_f, text=pct_text, bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM).pack(side=tk.RIGHT)

        self._video_card_widgets[bvid] = {
            "card": card, "inner": inner, "thumb": thumb,
            "title": title_lbl, "author": author_lbl,
            "views": views_lbl, "tag": tag_lbl, "online": online_lbl,
            "prog_fill": prog_fill, "gap_lbl": label_f.winfo_children()[0],
            "pct_lbl": label_f.winfo_children()[1],
        }

        def _select(e, bvid=bvid):
            self._select_video(bvid)
        for w in [card, inner, top, info, mid, prog_f, label_f,
                  title_lbl, author_lbl, views_lbl, tag_lbl, thumb]:
            w.bind("<Button-1>", _select)
        return card

    def _update_card(self, video):
        bvid  = video.get("bvid", "")
        refs  = self._video_card_widgets.get(bvid)
        if not refs:
            return
        views = video.get("view_count", 0)
        gap, tidx = nearest_threshold_gap(views)
        refs["title"].config(text=video.get("title","")[:28] + ("…" if len(video.get("title","")) > 28 else ""))
        refs["author"].config(text=video.get("author","")[:16])
        refs["views"].config(text=fmt_num(views))
        online_total = video.get("viewers_total", 0)
        online_text = f"👁 {fmt_num(online_total)}" if online_total > 0 else ""
        refs["online"].config(text=online_text)
        stag, stag_fg = card_status_tag(gap)
        refs["tag"].config(text=stag, fg=stag_fg)
        if tidx >= 0:
            thr = THRESHOLDS[tidx]
            pct = min(views / thr, 1.0)
            fill_c = THRESH_COLORS[tidx]
            refs["gap_lbl"].config(text=f"距{THRESHOLD_NAMES[tidx]}：{fmt_num(gap)}")
            refs["pct_lbl"].config(text=f"{pct*100:.1f}%")
        else:
            pct, fill_c = 1.0, C["success"]
            refs["gap_lbl"].config(text="已全部达标 ✓")
            refs["pct_lbl"].config(text="")
        refs["prog_fill"].config(bg=fill_c)
        refs["prog_fill"].place(relwidth=pct)
        is_sel = (bvid == self.selected_bvid)
        hl_bg = C["bg_elevated"] if is_sel else C["border_sub"]
        refs["card"].config(highlightbackground=hl_bg)

    def _select_video(self, bvid):
        prev = self.selected_bvid
        self.selected_bvid = bvid
        if prev and prev in self._video_card_widgets:
            self._video_card_widgets[prev]["card"].config(highlightbackground=C["border_sub"])
        if bvid in self._video_card_widgets:
            self._video_card_widgets[bvid]["card"].config(highlightbackground=C["bilibili"])
        video = next((v for v in self.monitored_videos if v.get("bvid") == bvid), None)
        if video:
            self._show_video_detail(video)
        cached = self.prediction_results.get(bvid)
        if cached:
            self._build_pred_hero(cached["prediction"], cached["current_view"],
                                  cached.get("rate_per_sec", 0))

    # ── 中间：详情 + 图表 ───────────────────────
    def _build_center_panel(self):
        p = self._center
        self._detail_header = tk.Frame(p, bg=C["bg_surface"])
        self._detail_header.pack(fill=tk.X)
        tk.Frame(p, bg=C["border"], height=1).pack(fill=tk.X)
        self._build_center_header_empty()

        self._stat_bar = tk.Frame(p, bg=C["bg_surface"])
        self._stat_bar.pack(fill=tk.X)
        tk.Frame(p, bg=C["border"], height=1).pack(fill=tk.X)
        self._stat_labels = {}

        tab_bar = tk.Frame(p, bg=C["bg_surface"])
        tab_bar.pack(fill=tk.X)
        tk.Frame(p, bg=C["border"], height=1).pack(fill=tk.X)
        self._tab_btns = {}
        for name in ["📈 播放量趋势", "📋 详细数据", "🔄 互动率"]:
            b = tk.Label(tab_bar, text=name, bg=C["bg_surface"], fg=C["text_2"],
                         font=FONT, cursor="hand2", padx=14, pady=8)
            b.pack(side=tk.LEFT)
            b.bind("<Button-1>", lambda e, n=name: self._switch_tab(n))
            b.bind("<Enter>", lambda e, b=b: b.config(fg=C["text_1"])
                   if b.cget("fg") != C["bilibili"] else None)
            b.bind("<Leave>", lambda e, b=b: b.config(fg=C["text_2"])
                   if b.cget("fg") != C["bilibili"] else None)
            self._tab_btns[name] = b
        self._current_tab = "📈 播放量趋势"
        self._tab_btns["📈 播放量趋势"].config(fg=C["bilibili"])

        self._content_area = tk.Frame(p, bg=C["bg_base"])
        self._content_area.pack(fill=tk.BOTH, expand=True)

        self._chart_canvas = tk.Canvas(self._content_area, bg=C["bg_base"],
                                        bd=0, highlightthickness=0)
        self._chart_canvas.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
        self._chart_canvas.bind("<Configure>", self._on_chart_resize)

        self._detail_text_frame = tk.Frame(self._content_area, bg=C["bg_base"])
        detail_vsb = ttk.Scrollbar(self._detail_text_frame)
        detail_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._detail_text = tk.Text(self._detail_text_frame, bg=C["bg_elevated"],
                                     fg=C["text_1"], font=FONT_MONO,
                                     relief="flat", bd=0, padx=12, pady=10,
                                     yscrollcommand=detail_vsb.set,
                                     state="disabled", cursor="arrow")
        self._detail_text.pack(fill=tk.BOTH, expand=True)
        detail_vsb.config(command=self._detail_text.yview)

        self._ratio_frame = tk.Frame(self._content_area, bg=C["bg_base"])

        draw_chart_placeholder(self._chart_canvas)
        self._rebuild_stat_bar({})

    def _build_center_header_empty(self):
        h = self._detail_header
        for w in h.winfo_children():
            w.destroy()
        tk.Label(h, text="← 从左侧选择一个视频", bg=C["bg_surface"],
                 fg=C["text_3"], font=FONT, padx=20, pady=18).pack(side=tk.LEFT)

    def _build_center_header(self, video):
        h = self._detail_header
        for w in h.winfo_children():
            w.destroy()
        bvid    = video.get("bvid", "")
        title   = video.get("title", "未知标题")
        author  = video.get("author", "未知UP主")
        dur_sec = video.get("duration", 0)
        pub_ts  = video.get("pubdate", 0)
        dur_str = f"{dur_sec//60}:{dur_sec%60:02d}" if dur_sec else "—"
        pub_str = datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d") if pub_ts else "—"

        self._cover_lbl = tk.Label(h, bg=C["bg_elevated"], fg=C["text_3"],
                                    text="🎬", font=("Microsoft YaHei UI", 32),
                                    width=40, height=10, relief="flat")
        self._cover_lbl.pack(side=tk.LEFT, padx=(14, 12), pady=10)
        self._load_cover_async(video.get("pic", ""), bvid)

        info = tk.Frame(h, bg=C["bg_surface"])
        info.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=10)
        tk.Label(info, text=title, bg=C["bg_surface"], fg=C["text_1"],
                 font=("Microsoft YaHei UI", 12, "bold"),
                 anchor="w", wraplength=500, justify="left").pack(fill=tk.X)
        meta = tk.Frame(info, bg=C["bg_surface"])
        meta.pack(fill=tk.X, pady=(4, 0))
        for icon, val in [("👤", author), ("⏱️", dur_str), ("📅", pub_str)]:
            tf = tk.Frame(meta, bg=C["bg_surface"])
            tf.pack(side=tk.LEFT, padx=(0, 14))
            tk.Label(tf, text=icon, bg=C["bg_surface"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)
            tk.Label(tf, text=" " + val, bg=C["bg_surface"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)

        bv_lbl = tk.Label(meta, text=bvid, bg=C["bg_elevated"], fg=C["text_3"],
                           font=FONT_MONO, padx=6, pady=2, cursor="hand2")
        bv_lbl.pack(side=tk.LEFT, padx=6)
        bv_lbl.bind("<Button-1>", lambda e: self._copy_bvid(bvid))
        bv_lbl.bind("<Enter>", lambda e: bv_lbl.config(fg=C["accent"]))
        bv_lbl.bind("<Leave>", lambda e: bv_lbl.config(fg=C["text_3"]))

    def _rebuild_stat_bar(self, video):
        bar = self._stat_bar
        for w in bar.winfo_children():
            w.destroy()
        self._stat_labels = {}
        fields = [
            ("播放量", "view_count",     C["bilibili"]),
            ("点赞",   "like_count",     C["text_1"]),
            ("投币",   "coin_count",     C["text_1"]),
            ("收藏",   "favorite_count", C["text_1"]),
            ("弹幕",   "danmaku_count",  C["text_1"]),
            ("评论",   "reply_count",    C["text_1"]),
            ("在线人数", "_online_viewers", C["accent"]),
            ("点赞率", "_like_rate",     C["success"]),
            ("周刊分数", "_weekly_score", C["accent"]),
            ("年刊分数", "_yearly_score", C["warning"]),
        ]
        for label, key, color in fields:
            card = tk.Frame(bar, bg=C["bg_elevated"], highlightthickness=1,
                            highlightbackground=C["border_sub"])
            card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, pady=8, ipady=4)
            tk.Label(card, text=label, bg=C["bg_elevated"], fg=C["text_3"],
                     font=FONT_SM).pack(anchor="w", padx=8, pady=(4, 0))
            if key == "_like_rate":
                views = video.get("view_count", 1) or 1
                val = f"{video.get('like_count',0)/views*100:.2f}%"
            elif key == "_weekly_score":
                val = self._calc_weekly_score_text(video)
            elif key == "_yearly_score":
                val = self._calc_yearly_score_text(video)
            elif key == "_online_viewers":
                total = video.get("viewers_total", 0)
                val = f"{fmt_num(total)}" if total > 0 else "—"
            else:
                val = fmt_num(video.get(key, 0)) if video else "—"
            val_lbl = tk.Label(card, text=val, bg=C["bg_elevated"], fg=color,
                                font=("Consolas", 13, "bold"))
            val_lbl.pack(anchor="w", padx=8)
            delta_lbl = tk.Label(card, text="", bg=C["bg_elevated"],
                                  fg=C["success"], font=FONT_SM)
            delta_lbl.pack(anchor="w", padx=8, pady=(0, 4))
            self._stat_labels[key] = (val_lbl, delta_lbl)

    def _update_stat_bar(self, video):
        fields = [
            ("view_count",      C["bilibili"]),
            ("like_count",      C["text_1"]),
            ("coin_count",      C["text_1"]),
            ("favorite_count",  C["text_1"]),
            ("danmaku_count",   C["text_1"]),
            ("reply_count",     C["text_1"]),
            ("_online_viewers", C["accent"]),
            ("_like_rate",      C["success"]),
            ("_weekly_score",   C["accent"]),
            ("_yearly_score",   C["warning"]),
        ]
        views = video.get("view_count", 1) or 1
        for key, color in fields:
            pair = self._stat_labels.get(key)
            if not pair:
                continue
            val_lbl, _ = pair
            if key == "_like_rate":
                val_lbl.config(text=f"{video.get('like_count',0)/views*100:.2f}%")
            elif key == "_weekly_score":
                val_lbl.config(text=self._calc_weekly_score_text(video))
            elif key == "_yearly_score":
                val_lbl.config(text=self._calc_yearly_score_text(video))
            elif key == "_online_viewers":
                total = video.get("viewers_total", 0)
                val_lbl.config(text=fmt_num(total) if total > 0 else "—")
            else:
                val_lbl.config(text=fmt_num(video.get(key, 0)))

    # ── 导航切换 ────────────────────────────────
    def _switch_nav(self, name):
        if name == self._current_nav:
            return
        self._current_nav = name
        for k, b in self._nav_btns.items():
            b.config(fg=C["bilibili"] if k == name else C["text_2"])
        if name == "日志":
            self._main_frame.pack_forget()
            self.log_panel.frame.pack(fill=tk.BOTH, expand=True)
            self.log_panel.refresh_log_view()
            self.log_panel.start_auto_refresh(self.root)
        else:
            self.log_panel.frame.pack_forget()
            self._main_frame.pack(fill=tk.BOTH, expand=True)
            self.log_panel.stop_auto_refresh()

    def _switch_tab(self, name):
        for k, b in self._tab_btns.items():
            b.config(fg=C["bilibili"] if k == name else C["text_2"])
        self._current_tab = name
        self._chart_canvas.pack_forget()
        self._detail_text_frame.pack_forget()
        self._ratio_frame.pack_forget()
        if name == "📈 播放量趋势":
            self._chart_canvas.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
            if self.selected_bvid:
                video = next((v for v in self.monitored_videos
                              if v.get("bvid") == self.selected_bvid), None)
                if video:
                    draw_chart(self._chart_canvas, self.history_data, self.selected_bvid, video, FONT)
                    return
            draw_chart_placeholder(self._chart_canvas)
        elif name == "📋 详细数据":
            self._detail_text_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
            if self.selected_bvid:
                video = next((v for v in self.monitored_videos
                              if v.get("bvid") == self.selected_bvid), None)
                if video:
                    self._fill_detail_text(video)
        elif name == "🔄 互动率":
            self._ratio_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
            if self.selected_bvid:
                video = next((v for v in self.monitored_videos
                              if v.get("bvid") == self.selected_bvid), None)
                if video:
                    self._fill_ratio_frame(video)

    def _on_chart_resize(self, event=None):
        if self.selected_bvid:
            video = next((v for v in self.monitored_videos
                          if v.get("bvid") == self.selected_bvid), None)
            if video:
                draw_chart(self._chart_canvas, self.history_data, self.selected_bvid, video, FONT)
                return
        draw_chart_placeholder(self._chart_canvas)

    # ── 详细数据文本 ─────────────────────────────
    def _fill_detail_text(self, video):
        self._detail_text.config(state="normal")
        self._detail_text.delete("1.0", tk.END)
        bvid    = video.get("bvid", "")
        title   = video.get("title", "N/A")
        author  = video.get("author", "未知")
        views   = video.get("view_count", 0)
        pub_ts  = video.get("pubdate", 0)
        dur     = video.get("duration", 0)
        pub_str = datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d %H:%M") if pub_ts else "—"
        dur_str = f"{dur//60}:{dur%60:02d}" if dur else "—"

        lines = [
            ("=== 视频信息 ===", "head"),
            (f"BV号    {bvid}", "mono"),
            (f"标题    {title}", "mono"),
            (f"UP主    {author}", "mono"),
            (f"时长    {dur_str}", "mono"),
            (f"发布    {pub_str}", "mono"),
            ("", ""),
            ("=== 播放数据 ===", "head"),
            (f"播放量  {fmt_num(views)}", "mono_b"),
            (f"点赞    {fmt_num(video.get('like_count', 0))}", "mono"),
            (f"投币    {fmt_num(video.get('coin_count', 0))}", "mono"),
            (f"分享    {fmt_num(video.get('share_count', 0))}", "mono"),
            (f"收藏    {fmt_num(video.get('favorite_count', 0))}", "mono"),
            (f"弹幕    {fmt_num(video.get('danmaku_count', 0))}", "mono"),
            (f"评论    {fmt_num(video.get('reply_count', 0))}", "mono"),
            ("", ""),
            ("=== 互动率 ===", "head"),
            (f"点赞率  {video.get('like_count',0)/max(views,1)*100:.2f}%", "mono"),
            (f"投币率  {video.get('coin_count',0)/max(views,1)*100:.2f}%", "mono"),
            (f"收藏率  {video.get('favorite_count',0)/max(views,1)*100:.2f}%", "mono"),
            ("", ""),
            ("=== 在线人数 ===", "head"),
        ]
        viewers_total = video.get("viewers_total", 0)
        viewers_web   = video.get("viewers_web", 0)
        viewers_app   = video.get("viewers_app", 0)
        viewers_raw   = video.get("viewers_total_raw", "")
        if viewers_total > 0:
            lines.append((f"总在线  {fmt_num(viewers_total)}  ({viewers_raw})", "mono_accent"))
            lines.append((f"Web端   {fmt_num(viewers_web)}", "mono"))
            lines.append((f"APP端   {fmt_num(viewers_app)}", "mono"))
        else:
            lines.append(("暂无在线人数数据", "mono"))
        lines.append(("", ""))
        lines.append(("=== 阈值进度 ===", "head"))
        for t, name in zip(THRESHOLDS, THRESHOLD_NAMES):
            p = min(100, views/t*100)
            g = t - views
            if g > 0:
                lines.append((f"{name}  {p:.1f}%  (还差 {fmt_num(g)})", "mono"))
            else:
                lines.append((f"{name}  已达成 ✓", "mono_ok"))

        self._detail_text.tag_config("head", foreground=C["bilibili"], font=("Consolas", 10, "bold"))
        self._detail_text.tag_config("mono",    foreground=C["text_1"],  font=FONT_MONO)
        self._detail_text.tag_config("mono_b",  foreground=C["bilibili"],font=("Consolas",10,"bold"))
        self._detail_text.tag_config("mono_ok", foreground=C["success"], font=FONT_MONO)
        self._detail_text.tag_config("mono_accent", foreground=C["accent"], font=("Consolas", 10, "bold"))
        for text, tag in lines:
            self._detail_text.insert(tk.END, text + "\n", tag if tag else ())

        # 周刊分数
        ws = self._calc_weekly_score(video)
        if ws:
            self._detail_text.insert(tk.END, "\n", ())
            self._detail_text.insert(tk.END, "=== 周刊分数 ===\n", "head")
            self._detail_text.insert(tk.END, f"最终得点  {ws.total_score:>10,.2f}\n", "mono_accent")
            self._detail_text.insert(tk.END, "\n", ())
            self._detail_text.insert(tk.END, f"播放得点  {ws.view_score:>10,.2f}  (基础 {ws.base_view_score:,.0f} × 修正D {ws.correction_d:.4f})\n", "mono")
            self._detail_text.insert(tk.END, f"互动得点  {ws.interaction_score:>10,.2f}  (修正A {ws.correction_a:.4f})\n", "mono")
            self._detail_text.insert(tk.END, f"收藏得点  {ws.favorite_score:>10,.2f}  ({video.get('favorite_count',0):,} × 修正B {ws.correction_b:.4f})\n", "mono")
            self._detail_text.insert(tk.END, f"硬币得点  {ws.coin_score:>10,.2f}  ({video.get('coin_count',0):,} × 修正C {ws.correction_c:.4f})\n", "mono")
            self._detail_text.insert(tk.END, f"点赞得点  {ws.like_score:>10,.2f}\n", "mono")

        ys = self._calc_yearly_score(video)
        if ys:
            self._detail_text.insert(tk.END, "\n", ())
            self._detail_text.insert(tk.END, "=== 年刊分数 ===\n", "head")
            self._detail_text.insert(tk.END, f"最终得点  {ys.total_score:>10,.2f}\n", "mono_accent")
            self._detail_text.insert(tk.END, "\n", ())
            self._detail_text.insert(tk.END, f"播放得点  {ys.view_score:>10,.2f}\n", "mono")
            self._detail_text.insert(tk.END, f"互动得点  {ys.interaction_score:>10,.2f}  (修正A {ys.correction_a:.4f})\n", "mono")
            self._detail_text.insert(tk.END, f"收藏得点  {ys.favorite_score:>10,.2f}  ({video.get('favorite_count',0):,} × 修正B {ys.correction_b:.4f})\n", "mono")
            self._detail_text.insert(tk.END, f"硬币得点  {ys.coin_score:>10,.2f}  ({video.get('coin_count',0):,} × 修正C {ys.correction_c:.4f})\n", "mono")
            self._detail_text.insert(tk.END, f"点赞得点  {ys.like_score:>10,.2f}\n", "mono")

        bvid = video.get("bvid", "")
        if bvid in self.video_dbs:
            history_scores = self.video_dbs[bvid].get_weekly_scores(limit=5)
            if len(history_scores) > 1:
                self._detail_text.insert(tk.END, "\n", ())
                self._detail_text.insert(tk.END, "=== 历史周刊分数 ===\n", "head")
                for row in history_scores:
                    ts_str = row.get("timestamp", "")[:16]
                    total = row.get("total_score", 0)
                    self._detail_text.insert(tk.END, f"  {ts_str}  {total:>10,.2f}\n", "mono")
            yearly_scores = self.video_dbs[bvid].get_yearly_scores(limit=5)
            if len(yearly_scores) > 1:
                self._detail_text.insert(tk.END, "\n", ())
                self._detail_text.insert(tk.END, "=== 历史年刊分数 ===\n", "head")
                for row in yearly_scores:
                    ts_str = row.get("timestamp", "")[:16]
                    total = row.get("total_score", 0)
                    self._detail_text.insert(tk.END, f"  {ts_str}  {total:>10,.2f}\n", "mono")
        self._detail_text.config(state="disabled")

    def _calc_weekly_score(self, video):
        try:
            from utils.weekly_score import calculate_from_dict
            return calculate_from_dict(video)
        except Exception:
            return None

    def _calc_weekly_score_text(self, video):
        ws = self._calc_weekly_score(video)
        return f"{ws.total_score:,.0f}" if ws else "—"

    def _calc_yearly_score(self, video):
        try:
            from utils.yearly_score import calculate_yearly_from_dict
            return calculate_yearly_from_dict(video)
        except Exception:
            return None

    def _calc_yearly_score_text(self, video):
        ys = self._calc_yearly_score(video)
        return f"{ys.total_score:,.0f}" if ys else "—"

    def _save_weekly_score(self, bvid, video, timestamp):
        try:
            from utils.weekly_score import calculate_from_dict
            from dataclasses import asdict
            ws = calculate_from_dict(video)
            if ws and bvid in self.video_dbs:
                score_data = asdict(ws)
                self.video_dbs[bvid].add_weekly_score(timestamp, score_data)
        except Exception:
            pass

    def _save_yearly_score(self, bvid, video, timestamp):
        try:
            from utils.yearly_score import calculate_yearly_from_dict
            from dataclasses import asdict
            ys = calculate_yearly_from_dict(video)
            if ys and bvid in self.video_dbs:
                score_data = asdict(ys)
                self.video_dbs[bvid].add_yearly_score(timestamp, score_data)
        except Exception:
            pass

    def _fill_ratio_frame(self, video):
        for w in self._ratio_frame.winfo_children():
            w.destroy()
        views = video.get("view_count", 1) or 1
        ratios = [
            ("点赞率", video.get("like_count",0)/views*100, C["bilibili"]),
            ("投币率", video.get("coin_count",0)/views*100, C["accent"]),
            ("收藏率", video.get("favorite_count",0)/views*100, C["success"]),
            ("弹幕率", video.get("danmaku_count",0)/views*100, C["warning"]),
        ]
        for label, pct, color in ratios:
            row = tk.Frame(self._ratio_frame, bg=C["bg_base"])
            row.pack(fill=tk.X, pady=6)
            tk.Label(row, text=label, bg=C["bg_base"], fg=C["text_2"],
                     font=FONT, width=6).pack(side=tk.LEFT)
            bg_bar = tk.Frame(row, bg=C["bg_elevated"], height=12)
            bg_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
            bg_bar.pack_propagate(False)
            fill_pct = min(pct / 20, 1.0)
            tk.Frame(bg_bar, bg=color, height=12).place(x=0, y=0, relwidth=fill_pct, relheight=1)
            tk.Label(row, text=f"{pct:.3f}%", bg=C["bg_base"], fg=color,
                     font=FONT_MONO, width=8).pack(side=tk.LEFT)

    # ── 右侧：预测分析 ───────────────────────────
    def _build_right_panel(self):
        p = self._right
        self._pred_hero = tk.Frame(p, bg=C["bg_surface"])
        self._pred_hero.pack(fill=tk.X)
        tk.Frame(p, bg=C["border"], height=1).pack(fill=tk.X)
        self._build_pred_hero_empty()

        algo_wrap = tk.Frame(p, bg=C["bg_surface"])
        algo_wrap.pack(fill=tk.BOTH, expand=True)
        self._algo_canvas = tk.Canvas(algo_wrap, bg=C["bg_surface"], bd=0, highlightthickness=0)
        algo_vsb = ttk.Scrollbar(algo_wrap, orient="vertical", command=self._algo_canvas.yview)
        self._algo_canvas.configure(yscrollcommand=algo_vsb.set)
        algo_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._algo_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._algo_frame = tk.Frame(self._algo_canvas, bg=C["bg_surface"])
        self._algo_cwin = self._algo_canvas.create_window((0, 0), window=self._algo_frame, anchor="nw")
        self._algo_frame.bind("<Configure>", lambda e: (
            self._algo_canvas.configure(scrollregion=self._algo_canvas.bbox("all")),
            self._algo_canvas.itemconfig(self._algo_cwin, width=self._algo_canvas.winfo_width())))
        self._algo_canvas.bind("<Configure>", lambda e:
            self._algo_canvas.itemconfig(self._algo_cwin, width=e.width))

    def _build_pred_hero_empty(self):
        h = self._pred_hero
        for w in h.winfo_children():
            w.destroy()
        tk.Label(h, text="数据刷新后自动预测", bg=C["bg_surface"], fg=C["text_3"],
                 font=FONT, padx=14, pady=14).pack()

    def _build_pred_hero(self, weighted_pred, current_views, rate_per_sec):
        h = self._pred_hero
        for w in h.winfo_children():
            w.destroy()
        outer = tk.Frame(h, bg=C["bg_surface"], padx=14, pady=12)
        outer.pack(fill=tk.X)
        tk.Label(outer, text="🎯 综合加权预测", bg=C["bg_surface"], fg=C["text_3"],
                 font=("Microsoft YaHei UI", 8)).pack(anchor="w")
        val_lbl = tk.Label(outer, text=fmt_num(weighted_pred), bg=C["bg_surface"], fg=C["text_1"],
                            font=("Consolas", 18, "bold"))
        val_lbl.pack(anchor="w", pady=(2, 0))
        delta = weighted_pred - current_views
        delta_text = f"▲ +{fmt_num(delta)}" if delta >= 0 else f"▼ {fmt_num(delta)}"
        delta_color = C["success"] if delta >= 0 else C["danger"]
        tk.Label(outer, text=delta_text, bg=C["bg_surface"], fg=delta_color, font=FONT).pack(anchor="w")
        if rate_per_sec > 0:
            per_min = rate_per_sec * 60
            per_hour = rate_per_sec * 3600
            if per_hour >= 1:
                rate_str = f"📈 +{fmt_num(per_hour)}/h"
            elif per_min >= 0.1:
                rate_str = f"📈 +{per_min:.1f}/min"
            else:
                rate_str = f"📈 +{rate_per_sec:.2f}/s"
            tk.Label(outer, text=rate_str, bg=C["bg_surface"], fg=C["accent"],
                     font=FONT_SM).pack(anchor="w", pady=(2, 0))

        tk.Frame(outer, bg=C["border"], height=1).pack(fill=tk.X, pady=6)
        for t, name, col in zip(THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS):
            row = tk.Frame(outer, bg=C["bg_surface"])
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=name, bg=C["bg_surface"], fg=C["text_2"],
                     font=FONT_SM, width=5).pack(side=tk.LEFT)
            bg_bar = tk.Frame(row, bg=C["bg_hover"], height=4)
            bg_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
            bg_bar.pack_propagate(False)
            pct = min(current_views / t, 1.0)
            tk.Frame(bg_bar, bg=col, height=4).place(x=0, y=0, relwidth=pct, relheight=1)
            if t <= current_views:
                eta_str, eta_c = "✓ 已达成", C["success"]
            elif rate_per_sec > 0:
                need = t - current_views
                seconds_left = need / rate_per_sec
                arrive_dt = datetime.now() + timedelta(seconds=seconds_left)
                eta_str = arrive_dt.strftime("%m-%d %H:%M")
                eta_c = C["danger"] if seconds_left < 3600 else C["warning"] if seconds_left < 86400 else C["text_2"]
            else:
                eta_str, eta_c = "—", C["text_3"]
            tk.Label(row, text=eta_str, bg=C["bg_surface"], fg=eta_c,
                     font=FONT_MONO, width=11, anchor="e").pack(side=tk.LEFT)

    def _update_algo_list(self, results, failed):
        f = self._algo_frame
        for w in f.winfo_children():
            w.destroy()
        if results:
            hdr = tk.Frame(f, bg=C["bg_surface"])
            hdr.pack(fill=tk.X, padx=8, pady=(6, 2))
            tk.Label(hdr, text="✅ 成功算法", bg=C["bg_surface"], fg=C["text_3"],
                     font=("Microsoft YaHei UI", 8, "bold")).pack(side=tk.LEFT)
            tk.Label(hdr, text=str(len(results)), bg=C["bg_elevated"], fg=C["text_2"],
                     font=FONT_SM, padx=5, pady=1).pack(side=tk.LEFT, padx=4)
            ALGO_COLORS = [C["bilibili"], C["accent"], C["success"], C["warning"], "#a78bfa", "#22d3ee"]
            for i, (name, pred, weight, conf) in enumerate(results):
                card = tk.Frame(f, bg=C["bg_surface"], highlightthickness=1,
                                highlightbackground=C["border_sub"])
                card.pack(fill=tk.X, padx=6, pady=2)
                inner = tk.Frame(card, bg=C["bg_surface"], padx=10, pady=7)
                inner.pack(fill=tk.X)
                top_row = tk.Frame(inner, bg=C["bg_surface"])
                top_row.pack(fill=tk.X)
                dot_c = ALGO_COLORS[i % len(ALGO_COLORS)]
                tk.Label(top_row, text="●", bg=C["bg_surface"], fg=dot_c, font=FONT_SM).pack(side=tk.LEFT)
                tk.Label(top_row, text=" " + name[:18], bg=C["bg_surface"], fg=C["text_1"], font=FONT).pack(side=tk.LEFT)
                tk.Label(top_row, text=fmt_num(pred), bg=C["bg_surface"], fg=C["accent"],
                         font=("Consolas", 10, "bold")).pack(side=tk.RIGHT)
                bar_row = tk.Frame(inner, bg=C["bg_surface"])
                bar_row.pack(fill=tk.X, pady=(4, 0))
                bg_bar = tk.Frame(bar_row, bg=C["bg_hover"], height=3)
                bg_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
                bg_bar.pack_propagate(False)
                tk.Frame(bg_bar, bg=C["accent"], height=3).place(x=0, y=0, relwidth=conf, relheight=1)
                tk.Label(bar_row, text=f"{conf*100:.0f}%", bg=C["bg_surface"], fg=C["text_3"],
                         font=("Consolas", 8), width=4).pack(side=tk.LEFT, padx=3)
                card.bind("<Enter>", lambda e, c=card: c.config(highlightbackground=C["border"]))
                card.bind("<Leave>", lambda e, c=card: c.config(highlightbackground=C["border_sub"]))
        if failed:
            hdr2 = tk.Frame(f, bg=C["bg_surface"])
            hdr2.pack(fill=tk.X, padx=8, pady=(10, 2))
            tk.Label(hdr2, text="❌ 失败算法", bg=C["bg_surface"], fg=C["text_3"],
                     font=("Microsoft YaHei UI", 8, "bold")).pack(side=tk.LEFT)
            tk.Label(hdr2, text=str(len(failed)), bg=C["bg_elevated"], fg=C["danger"],
                     font=FONT_SM, padx=5, pady=1).pack(side=tk.LEFT, padx=4)
            for name, err in failed:
                row = tk.Frame(f, bg=C["bg_surface"], padx=10, pady=5)
                row.pack(fill=tk.X, padx=6)
                tk.Label(row, text=name[:20], bg=C["bg_surface"], fg=C["text_3"], font=FONT).pack(side=tk.LEFT)
                tk.Label(row, text=str(err)[:30], bg=C["bg_surface"], fg=C["danger"], font=FONT_SM).pack(side=tk.RIGHT)
        self._algo_canvas.yview_moveto(0)

    # ── 底部操作栏 ──────────────────────────────
    def _build_bottom_bar(self):
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill=tk.X)
        bar = tk.Frame(self.root, bg=C["bg_surface"], height=46)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)
        ttk.Button(bar, text="＋ 添加监控", style="Primary.TButton",
                   command=self._add_monitor).pack(side=tk.LEFT, padx=(12, 4), pady=8)
        ttk.Button(bar, text="🔄 立即刷新",
                   command=self._refresh_data).pack(side=tk.LEFT, padx=4, pady=8)
        ttk.Button(bar, text="🗑 删除监控", style="Danger.TButton",
                   command=self._remove_monitor).pack(side=tk.LEFT, padx=4, pady=8)
        ar_f = tk.Frame(bar, bg=C["bg_surface"])
        ar_f.pack(side=tk.RIGHT, padx=14)
        self._ar_toggle = tk.Canvas(ar_f, width=36, height=18, bg=C["bg_surface"],
                                     bd=0, highlightthickness=0, cursor="hand2")
        self._ar_toggle.pack(side=tk.LEFT)
        self._ar_toggle.bind("<Button-1>", self._toggle_auto_refresh)
        tk.Label(ar_f, text="自动刷新", bg=C["bg_surface"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT, padx=4)
        self._draw_toggle(True)

    def _draw_toggle(self, on):
        c = self._ar_toggle
        c.delete("all")
        bg = C["success"] if on else C["bg_hover"]
        rounded_rect(c, 0, 0, 36, 18, 9, fill=bg, outline="")
        cx = 26 if on else 10
        c.create_oval(cx-7, 2, cx+7, 16, fill="#ffffff", outline="")

    def _toggle_theme(self, event=None):
        new_theme = "light" if current_theme_name() == "dark" else "dark"
        apply_theme(self.root, new_theme)
        icon = "☀️" if new_theme == "light" else "🌙"
        self._theme_btn.config(text=icon, bg=C["bg_elevated"], fg=C["text_2"])
        self.log_panel.recolor()
        if hasattr(self, '_detail_text'):
            from ui.theme import _recolor_text_tags
            _recolor_text_tags(self._detail_text)
            self._detail_text.config(bg=C["bg_elevated"], fg=C["text_1"], insertbackground=C["text_1"])
        if hasattr(self, '_chart_canvas') and self.selected_bvid:
            self._chart_canvas.config(bg=C["bg_base"])
            video = next((v for v in self.monitored_videos if v.get("bvid") == self.selected_bvid), None)
            if video:
                draw_chart(self._chart_canvas, self.history_data, self.selected_bvid, video, FONT)
        try:
            config = load_config()
            config.setdefault("ui", {})["theme"] = new_theme
            save_config(config)
        except Exception:
            pass

    # ── 状态栏 ────────────────────────────────────
    def _build_status_bar(self):
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill=tk.X)
        bar = tk.Frame(self.root, bg=C["bg_surface"], height=22)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)
        self._sb_labels = {}
        items = [("videos", "监控: 0 个"), ("interval", "刷新间隔: —"),
                 ("algo", "算法: —"), ("last_ref", "上次刷新: —"), ("status", "就绪")]
        for key, text in items:
            anchor = "e" if key == "status" else "w"
            side = tk.RIGHT if key == "status" else tk.LEFT
            lbl = tk.Label(bar, text=text, bg=C["bg_surface"], fg=C["text_3"],
                           font=("Microsoft YaHei UI", 8))
            lbl.pack(side=side, padx=10)
            self._sb_labels[key] = lbl

    def _sb(self, key, text, color=None):
        lbl = self._sb_labels.get(key)
        if lbl:
            lbl.config(text=text, fg=color or C["text_3"])

    # ──────────────────────────────────────────
    # 业务逻辑（调度层，具体实现在 monitor_service）
    # ──────────────────────────────────────────
    def _start_auto_refresh(self):
        if self.auto_refresh_enabled.get():
            self._schedule_refresh()

    def _schedule_refresh(self):
        if self.auto_refresh_job:
            self.root.after_cancel(self.auto_refresh_job)
        if self.countdown_job:
            self.root.after_cancel(self.countdown_job)
        self.seconds_remaining = self.refresh_interval
        self._tick_countdown()
        self.auto_refresh_job = self.root.after(self.refresh_interval * 1000, self._do_auto_refresh)

    def _tick_countdown(self):
        if self.seconds_remaining >= 0 and self.auto_refresh_enabled.get():
            self._countdown_badge.config(text=f"{self.seconds_remaining:02d} s")
            self.seconds_remaining -= 1
            self.countdown_job = self.root.after(1000, self._tick_countdown)
        elif not self.auto_refresh_enabled.get():
            self._countdown_badge.config(text="— s")

    def _do_auto_refresh(self):
        if not self.auto_refresh_enabled.get():
            return
        self._do_fetch()
        self._check_and_switch_mode()
        self._schedule_refresh()

    def _check_and_switch_mode(self):
        min_gap = float("inf")
        for v in self.monitored_videos:
            g, _ = nearest_threshold_gap(v.get("view_count", 0))
            if 0 < g < min_gap:
                min_gap = g
        if min_gap < self.THRESHOLD_GAP:
            if not self.fast_mode:
                self.fast_mode = True
                self.refresh_interval = self.FAST_INTERVAL
                self._mode_pill.config(text="⚡ 快速模式", fg=C["danger"])
                self._sb("interval", f"刷新间隔: {self.FAST_INTERVAL}s")
                self._schedule_refresh()
        else:
            if self.fast_mode:
                self.fast_mode = False
                self.refresh_interval = self.DEFAULT_INTERVAL
                self._mode_pill.config(text="● 正常模式", fg=C["success"])
                self._sb("interval", f"刷新间隔: {self.DEFAULT_INTERVAL}s")
                self._schedule_refresh()

    def _toggle_auto_refresh(self, event=None):
        cur = self.auto_refresh_enabled.get()
        self.auto_refresh_enabled.set(not cur)
        self._draw_toggle(not cur)
        if not cur:
            self._schedule_refresh()
            self._sb("status", "自动刷新已启用", C["success"])
        else:
            if self.auto_refresh_job:
                self.root.after_cancel(self.auto_refresh_job)
            if self.countdown_job:
                self.root.after_cancel(self.countdown_job)
            self._countdown_badge.config(text="已暂停")
            self._sb("status", "自动刷新已禁用", C["warning"])

    def _do_fetch(self):
        fetch_all_video_data(self)

    def _post_fetch(self):
        now_str = datetime.now().strftime("%H:%M:%S")
        self._sb("status",   "刷新完成", C["success"])
        self._sb("last_ref", f"上次刷新: {now_str}")
        self._sb("videos",   f"监控: {len(self.monitored_videos)} 个")
        self._sb("interval", f"刷新间隔: {self.refresh_interval}s")
        for video in self.monitored_videos:
            bvid = video.get("bvid", "")
            if bvid in self._video_card_widgets:
                self._update_card(video)
        if self.selected_bvid:
            video = next((v for v in self.monitored_videos if v.get("bvid") == self.selected_bvid), None)
            if video:
                self._update_stat_bar(video)
                if self._current_tab == "📈 播放量趋势":
                    draw_chart(self._chart_canvas, self.history_data, self.selected_bvid, video, FONT)
        auto_predict_all(self)

    def _show_video_detail(self, video):
        self._build_center_header(video)
        self._rebuild_stat_bar(video)
        self._switch_tab(self._current_tab)

    # ── 添加/删除监控 ────────────────────────────
    def _add_monitor(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("添加监控")
        dialog.geometry("400x180")
        dialog.configure(bg=C["bg_surface"])
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        tk.Label(dialog, text="请输入BV号或视频链接：", bg=C["bg_surface"], fg=C["text_1"],
                 font=FONT).pack(pady=(18, 4))
        entry_f = tk.Frame(dialog, bg=C["bg_elevated"], highlightthickness=1,
                           highlightbackground=C["border"], highlightcolor=C["bilibili"])
        entry_f.pack(padx=24, fill=tk.X)
        entry = tk.Entry(entry_f, bg=C["bg_elevated"], fg=C["text_1"], insertbackground=C["text_1"],
                         relief="flat", font=FONT, bd=0)
        entry.pack(fill=tk.X, padx=8, pady=6)
        entry.focus_set()
        tk.Label(dialog, text="格式：BV1xxx 或完整链接", bg=C["bg_surface"], fg=C["text_3"],
                 font=FONT_SM).pack()
        status_lbl = tk.Label(dialog, text="", bg=C["bg_surface"], fg=C["accent"], font=FONT_SM)
        status_lbl.pack(pady=2)

        def _confirm():
            raw = entry.get().strip()
            if not raw:
                messagebox.showwarning("提示", "请输入BV号", parent=dialog)
                return
            import re
            bvid = raw
            if "bilibili.com" in raw:
                m = re.search(r"BV[\w]+", raw)
                if m:
                    bvid = m.group()
                else:
                    messagebox.showerror("错误", "无法从链接中提取BV号", parent=dialog)
                    return
            if any(v.get("bvid") == bvid for v in self.monitored_videos):
                messagebox.showinfo("提示", f"{bvid} 已在监控列表中", parent=dialog)
                dialog.destroy()
                return
            status_lbl.config(text="正在获取视频信息…")
            dialog.update()
            def _fetch():
                info = bilibili_api.get_video_info(bvid)
                dialog.after(0, lambda: _done(info))
            def _done(info):
                if not info:
                    status_lbl.config(text="获取失败，请检查BV号", fg=C["danger"])
                    return
                video = self._map_api_to_video_dict(bvid, info)
                self._register_video_to_monitor(video)
                self._save_watch_list()
                messagebox.showinfo("成功", f"已添加监控\n标题：{video['title'][:40]}\nUP主：{video['author']}\n播放：{fmt_num(video['view_count'])}", parent=dialog)
                dialog.destroy()
            threading.Thread(target=_fetch, daemon=True).start()
        btn_f = tk.Frame(dialog, bg=C["bg_surface"])
        btn_f.pack(pady=10)
        ttk.Button(btn_f, text="确认添加", style="Primary.TButton", command=_confirm).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_f, text="取消", command=dialog.destroy).pack(side=tk.LEFT, padx=6)
        entry.bind("<Return>", lambda e: _confirm())

    def _remove_monitor(self):
        if not self.selected_bvid:
            messagebox.showwarning("提示", "请先在左侧选择要删除的视频")
            return
        bvid = self.selected_bvid
        video = next((v for v in self.monitored_videos if v.get("bvid") == bvid), None)
        title = video.get("title", bvid) if video else bvid
        if not messagebox.askyesno("确认删除", f"确定要删除监控：\n{title[:50]}？"):
            return
        self.monitored_videos = [v for v in self.monitored_videos if v.get("bvid") != bvid]
        self.history_data.pop(bvid, None)
        self.video_dbs.pop(bvid, None)
        self.prediction_results.pop(bvid, None)
        refs = self._video_card_widgets.pop(bvid, None)
        if refs:
            refs["card"].destroy()
        self.selected_bvid = None
        self._build_center_header_empty()
        self._rebuild_stat_bar({})
        draw_chart_placeholder(self._chart_canvas)
        self._build_pred_hero_empty()
        for w in self._algo_frame.winfo_children():
            w.destroy()
        self._video_count_lbl.config(text=str(len(self.monitored_videos)))
        self._sb("videos", f"监控: {len(self.monitored_videos)} 个")
        self._save_watch_list()

    def _refresh_data(self):
        self._do_fetch()

    # ── 预测结果回调 ─────────────────────────────
    def _prediction_done(self, w_pred, current_view, growth, rate_per_sec,
                          success_list, fail_list, valid, total):
        self._build_pred_hero(w_pred, current_view, rate_per_sec)
        self._update_algo_list(success_list, fail_list)
        self._sb("algo",   f"算法: {valid}/{total}")
        self._sb("status", "预测完成", C["success"])

    # ── 封面异步加载 ─────────────────────────────
    def _load_cover_async(self, url, bvid):
        if bvid in self._cover_cache:
            self._cover_lbl.config(image=self._cover_cache[bvid], text="")
            self._photo_ref = self._cover_cache[bvid]
            return
        if not url:
            return
        def _fetch():
            try:
                import requests as req
                from PIL import Image, ImageTk
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                          "Referer": "https://www.bilibili.com/"}
                r = req.get(url, timeout=8, headers=headers)
                if r.status_code != 200:
                    return
                img = Image.open(BytesIO(r.content))
                w, h = img.size
                target_w, target_h = 320, 180
                ratio = min(target_w / w, target_h / h)
                new_w, new_h = int(w * ratio), int(h * ratio)
                img = img.resize((new_w, new_h), Image.LANCZOS)
                ph = ImageTk.PhotoImage(img)
                self._cover_cache[bvid] = ph
                self.root.after(0, lambda: self._apply_cover(ph))
            except Exception as e:
                print(f"封面加载失败 {bvid}: {e}")
                self.log_panel.add_log("DEBUG", f"封面加载失败 {bvid}: {e}")
        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_cover(self, ph):
        self._photo_ref = ph
        if hasattr(self, "_cover_lbl") and self._cover_lbl.winfo_exists():
            self._cover_lbl.config(image=ph, text="")

    def _copy_bvid(self, bvid):
        self.root.clipboard_clear()
        self.root.clipboard_append(bvid)
        self._sb("status", f"已复制 {bvid}", C["success"])

    def _on_search(self, *args):
        q = self._search_var.get().strip().lower()
        if q == "搜索标题或bv号…" or q == "":
            q = ""
        for bvid, refs in self._video_card_widgets.items():
            video = next((v for v in self.monitored_videos if v.get("bvid") == bvid), None)
            if not video:
                continue
            visible = (not q or q in video.get("title", "").lower() or
                       q in bvid.lower() or q in video.get("author", "").lower())
            refs["card"].pack(fill=tk.X, padx=6, pady=2) if visible else refs["card"].pack_forget()

    # ── 设置窗口 ────────────────────────────────
    def _open_interval_settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("刷新间隔设置")
        dialog.geometry("320x220")
        dialog.configure(bg=C["bg_surface"])
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        tk.Label(dialog, text="普通刷新间隔（秒）：", bg=C["bg_surface"], fg=C["text_1"],
                 font=FONT).pack(pady=(20, 6))
        spin_f = tk.Frame(dialog, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border"])
        spin_f.pack(padx=40, fill=tk.X)
        var = tk.IntVar(value=self.DEFAULT_INTERVAL)
        ttk.Spinbox(spin_f, from_=10, to=3600, textvariable=var, width=10).pack(padx=8, pady=6)
        tk.Label(dialog, text=f"距阈值 < {FAST_GAP} 时自动切换快速模式（{FAST_INTERVAL}s）",
                 bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM, wraplength=280).pack(pady=6)
        def _save():
            self.DEFAULT_INTERVAL = var.get()
            if not self.fast_mode:
                self.refresh_interval = self.DEFAULT_INTERVAL
                self._sb("interval", f"刷新间隔: {self.refresh_interval}s")
                if self.auto_refresh_enabled.get():
                    self._schedule_refresh()
            dialog.destroy()
        btn_f = tk.Frame(dialog, bg=C["bg_surface"])
        btn_f.pack(pady=14)
        ttk.Button(btn_f, text="保存", style="Primary.TButton", command=_save).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_f, text="取消", command=dialog.destroy).pack(side=tk.LEFT, padx=6)

    # ── 子窗口 ────────────────────────────────────
    def _open_weight_settings(self):
        try:
            from .weight_settings import WeightSettingsWindow
            WeightSettingsWindow(self.root)
        except Exception as e:
            messagebox.showerror("错误", f"打开权重设置失败: {e}")

    def _open_database_query(self):
        try:
            from .database_query import DatabaseQueryWindow
            DatabaseQueryWindow(self.root)
        except Exception as e:
            messagebox.showerror("错误", f"打开数据库查询失败: {e}")

    def _open_video_search(self):
        try:
            from .video_search import VideoSearchWindow
            VideoSearchWindow(self.root, on_import=self._import_search_results)
        except Exception as e:
            messagebox.showerror("错误", f"打开视频搜索失败: {e}")

    def _import_search_results(self, videos: list):
        if not videos:
            return
        added, skipped = 0, 0
        for v in videos:
            bvid = v.get("bvid", "")
            if not bvid:
                continue
            if any(mv.get("bvid") == bvid for mv in self.monitored_videos):
                skipped += 1
                continue
            try:
                info = bilibili_api.get_video_info(bvid)
                if not info:
                    skipped += 1
                    continue
                video = self._map_api_to_video_dict(bvid, info, fallback=v)
                self._register_video_to_monitor(video)
                added += 1
            except Exception as e:
                self.log_panel.add_log("WARNING", f"导入 {bvid} 失败: {e}")
                skipped += 1
        self._save_watch_list()
        msg = f"成功导入 {added} 个视频"
        if skipped:
            msg += f"（跳过 {skipped} 个：已存在或获取失败）"
        if added or skipped:
            messagebox.showinfo("导入完成", msg)

    def _open_data_comparison(self):
        try:
            from .data_comparison import DataComparisonWindow
            DataComparisonWindow(self.root, monitored_videos=self.monitored_videos,
                                 history_data=self.history_data, video_dbs=self.video_dbs)
        except Exception as e:
            messagebox.showerror("错误", f"打开数据对比失败: {e}")

    def _open_crossover_analysis(self):
        try:
            from .crossover_analysis import CrossoverAnalysisWindow
            CrossoverAnalysisWindow(self.root, monitored_videos=self.monitored_videos,
                                    history_data=self.history_data, video_dbs=self.video_dbs)
        except Exception as e:
            messagebox.showerror("错误", f"打开交叉计算失败: {e}")

    def _open_weekly_score(self):
        try:
            from .weekly_score import WeeklyScoreWindow
            WeeklyScoreWindow(self.root, monitored_videos=self.monitored_videos,
                              video_dbs=self.video_dbs)
        except Exception as e:
            messagebox.showerror("错误", f"打开周刊分数计算失败: {e}")

    def _open_settings(self):
        try:
            from .settings_window import SettingsWindow
            SettingsWindow(self.root)
        except Exception as e:
            messagebox.showerror("错误", f"打开设置失败: {e}")

    def _open_network_settings(self):
        try:
            from .network_settings import NetworkSettingsWindow
            NetworkSettingsWindow(self.root)
        except Exception as e:
            messagebox.showerror("错误", f"打开网络设置失败: {e}")

    # ── 监控列表持久化 ─────────────────────────────
    def _load_watch_list(self):
        load_watch_list(self)

    def _restore_video(self, video):
        bvid = video.get("bvid", "")
        if any(v.get("bvid") == bvid for v in self.monitored_videos):
            return
        self.monitored_videos.append(video)
        self._make_video_card(video)
        self._video_count_lbl.config(text=str(len(self.monitored_videos)))
        self._sb("videos", f"监控: {len(self.monitored_videos)} 个")

    @staticmethod
    def _map_api_to_video_dict(bvid: str, info: dict, fallback: dict = None) -> dict:
        fb = fallback or {}
        stat = info.get("stat", {})
        owner = info.get("owner", {})
        return {
            "bvid": bvid, "title": info.get("title", fb.get("title", "未知标题")),
            "author": owner.get("name", fb.get("author", "未知UP主")),
            "pic": info.get("pic", fb.get("pic", "")),
            "view_count": stat.get("view", fb.get("play", 0)),
            "like_count": stat.get("like", fb.get("like", 0)),
            "coin_count": stat.get("coin", 0), "share_count": stat.get("share", 0),
            "favorite_count": stat.get("favorite", 0), "danmaku_count": stat.get("danmaku", 0),
            "reply_count": stat.get("reply", 0), "duration": info.get("duration", 0),
            "pubdate": info.get("pubdate", 0), "desc": info.get("desc", ""),
            "aid": info.get("aid", 0),
            "viewers_total": 0, "viewers_web": 0, "viewers_app": 0,
        }

    def _register_video_to_monitor(self, video: dict) -> None:
        bvid = video["bvid"]
        try:
            video_db = db.get_video_db(bvid)
            self.video_dbs[bvid] = video_db
            video_db.save_video_info(video)
            history = video_db.get_all_records()
            if history:
                self.history_data[bvid] = [(row["timestamp"], row["view_count"]) for row in history]
            else:
                now = datetime.now()
                self.history_data[bvid] = [(now, video["view_count"])]
                rec = MonitorRecord(bvid=bvid, timestamp=now.isoformat(),
                                    view_count=video["view_count"],
                                    like_count=video["like_count"],
                                    coin_count=video["coin_count"],
                                    share_count=video["share_count"],
                                    favorite_count=video["favorite_count"],
                                    danmaku_count=video["danmaku_count"],
                                    reply_count=video["reply_count"])
                video_db.add_monitor_record(rec)
                self._save_weekly_score(bvid, video, now.isoformat())
                self._save_yearly_score(bvid, video, now.isoformat())
        except Exception as e:
            self.log_panel.add_log("WARNING", f"数据库初始化失败: {bvid}: {e}")
        self.monitored_videos.append(video)
        self._make_video_card(video)
        self._video_count_lbl.config(text=str(len(self.monitored_videos)))
        self._sb("videos", f"监控: {len(self.monitored_videos)} 个")

    def _save_watch_list(self):
        config = load_config()
        config["watch_list"] = [v.get("bvid", "") for v in self.monitored_videos]
        save_config(config)

    # ── 退出 ─────────────────────────────────────
    def _on_exit(self):
        self._save_watch_list()
        self.log_panel.cleanup()
        if self.auto_refresh_job:
            self.root.after_cancel(self.auto_refresh_job)
        if self.countdown_job:
            self.root.after_cancel(self.countdown_job)
        self._file_logger.cancel_midnight_checker(self.root)
        self._file_logger.close()
        for bvid in self.video_dbs:
            try:
                db.sync_from_video_db(bvid)
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    app = BilibiliMonitorGUI()
    app.run()


if __name__ == "__main__":
    main()
