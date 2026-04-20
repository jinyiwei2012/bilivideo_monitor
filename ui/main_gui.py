"""
主GUI界面 - 全新设计版
深色三栏布局：左侧视频卡片 / 中间图表详情 / 右侧预测分析
"""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import threading
import time
import math
import sys
import os
from datetime import datetime, timedelta
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from algorithms.registry import AlgorithmRegistry
from core import bilibili_api, db, MonitorRecord
from config import load_config, save_config
from utils.file_logger import FileLogger

# ──────────────────────────────────────────────
# 设计令牌
# ──────────────────────────────────────────────
C = {
    "bg_base":      "#0d1117",
    "bg_surface":   "#161b22",
    "bg_elevated":  "#21262d",
    "bg_hover":     "#30363d",
    "border":       "#30363d",
    "border_sub":   "#21262d",

    "bilibili":     "#fb7299",
    "bilibili_dim": "#c45a79",

    "accent":       "#58a6ff",
    "success":      "#3fb950",
    "warning":      "#d29922",
    "danger":       "#f85149",

    "text_1":       "#e6edf3",
    "text_2":       "#8b949e",
    "text_3":       "#484f58",

    "chart_line":   "#fb7299",
    "chart_area":   "#fb7299",
    "chart_dot":    "#fb7299",
    "thresh_10w":   "#3fb950",
    "thresh_100w":  "#d29922",
    "thresh_1000w": "#a78bfa",
}

FONT      = ("Microsoft YaHei UI", 9)
FONT_BOLD = ("Microsoft YaHei UI", 9, "bold")
FONT_SM   = ("Microsoft YaHei UI", 8)
FONT_LG   = ("Microsoft YaHei UI", 11, "bold")
FONT_MONO = ("Consolas", 9)
FONT_MONO_LG = ("Consolas", 14, "bold")

THRESHOLDS      = [100_000, 1_000_000, 10_000_000]
THRESHOLD_NAMES = ["10万", "100万", "1000万"]
THRESH_COLORS   = [C["thresh_10w"], C["thresh_100w"], C["thresh_1000w"]]

DEFAULT_INTERVAL = 75
FAST_INTERVAL    = 10
FAST_GAP         = 500


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────
def fmt_num(n):
    """格式化数字"""
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def fmt_eta(minutes):
    """格式化预计时间"""
    if minutes <= 0:
        return "—"
    hours = int(minutes // 60)
    mins  = int(minutes % 60)
    days  = hours // 24
    hrs   = hours % 24
    if days > 0:
        return f"约{days}天{hrs}h"
    if hours > 0:
        return f"约{hours}h{mins}min"
    return f"约{mins}min"


def nearest_threshold_gap(views):
    """返回 (gap, threshold_index)，找最近未达到的阈值"""
    for i, t in enumerate(THRESHOLDS):
        if t > views:
            return t - views, i
    return 0, -1


def _card_status_tag(gap: int):
    """根据与阈值的距离返回 (标签文字, 颜色)，供视频卡片使用"""
    if 0 < gap < 500:
        return "🔥 接近", C["danger"]
    if 0 < gap < 10000:
        return "📈 进行中", C["success"]
    return "📊 正常", C["text_3"]


# ──────────────────────────────────────────────
# 深色风格 ttk Style 初始化
# ──────────────────────────────────────────────
def apply_dark_style(root):
    style = ttk.Style(root)
    style.theme_use("clam")

    # 通用背景
    style.configure(".",
        background=C["bg_base"],
        foreground=C["text_1"],
        bordercolor=C["border"],
        troughcolor=C["bg_elevated"],
        selectbackground=C["bilibili"],
        selectforeground="#ffffff",
        font=FONT,
    )
    # Frame
    style.configure("TFrame", background=C["bg_base"])
    style.configure("Surface.TFrame", background=C["bg_surface"])
    style.configure("Elevated.TFrame", background=C["bg_elevated"])

    # Label
    style.configure("TLabel", background=C["bg_base"], foreground=C["text_1"])
    style.configure("Surface.TLabel", background=C["bg_surface"], foreground=C["text_1"])
    style.configure("Muted.TLabel",   background=C["bg_surface"], foreground=C["text_3"])
    style.configure("Sub.TLabel",     background=C["bg_surface"], foreground=C["text_2"])
    style.configure("Bilibili.TLabel",background=C["bg_surface"], foreground=C["bilibili"])
    style.configure("Success.TLabel", background=C["bg_surface"], foreground=C["success"])
    style.configure("Danger.TLabel",  background=C["bg_surface"], foreground=C["danger"])
    style.configure("Warning.TLabel", background=C["bg_surface"], foreground=C["warning"])
    style.configure("Accent.TLabel",  background=C["bg_surface"], foreground=C["accent"])

    # Elevated Labels
    style.configure("EL.TLabel",     background=C["bg_elevated"], foreground=C["text_1"])
    style.configure("ELSub.TLabel",  background=C["bg_elevated"], foreground=C["text_2"])
    style.configure("ELMuted.TLabel",background=C["bg_elevated"], foreground=C["text_3"])

    # Separator
    style.configure("TSeparator", background=C["border"])

    # Scrollbar
    style.configure("TScrollbar",
        background=C["bg_elevated"],
        troughcolor=C["bg_surface"],
        bordercolor=C["bg_surface"],
        arrowcolor=C["text_3"],
        relief="flat",
    )

    # Button
    style.configure("TButton",
        background=C["bg_elevated"],
        foreground=C["text_2"],
        bordercolor=C["border"],
        relief="flat",
        padding=(8, 4),
        font=FONT,
    )
    style.map("TButton",
        background=[("active", C["bg_hover"]), ("pressed", C["bg_hover"])],
        foreground=[("active", C["text_1"])],
    )
    # Primary button
    style.configure("Primary.TButton",
        background=C["bilibili"],
        foreground="#ffffff",
        font=FONT_BOLD,
        padding=(10, 5),
    )
    style.map("Primary.TButton",
        background=[("active", C["bilibili_dim"]), ("pressed", C["bilibili_dim"])],
    )
    # Danger ghost
    style.configure("Danger.TButton",
        background=C["bg_surface"],
        foreground=C["danger"],
        bordercolor=C["danger"],
        font=FONT,
        padding=(8, 4),
    )
    style.map("Danger.TButton",
        background=[("active", "#f8514922")],
    )

    # Entry
    style.configure("TEntry",
        fieldbackground=C["bg_elevated"],
        foreground=C["text_1"],
        bordercolor=C["border"],
        insertcolor=C["text_1"],
        relief="flat",
        padding=4,
    )
    style.map("TEntry", bordercolor=[("focus", C["bilibili"])])

    # Notebook
    style.configure("TNotebook",
        background=C["bg_surface"],
        bordercolor=C["border"],
        tabmargins=[0, 0, 0, 0],
    )
    style.configure("TNotebook.Tab",
        background=C["bg_surface"],
        foreground=C["text_2"],
        padding=[14, 6],
        font=FONT,
        bordercolor=C["border"],
    )
    style.map("TNotebook.Tab",
        background=[("selected", C["bg_surface"])],
        foreground=[("selected", C["bilibili"])],
        focuscolor=[("selected", C["bilibili"])],
    )

    # Treeview（数据库查询等子窗口用）
    style.configure("Treeview",
        background=C["bg_elevated"],
        fieldbackground=C["bg_elevated"],
        foreground=C["text_1"],
        rowheight=24,
        bordercolor=C["border"],
    )
    style.configure("Treeview.Heading",
        background=C["bg_surface"],
        foreground=C["text_2"],
        bordercolor=C["border"],
        relief="flat",
        font=FONT,
    )
    style.map("Treeview",
        background=[("selected", C["bilibili_dim"])],
        foreground=[("selected", "#ffffff")],
    )

    # Spinbox
    style.configure("TSpinbox",
        fieldbackground=C["bg_elevated"],
        foreground=C["text_1"],
        bordercolor=C["border"],
        arrowcolor=C["text_2"],
        relief="flat",
    )

    root.configure(bg=C["bg_base"])


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
        apply_dark_style(root)

        # 状态变量
        self.refresh_interval      = self.DEFAULT_INTERVAL
        self.auto_refresh_enabled  = tk.BooleanVar(value=True)
        self.auto_refresh_job      = None
        self.countdown_job         = None
        self.seconds_remaining     = 0
        self.fast_mode             = False

        # 数据
        self.monitored_videos  = []          # List[dict]
        self.history_data      = {}          # bvid -> [(ts, views), ...]
        self.prediction_results= {}          # bvid -> results dict
        self.video_dbs         = {}          # bvid -> VideoDatabase
        self.selected_bvid     = None

        # UI 组件引用（提前初始化，防止事件回调在 build 前触发）
        self._video_card_widgets = {}        # bvid -> dict of widget refs

        # 图表封面缓存
        self._cover_cache      = {}          # bvid -> PhotoImage
        self._photo_ref        = None        # 当前显示封面的引用

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
        self._build_log_panel()     # 先创建日志面板（不 pack）
        self._build_main()
        self._build_bottom_bar()
        self._build_status_bar()

    # ── 顶部标题栏 ──────────────────────────────
    def _build_titlebar(self):
        bar = tk.Frame(self.root, bg=C["bg_surface"], height=46)
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)

        # 分隔线
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
                # 页面切换按钮
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

        # 左栏
        self._left = tk.Frame(main, bg=C["bg_surface"], width=310)
        self._left.pack(side=tk.LEFT, fill=tk.Y)
        self._left.pack_propagate(False)
        tk.Frame(main, bg=C["border"], width=1).pack(side=tk.LEFT, fill=tk.Y)

        # 中栏
        self._center = tk.Frame(main, bg=C["bg_base"])
        self._center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Frame(main, bg=C["border"], width=1).pack(side=tk.LEFT, fill=tk.Y)

        # 右栏
        self._right = tk.Frame(main, bg=C["bg_surface"], width=290)
        self._right.pack(side=tk.LEFT, fill=tk.Y)
        self._right.pack_propagate(False)

        self._build_left_panel()
        self._build_center_panel()
        self._build_right_panel()

    # ── 左侧：视频列表 ──────────────────────────
    def _build_left_panel(self):
        p = self._left

        # 标题行
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
        # placeholder
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
        self._video_card_widgets = {}   # bvid -> dict of widget refs

        # 底部操作按钮行
        bottom_f = tk.Frame(p, bg=C["bg_surface"])
        bottom_f.pack(fill=tk.X, padx=10, pady=8)

        btn = tk.Label(bottom_f, text="＋  添加监控",
                       bg=C["bg_surface"], fg=C["text_2"],
                       font=FONT, cursor="hand2", pady=6,
                       relief="flat",
                       highlightthickness=1,
                       highlightbackground=C["border"],
                       highlightcolor=C["bilibili"])
        btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        btn.bind("<Button-1>", lambda e: self._add_monitor())
        btn.bind("<Enter>", lambda e: btn.config(fg=C["bilibili"],
                                                  highlightbackground=C["bilibili"]))
        btn.bind("<Leave>", lambda e: btn.config(fg=C["text_2"],
                                                  highlightbackground=C["border"]))

        search_btn = tk.Label(bottom_f, text="🔍 搜索视频",
                              bg=C["bg_surface"], fg=C["text_2"],
                              font=FONT, cursor="hand2", pady=6, padx=8,
                              relief="flat",
                              highlightthickness=1,
                              highlightbackground=C["border"],
                              highlightcolor=C["accent"])
        search_btn.pack(side=tk.LEFT, padx=(3, 0))
        search_btn.bind("<Button-1>", lambda e: self._open_video_search())
        search_btn.bind("<Enter>", lambda e: search_btn.config(fg=C["accent"],
                                  highlightbackground=C["accent"]))
        search_btn.bind("<Leave>", lambda e: search_btn.config(fg=C["text_2"],
                                  highlightbackground=C["border"]))

    def _make_video_card(self, video):
        """创建视频卡片 Frame，返回 frame"""
        bvid   = video.get("bvid", "")
        title  = video.get("title", "未知标题")
        author = video.get("author", "未知UP主")
        views  = video.get("view_count", 0)
        gap, tidx = nearest_threshold_gap(views)

        card = tk.Frame(self._card_frame, bg=C["bg_surface"],
                        cursor="hand2",
                        highlightthickness=1,
                        highlightbackground=C["border_sub"])
        card.pack(fill=tk.X, padx=6, pady=2)

        inner = tk.Frame(card, bg=C["bg_surface"], padx=10, pady=8)
        inner.pack(fill=tk.X)

        # 上方行：缩略图 + 标题信息
        top = tk.Frame(inner, bg=C["bg_surface"])
        top.pack(fill=tk.X)

        thumb = tk.Label(top, width=8, bg=C["bg_elevated"], fg=C["text_3"],
                         text="🎬", font=("Microsoft YaHei UI", 14),
                         relief="flat")
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

        # 中间行：播放量 + 状态标签
        mid = tk.Frame(inner, bg=C["bg_surface"])
        mid.pack(fill=tk.X, pady=(6, 0))

        views_lbl = tk.Label(mid, text=fmt_num(views),
                              bg=C["bg_surface"], fg=C["text_1"],
                              font=("Consolas", 12, "bold"))
        views_lbl.pack(side=tk.LEFT)

        # 状态标签
        stag, stag_fg = _card_status_tag(gap)

        tag_lbl = tk.Label(mid, text=stag, bg=C["bg_surface"], fg=stag_fg,
                           font=FONT_SM)
        tag_lbl.pack(side=tk.RIGHT)

        # 进度条行
        prog_f = tk.Frame(inner, bg=C["bg_surface"])
        prog_f.pack(fill=tk.X, pady=(5, 0))

        prog_bg = tk.Frame(prog_f, bg=C["bg_hover"], height=3)
        prog_bg.pack(fill=tk.X)
        prog_bg.pack_propagate(False)

        if tidx >= 0:
            thr     = THRESHOLDS[tidx]
            pct     = min(views / thr, 1.0)
            fill_c  = THRESH_COLORS[tidx]
        else:
            pct, fill_c = 1.0, C["success"]

        prog_fill = tk.Frame(prog_bg, bg=fill_c, height=3)
        prog_fill.place(x=0, y=0, relwidth=pct, relheight=1)

        # 进度标签
        label_f = tk.Frame(inner, bg=C["bg_surface"])
        label_f.pack(fill=tk.X)
        if gap > 0:
            gap_text  = f"距{THRESHOLD_NAMES[tidx]}：{fmt_num(gap)}"
            pct_text  = f"{pct*100:.1f}%"
        else:
            gap_text  = "已全部达标 ✓"
            pct_text  = ""
        tk.Label(label_f, text=gap_text, bg=C["bg_surface"],
                 fg=C["text_3"], font=FONT_SM).pack(side=tk.LEFT)
        tk.Label(label_f, text=pct_text, bg=C["bg_surface"],
                 fg=C["text_3"], font=FONT_SM).pack(side=tk.RIGHT)

        # 缓存 widget 引用（用于更新）
        self._video_card_widgets[bvid] = {
            "card": card, "inner": inner, "thumb": thumb,
            "title": title_lbl, "author": author_lbl,
            "views": views_lbl, "tag": tag_lbl,
            "prog_fill": prog_fill, "gap_lbl": label_f.winfo_children()[0],
            "pct_lbl": label_f.winfo_children()[1],
        }

        # 点击选择
        def _select(e, bvid=bvid):
            self._select_video(bvid)
        for w in [card, inner, top, info, mid, prog_f, label_f,
                  title_lbl, author_lbl, views_lbl, tag_lbl, thumb]:
            w.bind("<Button-1>", _select)

        return card

    def _update_card(self, video):
        """更新已存在的视频卡片数据"""
        bvid  = video.get("bvid", "")
        refs  = self._video_card_widgets.get(bvid)
        if not refs:
            return
        views = video.get("view_count", 0)
        gap, tidx = nearest_threshold_gap(views)

        refs["title"].config(
            text=video.get("title","")[:28] + ("…" if len(video.get("title","")) > 28 else ""))
        refs["author"].config(text=video.get("author","")[:16])
        refs["views"].config(text=fmt_num(views))

        stag, stag_fg = _card_status_tag(gap)
        refs["tag"].config(text=stag, fg=stag_fg)

        if tidx >= 0:
            thr    = THRESHOLDS[tidx]
            pct    = min(views / thr, 1.0)
            fill_c = THRESH_COLORS[tidx]
            refs["gap_lbl"].config(text=f"距{THRESHOLD_NAMES[tidx]}：{fmt_num(gap)}")
            refs["pct_lbl"].config(text=f"{pct*100:.1f}%")
        else:
            pct, fill_c = 1.0, C["success"]
            refs["gap_lbl"].config(text="已全部达标 ✓")
            refs["pct_lbl"].config(text="")
        refs["prog_fill"].config(bg=fill_c)
        refs["prog_fill"].place(relwidth=pct)

        # 高亮选中卡片
        is_sel = (bvid == self.selected_bvid)
        hl_bg = C["bg_elevated"] if is_sel else C["border_sub"]
        refs["card"].config(highlightbackground=hl_bg)

    def _select_video(self, bvid):
        prev = self.selected_bvid
        self.selected_bvid = bvid
        # 重绘两张卡片边框
        if prev and prev in self._video_card_widgets:
            self._video_card_widgets[prev]["card"].config(
                highlightbackground=C["border_sub"])
        if bvid in self._video_card_widgets:
            self._video_card_widgets[bvid]["card"].config(
                highlightbackground=C["bilibili"])
        video = next((v for v in self.monitored_videos if v.get("bvid") == bvid), None)
        if video:
            self._show_video_detail(video)
        # 如果有缓存的预测结果，直接显示
        cached = self.prediction_results.get(bvid)
        if cached:
            self._build_pred_hero(
                cached["prediction"], cached["current_view"],
                cached.get("rate_per_sec", 0))

    # ── 中间：详情 + 图表 ───────────────────────
    def _build_center_panel(self):
        p = self._center

        # 1. 视频头部（封面 + 标题 + Meta）
        self._detail_header = tk.Frame(p, bg=C["bg_surface"])
        self._detail_header.pack(fill=tk.X)
        tk.Frame(p, bg=C["border"], height=1).pack(fill=tk.X)

        self._build_center_header_empty()

        # 2. 数据卡片行
        self._stat_bar = tk.Frame(p, bg=C["bg_surface"])
        self._stat_bar.pack(fill=tk.X)
        tk.Frame(p, bg=C["border"], height=1).pack(fill=tk.X)
        self._stat_labels = {}   # key -> (val_lbl, delta_lbl)

        # 3. Tab 栏
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

        # 4. 内容区（图表 / 详细 / 互动率）
        self._content_area = tk.Frame(p, bg=C["bg_base"])
        self._content_area.pack(fill=tk.BOTH, expand=True)

        # 图表 Canvas
        self._chart_canvas = tk.Canvas(self._content_area, bg=C["bg_base"],
                                        bd=0, highlightthickness=0)
        self._chart_canvas.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
        self._chart_canvas.bind("<Configure>", self._on_chart_resize)

        # 详细数据文本（隐藏）
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

        # 互动率文本（隐藏）
        self._ratio_frame = tk.Frame(self._content_area, bg=C["bg_base"])

        self._draw_chart_placeholder()
        self._rebuild_stat_bar({})

    def _build_center_header_empty(self):
        """初始空头部"""
        h = self._detail_header
        for w in h.winfo_children():
            w.destroy()
        tk.Label(h, text="← 从左侧选择一个视频", bg=C["bg_surface"],
                 fg=C["text_3"], font=FONT, padx=20, pady=18).pack(side=tk.LEFT)

    def _build_center_header(self, video):
        """填充视频头部"""
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

        # 封面
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
            tk.Label(tf, text=icon, bg=C["bg_surface"], fg=C["text_2"],
                     font=FONT).pack(side=tk.LEFT)
            tk.Label(tf, text=" " + val, bg=C["bg_surface"], fg=C["text_2"],
                     font=FONT).pack(side=tk.LEFT)

        bv_lbl = tk.Label(meta, text=bvid, bg=C["bg_elevated"], fg=C["text_3"],
                           font=FONT_MONO, padx=6, pady=2, cursor="hand2")
        bv_lbl.pack(side=tk.LEFT, padx=6)
        bv_lbl.bind("<Button-1>", lambda e: self._copy_bvid(bvid))
        bv_lbl.bind("<Enter>", lambda e: bv_lbl.config(fg=C["accent"]))
        bv_lbl.bind("<Leave>", lambda e: bv_lbl.config(fg=C["text_3"]))

    def _rebuild_stat_bar(self, video):
        """重建数据统计卡片行"""
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
            ("点赞率", "_like_rate",     C["success"]),
        ]
        for label, key, color in fields:
            card = tk.Frame(bar, bg=C["bg_elevated"],
                            highlightthickness=1,
                            highlightbackground=C["border_sub"])
            card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, pady=8, ipady=4)

            tk.Label(card, text=label, bg=C["bg_elevated"], fg=C["text_3"],
                     font=FONT_SM).pack(anchor="w", padx=8, pady=(4, 0))

            if key == "_like_rate":
                views = video.get("view_count", 1) or 1
                val   = f"{video.get('like_count',0)/views*100:.2f}%"
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
        """仅更新数值，不重建"""
        fields = [
            ("view_count",     C["bilibili"]),
            ("like_count",     C["text_1"]),
            ("coin_count",     C["text_1"]),
            ("favorite_count", C["text_1"]),
            ("danmaku_count",  C["text_1"]),
            ("reply_count",    C["text_1"]),
            ("_like_rate",     C["success"]),
        ]
        views = video.get("view_count", 1) or 1
        for key, color in fields:
            pair = self._stat_labels.get(key)
            if not pair:
                continue
            val_lbl, _ = pair
            if key == "_like_rate":
                val_lbl.config(text=f"{video.get('like_count',0)/views*100:.2f}%")
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
            # 隐藏监控页面，显示日志页面
            self._main_frame.pack_forget()
            self._log_frame.pack(fill=tk.BOTH, expand=True)
        else:
            # 隐藏日志页面，显示监控页面
            self._log_frame.pack_forget()
            self._main_frame.pack(fill=tk.BOTH, expand=True)

    # ── 日志面板 ────────────────────────────────
    def _build_log_panel(self):
        """构建日志面板（独立于主三栏布局）"""
        self._log_frame = tk.Frame(self.root, bg=C["bg_base"])

        # 顶部工具栏
        toolbar = tk.Frame(self._log_frame, bg=C["bg_surface"])
        toolbar.pack(fill=tk.X)

        tk.Label(toolbar, text="应用日志", bg=C["bg_surface"], fg=C["text_1"],
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side=tk.LEFT, padx=14, pady=8)

        # 等级筛选按钮
        self._log_level_var = tk.StringVar(value="ALL")
        self._log_levels = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"]
        self._log_level_btns = {}
        level_colors = {
            "ALL": C["text_2"], "DEBUG": "#8b949e",
            "INFO": C["accent"], "WARNING": C["warning"], "ERROR": C["danger"],
        }
        for lvl in self._log_levels:
            fg = level_colors.get(lvl, C["text_2"])
            btn = tk.Label(toolbar, text=lvl, bg=C["bg_elevated"] if lvl == "ALL" else C["bg_hover"],
                           fg=C["bilibili"] if lvl == "ALL" else fg,
                           font=("Consolas", 9), cursor="hand2", padx=8, pady=3)
            btn.pack(side=tk.LEFT, padx=(2, 0), pady=6)
            btn.bind("<Button-1>", lambda e, l=lvl: self._set_log_level(l))
            btn.bind("<Enter>", lambda e, b=btn: b.config(bg=C["bg_elevated"]))
            btn.bind("<Leave>", lambda e, b=btn, l=lvl:
                     b.config(bg=C["bg_elevated"] if l == self._log_level_var.get() else C["bg_hover"]))
            self._log_level_btns[lvl] = btn

        # 清空按钮
        tk.Label(toolbar, text="🗑 清空", bg=C["bg_surface"], fg=C["text_3"],
                 font=("Microsoft YaHei UI", 9), cursor="hand2", padx=8, pady=3
                 ).pack(side=tk.RIGHT, padx=14, pady=6)
        toolbar.winfo_children()[-1].bind("<Button-1>", lambda e: self._clear_log())
        toolbar.winfo_children()[-1].bind("<Enter>",
                 lambda e: toolbar.winfo_children()[-1].config(fg=C["danger"]))
        toolbar.winfo_children()[-1].bind("<Leave>",
                 lambda e: toolbar.winfo_children()[-1].config(fg=C["text_3"]))

        tk.Frame(self._log_frame, bg=C["border"], height=1).pack(fill=tk.X)

        # 日志文本框
        log_container = tk.Frame(self._log_frame, bg=C["bg_base"])
        log_container.pack(fill=tk.BOTH, expand=True)

        self._log_text = tk.Text(log_container, bg="#0d1117", fg="#c9d1d9",
                                  font=("Consolas", 10), wrap=tk.WORD,
                                  bd=0, highlightthickness=0,
                                  insertbackground=C["text_1"],
                                  state=tk.DISABLED, cursor="arrow")
        log_sb = ttk.Scrollbar(log_container, orient="vertical",
                                command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_sb.set)
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        log_sb.pack(side=tk.RIGHT, fill=tk.Y)

        # 日志颜色标签
        self._log_text.tag_configure("DEBUG", foreground="#8b949e")
        self._log_text.tag_configure("INFO",  foreground="#58a6ff")
        self._log_text.tag_configure("WARNING", foreground="#d29922")
        self._log_text.tag_configure("ERROR", foreground="#f85149")
        self._log_text.tag_configure("TIME",  foreground="#6e7681")

        # 日志存储
        self._log_entries = []   # [(level, timestamp_str, message), ...]

    def _set_log_level(self, level):
        self._log_level_var.set(level)
        for l, btn in self._log_level_btns.items():
            btn.config(
                bg=C["bg_elevated"] if l == level else C["bg_hover"],
                fg=C["bilibili"] if l == level else C["text_2"],
            )
        self._refresh_log_view()

    def _add_log(self, level: str, message: str):
        """添加日志条目"""
        ts = datetime.now()
        ts_str = ts.strftime("%H:%M:%S")
        self._log_entries.append((level, ts_str, message))
        # 写入文件
        try:
            self._file_logger.write(level, message, ts)
        except Exception:
            pass
        # 限制内存中日志数量
        if len(self._log_entries) > 2000:
            self._log_entries = self._log_entries[-1500:]
        # 如果日志面板可见且等级匹配，实时追加
        if self._current_nav == "日志":
            filter_level = self._log_level_var.get()
            if filter_level == "ALL" or level == filter_level or \
               (filter_level == "WARNING" and level == "ERROR") or \
               (filter_level == "INFO" and level in ("INFO", "WARNING", "ERROR")) or \
               (filter_level == "DEBUG"):
                self._append_log_line(level, ts, message)

    def _append_log_line(self, level, ts, message):
        self._log_text.config(state=tk.NORMAL)
        self._log_text.insert(tk.END, f"[{ts}] ", "TIME")
        self._log_text.insert(tk.END, f"[{level:>7s}] ", level)
        self._log_text.insert(tk.END, f"{message}\n")
        self._log_text.see(tk.END)
        self._log_text.config(state=tk.DISABLED)

    def _refresh_log_view(self):
        """根据当前等级筛选刷新日志"""
        self._log_text.config(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        filter_level = self._log_level_var.get()
        level_order = {"ERROR": 0, "WARNING": 1, "INFO": 2, "DEBUG": 3}
        for level, ts, msg in self._log_entries:
            if filter_level == "ALL":
                show = True
            elif filter_level == "DEBUG":
                show = True
            elif filter_level == "INFO":
                show = level in ("ERROR", "WARNING", "INFO")
            elif filter_level == "WARNING":
                show = level in ("ERROR", "WARNING")
            else:
                show = level == filter_level
            if show:
                self._log_text.insert(tk.END, f"[{ts}] ", "TIME")
                self._log_text.insert(tk.END, f"[{level:>7s}] ", level)
                self._log_text.insert(tk.END, f"{msg}\n")
        self._log_text.see(tk.END)
        self._log_text.config(state=tk.DISABLED)

    def _clear_log(self):
        self._log_entries.clear()
        self._log_text.config(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        self._log_text.config(state=tk.DISABLED)

    def _switch_tab(self, name):
        for k, b in self._tab_btns.items():
            b.config(fg=C["bilibili"] if k == name else C["text_2"])
        self._current_tab = name

        # 隐藏所有内容
        self._chart_canvas.pack_forget()
        self._detail_text_frame.pack_forget()
        self._ratio_frame.pack_forget()

        if name == "📈 播放量趋势":
            self._chart_canvas.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
            if self.selected_bvid:
                video = next((v for v in self.monitored_videos
                              if v.get("bvid") == self.selected_bvid), None)
                if video:
                    self._draw_chart(video)
                    return
            self._draw_chart_placeholder()

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

    # ── 图表绘制 ─────────────────────────────────
    def _on_chart_resize(self, event=None):
        if self.selected_bvid:
            video = next((v for v in self.monitored_videos
                          if v.get("bvid") == self.selected_bvid), None)
            if video:
                self._draw_chart(video)
                return
        self._draw_chart_placeholder()

    def _draw_chart_placeholder(self):
        c = self._chart_canvas
        c.delete("all")
        w = c.winfo_width()  or 600
        h = c.winfo_height() or 300
        c.create_text(w//2, h//2, text="选择视频后显示播放量趋势图",
                      fill=C["text_3"], font=("Microsoft YaHei UI", 11))

    def _draw_chart(self, video):
        c    = self._chart_canvas
        c.delete("all")
        bvid = video.get("bvid", "")

        W = c.winfo_width()  or 600
        H = c.winfo_height() or 300
        if W < 100 or H < 60:
            return

        ML, MR, MT, MB = 58, 20, 28, 36
        cw = W - ML - MR
        ch = H - MT - MB

        history = self.history_data.get(bvid, [])
        has_data = len(history) >= 2

        if not has_data:
            self._draw_chart_grid(c, W, H, ML, MR, MT, MB, cw, ch,
                                  0, 1, video.get("view_count", 0))
            c.create_text(W//2, H//2, text="数据点不足（需要至少2条记录）",
                          fill=C["text_3"], font=FONT)
            return

        views_list = [v for _, v in history]
        min_v, max_v, span, px, py = self._compute_chart_scale(
            views_list, history, ML, MR, MT, cw, ch)

        self._draw_chart_grid(c, W, H, ML, MR, MT, MB, cw, ch, min_v, max_v)
        self._draw_threshold_lines(c, min_v, max_v, py, W, ML, MR)
        self._draw_chart_series(c, history, px, py, ML, MT, W, MR, ch)
        self._draw_chart_annotations(c, history, views_list, px, py, W, H, ML, MR, MB)

    @staticmethod
    def _compute_chart_scale(views_list, history, ML, MR, MT, cw, ch):
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

    def _draw_threshold_lines(self, c, min_v, max_v, py, W, ML, MR):
        """绘制阈值虚线及标注"""
        for thr, col in zip(THRESHOLDS, THRESH_COLORS):
            if min_v <= thr <= max_v * 1.05:
                ty = py(thr)
                c.create_line(ML, ty, W - MR, ty, fill=col, width=1, dash=(6, 4))
                c.create_text(W - MR + 2, ty, text=fmt_num(thr),
                              anchor="w", fill=col, font=("Consolas", 8))

    def _draw_chart_series(self, c, history, px, py, ML, MT, W, MR, ch):
        """绘制面积填充 + 折线 + 数据点"""
        # 面积填充
        pts_area = [ML, MT + ch]
        for i, (_, v) in enumerate(history):
            pts_area += [px(i), py(v)]
        pts_area += [W - MR, MT + ch]
        c.create_polygon(pts_area, fill=C["chart_area"], outline="", stipple="gray25")

        # 折线
        pts_line = []
        for i, (_, v) in enumerate(history):
            pts_line += [px(i), py(v)]
        c.create_line(pts_line, fill=C["chart_line"], width=2.5,
                      smooth=True, joinstyle="round", capstyle="round")

        # 数据点（每8条取1个，末尾必绘）
        every = max(1, len(history) // 8)
        for i, (_, v) in enumerate(history):
            if i % every == 0 or i == len(history) - 1:
                x, y = px(i), py(v)
                c.create_oval(x-4, y-4, x+4, y+4,
                              fill=C["chart_dot"], outline=C["bg_base"], width=2)

    def _draw_chart_annotations(self, c, history, views_list, px, py, W, H, ML, MR, MB):
        """绘制最新值标注 + X 轴时间标签 + 图例"""
        # 最新值标注
        lx = px(len(history) - 1)
        lv = py(views_list[-1])
        c.create_rectangle(lx-32, lv-22, lx+32, lv-6, fill=C["bilibili"], outline="")
        c.create_text(lx, lv-14, text=fmt_num(views_list[-1]),
                      fill="#ffffff", font=("Consolas", 8, "bold"))

        # X 轴时间标签
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

        # 图例
        items = [("播放量", C["bilibili"])] + \
                [(THRESHOLD_NAMES[i] + "阈值", THRESH_COLORS[i]) for i in range(3)]
        lx0 = ML + 4
        for label, col in items:
            c.create_rectangle(lx0, 8, lx0+8, 16, fill=col, outline="")
            c.create_text(lx0+10, 12, text=label, anchor="w",
                          fill=C["text_2"], font=("Consolas", 8))
            lx0 += len(label) * 7 + 22

        # 数据点数提示
        c.create_text(W - MR - 2, 12, text=f"{len(history)} 个数据点",
                      anchor="e", fill=C["text_3"], font=("Consolas", 8))

    def _draw_chart_grid(self, c, W, H, ML, MR, MT, MB, cw, ch,
                          min_v, max_v, hint_v=None):
        """画坐标轴 + 网格"""
        # 坐标轴
        c.create_line(ML, MT, ML, MT + ch, fill=C["border"], width=1)
        c.create_line(ML, MT + ch, W - MR, MT + ch, fill=C["border"], width=1)

        # 水平网格 + Y轴标签
        rows = 5
        for i in range(rows + 1):
            y = MT + i * ch // rows
            c.create_line(ML, y, W - MR, y, fill=C["border_sub"], dash=(3, 5))
            frac = 1 - i / rows
            val  = min_v + frac * (max_v - min_v)
            c.create_text(ML - 4, y, text=_abbrev(val),
                          anchor="e", fill=C["text_3"], font=("Consolas", 8))

    def _fill_detail_text(self, video):
        """填充详细数据文本"""
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
            ("=== 阈值进度 ===", "head"),
        ]
        for t, name in zip(THRESHOLDS, THRESHOLD_NAMES):
            p = min(100, views/t*100)
            g = t - views
            if g > 0:
                lines.append((f"{name}  {p:.1f}%  (还差 {fmt_num(g)})", "mono"))
            else:
                lines.append((f"{name}  已达成 ✓", "mono_ok"))

        self._detail_text.tag_config("head", foreground=C["bilibili"],
                                      font=("Consolas", 10, "bold"))
        self._detail_text.tag_config("mono",    foreground=C["text_1"],  font=FONT_MONO)
        self._detail_text.tag_config("mono_b",  foreground=C["bilibili"],font=("Consolas",10,"bold"))
        self._detail_text.tag_config("mono_ok", foreground=C["success"], font=FONT_MONO)

        for text, tag in lines:
            self._detail_text.insert(tk.END, text + "\n", tag if tag else ())
        self._detail_text.config(state="disabled")

    def _fill_ratio_frame(self, video):
        """填充互动率面板"""
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
            fill_pct = min(pct / 20, 1.0)  # 以20%为满
            tk.Frame(bg_bar, bg=color, height=12).place(
                x=0, y=0, relwidth=fill_pct, relheight=1)
            tk.Label(row, text=f"{pct:.3f}%", bg=C["bg_base"], fg=color,
                     font=FONT_MONO, width=8).pack(side=tk.LEFT)

    # ── 右侧：预测分析 ───────────────────────────
    def _build_right_panel(self):
        p = self._right

        # 综合预测头部
        self._pred_hero = tk.Frame(p, bg=C["bg_surface"])
        self._pred_hero.pack(fill=tk.X)
        tk.Frame(p, bg=C["border"], height=1).pack(fill=tk.X)
        self._build_pred_hero_empty()

        # 算法列表区
        algo_wrap = tk.Frame(p, bg=C["bg_surface"])
        algo_wrap.pack(fill=tk.BOTH, expand=True)

        self._algo_canvas = tk.Canvas(algo_wrap, bg=C["bg_surface"],
                                       bd=0, highlightthickness=0)
        algo_vsb = ttk.Scrollbar(algo_wrap, orient="vertical",
                                  command=self._algo_canvas.yview)
        self._algo_canvas.configure(yscrollcommand=algo_vsb.set)
        algo_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._algo_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._algo_frame = tk.Frame(self._algo_canvas, bg=C["bg_surface"])
        self._algo_cwin  = self._algo_canvas.create_window(
            (0, 0), window=self._algo_frame, anchor="nw")
        self._algo_frame.bind("<Configure>", lambda e: (
            self._algo_canvas.configure(scrollregion=self._algo_canvas.bbox("all")),
            self._algo_canvas.itemconfig(self._algo_cwin,
                                          width=self._algo_canvas.winfo_width())))
        self._algo_canvas.bind("<Configure>", lambda e:
            self._algo_canvas.itemconfig(self._algo_cwin, width=e.width))

    def _build_pred_hero_empty(self):
        h = self._pred_hero
        for w in h.winfo_children():
            w.destroy()
        tk.Label(h, text="数据刷新后自动预测",
                 bg=C["bg_surface"], fg=C["text_3"],
                 font=FONT, padx=14, pady=14).pack()

    def _build_pred_hero(self, weighted_pred, current_views, rate_per_sec):
        h = self._pred_hero
        for w in h.winfo_children():
            w.destroy()

        outer = tk.Frame(h, bg=C["bg_surface"], padx=14, pady=12)
        outer.pack(fill=tk.X)

        tk.Label(outer, text="🎯 综合加权预测",
                 bg=C["bg_surface"], fg=C["text_3"],
                 font=("Microsoft YaHei UI", 8)).pack(anchor="w")

        val_lbl = tk.Label(outer, text=fmt_num(weighted_pred),
                            bg=C["bg_surface"], fg=C["text_1"],
                            font=("Consolas", 18, "bold"))
        val_lbl.pack(anchor="w", pady=(2, 0))

        delta = weighted_pred - current_views
        delta_text = f"▲ +{fmt_num(delta)}" if delta >= 0 else f"▼ {fmt_num(delta)}"
        delta_color = C["success"] if delta >= 0 else C["danger"]
        tk.Label(outer, text=delta_text, bg=C["bg_surface"],
                 fg=delta_color, font=FONT).pack(anchor="w")

        # 增长速率
        if rate_per_sec > 0:
            per_min = rate_per_sec * 60
            per_hour = rate_per_sec * 3600
            if per_hour >= 1:
                rate_str = f"📈 +{fmt_num(per_hour)}/h"
            elif per_min >= 0.1:
                rate_str = f"📈 +{per_min:.1f}/min"
            else:
                rate_str = f"📈 +{rate_per_sec:.2f}/s"
            tk.Label(outer, text=rate_str, bg=C["bg_surface"],
                     fg=C["accent"], font=FONT_SM).pack(anchor="w", pady=(2, 0))

        # 阈值进度 + 预计到达日期
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
            tk.Frame(bg_bar, bg=col, height=4).place(
                x=0, y=0, relwidth=pct, relheight=1)
            # 预计到达日期
            if t <= current_views:
                eta_str = "✓ 已达成"
                eta_c = C["success"]
            elif rate_per_sec > 0:
                need = t - current_views
                seconds_left = need / rate_per_sec
                arrive_dt = datetime.now() + timedelta(seconds=seconds_left)
                eta_str = arrive_dt.strftime("%m-%d %H:%M")
                eta_c = C["danger"] if seconds_left < 3600 else \
                        C["warning"] if seconds_left < 86400 else C["text_2"]
            else:
                eta_str = "—"
                eta_c = C["text_3"]
            tk.Label(row, text=eta_str, bg=C["bg_surface"],
                     fg=eta_c, font=FONT_MONO, width=11,
                     anchor="e").pack(side=tk.LEFT)

    def _update_algo_list(self, results, failed):
        """更新算法列表"""
        f = self._algo_frame
        for w in f.winfo_children():
            w.destroy()

        if results:
            hdr = tk.Frame(f, bg=C["bg_surface"])
            hdr.pack(fill=tk.X, padx=8, pady=(6, 2))
            tk.Label(hdr, text="✅ 成功算法", bg=C["bg_surface"],
                     fg=C["text_3"], font=("Microsoft YaHei UI", 8, "bold")).pack(side=tk.LEFT)
            tk.Label(hdr, text=str(len(results)), bg=C["bg_elevated"],
                     fg=C["text_2"], font=FONT_SM, padx=5, pady=1).pack(side=tk.LEFT, padx=4)

            ALGO_COLORS = [C["bilibili"], C["accent"], C["success"],
                           C["warning"], "#a78bfa", "#22d3ee"]
            for i, (name, pred, weight, conf) in enumerate(results):
                card = tk.Frame(f, bg=C["bg_surface"],
                                highlightthickness=1,
                                highlightbackground=C["border_sub"])
                card.pack(fill=tk.X, padx=6, pady=2)
                inner = tk.Frame(card, bg=C["bg_surface"], padx=10, pady=7)
                inner.pack(fill=tk.X)

                top_row = tk.Frame(inner, bg=C["bg_surface"])
                top_row.pack(fill=tk.X)

                dot_c = ALGO_COLORS[i % len(ALGO_COLORS)]
                tk.Label(top_row, text="●", bg=C["bg_surface"],
                         fg=dot_c, font=FONT_SM).pack(side=tk.LEFT)
                tk.Label(top_row, text=" " + name[:18], bg=C["bg_surface"],
                         fg=C["text_1"], font=FONT).pack(side=tk.LEFT)
                tk.Label(top_row, text=fmt_num(pred), bg=C["bg_surface"],
                         fg=C["accent"], font=("Consolas", 10, "bold")).pack(side=tk.RIGHT)

                # 置信度条
                bar_row = tk.Frame(inner, bg=C["bg_surface"])
                bar_row.pack(fill=tk.X, pady=(4, 0))
                bg_bar = tk.Frame(bar_row, bg=C["bg_hover"], height=3)
                bg_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
                bg_bar.pack_propagate(False)
                tk.Frame(bg_bar, bg=C["accent"], height=3).place(
                    x=0, y=0, relwidth=conf, relheight=1)
                tk.Label(bar_row, text=f"{conf*100:.0f}%",
                         bg=C["bg_surface"], fg=C["text_3"],
                         font=("Consolas", 8), width=4).pack(side=tk.LEFT, padx=3)

                card.bind("<Enter>", lambda e, c=card: c.config(
                    highlightbackground=C["border"]))
                card.bind("<Leave>", lambda e, c=card: c.config(
                    highlightbackground=C["border_sub"]))

        if failed:
            hdr2 = tk.Frame(f, bg=C["bg_surface"])
            hdr2.pack(fill=tk.X, padx=8, pady=(10, 2))
            tk.Label(hdr2, text="❌ 失败算法", bg=C["bg_surface"],
                     fg=C["text_3"], font=("Microsoft YaHei UI", 8, "bold")).pack(side=tk.LEFT)
            tk.Label(hdr2, text=str(len(failed)), bg=C["bg_elevated"],
                     fg=C["danger"], font=FONT_SM, padx=5, pady=1).pack(side=tk.LEFT, padx=4)

            for name, err in failed:
                row = tk.Frame(f, bg=C["bg_surface"], padx=10, pady=5)
                row.pack(fill=tk.X, padx=6)
                tk.Label(row, text=name[:20], bg=C["bg_surface"],
                         fg=C["text_3"], font=FONT).pack(side=tk.LEFT)
                tk.Label(row, text=str(err)[:30], bg=C["bg_surface"],
                         fg=C["danger"], font=FONT_SM).pack(side=tk.RIGHT)

        self._algo_canvas.yview_moveto(0)

    # ── 底部操作栏 ──────────────────────────────
    def _build_bottom_bar(self):
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill=tk.X)
        bar = tk.Frame(self.root, bg=C["bg_surface"], height=46)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)

        ttk.Button(bar, text="＋ 添加监控",
                   style="Primary.TButton",
                   command=self._add_monitor).pack(side=tk.LEFT, padx=(12, 4), pady=8)
        ttk.Button(bar, text="🔄 立即刷新",
                   command=self._refresh_data).pack(side=tk.LEFT, padx=4, pady=8)
        ttk.Button(bar, text="🗑 删除监控",
                   style="Danger.TButton",
                   command=self._remove_monitor).pack(side=tk.LEFT, padx=4, pady=8)

        # 自动刷新开关
        ar_f = tk.Frame(bar, bg=C["bg_surface"])
        ar_f.pack(side=tk.RIGHT, padx=14)
        self._ar_toggle = tk.Canvas(ar_f, width=36, height=18,
                                     bg=C["bg_surface"], bd=0,
                                     highlightthickness=0, cursor="hand2")
        self._ar_toggle.pack(side=tk.LEFT)
        self._ar_toggle.bind("<Button-1>", self._toggle_auto_refresh)
        tk.Label(ar_f, text="自动刷新", bg=C["bg_surface"],
                 fg=C["text_2"], font=FONT).pack(side=tk.LEFT, padx=4)
        self._draw_toggle(True)

    def _draw_toggle(self, on):
        c = self._ar_toggle
        c.delete("all")
        bg = C["success"] if on else C["bg_hover"]
        c.create_rounded_rect = _rounded_rect
        _rounded_rect(c, 0, 0, 36, 18, 9, fill=bg, outline="")
        cx = 26 if on else 10
        c.create_oval(cx-7, 2, cx+7, 16, fill="#ffffff", outline="")

    # ── 状态栏 ────────────────────────────────────
    def _build_status_bar(self):
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill=tk.X)
        bar = tk.Frame(self.root, bg=C["bg_surface"], height=22)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)

        self._sb_labels = {}
        items = [
            ("videos",   "监控: 0 个"),
            ("interval", "刷新间隔: —"),
            ("algo",     "算法: —"),
            ("last_ref", "上次刷新: —"),
            ("status",   "就绪"),
        ]
        for key, text in items:
            anchor = "e" if key == "status" else "w"
            side   = tk.RIGHT if key == "status" else tk.LEFT
            lbl = tk.Label(bar, text=text, bg=C["bg_surface"], fg=C["text_3"],
                           font=("Microsoft YaHei UI", 8))
            lbl.pack(side=side, padx=10)
            self._sb_labels[key] = lbl

    def _sb(self, key, text, color=None):
        lbl = self._sb_labels.get(key)
        if lbl:
            lbl.config(text=text, fg=color or C["text_3"])

    # ──────────────────────────────────────────
    # 业务逻辑
    # ──────────────────────────────────────────

    # ── 自动刷新 ─────────────────────────────────
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
        self.auto_refresh_job = self.root.after(
            self.refresh_interval * 1000, self._do_auto_refresh)

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
        self._fetch_all_video_data()
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

    # ── 数据拉取 ─────────────────────────────────
    def _fetch_all_video_data(self):
        if not self.monitored_videos:
            return
        self._sb("status", f"正在刷新 {len(self.monitored_videos)} 个视频…", C["accent"])
        self._add_log("INFO", f"开始刷新 {len(self.monitored_videos)} 个视频")

        def _worker():
            for video in self.monitored_videos:
                bvid = video.get("bvid", "")
                if not bvid:
                    continue
                info = bilibili_api.get_video_info(bvid)
                if info:
                    stat  = info.get("stat", {})
                    owner = info.get("owner", {})
                    video["title"]          = info.get("title",    video.get("title",""))
                    video["author"]         = owner.get("name",    video.get("author",""))
                    video["pic"]            = info.get("pic",      video.get("pic",""))
                    video["view_count"]     = stat.get("view",     video.get("view_count",0))
                    video["like_count"]     = stat.get("like",     video.get("like_count",0))
                    video["coin_count"]     = stat.get("coin",     video.get("coin_count",0))
                    video["share_count"]    = stat.get("share",    video.get("share_count",0))
                    video["favorite_count"] = stat.get("favorite", video.get("favorite_count",0))
                    video["danmaku_count"]  = stat.get("danmaku",  video.get("danmaku_count",0))
                    video["reply_count"]    = stat.get("reply",    video.get("reply_count",0))

                    # 记录历史
                    if bvid not in self.history_data:
                        self.history_data[bvid] = []
                    ts = datetime.now()
                    self.history_data[bvid].append((ts, video["view_count"]))

                    # 写数据库
                    if bvid in self.video_dbs:
                        try:
                            rec = MonitorRecord(
                                bvid=bvid, timestamp=ts.isoformat(),
                                view_count=video["view_count"],
                                like_count=video["like_count"],
                                coin_count=video["coin_count"],
                                share_count=video["share_count"],
                                favorite_count=video["favorite_count"],
                                danmaku_count=video["danmaku_count"],
                                reply_count=video["reply_count"],
                            )
                            self.video_dbs[bvid].add_monitor_record(rec)
                        except Exception as e:
                            print(f"写数据库失败 {bvid}: {e}")
                            self._add_log("WARNING", f"写数据库失败 {bvid}: {e}")
                time.sleep(0.2)

            self.root.after(0, self._post_fetch)

        threading.Thread(target=_worker, daemon=True).start()

    def _post_fetch(self):
        """数据拉取完成后刷新UI"""
        now_str = datetime.now().strftime("%H:%M:%S")
        self._sb("status",   "刷新完成", C["success"])
        self._sb("last_ref", f"上次刷新: {now_str}")
        self._sb("videos",   f"监控: {len(self.monitored_videos)} 个")
        self._sb("interval", f"刷新间隔: {self.refresh_interval}s")

        # 更新所有卡片
        for video in self.monitored_videos:
            bvid = video.get("bvid","")
            if bvid in self._video_card_widgets:
                self._update_card(video)

        # 更新当前选中视频的中间面板
        if self.selected_bvid:
            video = next((v for v in self.monitored_videos
                          if v.get("bvid") == self.selected_bvid), None)
            if video:
                self._update_stat_bar(video)
                if self._current_tab == "📈 播放量趋势":
                    self._draw_chart(video)

        # 自动预测所有视频
        self._auto_predict_all()

    # ── 视频详情展示 ─────────────────────────────
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

        tk.Label(dialog, text="请输入BV号或视频链接：",
                 bg=C["bg_surface"], fg=C["text_1"], font=FONT).pack(pady=(18, 4))

        entry_f = tk.Frame(dialog, bg=C["bg_elevated"],
                           highlightthickness=1,
                           highlightbackground=C["border"],
                           highlightcolor=C["bilibili"])
        entry_f.pack(padx=24, fill=tk.X)
        entry = tk.Entry(entry_f, bg=C["bg_elevated"], fg=C["text_1"],
                         insertbackground=C["text_1"],
                         relief="flat", font=FONT, bd=0)
        entry.pack(fill=tk.X, padx=8, pady=6)
        entry.focus_set()

        hint = tk.Label(dialog, text="格式：BV1xxx 或完整链接",
                        bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM)
        hint.pack()

        status_lbl = tk.Label(dialog, text="",
                               bg=C["bg_surface"], fg=C["accent"], font=FONT_SM)
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
                messagebox.showinfo("成功",
                    f"已添加监控\n标题：{video['title'][:40]}\n"
                    f"UP主：{video['author']}\n"
                    f"播放：{fmt_num(video['view_count'])}",
                    parent=dialog)
                dialog.destroy()

            threading.Thread(target=_fetch, daemon=True).start()

        btn_f = tk.Frame(dialog, bg=C["bg_surface"])
        btn_f.pack(pady=10)
        ttk.Button(btn_f, text="确认添加", style="Primary.TButton",
                   command=_confirm).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_f, text="取消",
                   command=dialog.destroy).pack(side=tk.LEFT, padx=6)

        entry.bind("<Return>", lambda e: _confirm())

    def _remove_monitor(self):
        if not self.selected_bvid:
            messagebox.showwarning("提示", "请先在左侧选择要删除的视频")
            return
        bvid  = self.selected_bvid
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
        self._draw_chart_placeholder()
        self._build_pred_hero_empty()
        for w in self._algo_frame.winfo_children():
            w.destroy()

        self._video_count_lbl.config(text=str(len(self.monitored_videos)))
        self._sb("videos", f"监控: {len(self.monitored_videos)} 个")
        self._save_watch_list()

    def _refresh_data(self):
        self._fetch_all_video_data()

    # ── 预测分析 ─────────────────────────────────
    def _predict_single(self, bvid, video, callback=None):
        """对单个视频运行预测，完成后回调 callback(results_dict)"""
        current_view = video.get("view_count", 0)
        history      = self._merge_history(bvid)

        results = AlgorithmRegistry.predict_all(
            history, current_view,
            thresholds=THRESHOLDS,
            threshold_names=THRESHOLD_NAMES,
        )

        weighted     = results.get("_weighted", {})
        w_pred       = weighted.get("prediction", current_view)
        success_list = []
        fail_list    = []
        for name, r in results.items():
            if name == "_weighted":
                continue
            if "error" in r:
                fail_list.append((name, r["error"]))
            else:
                success_list.append((name, r["prediction"], r["weight"], r["confidence"]))

        growth       = w_pred - current_view
        rate_per_sec = self._calc_growth_rate(history)

        result = {
            "bvid":         bvid,
            "prediction":   w_pred,
            "current_view": current_view,
            "growth":       max(0, growth),
            "rate_per_sec": rate_per_sec,
            "success_list": success_list,
            "fail_list":    fail_list,
            "valid":        weighted.get("valid_algorithms", 0),
            "total":        weighted.get("total_algorithms", 0),
        }
        self.prediction_results[bvid] = result

        if callback:
            callback(result)

    def _merge_history(self, bvid: str) -> list:
        """
        合并内存历史与数据库历史（去重），按时间排序后返回。
        若数据点不足 2 条，补充占位数据保证算法可运行。
        """
        current_view = next(
            (v.get("view_count", 0) for v in self.monitored_videos
             if v.get("bvid") == bvid), 0)
        history = list(self.history_data.get(bvid, []))

        # 从数据库补充历史
        try:
            if bvid in self.video_dbs:
                db_hist = self.video_dbs[bvid].get_all_records()
                if db_hist:
                    existing = {v for _, v in history}
                    for row in db_hist:
                        if row["view_count"] not in existing:
                            history.append((row["timestamp"], row["view_count"]))
        except Exception:
            pass

        # 按时间排序
        def _to_dt(t):
            return t if isinstance(t, datetime) else datetime.fromisoformat(str(t))

        history.sort(key=lambda x: _to_dt(x[0]))

        if len(history) < 2:
            now = datetime.now()
            history = [(now, current_view), (now, current_view)]

        return history

    @staticmethod
    def _calc_growth_rate(history: list) -> float:
        """
        根据历史数据计算播放量增长速率（播放量/秒）。
        数据不足或增长为负则返回 0.0。
        """
        try:
            if len(history) < 2:
                return 0.0

            def _to_dt(t):
                return t if isinstance(t, datetime) else datetime.fromisoformat(str(t))

            first_ts, first_v = _to_dt(history[0][0]),  history[0][1]
            last_ts,  last_v  = _to_dt(history[-1][0]), history[-1][1]
            dt_sec = (last_ts - first_ts).total_seconds()
            if dt_sec > 0 and last_v > first_v:
                return (last_v - first_v) / dt_sec
        except Exception:
            pass
        return 0.0

    def _run_prediction(self, bvid=None):
        """手动触发预测（按钮用），不传 bvid 则预测当前选中视频"""
        target_bvid = bvid or self.selected_bvid
        if not target_bvid:
            messagebox.showwarning("提示", "请先选择要预测的视频")
            return
        video = next((v for v in self.monitored_videos
                      if v.get("bvid") == target_bvid), None)
        if not video:
            return

        self._sb("status", "正在运行预测分析…", C["accent"])
        self._build_pred_hero_empty()

        def _worker():
            def _on_done(result):
                self.root.after(0, lambda: self._prediction_done(
                    result["prediction"], result["current_view"],
                    result["growth"], result["rate_per_sec"],
                    result["success_list"], result["fail_list"],
                    result["valid"], result["total"],
                ))
            self._predict_single(target_bvid, video, callback=_on_done)

        threading.Thread(target=_worker, daemon=True).start()

    def _auto_predict_all(self):
        """数据拉取完成后自动对所有视频预测（后台静默执行）"""
        if not self.monitored_videos:
            return

        # 如果没有选中视频，自动选中第一个
        if not self.selected_bvid and self.monitored_videos:
            first_bvid = self.monitored_videos[0].get("bvid", "")
            if first_bvid:
                self.root.after(0, lambda b=first_bvid: self._select_video(b))

        def _worker():
            count = len(self.monitored_videos)
            for i, video in enumerate(self.monitored_videos):
                bvid = video.get("bvid", "")
                if not bvid:
                    continue

                self._predict_single(bvid, video)
                # 如果是当前选中视频，更新右侧面板
                if bvid == self.selected_bvid:
                    result = self.prediction_results.get(bvid)
                    if result:
                        self.root.after(0, lambda r=result: self._prediction_done(
                            r["prediction"], r["current_view"],
                            r["growth"], r["rate_per_sec"],
                            r["success_list"], r["fail_list"],
                            r["valid"], r["total"],
                        ))
                time.sleep(0.05)

            self.root.after(0, lambda: self._sb(
                "status", f"自动预测完成 ({count} 个视频)", C["success"]))
            self._add_log("INFO", f"自动预测完成 ({count} 个视频)")

        threading.Thread(target=_worker, daemon=True).start()

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
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0.0.0 Safari/537.36",
                    "Referer": "https://www.bilibili.com/",
                }
                r = req.get(url, timeout=8, headers=headers)
                if r.status_code != 200:
                    return
                img = Image.open(BytesIO(r.content))
                # 按比例缩放到合适大小，保持 16:9
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
                self._add_log("DEBUG", f"封面加载失败 {bvid}: {e}")

        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_cover(self, ph):
        self._photo_ref = ph
        if hasattr(self, "_cover_lbl") and self._cover_lbl.winfo_exists():
            self._cover_lbl.config(image=ph, text="")

    # ── BV号复制 ────────────────────────────────
    def _copy_bvid(self, bvid):
        self.root.clipboard_clear()
        self.root.clipboard_append(bvid)
        self._sb("status", f"已复制 {bvid}", C["success"])

    # ── 搜索过滤 ────────────────────────────────
    def _on_search(self, *args):
        q = self._search_var.get().strip().lower()
        if q == "搜索标题或bv号…" or q == "":
            q = ""
        for bvid, refs in self._video_card_widgets.items():
            video = next((v for v in self.monitored_videos if v.get("bvid") == bvid), None)
            if not video:
                continue
            visible = (not q or
                       q in video.get("title","").lower() or
                       q in bvid.lower() or
                       q in video.get("author","").lower())
            refs["card"].pack(fill=tk.X, padx=6, pady=2) if visible else refs["card"].pack_forget()

    # ── 刷新间隔设置 ────────────────────────────
    def _open_interval_settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("刷新间隔设置")
        dialog.geometry("320x220")
        dialog.configure(bg=C["bg_surface"])
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        tk.Label(dialog, text="普通刷新间隔（秒）：",
                 bg=C["bg_surface"], fg=C["text_1"], font=FONT).pack(pady=(20, 6))

        spin_f = tk.Frame(dialog, bg=C["bg_elevated"],
                          highlightthickness=1, highlightbackground=C["border"])
        spin_f.pack(padx=40, fill=tk.X)
        var = tk.IntVar(value=self.DEFAULT_INTERVAL)
        ttk.Spinbox(spin_f, from_=10, to=3600, textvariable=var,
                    width=10).pack(padx=8, pady=6)

        tk.Label(dialog,
                 text=f"距阈值 < {FAST_GAP} 时自动切换快速模式（{self.FAST_INTERVAL}s）",
                 bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM,
                 wraplength=280).pack(pady=6)

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
        ttk.Button(btn_f, text="保存", style="Primary.TButton",
                   command=_save).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_f, text="取消",
                   command=dialog.destroy).pack(side=tk.LEFT, padx=6)

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
        """接收搜索窗口批量导入的视频列表"""
        if not videos:
            return
        added = 0
        skipped = 0
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
                self._add_log("WARNING", f"导入 {bvid} 失败: {e}")
                skipped += 1

        self._save_watch_list()

        msg = f"成功导入 {added} 个视频"
        if skipped:
            msg += f"（跳过 {skipped} 个：已存在或获取失败）"
        if added:
            messagebox.showinfo("导入完成", msg)
        elif skipped:
            messagebox.showinfo("导入完成", msg)

    def _open_data_comparison(self):
        try:
            from .data_comparison import DataComparisonWindow
            DataComparisonWindow(self.root,
                                 monitored_videos=self.monitored_videos,
                                 history_data=self.history_data,
                                 video_dbs=self.video_dbs)
        except Exception as e:
            messagebox.showerror("错误", f"打开数据对比失败: {e}")

    def _open_crossover_analysis(self):
        try:
            from .crossover_analysis import CrossoverAnalysisWindow
            CrossoverAnalysisWindow(self.root,
                                    monitored_videos=self.monitored_videos,
                                    history_data=self.history_data,
                                    video_dbs=self.video_dbs)
        except Exception as e:
            messagebox.showerror("错误", f"打开交叉计算失败: {e}")

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
        """启动时从 settings.json 加载监控列表"""
        config = load_config()
        watch_list = config.get("watch_list", [])
        if not watch_list:
            return

        self._sb("status", f"正在加载 {len(watch_list)} 个监控视频…", C["accent"])

        def _worker():
            for bvid in watch_list:
                if any(v.get("bvid") == bvid for v in self.monitored_videos):
                    continue
                try:
                    info = bilibili_api.get_video_info(bvid)
                    if not info:
                        continue
                    video = self._map_api_to_video_dict(bvid, info)

                    # 加载监控列表时不调用 _register_video_to_monitor（需在主线程执行UI操作）
                    # 数据库部分在后台线程完成，UI 部分交给 root.after
                    try:
                        video_db = db.get_video_db(bvid)
                        self.video_dbs[bvid] = video_db
                        video_db.save_video_info(video)
                        history = video_db.get_all_records()
                        if history:
                            self.history_data[bvid] = [
                                (row["timestamp"], row["view_count"])
                                for row in history
                            ]
                    except Exception:
                        pass

                    self.root.after(0, lambda v=video: self._restore_video(v))
                    time.sleep(0.15)
                except Exception as e:
                    self._add_log("ERROR", f"加载视频 {bvid} 失败: {e}")
                    continue

            self.root.after(0, lambda: self._sb(
                "status",
                f"已加载 {len(self.monitored_videos)} 个监控视频",
                C["success"]))

            # 加载完成后自动预测
            if self.monitored_videos:
                self.root.after(500, self._auto_predict_all)

        threading.Thread(target=_worker, daemon=True).start()

    def _restore_video(self, video):
        """在主线程中恢复视频卡片（不重复添加）"""
        bvid = video.get("bvid", "")
        if any(v.get("bvid") == bvid for v in self.monitored_videos):
            return
        self.monitored_videos.append(video)
        self._make_video_card(video)
        self._video_count_lbl.config(text=str(len(self.monitored_videos)))
        self._sb("videos", f"监控: {len(self.monitored_videos)} 个")

    # ──────────────────────────────────────────
    # 视频注册公共方法（消除 _add_monitor / _import_search_results /
    # _load_watch_list 三处重复逻辑）
    # ──────────────────────────────────────────

    @staticmethod
    def _map_api_to_video_dict(bvid: str, info: dict,
                                fallback: dict = None) -> dict:
        """
        将 B 站 API 的 get_video_info 响应映射为内部 video 字典。

        Args:
            bvid: BV 号
            info: API 返回的原始数据（非 None）
            fallback: 字段缺失时的备用值（如搜索结果字典）

        Returns:
            标准化的 video dict
        """
        fb  = fallback or {}
        stat  = info.get("stat",  {})
        owner = info.get("owner", {})
        return {
            "bvid":           bvid,
            "title":          info.get("title",    fb.get("title",  "未知标题")),
            "author":         owner.get("name",    fb.get("author", "未知UP主")),
            "pic":            info.get("pic",      fb.get("pic",    "")),
            "view_count":     stat.get("view",     fb.get("play",   0)),
            "like_count":     stat.get("like",     fb.get("like",   0)),
            "coin_count":     stat.get("coin",     0),
            "share_count":    stat.get("share",    0),
            "favorite_count": stat.get("favorite", 0),
            "danmaku_count":  stat.get("danmaku",  0),
            "reply_count":    stat.get("reply",    0),
            "duration":       info.get("duration", 0),
            "pubdate":        info.get("pubdate",  0),
            "desc":           info.get("desc",     ""),
            "aid":            info.get("aid",      0),
        }

    def _register_video_to_monitor(self, video: dict) -> None:
        """
        将已构建好的 video dict 注册到监控系统：
          1. 初始化/加载对应的 VideoDatabase
          2. 更新 history_data（有历史则加载，否则写入初始记录）
          3. 将 video 添加到 monitored_videos + 创建卡片 + 更新计数/状态栏

        调用方必须在主线程中执行此方法（UI 操作）。
        """
        bvid = video["bvid"]

        # 1. 数据库初始化 / 历史加载
        try:
            video_db = db.get_video_db(bvid)
            self.video_dbs[bvid] = video_db
            video_db.save_video_info(video)
            history = video_db.get_all_records()
            if history:
                self.history_data[bvid] = [
                    (row["timestamp"], row["view_count"]) for row in history
                ]
            else:
                now = datetime.now()
                self.history_data[bvid] = [(now, video["view_count"])]
                rec = MonitorRecord(
                    bvid=bvid, timestamp=now.isoformat(),
                    view_count=video["view_count"],
                    like_count=video["like_count"],
                    coin_count=video["coin_count"],
                    share_count=video["share_count"],
                    favorite_count=video["favorite_count"],
                    danmaku_count=video["danmaku_count"],
                    reply_count=video["reply_count"],
                )
                video_db.add_monitor_record(rec)
        except Exception as e:
            self._add_log("WARNING", f"数据库初始化失败: {bvid}: {e}")

        # 2. 添加到内存列表 + UI
        self.monitored_videos.append(video)
        self._make_video_card(video)
        self._video_count_lbl.config(text=str(len(self.monitored_videos)))
        self._sb("videos", f"监控: {len(self.monitored_videos)} 个")

    def _save_watch_list(self):
        """将当前监控列表持久化到 settings.json"""
        config = load_config()
        config["watch_list"] = [v.get("bvid", "") for v in self.monitored_videos]
        save_config(config)

    # ── 退出 ─────────────────────────────────────
    def _on_exit(self):
        self._save_watch_list()
        if self.auto_refresh_job:
            self.root.after_cancel(self.auto_refresh_job)
        if self.countdown_job:
            self.root.after_cancel(self.countdown_job)
        # 关闭文件日志
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


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────
def _abbrev(n):
    """数字缩写：99500 -> 9.9w"""
    n = int(n)
    if n >= 10_000_000:
        return f"{n/10_000_000:.0f}kw"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}w"
    if n >= 10_000:
        return f"{n/10_000:.1f}w"
    return str(n)


def _rounded_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    """在 Canvas 上画圆角矩形"""
    pts = [
        x1+r, y1,   x2-r, y1,
        x2,   y1,   x2,   y1+r,
        x2,   y2-r, x2,   y2,
        x2-r, y2,   x1+r, y2,
        x1,   y2,   x1,   y2-r,
        x1,   y1+r, x1,   y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kwargs)


# ──────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────
def main():
    app = BilibiliMonitorGUI()
    app.run()


if __name__ == "__main__":
    main()
