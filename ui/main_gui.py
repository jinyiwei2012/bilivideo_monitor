"""
主GUI界面模块 — 深色三栏布局

应用程序的核心窗口，采用三栏布局：
  左侧  — 视频卡片列表（监控中的视频）
  中间  — 图表详情（播放量趋势图 + 视频详细信息）
  右侧  — 预测分析（加权预测值 + 阈值进度条 + 算法统计）

UI 已拆分为独立模块：
  - video_list_panel.py   : 左侧视频列表
  - detail_panel.py       : 中间详情+图表
  - prediction_panel.py   : 右侧预测面板
  - bottom_bar.py         : 底部状态栏
  - dialogs.py            : 所有弹窗（搜索、设置、对比等）
  - log_panel.py          : 日志面板
  - main_gui_tick.py      : 全局 tick 循环与周期性维护
  - main_gui_events.py    : 事件处理器（更新检查、下载、监控管理等）
  - main_gui_data.py      : 数据操作（持久化、注册、同步）

本文件作为薄委托层，将所有业务逻辑委托到对应的子模块中实现。
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
    """主界面 — 深色三栏布局

    核心状态管理:
      - monitored_videos  : 当前监控中的所有视频字典列表
      - history_data      : {bvid: [(timestamp, view_count), ...]} 历史播放量数据
      - prediction_results: {bvid: {...}} 预测结果缓存
      - video_dbs         : {bvid: VideoDatabase} 每个视频的独立数据库连接
      - selected_bvid     : 当前选中的视频 BV 号
      - _video_index      : {bvid: video_dict} 视频快速查找索引

    本类大量方法为薄委托包装器，实际逻辑在 main_gui_events / main_gui_data / main_gui_tick 中。
    """

    DEFAULT_INTERVAL = DEFAULT_INTERVAL
    FAST_INTERVAL = FAST_INTERVAL
    THRESHOLD_GAP = FAST_GAP

    def __init__(self, root=None):
        """初始化主界面

        执行流程:
          1. 创建 Tkinter 根窗口（若未提供则新建）
          2. 设置窗口图标
          3. 初始化深色主题
          4. 创建内部状态变量
          5. 构建 UI 布局
          6. 加载监控列表
          7. 预加载算法
          8. 配置通知服务
          9. 启动自动刷新 tick
          10. 安排更新检查

        Args:
            root: 可选的 Tkinter 根窗口对象
        """
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

        # ── 状态变量 ──
        self.auto_refresh_enabled = tk.BooleanVar(value=True)  # 是否启用自动刷新
        self._global_tick_job = None  # 全局 tick 的 after 任务 ID
        self._video_timers = {}  # {bvid: {"next": timestamp, "interval": seconds}}
        self._data_lock = threading.Lock()  # 数据访问锁（保护 monitored_videos 等共享数据）
        self._tick_counter = 0  # tick 计数器（用于周期性任务调度）

        # ── 视频数据 ──
        self.monitored_videos = []  # 监控中的视频列表
        self.history_data = {}  # {bvid: [(timestamp, view_count), ...]}
        self.prediction_results = {}  # {bvid: {prediction, growth, ...}}
        self.video_dbs = {}  # {bvid: VideoDatabase}
        self.selected_bvid = None  # 当前选中的视频 BV 号
        self._video_index = {}  # {bvid: video_dict} O(1) 查找

        # ── 防抖定时器 ──
        self._chart_debounce = None  # 图表重绘防抖
        self._selected_debounce = None  # 选中视频更新防抖

        # ── 日志系统 ──
        self._file_logger = FileLogger(project_path("data", "log"))
        if not logging.root.handlers:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s.%(msecs)03d [%(levelname)-7s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        # 抑制 Prophet 的冗余日志
        logging.getLogger("prophet.plot").setLevel(logging.CRITICAL)
        logging.getLogger("prophet").setLevel(logging.WARNING)

        # ── 启动流程 ──
        self.root.protocol("WM_DELETE_WINDOW", self._on_exit)  # 窗口关闭回调
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
        """设置窗口图标（从 assets/app_icon.png 加载）"""
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
        """构建整体 UI 布局

        结构从上到下:
          - 标题栏（Logo + 导航按钮 + 右侧操作按钮）
          - 日志面板（初始隐藏，通过导航切出）
          - 主体三栏布局（左侧视频列表 / 中间详情图表 / 右侧预测面板）
          - 底部状态栏
        """
        self._build_titlebar()
        self.log_panel = LogPanel(self.root, self._file_logger)
        from ui.log_panel import install_logging_bridge
        install_logging_bridge(self.log_panel)
        self._build_main()
        self.training_panel = None  # 模型训练面板（懒加载）
        self.finetune_panel = None  # 微调训练面板（懒加载）
        self.bottom_bar = BottomBar(self.root, self)
        self._build_status_bar()

    def _build_titlebar(self):
        """构建标题栏 — 重构版

        包含: Logo 区域 + 导航按钮（监控列表/日志/模型训练/微调训练）+ 右侧操作按钮
        """
        self._create_titlebar_container()
        self._build_logo_section()
        self._build_navigation_buttons()
        self._build_right_buttons()

    def _create_titlebar_container(self):
        """创建标题栏容器（固定高度 46px，含底部分隔线）"""
        bar = tk.Frame(self.root, bg=C["bg_surface"], height=46)
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)  # 防止内容撑大容器
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill=tk.X)  # 分隔线
        self._bar = bar

    def _build_logo_section(self):
        """构建Logo区域

        显示 B 站风格的粉色圆形 Logo + "B站监控" 主标题 + "播放量预测系统" 副标题
        """
        bar = self._bar
        logo_f = tk.Frame(bar, bg=C["bg_surface"])
        logo_f.pack(side=tk.LEFT, padx=(14, 0))
        # 粉色圆形 Logo（Canvas 绘制）
        logo_canvas = tk.Canvas(logo_f, width=32, height=32, bg=C["bg_surface"], highlightthickness=0)
        logo_canvas.create_oval(4, 4, 28, 28, fill=C["bilibili"], outline="")
        logo_canvas.create_text(16, 16, text="B", fill="white", font=("Microsoft YaHei UI", 14, "bold"))
        logo_canvas.pack(side=tk.LEFT, padx=(0, 8))
        title_f = tk.Frame(logo_f, bg=C["bg_surface"])
        title_f.pack(side=tk.LEFT)
        tk.Label(title_f, text="B站监控", bg=C["bg_surface"], fg=C["bilibili"], font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        tk.Label(title_f, text="播放量预测系统", bg=C["bg_surface"], fg=C["text_3"], font=("Microsoft YaHei UI", 10)).pack(anchor="w")

    def _build_navigation_buttons(self):
        """构建导航按钮（监控列表 / 日志 / 模型训练 / 微调训练）

        每个按钮包含图标 + 文字标签 + 底部激活指示器条
        """
        bar = self._bar
        nav_f = tk.Frame(bar, bg=C["bg_surface"])
        nav_f.pack(side=tk.LEFT, padx=16)
        self._nav_btns = {}  # {label: (icon_lbl, text_lbl, indicator)}
        self._page_views = ["监控列表", "日志", "模型训练", "微调训练"]
        self._dialogs = Dialogs(self)  # 弹窗管理器
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
        """创建单个导航按钮

        结构: 图标 Label + 文字 Label + 底部指示器 Frame
        交互: 鼠标悬浮高亮 / 点击切换激活状态 / 切换对应的页面视图

        Args:
            parent: 父容器
            icon: 图标文字（如 "📊"）
            label: 按钮文字（如 "监控列表"）
            cmd: 点击回调（可选）
        """
        btn = tk.Frame(parent, bg=C["bg_surface"], cursor="hand2")
        btn.pack(side=tk.LEFT, padx=4)
        icon_lbl = tk.Label(btn, text=icon, bg=C["bg_surface"], fg=C["text_secondary"], font=("Microsoft YaHei UI", 12))
        icon_lbl.pack(side=tk.LEFT, padx=(8, 4))
        text_lbl = tk.Label(btn, text=label, bg=C["bg_surface"], fg=C["text_secondary"], font=FONT)
        text_lbl.pack(side=tk.LEFT, padx=(0, 8))
        indicator = tk.Frame(btn, bg=C["bg_surface"], height=2)  # 激活指示条
        indicator.pack(side=tk.BOTTOM, fill=tk.X)

        def on_enter(e):
            """鼠标进入：前景色变亮，背景色变浅"""
            icon_lbl.config(fg=C["text_1"])
            text_lbl.config(fg=C["text_1"])
            btn.config(bg=C["bg_hover"])
            icon_lbl.config(bg=C["bg_hover"])
            text_lbl.config(bg=C["bg_hover"])

        def on_leave(e):
            """鼠标离开：恢复默认样式（除非当前按钮已激活）"""
            if indicator.cget("bg") != C["bilibili"]:
                icon_lbl.config(fg=C["text_secondary"])
                text_lbl.config(fg=C["text_secondary"])
                btn.config(bg=C["bg_surface"])
                icon_lbl.config(bg=C["bg_surface"])
                text_lbl.config(bg=C["bg_surface"])

        def on_click(e):
            """点击：取消其他按钮激活 → 激活当前 → 切换页面"""
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
        # 默认激活"监控列表"
        if label == "监控列表":
            indicator.config(bg=C["bilibili"])
            icon_lbl.config(fg=C["bilibili"])
            text_lbl.config(fg=C["bilibili"])

    def _build_right_buttons(self):
        """构建右侧按钮区：设置菜单 + 模型激活 + 搜索 + 倒计时徽章 + 模式指示器"""
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
        """创建设置下拉菜单

        包含: 刷新间隔、算法信息、数据对比、交叉计算、周刊分数、里程碑、
        UP主追踪、弹幕分析、热门发现、视频标签、异常检测、视频排行、
        预测回测、AI智能问答、数据大屏、导出报告、数据库查询、系统设置
        """
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
        # 高级功能仅在开发模式下启用
        self._settings_menu.add_command(label="🗄  数据库查询", command=self._dialogs.open_database_query, state="normal" if _x() else "disabled")
        self._settings_menu.add_command(label="⚙️  系统设置", command=self._dialogs.open_settings, state="normal" if _x() else "disabled")

    def _create_icon_button(self, parent, icon, command, tooltip=None):
        """创建图标按钮（可复用）

        Args:
            parent: 父容器
            icon: 图标字符（如 "⚙️"）
            command: 点击回调函数
            tooltip: 悬浮提示文字（暂未使用）

        Returns:
            tk.Label: 创建的按钮 Label 对象
        """
        btn = tk.Label(parent, text=icon, bg=C["bg_elevated"], fg=C["text_2"],
                       font=("Microsoft YaHei UI", 11), cursor="hand2", padx=6, pady=2, relief="flat")
        btn.pack(side=tk.RIGHT, padx=2)
        if callable(command):
            btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e, b=btn: b.config(bg=C["bg_hover"], fg=C["text_1"]))
        btn.bind("<Leave>", lambda e, b=btn: b.config(bg=C["bg_elevated"], fg=C["text_2"]))
        return btn

    def _popup_settings_menu(self):
        """弹出设置菜单（在齿轮按钮下方）"""
        try:
            x = self._gear_btn.winfo_rootx()
            y = self._gear_btn.winfo_rooty() + self._gear_btn.winfo_height()
            self._settings_menu.tk_popup(x, y)
        except Exception as e:
            logger.debug("弹出设置菜单失败: %s", e)

    def _create_countdown_badge(self, parent):
        """创建倒计时徽章（显示距离下次刷新的秒数）"""
        self._countdown_badge = tk.Label(
            parent, text="-- s", bg=C["bg_elevated"], fg=C["accent"], font=FONT_MONO, padx=8, pady=2, relief="flat"
        )
        self._countdown_badge.pack(side=tk.RIGHT, padx=6)

    def _create_mode_pill(self, parent):
        """创建模式指示器（正常模式/快速模式/已暂停）"""
        self._mode_pill = tk.Label(
            parent, text="● 正常模式", bg=C["bg_surface"], fg=C["success"], font=("Microsoft YaHei UI", 9, "bold")
        )
        self._mode_pill.pack(side=tk.RIGHT, padx=6)

    # ── 模型激活 ─────────────────────────────────

    def _build_model_activation(self, parent):
        """构建模型激活按钮 + 状态指示

        显示"激活模型"按钮和当前状态文字（如 "3/15 待激活" 或 "✓ 15 个已最新"）
        """
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
        """构建主体三栏布局

        使用 grid 布局，列权重 22:1:58:1:20（左:分隔线:中:分隔线:右），
        确保左侧视频列表和右侧预测面板有固定最小宽度，
        中间图表详情区域自适应填充剩余空间。
        """
        self._main_frame = tk.Frame(self.root, bg=C["bg_base"])
        self._main_frame.pack(fill=tk.BOTH, expand=True)
        main = tk.Frame(self._main_frame, bg=C["bg_base"])
        main.pack(fill=tk.BOTH, expand=True)
        main.grid_columnconfigure(0, weight=22, minsize=220)  # 左侧视频列表
        main.grid_columnconfigure(1, weight=0)                # 分隔线
        main.grid_columnconfigure(2, weight=58, minsize=360)  # 中间详情图表
        main.grid_columnconfigure(3, weight=0)                # 分隔线
        main.grid_columnconfigure(4, weight=20, minsize=200)  # 右侧预测面板
        main.grid_rowconfigure(0, weight=1)
        self._left = tk.Frame(main, bg=C["bg_surface"])
        self._left.grid(row=0, column=0, sticky="nsew")
        tk.Frame(main, bg=C["border"], width=1).grid(row=0, column=1, sticky="ns")
        self._center = tk.Frame(main, bg=C["bg_base"])
        self._center.grid(row=0, column=2, sticky="nsew")
        tk.Frame(main, bg=C["border"], width=1).grid(row=0, column=3, sticky="ns")
        self._right = tk.Frame(main, bg=C["bg_surface"])
        self._right.grid(row=0, column=4, sticky="nsew")
        # 初始化三大面板
        self.video_list = VideoListPanel(self._left, self)
        self.detail = DetailPanel(self._center, self)
        self.prediction = PredictionPanel(self._right, self)

    # ──────────────────────────────────────────
    # 状态栏
    # ──────────────────────────────────────────

    def _build_status_bar(self):
        """状态栏（已迁移至 BottomBar 组件）"""
        pass

    def _sb(self, key, text, color=None):
        """更新状态栏指定槽位的文本

        Args:
            key: 槽位名称（"status", "videos", "interval", "algo", "last_ref", "alert", "finetune"）
            text: 显示文本
            color: 文本颜色（可选，使用主题色）
        """
        self.bottom_bar.update_sb(key, text, color)

    def set_finetune_status(self, text: str, color=None):
        """更新主界面底部状态栏的微调状态显示

        Args:
            text: 状态文本
            color: 文本颜色（默认为主题色 accent）
        """
        self._sb("finetune", text, color=color or C.get("accent", "#4A90D9"))

    # ──────────────────────────────────────────
    # 导航切换
    # ──────────────────────────────────────────

    def _switch_nav(self, name):
        """切换导航页面（监控列表 / 日志 / 模型训练 / 微调训练）

        管理各页面的显示/隐藏状态:
          - "监控列表": 显示三栏主布局
          - "日志"    : 显示日志面板 + 启动自动刷新
          - "模型训练": 懒加载并显示训练面板
          - "微调训练": 懒加载并显示微调面板

        Args:
            name: 目标页面名称
        """
        if name == self._current_nav:
            return
        self._current_nav = name
        # 更新所有导航按钮的激活状态
        for k, b in self._nav_btns.items():
            ic, tl, ind = b
            ic.config(fg=C["bilibili"] if k == name else C["text_secondary"])
            tl.config(fg=C["bilibili"] if k == name else C["text_secondary"])
            ind.config(bg=C["bilibili"] if k == name else C["bg_surface"])
        # 隐藏所有面板
        self._main_frame.pack_forget()
        self.log_panel.frame.pack_forget()
        if self.training_panel is not None:
            self.training_panel.frame.pack_forget()
        if self.finetune_panel is not None:
            self.finetune_panel.frame.pack_forget()
        self.log_panel.stop_auto_refresh()
        # 显示目标面板
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
    # 每个方法仅调用对应子模块中的实现函数，
    # 保证 main_gui.py 作为总控层的简洁性。
    # ══════════════════════════════════════════

    # ── 全局 Tick ─────────────────────────────

    def _start_global_tick(self):
        """启动全局 tick 循环（每秒一次）"""
        _start_global_tick_impl(self)

    def _stop_global_tick(self):
        """停止全局 tick 循环"""
        _stop_global_tick_impl(self)

    def _global_tick(self):
        """全局 tick：更新倒计时、模式指示、周期性维护任务"""
        _global_tick_impl(self)

    def _do_periodic_sync(self):
        """每小时数据库同步（后台线程执行）"""
        _do_periodic_sync_impl(self)

    def _wal_checkpoint_worker(self):
        """WAL checkpoint 优化（后台线程执行）"""
        _wal_checkpoint_worker_impl(self)

    def _scan_alerts_background(self):
        """后台扫描异常告警"""
        _scan_alerts_background_impl(self)

    # ── 更新 / 通道 ───────────────────────────

    def _check_update(self):
        """异步检查 GitHub Release 更新"""
        _check_update_impl(self)

    def _show_update_dialog(self, latest, current, url, changelog, channel="stable"):
        """显示更新弹窗

        Args:
            latest: 最新版本号
            current: 当前版本号
            url: 下载地址
            changelog: 更新日志文本
            channel: 更新通道（"stable"/"beta"）
        """
        _show_update_dialog_impl(self, latest, current, url, changelog, channel)

    def _on_channel_switch(self, new_channel, dlg):
        """切换更新通道并重新检查更新

        Args:
            new_channel: 新通道名
            dlg: 原更新弹窗
        """
        _on_channel_switch_impl(self, new_channel, dlg)

    def _show_download_progress(self, title, download_fn):
        """显示 aria2 下载进度窗口

        Args:
            title: 窗口标题
            download_fn: 下载函数（接受 on_progress, on_done 回调）
        """
        _show_download_progress_impl(self, title, download_fn)

    def _on_exit(self):
        """应用退出时的清理工作：保存配置、停止线程、关闭数据库"""
        _on_exit_impl(self)

    # ── 模型激活 ─────────────────────────────

    def _refresh_model_status(self):
        """刷新模型激活状态显示"""
        _refresh_model_status_impl(self)

    def _on_activate_models(self):
        """手动激活所有算法的最新 checkpoint"""
        _activate_models_impl(self)

    def _auto_activate_on_startup(self):
        """启动时自动激活所有算法的最新 checkpoint（后台线程）"""
        _auto_activate_on_startup_impl(self)

    # ── 初始化 ────────────────────────────────

    def _preload_algorithms(self):
        """后台线程预加载 AlgorithmRegistry，避免首次预测时等待"""
        _preload_algorithms_impl(self)

    # ── 视频间隔 / 定时器 ─────────────────────

    def _get_video_interval(self, video):
        """根据视频播放量确定刷新间隔

        Args:
            video: 视频数据字典

        Returns:
            int: 刷新间隔（秒）
        """
        return _get_video_interval_impl(self, video)

    def _register_video_timer(self, bvid):
        """注册视频定时器

        Args:
            bvid: 视频 BV 号
        """
        _register_video_timer_impl(self, bvid)

    def _start_auto_refresh(self):
        """启动自动刷新机制"""
        _start_auto_refresh_impl(self)

    # ── 刷新 / 拉取 ──────────────────────────

    def _toggle_auto_refresh(self, event=None):
        """切换自动刷新开关

        Args:
            event: 触发事件（可选）
        """
        _toggle_auto_refresh_impl(self, event)

    def _do_fetch(self):
        """执行数据拉取"""
        _do_fetch_impl(self)

    def _post_fetch(self):
        """拉取完成后的回调处理"""
        _post_fetch_impl(self)

    # ── 视频选中 / 详情 ──────────────────────

    def _show_video_detail(self, video):
        """显示视频详情

        Args:
            video: 视频数据字典
        """
        _show_video_detail_impl(self, video)

    def _select_video(self, bvid):
        """选中视频（更新左侧高亮 + 中间详情 + 右侧预测）

        Args:
            bvid: 视频 BV 号
        """
        _select_video_impl(self, bvid)

    # ── 添加监控 ──────────────────────────────

    def _add_monitor(self):
        """打开添加监控对话框"""
        _add_monitor_impl(self)

    def _get_video(self, bvid):
        """O(1) 按 bvid 查找视频对象

        Args:
            bvid: 视频 BV 号

        Returns:
            dict 或 None: 视频数据字典
        """
        from ui.main_gui_events import get_video
        return get_video(self, bvid)

    # ── 删除监控 ──────────────────────────────

    def _remove_monitor(self):
        """删除当前选中视频的监控"""
        _remove_monitor_impl(self)

    # ── 推送 ──────────────────────────────────

    def _push_single(self, bvid):
        """推送单个视频状态到 QQ/Windows 通知

        Args:
            bvid: 视频 BV 号
        """
        _push_single_impl(self, bvid)

    def _manual_push(self):
        """手动推送所有监控视频状态"""
        _manual_push_impl(self)

    # ── 训练完成回调 ──────────────────────────

    def _on_training_completed(self, mode="训练", count=0, detail="", trained_ids=None):
        """训练/微调完成后自动刷新预测 + 推送通知 + 更新权重

        Args:
            mode: 模式名称（"训练"或"微调"）
            count: 训练完成的算法数量
            detail: 详细结果文本
            trained_ids: 已训练的算法 ID 列表
        """
        _on_training_completed_impl(self, mode, count, detail, trained_ids)

    def _update_trained_weights(self, algo_ids):
        """训练完成后提升算法 ML 权重

        Args:
            algo_ids: 算法 ID 列表
        """
        _update_trained_weights_impl(self, algo_ids)

    def _run_post_training_predict(self):
        """后台重跑所有监控视频的预测"""
        _run_post_training_predict_impl(self)

    # ── 每日推送 ──────────────────────────────

    def _schedule_daily_push(self):
        """安排每日 23:50 的自动推送"""
        _schedule_daily_push_impl(self)

    def _daily_push(self):
        """每日 23:50 自动推送日报"""
        _daily_push_impl(self)

    def _build_daily_push_msg(self):
        """构建每日日报消息文本"""
        return _build_daily_push_msg_impl(self)

    def _build_push_msg(self, videos):
        """构建手动推送消息文本

        Args:
            videos: 视频列表

        Returns:
            str: 格式化的推送消息
        """
        return _build_push_msg_impl(self, videos)

    # ── 预测结果回调 ──────────────────────────

    def _prediction_done(self, w_pred, current_view, growth, rate_per_sec, success_list, fail_list, valid, total):
        """预测完成回调：更新预测面板和状态栏

        Args:
            w_pred: 加权预测播放量
            current_view: 当前播放量
            growth: 预测增长量
            rate_per_sec: 每秒增长率
            success_list: 成功的算法列表
            fail_list: 失败的算法列表
            valid: 有效算法数
            total: 总算法数
        """
        _prediction_done_impl(self, w_pred, current_view, growth, rate_per_sec, success_list, fail_list, valid, total)

    def _copy_bvid(self, bvid):
        """复制 BV 号到剪贴板

        Args:
            bvid: 视频 BV 号
        """
        _copy_bvid_impl(self, bvid)

    # ── 弹窗透传 ──────────────────────────────

    def _open_interval_settings(self):
        """打开刷新间隔设置弹窗"""
        _open_interval_settings_impl(self)

    def _open_database_query(self):
        """打开数据库查询窗口"""
        _open_database_query_impl(self)

    def _open_video_search(self):
        """打开视频搜索窗口"""
        _open_video_search_impl(self)

    def _open_data_comparison(self):
        """打开数据对比窗口"""
        _open_data_comparison_impl(self)

    def _open_crossover_analysis(self):
        """打开交叉计算分析窗口"""
        _open_crossover_analysis_impl(self)

    def _open_weekly_score(self):
        """打开周刊分数窗口"""
        _open_weekly_score_impl(self)

    def _open_milestone_stats(self):
        """打开里程碑统计窗口"""
        _open_milestone_stats_impl(self)

    def _add_bvid_to_monitor(self, bvid: str):
        """将指定 BV 号添加到监控列表

        Args:
            bvid: B站视频 BV 号
        """
        _add_bvid_to_monitor_impl(self, bvid)

    def _import_search_results(self, videos: list):
        """导入视频搜索结果到监控列表

        Args:
            videos: 视频信息列表
        """
        _import_search_results_impl(self, videos)

    # ── 监控列表持久化 ────────────────────────

    def _load_watch_list(self):
        """从配置文件加载监控列表"""
        _load_watch_list_impl(self)

    def _restore_video(self, video):
        """从 watch_list 恢复视频到界面

        Args:
            video: 视频数据字典
        """
        _restore_video_impl(self, video)

    @staticmethod
    def _map_api_to_video_dict(bvid: str, info: dict = None, video_info=None) -> dict:
        """将 B站 API 数据或 VideoInfo 对象映射为统一的视频字典格式

        Args:
            bvid: BV 号
            info: B站 API 返回的数据
            video_info: VideoInfo 对象

        Returns:
            dict: 标准化的视频数据字典
        """
        return _map_api_to_video_dict_impl(bvid, info, video_info)

    def _register_video_to_monitor(self, video: dict) -> None:
        """注册视频到监控系统：初始化数据库 + 创建卡片 + 启动 Worker

        Args:
            video: 视频数据字典
        """
        _register_video_to_monitor_impl(self, video)

    def _save_weekly_score(self, bvid, video, timestamp):
        """保存周刊分数到数据库

        Args:
            bvid: BV 号
            video: 视频数据字典
            timestamp: 时间戳
        """
        _save_weekly_score_impl(self, bvid, video, timestamp)

    def _save_yearly_score(self, bvid, video, timestamp):
        """保存年刊分数到数据库

        Args:
            bvid: BV 号
            video: 视频数据字典
            timestamp: 时间戳
        """
        _save_yearly_score_impl(self, bvid, video, timestamp)

    def _save_watch_list(self):
        """保存监控列表到配置文件"""
        _save_watch_list_impl(self)

    def _prompt_backup_sync(self, diffs, db):
        """数据目录差异弹窗，让用户选择保留哪边的数据

        Args:
            diffs: 差异数据列表
            db: 数据库对象
        """
        _prompt_backup_sync_impl(self, diffs, db)

    def _refresh_data(self):
        """手动刷新数据"""
        _refresh_data_impl(self)

    # ── 运行 ─────────────────────────────────

    def run(self):
        """启动主循环（调用 root.mainloop()）"""
        self.root.mainloop()


def main():
    """主入口函数：创建并启动 GUI 应用"""
    app = BilibiliMonitorGUI()
    app.run()


if __name__ == "__main__":
    main()
