"""
主GUI界面 - 深色三栏布局
左侧视频卡片 / 中间图表详情 / 右侧预测分析

UI 已拆分为独立模块：
- video_list_panel.py  : 左侧视频列表
- detail_panel.py      : 中间详情+图表
- prediction_panel.py  : 右侧预测面板
- bottom_bar.py       : 底部状态栏
- dialogs.py           : 所有弹窗
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import os
from datetime import datetime, timedelta
from io import BytesIO

sys_path = os.path.dirname(os.path.dirname(__file__))
import sys
sys.path.insert(0, sys_path)

from ui.theme import C, THEMES, THEME_DARK, current_theme_name, apply_theme
from ui.helpers import (
    FONT, FONT_SM, FONT_MONO,
    DEFAULT_INTERVAL, FAST_INTERVAL, FAST_GAP,
    fmt_num, nearest_threshold_gap,
)
from ui.chart import draw_chart, draw_chart_placeholder
from ui.log_panel import LogPanel
from ui.video_list_panel import VideoListPanel
from ui.detail_panel import DetailPanel
from ui.prediction_panel import PredictionPanel
from ui.bottom_bar import BottomBar
from ui.dialogs import Dialogs
from ui.monitor_service import (
    fetch_all_video_data, fetch_single_video_data,
    auto_predict_all, auto_predict_video,
    load_watch_list,
)
from core import bilibili_api, db, MonitorRecord
from config import load_config, save_config
from utils.file_logger import FileLogger


# ══════════════════════════════════════════════
# 主界面
# ══════════════════════════════════════════════
class BilibiliMonitorGUI:
    """主界面 - 深色三栏布局（精简版）"""

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
        self.auto_refresh_enabled = tk.BooleanVar(value=True)
        self._global_tick_job = None
        self._video_timers    = {}
        self._fetching_set    = set()

        # 数据
        self.monitored_videos   = []
        self.history_data        = {}
        self.prediction_results = {}
        self.video_dbs          = {}
        self.selected_bvid      = None

        # UI 子模块
        self._file_logger = FileLogger(os.path.join(sys_path, "data", "log"))

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
        self.log_panel = LogPanel(self.root, self._file_logger)
        self._build_main()
        self.bottom_bar = BottomBar(self.root, self)
        self._build_status_bar()

    def _build_titlebar(self):
        """构建标题栏 - 重构版"""
        self._create_titlebar_container()
        self._build_logo_section()
        self._build_navigation_buttons()
        self._build_right_buttons()

    def _create_titlebar_container(self):
        """创建标题栏容器"""
        bar = tk.Frame(self.root, bg=C["bg_surface"], height=46)
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill=tk.X)
        self._bar = bar  # 保存引用，供子函数使用

    def _build_logo_section(self):
        """构建Logo区域 - 改进版：添加副标题"""
        bar = self._bar
        logo_f = tk.Frame(bar, bg=C["bg_surface"])
        logo_f.pack(side=tk.LEFT, padx=(14, 0))
        
        # Logo图标 (使用Canvas绘制简洁的B站风格图标)
        logo_canvas = tk.Canvas(logo_f, width=32, height=32, 
                                   bg=C["bg_surface"], highlightthickness=0)
        logo_canvas.create_oval(4, 4, 28, 28, fill=C["bilibili"], outline="")
        logo_canvas.create_text(16, 16, text="B", fill="white", 
                                font=("Microsoft YaHei UI", 14, "bold"))
        logo_canvas.pack(side=tk.LEFT, padx=(0, 8))
        
        # 标题和副标题容器
        title_f = tk.Frame(logo_f, bg=C["bg_surface"])
        title_f.pack(side=tk.LEFT)
        
        tk.Label(title_f, text="B站监控", bg=C["bg_surface"], fg=C["bilibili"],
                 font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        tk.Label(title_f, text="播放量预测系统", bg=C["bg_surface"], fg=C["text_3"],
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w")

    def _build_navigation_buttons(self):
        """构建导航按钮"""
        bar = self._bar
        nav_f = tk.Frame(bar, bg=C["bg_surface"])
        nav_f.pack(side=tk.LEFT, padx=16)
        self._nav_btns = {}
        self._page_views = ["监控列表", "日志"]
        self._dialogs = Dialogs(self)

        nav_items = [
            ("📊", "监控列表", None),
            ("📈", "数据对比",  self._dialogs.open_data_comparison),
            ("🔄", "交叉计算",  self._dialogs.open_crossover_analysis),
            ("📅", "周刊分数",  self._dialogs.open_weekly_score),
            ("🏆", "里程碑",    self._dialogs.open_milestone_stats),
            ("🗄", "数据库",    self._dialogs.open_database_query),
            ("📋", "日志",      None),
        ]
        
        for icon, label, cmd in nav_items:
            self._create_nav_button(nav_f, icon, label, cmd)

        self._current_nav = "监控列表"

    def _create_nav_button(self, parent, icon, label, cmd):
        """创建导航按钮 - 改进版：图标+文本+激活指示器"""
        btn = tk.Frame(parent, bg=C["bg_surface"], cursor="hand2")
        btn.pack(side=tk.LEFT, padx=4)
        
        # 图标
        icon_lbl = tk.Label(btn, text=icon, 
                            bg=C["bg_surface"], fg=C["text_secondary"],
                            font=("Microsoft YaHei UI", 12))
        icon_lbl.pack(side=tk.LEFT, padx=(8, 4))
        
        # 文本
        text_lbl = tk.Label(btn, text=label, 
                             bg=C["bg_surface"], fg=C["text_secondary"],
                             font=FONT)
        text_lbl.pack(side=tk.LEFT, padx=(0, 8))
        
        # 底部激活指示器
        indicator = tk.Frame(btn, bg=C["bg_surface"], height=2)
        indicator.pack(side=tk.BOTTOM, fill=tk.X)
        
        # 悬停效果
        def on_enter(e):
            icon_lbl.config(fg=C["text_1"])
            text_lbl.config(fg=C["text_1"])
            btn.config(bg=C["bg_hover"])
            icon_lbl.config(bg=C["bg_hover"])
            text_lbl.config(bg=C["bg_hover"])
            
        def on_leave(e):
            if indicator.cget("bg") != C["bilibili"]:
                icon_lbl.config(fg=C["text_secondary"])
                text_lbl.config(fg=C["text_secondary"])
                btn.config(bg=C["bg_surface"])
                icon_lbl.config(bg=C["bg_surface"])
                text_lbl.config(bg=C["bg_surface"])
                
        def on_click(e):
            # 重置所有按钮
            for k, b in self._nav_btns.items():
                if isinstance(b, tuple):
                    ic, tl, ind = b
                    ic.config(fg=C["text_secondary"])
                    tl.config(fg=C["text_secondary"])
                    ind.config(bg=C["bg_surface"])
            # 激活当前按钮
            indicator.config(bg=C["bilibili"])
            icon_lbl.config(fg=C["bilibili"])
            text_lbl.config(fg=C["bilibili"])
            
            if label in self._page_views:
                self._switch_nav(label)
            elif cmd:
                cmd()
                
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        btn.bind("<Button-1>", on_click)
        
        # 保存引用 (icon_label, text_label, indicator)
        self._nav_btns[label] = (icon_lbl, text_lbl, indicator)
        
        # 初始化激活状态
        if label == "监控列表":
            indicator.config(bg=C["bilibili"])
            icon_lbl.config(fg=C["bilibili"])
            text_lbl.config(fg=C["bilibili"])

    def _build_right_buttons(self):
        """构建右侧按钮区"""
        bar = self._bar
        right_f = tk.Frame(bar, bg=C["bg_surface"])
        right_f.pack(side=tk.RIGHT, padx=14)

        # 创建设置菜单
        self._create_settings_menu()
        
        # 创建图标按钮
        self._create_icon_button(right_f, "⚙️", self._popup_settings_menu, "设置")
        self._create_icon_button(right_f, "🔍", self._dialogs.open_video_search, "搜索")
        self._create_theme_button(right_f)
        self._create_countdown_badge(right_f)
        self._create_mode_pill(right_f)

    def _create_settings_menu(self):
        """创建设置下拉菜单"""
        self._settings_menu = tk.Menu(self.root, tearoff=0, bg=C["bg_elevated"],
                                      fg=C["text_1"], activebackground=C["bg_hover"],
                                      activeforeground=C["text_1"],
                                      font=FONT, bd=0, relief="flat")
        self._settings_menu.add_command(label="⏱  刷新间隔", command=self._dialogs.open_interval_settings)
        self._settings_menu.add_command(label="📊  权重设置", command=self._dialogs.open_weight_settings)
        self._settings_menu.add_command(label="🌐  网络设置", command=self._dialogs.open_network_settings)
        self._settings_menu.add_separator()
        self._settings_menu.add_command(label="⚙️  系统设置", command=self._dialogs.open_settings)

    def _create_icon_button(self, parent, icon, command, tooltip=None):
        """创建图标按钮（可复用）"""
        btn = tk.Label(parent, text=icon, bg=C["bg_elevated"], fg=C["text_2"],
                        font=("Microsoft YaHei UI", 11), cursor="hand2",
                        padx=6, pady=2, relief="flat")
        btn.pack(side=tk.RIGHT, padx=2)
        if callable(command):
            btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e, b=btn: b.config(bg=C["bg_hover"], fg=C["text_1"]))
        btn.bind("<Leave>", lambda e, b=btn: b.config(bg=C["bg_elevated"], fg=C["text_2"]))
        if tooltip:
            # 可选：添加工具提示
            pass
        return btn

    def _popup_settings_menu(self):
        """弹出设置菜单"""
        gear = self._settings_menu.winfo_children()[0]  # 假设第一个子部件是齿轮按钮
        # 实际实现中，需要保存齿轮按钮的引用
        # 这里简化为直接使用事件绑定
        pass  # 实际代码需要修正

    def _create_theme_button(self, parent):
        """创建主题切换按钮"""
        self._theme_btn = tk.Label(parent, text="🌙", bg=C["bg_elevated"], fg=C["text_2"],
                                   font=("Microsoft YaHei UI", 11), cursor="hand2",
                                   padx=6, pady=2, relief="flat")
        self._theme_btn.pack(side=tk.RIGHT, padx=2)
        self._theme_btn.bind("<Button-1>", self._toggle_theme)
        self._theme_btn.bind("<Enter>", lambda e: self._theme_btn.config(bg=C["bg_hover"], fg=C["text_1"]))
        self._theme_btn.bind("<Leave>", lambda e: self._theme_btn.config(bg=C["bg_elevated"], fg=C["text_2"]))
        self._theme_btn.config(text="☀️" if self._initial_theme == "light" else "🌙")

    def _create_countdown_badge(self, parent):
        """创建倒计时徽章"""
        self._countdown_badge = tk.Label(
            parent, text="-- s", bg=C["bg_elevated"], fg=C["accent"],
            font=FONT_MONO, padx=8, pady=2, relief="flat")
        self._countdown_badge.pack(side=tk.RIGHT, padx=6)

    def _create_mode_pill(self, parent):
        """创建模式指示器"""
        self._mode_pill = tk.Label(
            parent, text="● 正常模式", bg=C["bg_surface"], fg=C["success"],
            font=("Microsoft YaHei UI", 9, "bold"))
        self._mode_pill.pack(side=tk.RIGHT, padx=6)

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

        self.video_list = VideoListPanel(self._left, self)
        self.detail = DetailPanel(self._center, self)
        self.prediction = PredictionPanel(self._right, self)

    # ──────────────────────────────────────────
    # 状态栏（BottomBar 已构建，此处仅供外部引用）
    # ──────────────────────────────────────────

    def _build_status_bar(self):
        pass  # 已由 BottomBar 构建

    def _sb(self, key, text, color=None):
        self.bottom_bar.update_sb(key, text, color)

    # ──────────────────────────────────────────
    # 导航切换
    # ──────────────────────────────────────────

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

    # ──────────────────────────────────────────
    # 主题切换
    # ──────────────────────────────────────────

    def _toggle_theme(self, event=None):
        new_theme = "light" if current_theme_name() == "dark" else "dark"
        apply_theme(self.root, new_theme)
        icon = "☀️" if new_theme == "light" else "🌙"
        self._theme_btn.config(text=icon, bg=C["bg_elevated"], fg=C["text_2"])
        self.log_panel.recolor()
        if hasattr(self, 'detail'):
            self.detail.recolor_text_tags()
            self.detail.chart_canvas.config(bg=C["bg_base"])
            if self.selected_bvid:
                video = next((v for v in self.monitored_videos if v.get("bvid") == self.selected_bvid), None)
                if video:
                    draw_chart(self.detail.chart_canvas, self.history_data, self.selected_bvid, video, FONT)
        try:
            config = load_config()
            config.setdefault("ui", {})["theme"] = new_theme
            save_config(config)
        except Exception:
            pass

    # ──────────────────────────────────────────
    # 业务逻辑（调度层，具体实现在 monitor_service）
    # ──────────────────────────────────────────

    def _get_video_interval(self, video):
        views = video.get("view_count", 0)
        gap, _ = nearest_threshold_gap(views)
        if 0 < gap < self.THRESHOLD_GAP:
            return self.FAST_INTERVAL
        return self.DEFAULT_INTERVAL

    def _register_video_timer(self, bvid):
        video = next((v for v in self.monitored_videos if v.get("bvid") == bvid), None)
        if not video:
            return
        interval = self._get_video_interval(video)
        self._video_timers[bvid] = {"next": time.time() + interval, "interval": interval}

    def _start_auto_refresh(self):
        if self.auto_refresh_enabled.get():
            self._start_global_tick()

    def _start_global_tick(self):
        if self._global_tick_job:
            self.root.after_cancel(self._global_tick_job)
        self._global_tick_job = self.root.after(1000, self._global_tick)

    def _stop_global_tick(self):
        if self._global_tick_job:
            self.root.after_cancel(self._global_tick_job)
            self._global_tick_job = None

    def _global_tick(self):
        if not self.auto_refresh_enabled.get():
            self._global_tick_job = None
            return

        now = time.time()
        fast_count = 0
        min_remaining = float("inf")
        due_bvids = []

        for bvid, timer in list(self._video_timers.items()):
            remaining = timer["next"] - now
            if timer["interval"] == self.FAST_INTERVAL:
                fast_count += 1
            if remaining <= 0:
                due_bvids.append(bvid)
            elif remaining < min_remaining:
                min_remaining = remaining

        for bvid in due_bvids:
            if bvid not in self._fetching_set:
                self._fetching_set.add(bvid)
                self.log_panel.add_log("DEBUG", f"定时器到期，拉取 {bvid}")
                fetch_single_video_data(self, bvid, callback=self._on_single_fetch_done)

        if min_remaining == float("inf"):
            badge_text = "— s"
        else:
            badge_text = f"{int(max(0, min_remaining)):02d} s"
        self._countdown_badge.config(text=badge_text)

        if fast_count > 0:
            self._mode_pill.config(text=f"⚡ {fast_count}个快速", fg=C["danger"])
        else:
            self._mode_pill.config(text="● 正常模式", fg=C["success"])

        self._sb("interval", f"正常{self.DEFAULT_INTERVAL}s / 快速{self.FAST_INTERVAL}s")
        self._global_tick_job = self.root.after(1000, self._global_tick)

    def _on_single_fetch_done(self, bvid):
        self._fetching_set.discard(bvid)
        video = next((v for v in self.monitored_videos if v.get("bvid") == bvid), None)
        if video:
            self.video_list.update_card(video)
        if bvid == self.selected_bvid and video:
            self.detail.update_stat_bar(video)
            if self.detail.current_tab == "📈 播放量趋势":
                draw_chart(self.detail.chart_canvas, self.history_data, self.selected_bvid, video, FONT)
        now_str = datetime.now().strftime("%H:%M:%S")
        self._sb("last_ref", f"上次刷新: {now_str}")
        self._sb("videos", f"监控: {len(self.monitored_videos)} 个")
        self._register_video_timer(bvid)
        auto_predict_video(self, bvid)

    def _toggle_auto_refresh(self, event=None):
        cur = self.auto_refresh_enabled.get()
        self.auto_refresh_enabled.set(not cur)
        self.bottom_bar._draw_toggle(not cur)
        if not cur:
            self._start_global_tick()
            self._sb("status", "自动刷新已启用", C["success"])
        else:
            self._stop_global_tick()
            self._countdown_badge.config(text="已暂停")
            self._mode_pill.config(text="已暂停", fg=C["text_3"])
            self._sb("status", "自动刷新已禁用", C["warning"])

    def _do_fetch(self):
        fetch_all_video_data(self)

    def _post_fetch(self):
        now_str = datetime.now().strftime("%H:%M:%S")
        self._sb("status",   "刷新完成", C["success"])
        self._sb("last_ref", f"上次刷新: {now_str}")
        self._sb("videos",   f"监控: {len(self.monitored_videos)} 个")
        for video in self.monitored_videos:
            bvid = video.get("bvid", "")
            if bvid in self.video_list.get_card_widgets():
                self.video_list.update_card(video)
        if self.selected_bvid:
            video = next((v for v in self.monitored_videos if v.get("bvid") == self.selected_bvid), None)
            if video:
                self.detail.update_stat_bar(video)
                if self.detail.current_tab == "📈 播放量趋势":
                    draw_chart(self.detail.chart_canvas, self.history_data, self.selected_bvid, video, FONT)
        for video in self.monitored_videos:
            self._register_video_timer(video.get("bvid", ""))
        auto_predict_all(self)

    def _show_video_detail(self, video):
        self.detail._build_center_header(video)
        self.detail._rebuild_stat_bar(video)
        self.detail._switch_tab(self.detail.current_tab)

    def _select_video(self, bvid):
        prev = self.selected_bvid
        self.selected_bvid = bvid
        self.video_list.highlight_card(bvid)
        video = next((v for v in self.monitored_videos if v.get("bvid") == bvid), None)
        if video:
            self._show_video_detail(video)
        cached = self.prediction_results.get(bvid)
        if cached:
            self.prediction._build_pred_hero(cached["prediction"], cached["current_view"],
                                              cached.get("rate_per_sec", 0))

    # ── 添加/删除监控 ────────────────────────────

    def _add_monitor(self):
        """添加监控 - 重构版"""
        # 创建对话框
        dialog = self._create_add_dialog()
        
        # 构建对话框UI
        entry, status_lbl = self._build_add_dialog_ui(dialog)
        
        # 设置按钮和事件绑定
        self._setup_add_dialog_buttons(dialog, entry, status_lbl)

    def _create_add_dialog(self):
        """创建添加监控对话框"""
        dialog = tk.Toplevel(self.root)
        dialog.title("添加监控")
        dialog.geometry("400x180")
        dialog.configure(bg=C["bg_surface"])
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        return dialog

    def _build_add_dialog_ui(self, dialog):
        """构建对话框UI元素"""
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
        
        return entry, status_lbl

    def _setup_add_dialog_buttons(self, dialog, entry, status_lbl):
        """设置对话框按钮和事件绑定"""
        def _confirm():
            self._validate_and_add_video(entry.get().strip(), dialog, status_lbl)

        btn_f = tk.Frame(dialog, bg=C["bg_surface"])
        btn_f.pack(pady=10)
        ttk.Button(btn_f, text="确认添加", style="Primary.TButton", command=_confirm).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_f, text="取消", command=dialog.destroy).pack(side=tk.LEFT, padx=6)
        entry.bind("<Return>", lambda e: _confirm())

    def _validate_and_add_video(self, raw_input, dialog, status_lbl):
        """验证输入并添加视频"""
        if not raw_input:
            messagebox.showwarning("提示", "请输入BV号", parent=dialog)
            return
        
        # 提取BV号
        bvid = self._extract_bvid_from_input(raw_input)
        if bvid is None:
            return
        
        # 检查是否已在监控列表
        if self._check_video_in_monitor_list(bvid, dialog):
            return
            
        # 获取视频信息并添加
        self._fetch_video_info_and_add(bvid, dialog, status_lbl)

    def _extract_bvid_from_input(self, raw_input):
        """从输入中提取BV号"""
        bvid = raw_input
        if "bilibili.com" in raw_input:
            m = re.search(r"BV[\w]+", raw_input)
            if m:
                bvid = m.group()
            else:
                messagebox.showerror("错误", "无法从链接中提取BV号", parent=self.root)
                return None
        return bvid

    def _check_video_in_monitor_list(self, bvid, dialog):
        """检查视频是否已在监控列表"""
        if any(v.get("bvid") == bvid for v in self.monitored_videos):
            messagebox.showinfo("提示", f"{bvid} 已在监控列表中", parent=dialog)
            dialog.destroy()
            return True
        return False

    def _fetch_video_info_and_add(self, bvid, dialog, status_lbl):
        """获取视频信息并添加到监控"""
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
        self._video_timers.pop(bvid, None)
        self._fetching_set.discard(bvid)
        self.video_list.remove_card(bvid)
        self.selected_bvid = None
        self.detail._build_center_header_empty()
        self.detail._rebuild_stat_bar({})
        draw_chart_placeholder(self.detail.chart_canvas)
        self.prediction._build_pred_hero_empty()
        for w in self.prediction.algo_frame.winfo_children():
            w.destroy()
        self.video_list.update_video_count()
        self._sb("videos", f"监控: {len(self.monitored_videos)} 个")
        self._save_watch_list()

    def _refresh_data(self):
        self._do_fetch()

    # ── 预测结果回调 ─────────────────────────────

    def _prediction_done(self, w_pred, current_view, growth, rate_per_sec,
                          success_list, fail_list, valid, total):
        self.prediction._build_pred_hero(w_pred, current_view, rate_per_sec)
        self.prediction._update_algo_list(success_list, fail_list)
        self._sb("algo",   f"算法: {valid}/{total}")
        self._sb("status", "预测完成", C["success"])

    def _copy_bvid(self, bvid):
        self.root.clipboard_clear()
        self.root.clipboard_append(bvid)
        self._sb("status", f"已复制 {bvid}", C["success"])

    # ── 设置窗口（透传 Dialogs）────────────────

    def _open_interval_settings(self):
        self._dialogs.open_interval_settings()

    def _open_weight_settings(self):
        self._dialogs.open_weight_settings()

    def _open_database_query(self):
        self._dialogs.open_database_query()

    def _open_video_search(self):
        self._dialogs.open_video_search()

    def _open_data_comparison(self):
        self._dialogs.open_data_comparison()

    def _open_crossover_analysis(self):
        self._dialogs.open_crossover_analysis()

    def _open_weekly_score(self):
        self._dialogs.open_weekly_score()

    def _open_milestone_stats(self):
        self._dialogs.open_milestone_stats()

    def _add_bvid_to_monitor(self, bvid: str):
        self._dialogs.add_bvid_to_monitor(bvid)

    def _open_network_settings(self):
        self._dialogs.open_network_settings()

    def _open_settings(self):
        self._dialogs.open_settings()

    def _import_search_results(self, videos: list):
        self._dialogs.import_search_results(videos)

    # ── 监控列表持久化 ─────────────────────────────

    def _load_watch_list(self):
        load_watch_list(self)

    def _restore_video(self, video):
        bvid = video.get("bvid", "")
        if any(v.get("bvid") == bvid for v in self.monitored_videos):
            return
        self.monitored_videos.append(video)
        self.video_list.make_card(video)
        self.video_list.update_video_count()
        self._sb("videos", f"监控: {len(self.monitored_videos)} 个")
        self._register_video_timer(bvid)

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
        self.video_list.make_card(video)
        self.video_list.update_video_count()
        self._sb("videos", f"监控: {len(self.monitored_videos)} 个")
        self._register_video_timer(bvid)

    def _save_weekly_score(self, bvid, video, timestamp):
        try:
            from utils.weekly_score import calculate_from_dict
            from dataclasses import asdict
            ws = calculate_from_dict(video)
            if ws and bvid in self.video_dbs:
                score_data = asdict(ws)
                self.video_dbs[bvid].add_weekly_score(timestamp, score_data)
        except Exception as e:
            print(f"保存周刊分数失败 {bvid}: {e}")

    def _save_yearly_score(self, bvid, video, timestamp):
        try:
            from utils.yearly_score import calculate_yearly_from_dict
            from dataclasses import asdict
            ys = calculate_yearly_from_dict(video)
            if ys and bvid in self.video_dbs:
                score_data = asdict(ys)
                self.video_dbs[bvid].add_yearly_score(timestamp, score_data)
        except Exception as e:
            print(f"保存年刊分数失败 {bvid}: {e}")

    def _save_watch_list(self):
        config = load_config()
        config["watch_list"] = [v.get("bvid", "") for v in self.monitored_videos]
        save_config(config)

    # ── 退出 ─────────────────────────────────────

    def _on_exit(self):
        self._save_watch_list()
        self.log_panel.cleanup()
        self._stop_global_tick()
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
