"""
主GUI界面 - 深色三栏布局

左侧视频卡片 / 中间图表详情 / 右侧预测分析

UI 已拆分为独立模块：
- video_list_panel.py  : 左侧视频列表
- detail_panel.py      : 中间详情+图表
- prediction_panel.py  : 右侧预测面板
- bottom_bar.py       : 底部状态栏
- dialogs.py           : 所有弹窗
- main_gui_tick.py     : 全局 tick 循环与周期性维护
- main_gui_events.py   : 事件处理器
- main_gui_data.py     : 数据操作
"""

import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk
import threading
import time
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

import sys

from utils import project_path as _pp
from utils.update_checker import _x

sys.path.insert(0, str(_pp()))

from ui.theme import C, init_theme
from ui.helpers import (
    FONT, FONT_SM, FONT_MONO,
    DEFAULT_INTERVAL, FAST_INTERVAL, FAST_GAP,
    THRESHOLD_NAMES, fmt_num, nearest_threshold_gap, fmt_eta,
    project_path,
)
from ui.chart import draw_chart_placeholder
from ui.log_panel import LogPanel
from ui.video_list_panel import VideoListPanel
from ui.detail_panel import DetailPanel
from ui.prediction_panel import PredictionPanel
from ui.bottom_bar import BottomBar
from ui.dialogs import Dialogs
from utils.yearly_score import calculate_yearly_from_dict as _calc_ys
from ui.monitor_service import fetch_all_video_data, auto_predict_all
from core import bilibili_api, db, notification_manager
from config import load_config
from utils.file_logger import FileLogger
from ui.main_gui_tick import (
    start_global_tick as _start_global_tick_impl,
    stop_global_tick as _stop_global_tick_impl,
    global_tick as _global_tick_impl,
    do_periodic_sync as _do_periodic_sync_impl,
    wal_checkpoint_worker as _wal_checkpoint_worker_impl,
    scan_alerts_background as _scan_alerts_background_impl,
)
from ui.main_gui_events import (
    on_channel_switch as _on_channel_switch_impl,
    show_download_progress as _show_download_progress_impl,
    check_update as _check_update_impl,
    show_update_dialog as _show_update_dialog_impl,
    on_exit as _on_exit_impl,
    refresh_model_status as _refresh_model_status_impl,
    activate_models as _activate_models_impl,
    auto_activate_on_startup as _auto_activate_on_startup_impl,
    preload_algorithms as _preload_algorithms_impl,
    get_video_interval as _get_video_interval_impl,
    register_video_timer as _register_video_timer_impl,
    start_auto_refresh as _start_auto_refresh_impl,
    toggle_auto_refresh as _toggle_auto_refresh_impl,
    do_fetch as _do_fetch_impl,
    post_fetch as _post_fetch_impl,
    show_video_detail as _show_video_detail_impl,
    select_video as _select_video_impl,
    add_monitor as _add_monitor_impl,
    remove_monitor as _remove_monitor_impl,
    push_single as _push_single_impl,
    manual_push as _manual_push_impl,
    on_training_completed as _on_training_completed_impl,
    update_trained_weights as _update_trained_weights_impl,
    run_post_training_predict as _run_post_training_predict_impl,
    schedule_daily_push as _schedule_daily_push_impl,
    daily_push as _daily_push_impl,
    build_daily_push_msg as _build_daily_push_msg_impl,
    build_push_msg as _build_push_msg_impl,
    prediction_done as _prediction_done_impl,
    copy_bvid as _copy_bvid_impl,
    open_interval_settings as _open_interval_settings_impl,
    open_database_query as _open_database_query_impl,
    open_video_search as _open_video_search_impl,
    open_data_comparison as _open_data_comparison_impl,
    open_crossover_analysis as _open_crossover_analysis_impl,
    open_weekly_score as _open_weekly_score_impl,
    open_milestone_stats as _open_milestone_stats_impl,
    add_bvid_to_monitor as _add_bvid_to_monitor_impl,
    import_search_results as _import_search_results_impl,
)
from ui.main_gui_data import (
    map_api_to_video_dict as _map_api_to_video_dict_impl,
    refresh_data as _refresh_data_impl,
    load_watch_list as _load_watch_list_impl,
    save_watch_list as _save_watch_list_impl,
    save_weekly_score as _save_weekly_score_impl,
    save_yearly_score as _save_yearly_score_impl,
    restore_video as _restore_video_impl,
    register_video_to_monitor as _register_video_to_monitor_impl,
    prompt_backup_sync as _prompt_backup_sync_impl,
)


# ══════════════════════════════════════════════
# 主界面
# ══════════════════════════════════════════════
class BilibiliMonitorGUI:
    """主界面 - 深色三栏布局（精简版）"""

    DEFAULT_INTERVAL = DEFAULT_INTERVAL
    FAST_INTERVAL = FAST_INTERVAL
    THRESHOLD_GAP = FAST_GAP

    def __init__(self, root=None):
        """初始化主界面"""
        if root is None:
            root = ctk.CTk()
            from __init__ import __version__
            from utils.update_checker import _x as _z

            _s = " dev 开发中" if _z() else ""
            root.title(f"B站视频监控与播放量预测系统 v{__version__}{_s}")
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
            root.geometry(f"{int(sw * 0.85)}x{int(sh * 0.85)}")
            root.minsize(int(sw * 0.50), int(sh * 0.55))

        self.root = root
        self._set_window_icon()
        init_theme(root)

        self.auto_refresh_enabled = tk.BooleanVar(value=True)
        self._global_tick_job = None
        self._video_timers = {}
        self._data_lock = threading.Lock()
        self._tick_counter = 0

        self.monitored_videos = []
        self.history_data = {}
        self.prediction_results = {}
        self.video_dbs = {}
        self.selected_bvid = None
        self._video_index = {}

        self._chart_debounce = None
        self._selected_debounce = None

        self._file_logger = FileLogger(project_path("data", "log"))
        if not logging.root.handlers:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s.%(msecs)03d [%(levelname)-7s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        logging.getLogger("prophet.plot").setLevel(logging.CRITICAL)
        logging.getLogger("prophet").setLevel(logging.WARNING)

        self.root.protocol("WM_DELETE_WINDOW", self._on_exit)
        self._build_ui()
        self.root.after(500, self._auto_activate_on_startup)
        self._load_watch_list()
        self._preload_algorithms()
        notification_manager.configure(load_config())
        self._schedule_daily_push()
        self._start_auto_refresh()
        self._file_logger.start_midnight_checker(self.root)
        self.root.after(3000, self._check_update)

    def _set_window_icon(self):
        """设置窗口图标"""
        try:
            from PIL import Image, ImageTk

            icon_path = project_path("assets", "app_icon.png")
            if os.path.exists(icon_path):
                img = Image.open(icon_path)
                photo = ImageTk.PhotoImage(img)
                self.root.iconphoto(True, photo)
        except Exception as e:
            logger.debug("设置窗口图标失败: %s", e)

    # ──────────────────────────────────────────
    # UI 构建
    # ──────────────────────────────────────────

    def _build_ui(self):
        """构建整体 UI 布局"""
        self._build_titlebar()
        self.log_panel = LogPanel(self.root, self._file_logger)
        from ui.log_panel import install_logging_bridge
        install_logging_bridge(self.log_panel)
        self._build_main()
        self.training_panel = None
        self.finetune_panel = None
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
        self._bar = bar

    def _build_logo_section(self):
        """构建Logo区域 - 改进版：添加副标题"""
        bar = self._bar
        logo_f = tk.Frame(bar, bg=C["bg_surface"])
        logo_f.pack(side=tk.LEFT, padx=(14, 0))
        logo_canvas = tk.Canvas(logo_f, width=32, height=32, bg=C["bg_surface"], highlightthickness=0)
        logo_canvas.create_oval(4, 4, 28, 28, fill=C["bilibili"], outline="")
        logo_canvas.create_text(16, 16, text="B", fill="white", font=("Microsoft YaHei UI", 14, "bold"))
        logo_canvas.pack(side=tk.LEFT, padx=(0, 8))
        title_f = tk.Frame(logo_f, bg=C["bg_surface"])
        title_f.pack(side=tk.LEFT)
        tk.Label(title_f, text="B站监控", bg=C["bg_surface"], fg=C["bilibili"], font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        tk.Label(title_f, text="播放量预测系统", bg=C["bg_surface"], fg=C["text_3"], font=("Microsoft YaHei UI", 10)).pack(anchor="w")

    def _build_navigation_buttons(self):
        """构建导航按钮"""
        bar = self._bar
        nav_f = tk.Frame(bar, bg=C["bg_surface"])
        nav_f.pack(side=tk.LEFT, padx=16)
        self._nav_btns = {}
        self._page_views = ["监控列表", "日志", "模型训练", "微调训练"]
        self._dialogs = Dialogs(self)
        nav_items = [
            ("📊", "监控列表", None),
            ("📋", "日志", None),
            ("🧠", "模型训练", None),
            ("🎯", "微调训练", None),
        ]
        for icon, label, cmd in nav_items:
            self._create_nav_button(nav_f, icon, label, cmd)
        self._current_nav = "监控列表"

    def _create_nav_button(self, parent, icon, label, cmd):
        """创建导航按钮 - 改进版：图标+文本+激活指示器"""
        btn = tk.Frame(parent, bg=C["bg_surface"], cursor="hand2")
        btn.pack(side=tk.LEFT, padx=4)
        icon_lbl = tk.Label(btn, text=icon, bg=C["bg_surface"], fg=C["text_secondary"], font=("Microsoft YaHei UI", 12))
        icon_lbl.pack(side=tk.LEFT, padx=(8, 4))
        text_lbl = tk.Label(btn, text=label, bg=C["bg_surface"], fg=C["text_secondary"], font=FONT)
        text_lbl.pack(side=tk.LEFT, padx=(0, 8))
        indicator = tk.Frame(btn, bg=C["bg_surface"], height=2)
        indicator.pack(side=tk.BOTTOM, fill=tk.X)

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
            for k, b in self._nav_btns.items():
                if isinstance(b, tuple):
                    ic, tl, ind = b
                    ic.config(fg=C["text_secondary"])
                    tl.config(fg=C["text_secondary"])
                    ind.config(bg=C["bg_surface"])
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
        icon_lbl.bind("<Button-1>", on_click)
        text_lbl.bind("<Button-1>", on_click)
        self._nav_btns[label] = (icon_lbl, text_lbl, indicator)
        if label == "监控列表":
            indicator.config(bg=C["bilibili"])
            icon_lbl.config(fg=C["bilibili"])
            text_lbl.config(fg=C["bilibili"])

    def _build_right_buttons(self):
        """构建右侧按钮区"""
        bar = self._bar
        right_f = tk.Frame(bar, bg=C["bg_surface"])
        right_f.pack(side=tk.RIGHT, padx=14)
        self._create_settings_menu()
        self._build_model_activation(right_f)
        self._gear_btn = self._create_icon_button(right_f, "⚙️", self._popup_settings_menu, "设置")
        self._create_icon_button(right_f, "🔍", self._dialogs.open_video_search, "搜索")
        self._create_countdown_badge(right_f)
        self._create_mode_pill(right_f)

    def _create_settings_menu(self):
        """创建设置下拉菜单"""
        self._settings_menu = tk.Menu(
            self.root, tearoff=0, bg=C["bg_elevated"], fg=C["text_1"],
            activebackground=C["bg_hover"], activeforeground=C["text_1"],
            font=FONT, bd=0, relief="flat",
        )
        self._settings_menu.add_command(label="⏱  刷新间隔", command=self._dialogs.open_interval_settings)
        self._settings_menu.add_command(label="🧠  算法信息", command=self._dialogs.open_algorithm_info)
        self._settings_menu.add_separator()
        self._settings_menu.add_command(label="📊  数据对比", command=self._dialogs.open_data_comparison)
        self._settings_menu.add_command(label="🔄  交叉计算", command=self._dialogs.open_crossover_analysis)
        self._settings_menu.add_command(label="📅  周刊分数", command=self._dialogs.open_weekly_score)
        self._settings_menu.add_command(label="🏆  里程碑", command=self._dialogs.open_milestone_stats)
        self._settings_menu.add_command(label="🆙  UP主追踪", command=self._dialogs.open_up_tracker)
        self._settings_menu.add_command(label="💬  弹幕分析", command=self._dialogs.open_danmaku_analysis)
        self._settings_menu.add_command(label="🔥  热门发现", command=self._dialogs.open_trending_discovery)
        self._settings_menu.add_command(label="🎫  视频标签", command=self._dialogs.open_tag_manager)
        self._settings_menu.add_command(label="🚨  异常检测", command=self._dialogs.open_anomaly_detection)
        self._settings_menu.add_command(label="🏆  视频排行", command=self._dialogs.open_ranking)
        self._settings_menu.add_command(label="📊  预测回测", command=self._dialogs.open_backtest)
        self._settings_menu.add_separator()
        self._settings_menu.add_command(label="🤖  AI智能问答", command=self._dialogs.open_ai_qa)
        self._settings_menu.add_command(label="📊  数据大屏", command=self._dialogs.open_dashboard)
        self._settings_menu.add_command(label="📋  导出报告", command=self._dialogs.open_report_scheduler)
        self._settings_menu.add_separator()
        self._settings_menu.add_command(label="🗄  数据库查询", command=self._dialogs.open_database_query, state="normal" if _x() else "disabled")
        self._settings_menu.add_command(label="⚙️  系统设置", command=self._dialogs.open_settings, state="normal" if _x() else "disabled")

    def _create_icon_button(self, parent, icon, command, tooltip=None):
        """创建图标按钮（可复用）"""
        btn = tk.Label(parent, text=icon, bg=C["bg_elevated"], fg=C["text_2"],
                       font=("Microsoft YaHei UI", 11), cursor="hand2", padx=6, pady=2, relief="flat")
        btn.pack(side=tk.RIGHT, padx=2)
        if callable(command):
            btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e, b=btn: b.config(bg=C["bg_hover"], fg=C["text_1"]))
        btn.bind("<Leave>", lambda e, b=btn: b.config(bg=C["bg_elevated"], fg=C["text_2"]))
        return btn

    def _popup_settings_menu(self):
        """弹出设置菜单"""
        try:
            x = self._gear_btn.winfo_rootx()
            y = self._gear_btn.winfo_rooty() + self._gear_btn.winfo_height()
            self._settings_menu.tk_popup(x, y)
        except Exception as e:
            logger.debug("弹出设置菜单失败: %s", e)

    def _create_countdown_badge(self, parent):
        """创建倒计时徽章"""
        self._countdown_badge = tk.Label(
            parent, text="-- s", bg=C["bg_elevated"], fg=C["accent"], font=FONT_MONO, padx=8, pady=2, relief="flat"
        )
        self._countdown_badge.pack(side=tk.RIGHT, padx=6)

    def _create_mode_pill(self, parent):
        """创建模式指示器"""
        self._mode_pill = tk.Label(
            parent, text="● 正常模式", bg=C["bg_surface"], fg=C["success"], font=("Microsoft YaHei UI", 9, "bold")
        )
        self._mode_pill.pack(side=tk.RIGHT, padx=6)

    # ── 模型激活 ─────────────────────────────────

    def _build_model_activation(self, parent):
        """构建模型激活按钮 + 状态指示"""
        f = tk.Frame(parent, bg=C["bg_surface"])
        f.pack(side=tk.RIGHT, padx=2)
        self._model_act_btn = tk.Label(
            f, text="🧠 激活模型", bg=C["bg_elevated"], fg=C["accent"],
            font=FONT, cursor="hand2", padx=6, pady=2, relief="flat",
        )
        self._model_act_btn.pack(side=tk.RIGHT, padx=2)
        self._model_act_btn.bind("<Button-1>", lambda e: self._on_activate_models())
        self._model_act_btn.bind("<Enter>", lambda e: self._model_act_btn.config(bg=C["bg_hover"]))
        self._model_act_btn.bind("<Leave>", lambda e: self._model_act_btn.config(bg=C["bg_elevated"]))
        self._model_act_status = tk.Label(
            f, text="", bg=C["bg_surface"], fg=C["text_3"], font=("Microsoft YaHei UI", 9),
        )
        self._model_act_status.pack(side=tk.RIGHT, padx=2)

    def _build_main(self):
        """构建主体三栏布局"""
        self._main_frame = tk.Frame(self.root, bg=C["bg_base"])
        self._main_frame.pack(fill=tk.BOTH, expand=True)
        main = tk.Frame(self._main_frame, bg=C["bg_base"])
        main.pack(fill=tk.BOTH, expand=True)
        main.grid_columnconfigure(0, weight=22, minsize=220)
        main.grid_columnconfigure(1, weight=0)
        main.grid_columnconfigure(2, weight=58, minsize=360)
        main.grid_columnconfigure(3, weight=0)
        main.grid_columnconfigure(4, weight=20, minsize=200)
        main.grid_rowconfigure(0, weight=1)
        self._left = tk.Frame(main, bg=C["bg_surface"])
        self._left.grid(row=0, column=0, sticky="nsew")
        tk.Frame(main, bg=C["border"], width=1).grid(row=0, column=1, sticky="ns")
        self._center = tk.Frame(main, bg=C["bg_base"])
        self._center.grid(row=0, column=2, sticky="nsew")
        tk.Frame(main, bg=C["border"], width=1).grid(row=0, column=3, sticky="ns")
        self._right = tk.Frame(main, bg=C["bg_surface"])
        self._right.grid(row=0, column=4, sticky="nsew")
        self.video_list = VideoListPanel(self._left, self)
        self.detail = DetailPanel(self._center, self)
        self.prediction = PredictionPanel(self._right, self)

    # ──────────────────────────────────────────
    # 状态栏
    # ──────────────────────────────────────────

    def _build_status_bar(self):
        pass

    def _sb(self, key, text, color=None):
        """更新状态栏"""
        self.bottom_bar.update_sb(key, text, color)

    def set_finetune_status(self, text: str, color=None):
        """更新主界面底部状态栏的微调状态"""
        self._sb("finetune", text, color=color or C.get("accent", "#4A90D9"))

    # ──────────────────────────────────────────
    # 导航切换
    # ──────────────────────────────────────────

    def _switch_nav(self, name):
        """切换导航页面"""
        if name == self._current_nav:
            return
        self._current_nav = name
        for k, b in self._nav_btns.items():
            ic, tl, ind = b
            ic.config(fg=C["bilibili"] if k == name else C["text_secondary"])
            tl.config(fg=C["bilibili"] if k == name else C["text_secondary"])
            ind.config(bg=C["bilibili"] if k == name else C["bg_surface"])
        self._main_frame.pack_forget()
        self.log_panel.frame.pack_forget()
        if self.training_panel is not None:
            self.training_panel.frame.pack_forget()
        if self.finetune_panel is not None:
            self.finetune_panel.frame.pack_forget()
        self.log_panel.stop_auto_refresh()
        if name == "日志":
            self.log_panel.frame.pack(fill=tk.BOTH, expand=True)
            self.log_panel.refresh_log_view()
            self.log_panel.start_auto_refresh(self.root)
        elif name == "模型训练":
            if self.training_panel is None:
                from ui.training_panel import TrainingPanel
                self.training_panel = TrainingPanel(self.root, self)
            self.training_panel.frame.pack(fill=tk.BOTH, expand=True)
            self.training_panel.on_show()
        elif name == "微调训练":
            if self.finetune_panel is None:
                from ui.finetune_panel import FinetunePanel
                self.finetune_panel = FinetunePanel(self.root, self)
            self.finetune_panel.frame.pack(fill=tk.BOTH, expand=True)
            self.finetune_panel.on_show()
        else:
            self._main_frame.pack(fill=tk.BOTH, expand=True)

    # ══════════════════════════════════════════
    # 以下为薄委托包装器 — 实现移至各子模块
    # ══════════════════════════════════════════

    # ── 全局 Tick ─────────────────────────────

    def _start_global_tick(self):
        _start_global_tick_impl(self)

    def _stop_global_tick(self):
        _stop_global_tick_impl(self)

    def _global_tick(self):
        _global_tick_impl(self)

    def _do_periodic_sync(self):
        _do_periodic_sync_impl(self)

    def _wal_checkpoint_worker(self):
        _wal_checkpoint_worker_impl(self)

    def _scan_alerts_background(self):
        _scan_alerts_background_impl(self)

    # ── 更新 / 通道 ───────────────────────────

    def _check_update(self):
        _check_update_impl(self)

    def _show_update_dialog(self, latest, current, url, changelog, channel="stable"):
        _show_update_dialog_impl(self, latest, current, url, changelog, channel)

    def _on_channel_switch(self, new_channel, dlg):
        _on_channel_switch_impl(self, new_channel, dlg)

    def _show_download_progress(self, title, download_fn):
        _show_download_progress_impl(self, title, download_fn)

    def _on_exit(self):
        _on_exit_impl(self)

    # ── 模型激活 ─────────────────────────────

    def _refresh_model_status(self):
        _refresh_model_status_impl(self)

    def _on_activate_models(self):
        _activate_models_impl(self)

    def _auto_activate_on_startup(self):
        _auto_activate_on_startup_impl(self)

    # ── 初始化 ────────────────────────────────

    def _preload_algorithms(self):
        _preload_algorithms_impl(self)

    # ── 视频间隔 / 定时器 ─────────────────────

    def _get_video_interval(self, video):
        return _get_video_interval_impl(self, video)

    def _register_video_timer(self, bvid):
        _register_video_timer_impl(self, bvid)

    def _start_auto_refresh(self):
        _start_auto_refresh_impl(self)

    # ── 刷新 / 拉取 ──────────────────────────

    def _toggle_auto_refresh(self, event=None):
        _toggle_auto_refresh_impl(self, event)

    def _do_fetch(self):
        _do_fetch_impl(self)

    def _post_fetch(self):
        _post_fetch_impl(self)

    # ── 视频选中 / 详情 ──────────────────────

    def _show_video_detail(self, video):
        _show_video_detail_impl(self, video)

    def _select_video(self, bvid):
        _select_video_impl(self, bvid)

    # ── 添加监控 ──────────────────────────────

    def _add_monitor(self):
        _add_monitor_impl(self)

    def _get_video(self, bvid):
        from ui.main_gui_events import get_video
        return get_video(self, bvid)

    # ── 删除监控 ──────────────────────────────

    def _remove_monitor(self):
        _remove_monitor_impl(self)

    # ── 推送 ──────────────────────────────────

    def _push_single(self, bvid):
        _push_single_impl(self, bvid)

    def _manual_push(self):
        _manual_push_impl(self)

    # ── 训练完成回调 ──────────────────────────

    def _on_training_completed(self, mode="训练", count=0, detail="", trained_ids=None):
        _on_training_completed_impl(self, mode, count, detail, trained_ids)

    def _update_trained_weights(self, algo_ids):
        _update_trained_weights_impl(self, algo_ids)

    def _run_post_training_predict(self):
        _run_post_training_predict_impl(self)

    # ── 每日推送 ──────────────────────────────

    def _schedule_daily_push(self):
        _schedule_daily_push_impl(self)

    def _daily_push(self):
        _daily_push_impl(self)

    def _build_daily_push_msg(self):
        return _build_daily_push_msg_impl(self)

    def _build_push_msg(self, videos):
        return _build_push_msg_impl(self, videos)

    # ── 预测结果回调 ──────────────────────────

    def _prediction_done(self, w_pred, current_view, growth, rate_per_sec, success_list, fail_list, valid, total):
        _prediction_done_impl(self, w_pred, current_view, growth, rate_per_sec, success_list, fail_list, valid, total)

    def _copy_bvid(self, bvid):
        _copy_bvid_impl(self, bvid)

    # ── 弹窗透传 ──────────────────────────────

    def _open_interval_settings(self):
        _open_interval_settings_impl(self)

    def _open_database_query(self):
        _open_database_query_impl(self)

    def _open_video_search(self):
        _open_video_search_impl(self)

    def _open_data_comparison(self):
        _open_data_comparison_impl(self)

    def _open_crossover_analysis(self):
        _open_crossover_analysis_impl(self)

    def _open_weekly_score(self):
        _open_weekly_score_impl(self)

    def _open_milestone_stats(self):
        _open_milestone_stats_impl(self)

    def _add_bvid_to_monitor(self, bvid: str):
        _add_bvid_to_monitor_impl(self, bvid)

    def _import_search_results(self, videos: list):
        _import_search_results_impl(self, videos)

    # ── 监控列表持久化 ────────────────────────

    def _load_watch_list(self):
        _load_watch_list_impl(self)

    def _restore_video(self, video):
        _restore_video_impl(self, video)

    @staticmethod
    def _map_api_to_video_dict(bvid: str, info: dict = None, video_info=None) -> dict:
        return _map_api_to_video_dict_impl(bvid, info, video_info)

    def _register_video_to_monitor(self, video: dict) -> None:
        _register_video_to_monitor_impl(self, video)

    def _save_weekly_score(self, bvid, video, timestamp):
        _save_weekly_score_impl(self, bvid, video, timestamp)

    def _save_yearly_score(self, bvid, video, timestamp):
        _save_yearly_score_impl(self, bvid, video, timestamp)

    def _save_watch_list(self):
        _save_watch_list_impl(self)

    def _prompt_backup_sync(self, diffs, db):
        _prompt_backup_sync_impl(self, diffs, db)

    def _refresh_data(self):
        _refresh_data_impl(self)

    # ── 运行 ─────────────────────────────────

    def run(self):
        """启动主循环"""
        self.root.mainloop()


def main():
    """主入口函数"""
    app = BilibiliMonitorGUI()
    app.run()


if __name__ == "__main__":
    main()
