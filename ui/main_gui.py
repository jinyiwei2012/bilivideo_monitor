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
import customtkinter as ctk
import math
import re
import threading
import time
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

import sys

from utils import project_path as _pp
from utils.update_checker import _s

sys.path.insert(0, str(_pp()))

from ui.theme import C, init_theme
from ui.helpers import (
    FONT,
    FONT_SM,
    FONT_MONO,
    DEFAULT_INTERVAL,
    FAST_INTERVAL,
    FAST_GAP,
    THRESHOLD_NAMES,
    fmt_num,
    nearest_threshold_gap,
    fmt_eta,
    project_path,
)
from ui.chart import draw_chart_placeholder
from ui.log_panel import LogPanel
from ui.video_list_panel import VideoListPanel
from ui.detail_panel import DetailPanel
from ui.prediction_panel import PredictionPanel
from ui.bottom_bar import BottomBar
from ui.dialogs import Dialogs
from utils.time_utils import safe_timestamp
from utils.weekly_score import calculate_from_dict as _calc_ws
from utils.yearly_score import calculate_yearly_from_dict as _calc_ys
from dataclasses import asdict
from ui.monitor_service import (
    fetch_all_video_data,
    auto_predict_all,
    load_watch_list,
    _start_worker,
)
from core import bilibili_api, db, MonitorRecord, notification_manager
from config import load_config, save_config
from utils.file_logger import FileLogger
# 以下两个模块延迟到 _switch_nav 中按需加载
# from ui.training_panel import TrainingPanel
# from ui.finetune_panel import FinetunePanel


# ══════════════════════════════════════════════
# 主界面
# ══════════════════════════════════════════════
class BilibiliMonitorGUI:
    """主界面 - 深色三栏布局（精简版）"""

    DEFAULT_INTERVAL = DEFAULT_INTERVAL
    FAST_INTERVAL = FAST_INTERVAL
    THRESHOLD_GAP = FAST_GAP

    def __init__(self, root=None):
        """
        初始化主界面

        :param root: 可选的 CTk 根窗口，为 None 时自动创建
        """
        if root is None:
            root = ctk.CTk()
            from __init__ import __version__
            from utils.update_checker import _x as _z

            _s = (
                (" " + chr(100) + chr(101) + chr(118) + " " + chr(24320) + chr(21457) + chr(20013)) if _z() else ""
            )  # noqa: E225,E226
            root.title(f"B站视频监控与播放量预测系统 v{__version__}{_s}")
            # 自适应窗口：85% 屏幕尺寸，最低 55%
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
            root.geometry(f"{int(sw * 0.85)}x{int(sh * 0.85)}")
            root.minsize(int(sw * 0.50), int(sh * 0.55))

        self.root = root
        self._set_window_icon()
        init_theme(root)

        # 状态变量
        self.auto_refresh_enabled = tk.BooleanVar(value=True)
        self._global_tick_job = None
        self._video_timers = {}
        self._data_lock = threading.Lock()  # 保护 shared data（history_data, prediction_results, video_dbs）
        self._tick_counter = 0  # 用于周期性维护任务

        # 数据
        self.monitored_videos = []
        self.history_data = {}
        self.prediction_results = {}
        self.video_dbs = {}
        self.selected_bvid = None

        # 视频列表的 bvid→dict 索引，避免 O(n) 线性查找
        self._video_index = {}

        # 防抖计时器
        self._chart_debounce = None
        self._selected_debounce = None

        # UI 子模块
        self._file_logger = FileLogger(project_path("data", "log"))
        # 统一标准 logging 格式（让 stderr 输出和 FileLogger / LogPanel 一致）
        if not logging.root.handlers:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s.%(msecs)03d [%(levelname)-7s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        # 压制杂音日志：prophet 缺失 plotly 时的无用 ERROR
        logging.getLogger("prophet.plot").setLevel(logging.CRITICAL)
        logging.getLogger("prophet").setLevel(logging.WARNING)

        self.root.protocol("WM_DELETE_WINDOW", self._on_exit)
        self._build_ui()
        # 启动时自动激活所有算法的最新 checkpoint
        self.root.after(500, self._auto_activate_on_startup)
        self._load_watch_list()
        # 后台预加载算法（线程安全），避免首次预测时卡住等待扫描 103 个文件
        self._preload_algorithms()
        # 加载 OneBot 通知配置
        notification_manager.configure(load_config())
        # 安排每日 23:50 自动推送
        self._schedule_daily_push()
        self._start_auto_refresh()
        self._file_logger.start_midnight_checker(self.root)
        # 异步检查更新
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
        # 将标准 logging 桥接到 GUI 日志面板
        from ui.log_panel import install_logging_bridge

        install_logging_bridge(self.log_panel)
        self._build_main()
        # 训练面板/微调面板 — 改为按需加载（_switch_nav 中创建）
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
        self._bar = bar  # 保存引用，供子函数使用

    def _build_logo_section(self):
        """构建Logo区域 - 改进版：添加副标题"""
        bar = self._bar
        logo_f = tk.Frame(bar, bg=C["bg_surface"])
        logo_f.pack(side=tk.LEFT, padx=(14, 0))

        # Logo图标 (使用Canvas绘制简洁的B站风格图标)
        logo_canvas = tk.Canvas(logo_f, width=32, height=32, bg=C["bg_surface"], highlightthickness=0)
        logo_canvas.create_oval(4, 4, 28, 28, fill=C["bilibili"], outline="")
        logo_canvas.create_text(16, 16, text="B", fill="white", font=("Microsoft YaHei UI", 14, "bold"))
        logo_canvas.pack(side=tk.LEFT, padx=(0, 8))

        # 标题和副标题容器
        title_f = tk.Frame(logo_f, bg=C["bg_surface"])
        title_f.pack(side=tk.LEFT)

        tk.Label(
            title_f, text="B站监控", bg=C["bg_surface"], fg=C["bilibili"], font=("Microsoft YaHei UI", 13, "bold")
        ).pack(anchor="w")
        tk.Label(
            title_f, text="播放量预测系统", bg=C["bg_surface"], fg=C["text_3"], font=("Microsoft YaHei UI", 10)
        ).pack(anchor="w")

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

        # 图标
        icon_lbl = tk.Label(btn, text=icon, bg=C["bg_surface"], fg=C["text_secondary"], font=("Microsoft YaHei UI", 12))
        icon_lbl.pack(side=tk.LEFT, padx=(8, 4))

        # 文本
        text_lbl = tk.Label(btn, text=label, bg=C["bg_surface"], fg=C["text_secondary"], font=FONT)
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
        icon_lbl.bind("<Button-1>", on_click)
        text_lbl.bind("<Button-1>", on_click)

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

        # 模型激活按钮（放在最左侧）
        self._build_model_activation(right_f)

        # 创建图标按钮
        self._gear_btn = self._create_icon_button(right_f, "⚙️", self._popup_settings_menu, "设置")
        self._create_icon_button(right_f, "🔍", self._dialogs.open_video_search, "搜索")
        self._create_countdown_badge(right_f)
        self._create_mode_pill(right_f)

    def _create_settings_menu(self):
        """创建设置下拉菜单"""
        self._settings_menu = tk.Menu(
            self.root,
            tearoff=0,
            bg=C["bg_elevated"],
            fg=C["text_1"],
            activebackground=C["bg_hover"],
            activeforeground=C["text_1"],
            font=FONT,
            bd=0,
            relief="flat",
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
        self._settings_menu.add_command(label="🗄  数据库查询", command=self._dialogs.open_database_query, state=_s())
        self._settings_menu.add_command(label="⚙️  系统设置", command=self._dialogs.open_settings, state=_s())

    def _create_icon_button(self, parent, icon, command, tooltip=None):
        """创建图标按钮（可复用）"""
        btn = tk.Label(
            parent,
            text=icon,
            bg=C["bg_elevated"],
            fg=C["text_2"],
            font=("Microsoft YaHei UI", 11),
            cursor="hand2",
            padx=6,
            pady=2,
            relief="flat",
        )
        btn.pack(side=tk.RIGHT, padx=2)
        if callable(command):
            btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e, b=btn: b.config(bg=C["bg_hover"], fg=C["text_1"]))
        btn.bind("<Leave>", lambda e, b=btn: b.config(bg=C["bg_elevated"], fg=C["text_2"]))
        if tooltip:
            pass  # 可选：添加工具提示
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
            f,
            text="🧠 激活模型",
            bg=C["bg_elevated"],
            fg=C["accent"],
            font=FONT,
            cursor="hand2",
            padx=6,
            pady=2,
            relief="flat",
        )
        self._model_act_btn.pack(side=tk.RIGHT, padx=2)
        self._model_act_btn.bind("<Button-1>", lambda e: self._on_activate_models())
        self._model_act_btn.bind("<Enter>", lambda e: self._model_act_btn.config(bg=C["bg_hover"]))
        self._model_act_btn.bind("<Leave>", lambda e: self._model_act_btn.config(bg=C["bg_elevated"]))

        self._model_act_status = tk.Label(
            f,
            text="",
            bg=C["bg_surface"],
            fg=C["text_3"],
            font=("Microsoft YaHei UI", 9),
        )
        self._model_act_status.pack(side=tk.RIGHT, padx=2)

    def _refresh_model_status(self):
        """刷新模型激活状态显示"""
        try:
            from algorithms.training.checkpoint_manager import get_all_activation_status
            status = get_all_activation_status()
            pending = [aid for aid, s in status.items() if s["needs_activation"]]
            trained = len(status)
        except Exception:
            self._model_act_status.config(text="")
            return
        if pending:
            self._model_act_status.config(
                text=f"⚡ {len(pending)}/{trained} 待激活",
                fg=C["danger"],
            )
            self._model_act_btn.config(fg=C["accent"])
        elif trained > 0:
            self._model_act_status.config(
                text=f"✓ {trained} 个已最新",
                fg=C["success"],
            )
            self._model_act_btn.config(fg=C["text_3"])
        else:
            self._model_act_status.config(text="")
            self._model_act_btn.config(fg=C["text_3"])

    def _on_activate_models(self):
        """手动激活所有算法的最新 checkpoint"""
        from algorithms.training.checkpoint_manager import activate_latest_for_all
        switched = activate_latest_for_all()
        if not switched:
            self._sb("status", "所有模型已是最新版本", C["success"])
            self._refresh_model_status()
            return
        names = ", ".join(switched.keys())
        self._sb("status", f"已激活 {len(switched)} 个模型: {names}", C["success"])
        self._refresh_model_status()
        self.log_panel.add_log("INFO", f"手动激活模型: {switched}")

    def _auto_activate_on_startup(self):
        """启动时自动激活所有算法的最新 checkpoint（后台线程，避免 torch 导入阻塞主线程）"""
        def _worker():
            try:
                from algorithms.training.checkpoint_manager import activate_latest_for_all
                switched = activate_latest_for_all()
                if switched:
                    names = ", ".join(switched.keys())
                    self.root.after(0, lambda: self.log_panel.add_log("INFO", f"启动自动激活模型: {switched}"))
                    self.root.after(0, lambda: self._sb("status", f"自动激活 {len(switched)} 个模型: {names}", C["success"]))
                self.root.after(0, self._refresh_model_status)
            except Exception as e:
                logger.debug("自动激活模型失败: %s", e)
                self.root.after(0, self._refresh_model_status)
        threading.Thread(target=_worker, daemon=True, name="auto-activate").start()

    def _preload_algorithms(self):
        """后台线程预加载 AlgorithmRegistry，避免首次预测时等待 8s 扫描"""
        def _worker():
            from algorithms.registry import AlgorithmRegistry
            AlgorithmRegistry.initialize()
            n = len(AlgorithmRegistry.get_algorithm_names())
            logger.info("后台算法预加载完成，共 %d 个算法", n)
        threading.Thread(target=_worker, daemon=True, name="algo-preload").start()

    def _build_main(self):
        """构建主体三栏布局"""
        self._main_frame = tk.Frame(self.root, bg=C["bg_base"])
        self._main_frame.pack(fill=tk.BOTH, expand=True)

        main = tk.Frame(self._main_frame, bg=C["bg_base"])
        main.pack(fill=tk.BOTH, expand=True)

        # 自适应比例布局：左 22% | 分隔线 | 中 58% | 分隔线 | 右 20%
        main.grid_columnconfigure(0, weight=22, minsize=220)
        main.grid_columnconfigure(1, weight=0)  # 分隔线
        main.grid_columnconfigure(2, weight=58, minsize=360)
        main.grid_columnconfigure(3, weight=0)  # 分隔线
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
    # 状态栏（BottomBar 已构建，此处仅供外部引用）
    # ──────────────────────────────────────────

    def _build_status_bar(self):
        pass  # 已由 BottomBar 构建

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
        # 隐藏所有面板
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

    # ──────────────────────────────────────────

    def _get_video_interval(self, video):
        """根据视频播放量确定刷新间隔（接近阈值时使用快速模式）"""
        views = video.get("view_count", 0)
        gap, _ = nearest_threshold_gap(views)
        if 0 < gap < self.THRESHOLD_GAP:
            return self.FAST_INTERVAL
        return self.DEFAULT_INTERVAL

    def _register_video_timer(self, bvid):
        """注册视频定时器"""
        video = self._get_video(bvid)
        if not video:
            return
        interval = self._get_video_interval(video)
        self._video_timers[bvid] = {"next": time.time() + interval, "interval": interval}

    def _start_auto_refresh(self):
        """启动自动刷新"""
        if self.auto_refresh_enabled.get():
            self._start_global_tick()

    def _start_global_tick(self):
        """启动全局 tick 循环"""
        if self._global_tick_job:
            self.root.after_cancel(self._global_tick_job)
        self._global_tick_job = self.root.after(1000, self._global_tick)

    def _stop_global_tick(self):
        """停止全局 tick 循环"""
        if self._global_tick_job:
            self.root.after_cancel(self._global_tick_job)
            self._global_tick_job = None

    def _global_tick(self):
        """每秒一次的全局 tick：更新倒计时、模式指示、周期性维护"""
        try:
            if not self.auto_refresh_enabled.get():
                self._global_tick_job = None
                return

            now = time.time()
            fast_count = 0
            min_remaining = float("inf")

            # 计算最小剩余时间和快速模式数量
            for bvid, timer in list(self._video_timers.items()):
                remaining = timer["next"] - now
                if timer["interval"] == self.FAST_INTERVAL:
                    fast_count += 1
                if remaining < min_remaining:
                    min_remaining = remaining

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

            # 每300 tick（≈5min）执行一次数据库WAL checkpoint，控制WAL文件膨胀
            self._tick_counter = (self._tick_counter + 1) % 3600
            if self._tick_counter == 0:
                self._do_periodic_sync()
            elif self._tick_counter % 300 == 0:
                threading.Thread(target=self._wal_checkpoint_worker, daemon=True).start()
                threading.Thread(target=self._scan_alerts_background, daemon=True).start()
        except Exception:
            logger.exception("_global_tick 异常，继续调度")
        self._global_tick_job = self.root.after(1000, self._global_tick)

    def _do_periodic_sync(self):
        """每小时执行一次数据库同步（不阻塞主线程）"""
        logger.info("开始每小时数据同步…")
        import threading as _th

        def _sync_worker():
            try:
                for bvid in list(self.video_dbs.keys()):
                    try:
                        db.sync_from_video_db(bvid)
                    except Exception as e:
                        logger.debug("同步视频库 %s 失败: %s", bvid, e)
                result = db.sync_to_central()
                logger.info(
                    "每小时同步完成: %d视频 %d记录 %d瑕疵",
                    result.get("synced_videos", 0),
                    result.get("synced_records", 0),
                    result.get("fixed_flaws", 0),
                )
                try:
                    db.sync_per_video_dbs_to_backup()
                except Exception as e:
                    logger.debug("忽略异常: %s", e)
            except Exception as e:
                logger.warning("每小时同步异常: %s", e)

        _th.Thread(target=_sync_worker, daemon=True).start()

    def _scan_alerts_background(self):
        """后台扫描全量视频的异常，更新状态栏 + 推送通知"""
        from core.smart_alert import AnomalyDetector
        from core.notification import notification_manager

        alerts = []
        for video in self.monitored_videos:
            bvid = video.get("bvid", "")
            records = []
            try:
                video_db = self.video_dbs.get(bvid)
                if video_db:
                    raw = video_db.get_all_records(limit=20)
                    for r in raw:
                        records.append({
                            "timestamp": r["timestamp"],
                            "view_count": r["view_count"],
                            "like_count": r.get("like_count", 0),
                            "coin_count": r.get("coin_count", 0),
                            "viewers_total": r.get("viewers_total", 0),
                        })
            except Exception as e:
                logger.debug("从DB获取记录失败 %s: %s", bvid, e)
            if len(records) < 3:
                continue
            try:
                for msg in AnomalyDetector.detect_all(records, bvid=bvid, video=video):
                    alerts.append((bvid, video.get("title", bvid)[:20], msg))
            except Exception as e:
                logger.debug("忽略异常: %s", e)

        if alerts:
            n = len(alerts)
            self.root.after(0, lambda: self._sb("alert", f"🚨 {n} 条异常", C["danger"]))
            # 推送通知
            title = f"🚨 B站监控异常告警 ({n} 条)"
            msg_lines = [title, "─" * 20]
            for bvid, t, a in alerts[:5]:
                msg_lines.append(f"  [{bvid}] {t}")
                msg_lines.append(f"    {a}")
            if n > 5:
                msg_lines.append(f"  … 还有 {n - 5} 条")
            msg = "\n".join(msg_lines)
            try:
                notification_manager.send_qq_private(msg)
                notification_manager.send_qq_group(msg)
                notification_manager.send_windows_notification(title, msg[:256])
                self.log_panel.add_log("INFO", f"异常告警已推送 ({n} 条)")
            except Exception as e:
                logger.debug("推送异常告警失败: %s", e)
        else:
            self.root.after(0, lambda: self._sb("alert", ""))

    def _wal_checkpoint_worker(self):
        """后台线程执行 WAL checkpoint，避免阻塞主线程"""
        try:
            db.wal_checkpoint()
            for vdb in list(self.video_dbs.values()):
                try:
                    with vdb._get_connection() as conn:
                        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception as e:
                    logger.debug("忽略异常: %s", e)
        except Exception as e:
            logger.debug("忽略异常: %s", e)

    def _toggle_auto_refresh(self, event=None):
        """切换自动刷新开关"""
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
        """执行数据拉取"""
        fetch_all_video_data(self)

    def _post_fetch(self):
        """拉取完成后的回调处理"""
        now_str = datetime.now().strftime("%H:%M:%S")
        self._sb("status", "刷新完成", C["success"])
        self._sb("last_ref", f"上次刷新: {now_str}")
        self._sb("videos", f"监控: {len(self.monitored_videos)} 个")
        # 更新所有卡片
        for video in self.monitored_videos:
            bvid = video.get("bvid", "")
            if bvid in self.video_list.get_card_widgets():
                self.video_list.update_card(video)
        # 更新选中视频的详情
        if self.selected_bvid:
            video = self._get_video(self.selected_bvid)
            if video:
                self.detail.update_stat_bar(video)
                if self.detail.current_tab == "📈 播放量趋势":
                    self.detail._auto_render_chart()
        # 重新注册定时器
        for video in self.monitored_videos:
            self._register_video_timer(video.get("bvid", ""))
        auto_predict_all(self)

    def _show_video_detail(self, video):
        """显示视频详情"""
        self.detail._build_center_header(video)
        self.detail._rebuild_stat_bar(video)
        self.detail._switch_tab(self.detail.current_tab)

    def _select_video(self, bvid):
        """选中视频"""
        self.selected_bvid = bvid
        self.video_list.highlight_card(bvid)
        video = self._get_video(bvid)
        if video:
            self._show_video_detail(video)
        # 更新预测面板（如有缓存结果）
        cached = self.prediction_results.get(bvid)
        if cached:
            self.prediction._build_pred_hero(
                cached["prediction"], cached["current_view"], cached.get("rate_per_sec", 0)
            )
            self.prediction._update_algo_list(
                cached.get("success_list", []), cached.get("fail_list", [])
            )

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
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        dialog.geometry(f"{int(sw * 0.28)}x{int(sh * 0.22)}")
        dialog.configure(bg=C["bg_surface"])
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(True, True)
        return dialog

    def _build_add_dialog_ui(self, dialog):
        """构建对话框UI元素"""
        content = tk.Frame(dialog, bg=C["bg_surface"])
        content.pack(fill=tk.BOTH, expand=True)

        tk.Label(content, text="请输入BV号或视频链接：", bg=C["bg_surface"], fg=C["text_1"], font=FONT).pack(
            pady=(18, 4)
        )

        entry_f = tk.Frame(
            content,
            bg=C["bg_elevated"],
            highlightthickness=1,
            highlightbackground=C["border"],
            highlightcolor=C["bilibili"],
        )
        entry_f.pack(padx=24, fill=tk.X)
        entry = tk.Entry(
            entry_f, bg=C["bg_elevated"], fg=C["text_1"], insertbackground=C["text_1"], relief="flat", font=FONT, bd=0
        )
        entry.pack(fill=tk.X, padx=8, pady=6)
        entry.focus_set()
        tk.Label(content, text="格式：BV1xxx 或完整链接", bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM).pack()
        status_lbl = tk.Label(content, text="", bg=C["bg_surface"], fg=C["accent"], font=FONT_SM)
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
            m = re.search(r"BV[\w]+", raw_input)  # noqa: F821
            if m:
                bvid = m.group()
            else:
                messagebox.showerror("错误", "无法从链接中提取BV号", parent=self.root)
                return None
        return bvid

    def _check_video_in_monitor_list(self, bvid, dialog):
        """检查视频是否已在监控列表"""
        if bvid in self._video_index:
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
            messagebox.showinfo(
                "成功",
                f"已添加监控\n标题：{video['title'][:40]}\nUP主：{video['author']}\n播放：{fmt_num(video['view_count'])}",
                parent=dialog,
            )
            dialog.destroy()

        threading.Thread(target=_fetch, daemon=True).start()

    def _get_video(self, bvid):
        """O(1) 按 bvid 查找视频对象。"""
        return self._video_index.get(bvid)

    def _remove_monitor(self):
        """删除当前选中视频的监控"""
        if not self.selected_bvid:
            messagebox.showwarning("提示", "请先在左侧选择要删除的视频")
            return
        bvid = self.selected_bvid
        video = self._get_video(bvid)
        title = video.get("title", bvid) if video else bvid
        if not messagebox.askyesno("确认删除", f"确定要删除监控：\n{title[:50]}？"):
            return
        # 清理所有相关数据
        self.monitored_videos = [v for v in self.monitored_videos if v.get("bvid") != bvid]
        self._video_index.pop(bvid, None)
        self.history_data.pop(bvid, None)
        vdb = self.video_dbs.pop(bvid, None)
        if vdb:
            try:
                vdb.close()
            except Exception as e:
                logger.debug("忽略异常: %s", e)
        self.prediction_results.pop(bvid, None)
        self._video_timers.pop(bvid, None)
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

    def _push_single(self, bvid):
        """推送单个视频状态"""
        from core.notification import notification_manager

        video = self._get_video(bvid)
        if not video:
            messagebox.showwarning("提示", f"未找到视频 {bvid}")
            return

        msg = self._build_push_msg([video])
        title = video.get("title", bvid)[:30]

        notification_manager.send_qq_private(msg)
        notification_manager.send_qq_group(msg)
        notification_manager.send_windows_notification(f"📊 B站监控 — {title[:20]}", msg[:256])
        self._sb("status", f"已推送「{title[:20]}」", C["success"])

    def _manual_push(self):
        """手动推送所有监控视频状态到 QQ/Windows 通知"""
        from core.notification import notification_manager

        videos = self.monitored_videos
        if not videos:
            messagebox.showwarning("提示", "没有监控中的视频可推送")
            return

        msg = self._build_push_msg(videos)
        now_str = datetime.now().strftime("%H:%M")

        ok_qq_private = notification_manager.send_qq_private(msg)
        ok_qq_group = notification_manager.send_qq_group(msg)
        ok_win = notification_manager.send_windows_notification(f"📊 B站监控报告 ({now_str})", msg[:256])

        if ok_qq_private or ok_qq_group:
            self._sb("status", f"已推送 {len(videos)} 个视频状态", C["success"])
        elif ok_win:
            self._sb("status", "仅发送了 Windows 通知", C["warning"])
        else:
            self._sb("status", "推送失败 (未配置 QQ / 通知服务不可用)", C["danger"])

    # ── 每日 23:50 定时推送 ─────────────────────────

    # ── 训练完成自动回调 ──────────────────────────

    def _on_training_completed(self, mode="训练", count=0, detail="", trained_ids=None):
        """训练/微调完成后自动刷新预测 + 推送通知 + 更新权重"""
        # 1. 推送通知
        try:
            from core.notification import notification_manager

            now_str = datetime.now().strftime("%H:%M")
            if count > 0 and detail:
                msg = f"🤖 {mode}完成 ({now_str})\n{count} 个算法: {detail}"
            elif count > 0:
                msg = f"🤖 {mode}完成 ({now_str})\n共 {count} 个算法已更新"
            else:
                msg = f"🤖 {mode}完成 ({now_str})"
            notification_manager.send_qq_private(msg)
            notification_manager.send_qq_group(msg)
            notification_manager.send_windows_notification(f"🤖 {mode}完成", msg[:256])
        except Exception as e:
            logger.debug("训练推送异常: %s", e)

        # 2. 更新训练完成算法的权重（提升置信度）
        if trained_ids:
            try:
                self._update_trained_weights(trained_ids)
            except Exception as e:
                logger.debug("更新训练算法权重失败: %s", e)

        # 3. 后台重新预测所有视频
        try:
            threading.Thread(target=self._run_post_training_predict, daemon=True).start()
        except Exception as e:
            logger.debug("启动训练后预测失败: %s", e)

    def _update_trained_weights(self, algo_ids):
        """训练完成后提升算法 ML 权重"""
        from algorithms.registry import AlgorithmRegistry
        from ui.helpers import load_algo_confidence

        for algo_id in algo_ids:
            conf = load_algo_confidence(algo_id)
            accuracy = max(0.5, conf)  # 训练后至少 0.5，避免拉低加权
            AlgorithmRegistry.update_accuracy(algo_id, 1.0, accuracy)
        logger.info("已更新 %d 个训练完成算法的权重", len(algo_ids))

    def _run_post_training_predict(self):
        """后台重跑所有监控视频的预测"""
        from ui.monitor_service import _predict_single

        bvids = [v.get("bvid", "") for v in self.monitored_videos if v.get("bvid")]
        if not bvids:
            return
        logger.info("训练完成，开始重新预测 %d 个视频…", len(bvids))
        for bvid in bvids:
            video = next((v for v in self.monitored_videos if v.get("bvid") == bvid), None)
            if not video:
                continue
            try:
                _predict_single(self, bvid, video)
            except Exception as e:
                logger.debug("训练后预测 %s 失败: %s", bvid, e)
        trained = sum(1 for _ in self.monitored_videos)
        self.root.after(0, lambda: self._sb("status", f"训练后预测完成 ({trained} 个视频)", C["success"]))
        # 若当前有选中视频，刷新其预测面板 + 图表
        if self.selected_bvid:
            if self.selected_bvid in self.prediction_results:
                r = self.prediction_results[self.selected_bvid]
                self.root.after(
                    0,
                    lambda: self._prediction_done(
                        r["prediction"],
                        r["current_view"],
                        r["growth"],
                        r["rate_per_sec"],
                        r.get("success_list", []),
                        r.get("fail_list", []),
                        r["valid"],
                        r["total"],
                    ),
                )
            # 强制刷新图表（预测线已更新）
            self.root.after(100, lambda: self.detail._manual_render_chart())
        logger.info("训练后预测完成 (%d 个视频)", len(bvids))

    def _schedule_daily_push(self):
        """计算到下次 23:50 的秒数，用 root.after 排程"""
        from datetime import timedelta

        now = datetime.now()
        target = now.replace(hour=23, minute=50, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        delay_ms = int((target - now).total_seconds() * 1000)
        self.root.after(delay_ms, self._daily_push)
        logger.info("已安排每日推送: %s", target.strftime("%Y-%m-%d %H:%M"))

    def _check_update(self):
        """异步检查 GitHub Release 更新，含 changelog 展示"""
        from utils.update_checker import check_for_update_async

        def _on_result(has_update, latest, url, changelog, channel):
            if has_update and latest:
                from __init__ import __version__

                self.root.after(
                    0, lambda: self._sb("status", f"发现新版本 v{latest} (当前 v{__version__})", C["warning"])
                )
                logger.info("有新版本可用: v%s (当前 v%s), %s", latest, __version__, url)
                self.root.after(0, lambda: self._show_update_dialog(latest, __version__, url, changelog, channel))

        check_for_update_async(_on_result)

    def _show_update_dialog(self, latest, current, url, changelog, channel="stable"):
        """显示更新弹窗（含 changelog），根据运行模式提供不同更新方式"""
        from utils.update_checker import (
            format_changelog_for_display,
            is_frozen,
            perform_source_git_pull,
            perform_source_download_zip,
            perform_exe_self_update,
            get_update_channel,
        )

        is_beta = channel == "beta"
        git_branch = "pre-release" if is_beta else "releases"
        dlg = tk.Toplevel(self.root)
        dlg.title("发现新版本")
        dlg.configure(bg=C["bg_base"])
        dlg.resizable(True, True)
        dlg.geometry("640x580")
        dlg.transient(self.root)
        dlg.grab_set()

        # 标题
        mode_label = "打包版" if is_frozen() else "源码版"
        channel_label = "测试版" if is_beta else "稳定版"
        tk.Label(
            dlg,
            text=f"新版本 v{latest} 可用 ({mode_label} · {channel_label})",
            font=("Microsoft YaHei UI", 14, "bold"),
            bg=C["bg_base"],
            fg=C["text_1"],
        ).pack(pady=(16, 4))
        tk.Label(
            dlg, text=f"当前版本: v{current}", font=("Microsoft YaHei UI", 10), bg=C["bg_base"], fg=C["text_3"]
        ).pack(pady=(0, 12))

        # 测试版警告
        if is_beta:
            warn_frame = tk.Frame(dlg, bg="#3b1f1f", highlightthickness=1, highlightbackground="#ff4444")
            warn_frame.pack(fill=tk.X, padx=16, pady=(0, 8))
            tk.Label(
                warn_frame,
                text="⚠ 测试版警告",
                font=("Microsoft YaHei UI", 10, "bold"),
                bg="#3b1f1f",
                fg="#ff6666",
            ).pack(anchor="w", padx=8, pady=(4, 0))
            tk.Label(
                warn_frame,
                text="当前为测试版更新通道，可能存在不稳定或未完成的功能。\n建议在非生产环境中使用。",
                font=("Microsoft YaHei UI", 9),
                bg="#3b1f1f",
                fg="#ff9999",
                justify=tk.LEFT,
            ).pack(anchor="w", padx=8, pady=(0, 4))

        # Changelog 区域
        frame = tk.Frame(dlg, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))

        tk.Label(
            frame, text="更新内容", font=("Microsoft YaHei UI", 10, "bold"), bg=C["bg_elevated"], fg=C["text_2"]
        ).pack(anchor="w", padx=8, pady=(8, 4))

        text = tk.Text(
            frame,
            wrap=tk.WORD,
            font=("Consolas", 9),
            bg=C["bg_surface"],
            fg=C["text_1"],
            relief=tk.FLAT,
            borderwidth=0,
            padx=8,
            pady=8,
        )
        text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        text.insert("1.0", format_changelog_for_display(changelog))
        text.config(state=tk.DISABLED)

        scroll = tk.Scrollbar(text, command=text.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text.config(yscrollcommand=scroll.set)

        # ── 更新通道切换 ────────────────────────────
        channel_frame = tk.Frame(dlg, bg=C["bg_base"])
        channel_frame.pack(fill=tk.X, padx=16, pady=(0, 8))
        tk.Label(
            channel_frame,
            text="更新通道:",
            font=("Microsoft YaHei UI", 9),
            bg=C["bg_base"],
            fg=C["text_3"],
        ).pack(side=tk.LEFT, padx=(0, 8))

        current_channel = get_update_channel()
        channel_var = tk.StringVar(value=current_channel)
        self._channel_var_ref = channel_var  # keep reference
        stable_rb = ttk.Radiobutton(
            channel_frame,
            text="稳定版 (推荐)",
            variable=channel_var,
            value="stable",
            command=lambda: self._on_channel_switch(channel_var.get(), dlg),
        )
        stable_rb.pack(side=tk.LEFT, padx=(0, 8))
        beta_rb = ttk.Radiobutton(
            channel_frame,
            text="测试版",
            variable=channel_var,
            value="beta",
            command=lambda: self._on_channel_switch(channel_var.get(), dlg),
        )
        beta_rb.pack(side=tk.LEFT)

        # ── 底部按钮 ─────────────────────────────────
        btn_frame = tk.Frame(dlg, bg=C["bg_base"])
        btn_frame.pack(fill=tk.X, padx=16, pady=(0, 16))

        if is_frozen() and is_beta:
            # 打包版 + 测试通道：暂不提供 EXE
            tk.Label(
                btn_frame,
                text="测试版暂不提供 EXE 下载，请切换到稳定版通道。\n也可以使用源码版通过 Git/ZIP 更新。",
                font=("Microsoft YaHei UI", 9),
                bg=C["bg_base"],
                fg=C["warning"],
                justify=tk.CENTER,
            ).pack(side=tk.TOP, pady=(0, 8))
            ttk.Button(btn_frame, text="知道了", command=dlg.destroy).pack(side=tk.RIGHT)
        elif is_frozen():

            def _download_exe():
                dlg.destroy()
                self._show_download_progress("正在下载新版本…", perform_exe_self_update)

            ttk.Button(
                btn_frame,
                text="⬇ aria2 下载更新",
                command=_download_exe,
            ).pack(side=tk.RIGHT, padx=(8, 0))
            ttk.Button(btn_frame, text="稍后提醒", command=dlg.destroy).pack(side=tk.RIGHT)
        else:

            def _download_zip():
                dlg.destroy()
                self._show_download_progress("正在下载最新源码…", perform_source_download_zip)

            def _on_git_pull():
                ok, msg = perform_source_git_pull(branch=git_branch)
                if ok:
                    self.log_panel.add_log("INFO", "git pull 更新成功")
                    self._sb("status", "git pull 更新成功，建议重启应用", C["success"])
                else:
                    self.log_panel.add_log("ERROR", f"git pull 失败: {msg}")
                    self._sb("status", "git pull 失败，请手动更新", C["danger"])
                dlg.destroy()

            ttk.Button(
                btn_frame,
                text="📥 Git Pull 自动拉取",
                command=_on_git_pull,
            ).pack(side=tk.RIGHT, padx=(8, 0))
            ttk.Button(
                btn_frame,
                text="⬇ aria2 下载 ZIP",
                command=_download_zip,
            ).pack(side=tk.RIGHT, padx=(8, 0))
            ttk.Button(btn_frame, text="稍后提醒", command=dlg.destroy).pack(side=tk.RIGHT)

    def _on_channel_switch(self, new_channel, dlg):
        """切换更新通道"""
        from utils.update_checker import set_update_channel

        set_update_channel(new_channel)
        dlg.destroy()
        self._sb(
            "status", f"已切换到 {'稳定版' if new_channel == 'stable' else '测试版'} 通道，重新检查更新…", C.get("text_2", "#8b949e")
        )
        self.root.after(500, self._check_update)

    def _show_download_progress(self, title, download_fn):
        """显示 aria2 下载进度窗口"""
        from utils.update_checker import is_frozen

        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(bg=C["bg_base"])
        win.geometry("400x150")
        win.transient(self.root)
        win.grab_set()

        tk.Label(win, text=title, bg=C["bg_base"], fg=C["text_1"], font=("Microsoft YaHei UI", 12)).pack(pady=(16, 8))

        progress = ttk.Progressbar(win, mode="determinate", length=320)
        progress.pack(pady=8)

        status_lbl = tk.Label(win, text="准备中…", bg=C["bg_base"], fg=C["text_3"], font=("Microsoft YaHei UI", 9))
        status_lbl.pack(pady=4)

        def on_progress(downloaded, total):
            if total > 0:
                pct = min(100, int(downloaded / total * 100))
                progress["value"] = pct
                from ui.helpers import fmt_num

                status_lbl.config(text=f"已下载 {fmt_num(downloaded)} / {fmt_num(total)}")
            else:
                status_lbl.config(text="已下载…")

        def on_done(success, msg):
            win.destroy()
            if success:
                self._sb("status", "下载完成", C["success"])
                self.log_panel.add_log("INFO", f"下载完成: {title}")
                if is_frozen() and "更新" in title:
                    messagebox.showinfo("更新", "下载完成，程序将自动重启以完成更新", parent=self.root)
            else:
                self._sb("status", f"下载失败: {msg}", C["danger"])
                self.log_panel.add_log("ERROR", f"下载失败: {msg}")

        threading.Thread(
            target=download_fn,
            args=(on_progress, on_done),
            daemon=True,
        ).start()

    def _daily_push(self):
        """每日 23:50 自动推送日报"""
        from core.notification import notification_manager

        try:
            msg = self._build_daily_push_msg()
            notification_manager.send_qq_private(msg)
            notification_manager.send_qq_group(msg)
            notification_manager.send_windows_notification("📊 B站监控日报", msg[:256])
            logger.info("每日推送完成")
        except Exception as e:
            logger.error("每日推送异常: %s", e)
        finally:
            self._schedule_daily_push()

    def _build_daily_push_msg(self):
        """构建每日日报消息：日增量 + 年刊分数 + 预测"""
        from datetime import date

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        today = date.today()
        lines = [f"📊 B站监控日报 ({now_str})", f"监控 {len(self.monitored_videos)} 个视频：", "─" * 30]

        for i, v in enumerate(self.monitored_videos, 1):
            bvid = v.get("bvid", "")
            title = v.get("title", bvid)[:30]
            views = v.get("view_count", 0)
            likes = v.get("like_count", 0)
            coins = v.get("coin_count", 0)

            # 今日播放增量
            history = self.history_data.get(bvid, [])
            daily_incr = 0
            first_today = None
            for ts, vc in history:
                try:
                    if isinstance(ts, str):
                        ts = datetime.fromisoformat(ts)
                    if ts.date() == today:
                        if first_today is None:
                            first_today = vc
                        daily_incr = max(0, vc - first_today)
                except Exception as e:
                    logger.debug("忽略异常: %s", e)

            # 年刊分数
            ys_text = "—"
            try:
                ys = _calc_ys(v)
                if ys:
                    ys_text = f"{ys.total_score:,.0f}"
            except Exception as e:
                logger.debug("忽略异常: %s", e)

            # 预测
            pred_info = ""
            cached = self.prediction_results.get(bvid)
            if cached:
                w_pred = cached.get("prediction", 0)
                growth = cached.get("growth", 0)
                valid = cached.get("valid", 0)
                total = cached.get("total", 0)
                if w_pred > 0:
                    pred_info = f"  预测: {fmt_num(int(w_pred))} (+{fmt_num(int(growth))})  有效: {valid}/{total}"

            lines.append(f"\n{i}. 《{title}》")
            lines.append(f"   播放: {fmt_num(views)}  (+{fmt_num(daily_incr)} 今天)")
            lines.append(f"   👍 {fmt_num(likes)}  🪙 {fmt_num(coins)}")
            lines.append(f"   年刊: {ys_text}{pred_info}")

        return "\n".join(lines)

    # ── 推送消息构建（手动/单条共用） ────────────────

    def _build_push_msg(self, videos):
        """构建手动推送消息文本（含年刊分数 + 算法预测时间）"""
        from datetime import datetime

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [f"📊 B站监控报告 ({now_str})", f"监控 {len(videos)} 个视频：", "─" * 20]

        for i, v in enumerate(videos, 1):
            bvid = v.get("bvid", "?")
            title = v.get("title", bvid)[:30]
            views = v.get("view_count", 0)
            likes = v.get("like_count", 0)
            coins = v.get("coin_count", 0)

            # 年刊分数
            ys_text = ""
            try:
                ys = _calc_ys(v)
                if ys:
                    ys_text = f"  年刊: {ys.total_score:,.0f}"
            except Exception as e:
                logger.debug("忽略异常: %s", e)

            # 速度 + 预计到达阈值时间
            history = self.history_data.get(bvid, [])
            velocity = 0
            if len(history) >= 2:
                t1, c1 = history[-2]
                t0, c0 = history[-1]
                t0 = safe_timestamp(t0)
                t1 = safe_timestamp(t1)
                dt = (t0 - t1) / 3600
                if dt > 0:
                    velocity = max(0, (c0 - c1)) / dt if isinstance(c0, (int, float)) else 0

            gap, idx = nearest_threshold_gap(views)
            eta = ""
            if gap > 0 and velocity > 0:
                eta_min = gap / velocity * 60
                eta = f"  预计达{THRESHOLD_NAMES[idx]}: {fmt_eta(eta_min)}"

            # 算法预测时间（取置信度最高的 3 个）
            algo_lines = []
            cached = self.prediction_results.get(bvid)
            if cached:
                succ = cached.get("success_list", [])
                # success_list: (name, prediction, weight, confidence, predicted_hours)
                sorted_algos = sorted(succ, key=lambda x: x[3], reverse=True)[:3]
                for name, pv, _, conf, ph in sorted_algos:
                    if ph > 0:
                        eta_str = fmt_eta(ph * 60)
                        conf_pct = f"{conf * 100:.0f}%" if conf > 0 else "—"
                        algo_lines.append(f"     {name}: {fmt_num(int(pv))} ({eta_str}, {conf_pct})")

            lines.append(f"{i}. 《{title}》")
            lines.append(f"   播放: {fmt_num(views)}  |  👍 {fmt_num(likes)}  |  🪙 {fmt_num(coins)}")
            lines.append(f"   增速: {math.ceil(velocity)}/h{eta}{ys_text}")
            if algo_lines:
                lines.extend(algo_lines)

        return "\n".join(lines)

    def _prompt_backup_sync(self, diffs, db):
        """数据目录差异弹窗，让用户选择保留哪边的数据"""
        msg = [f"检测到 {len(diffs)} 个视频在 core/data/ 与 data/ 中存在数据差异：", ""]
        for d in diffs[:10]:
            dir_label = "主库更多" if d["primary_records"] > d["backup_records"] else "备份更多"
            msg.append(
                f"  {d['bvid']}: core/data/={d['primary_records']}条  data/={d['backup_records']}条 ({dir_label})"
            )
        if len(diffs) > 10:
            msg.append(f"  ... 等 {len(diffs)} 个")
        msg.append("")
        msg.append("是否将 core/data/ 的数据同步到 data/？")
        choice = messagebox.askyesno(
            "数据库差异检测",
            "\n".join(msg),
            icon="warning",
            parent=self.root,
        )
        if choice:
            db.sync_per_video_dbs_to_backup()
            self.log_panel.add_log("INFO", f"已同步 {len(diffs)} 个视频独立库到 data/")
        else:
            self.log_panel.add_log("INFO", "用户跳过数据同步")

    def _refresh_data(self):
        """手动刷新数据"""
        self._do_fetch()

    # ── 预测结果回调 ─────────────────────────────

    def _prediction_done(self, w_pred, current_view, growth, rate_per_sec, success_list, fail_list, valid, total):
        """预测完成回调：更新预测面板和状态栏"""
        self.prediction._build_pred_hero(w_pred, current_view, rate_per_sec)
        self.prediction._update_algo_list(success_list, fail_list)
        self._sb("algo", f"算法: {valid}/{total}")
        self._sb("status", "预测完成", C["success"])

    def _copy_bvid(self, bvid):
        """复制 BV 号到剪贴板"""
        self.root.clipboard_clear()
        self.root.clipboard_append(bvid)
        self._sb("status", f"已复制 {bvid}", C["success"])

    # ── 设置窗口（透传 Dialogs）────────────────

    def _open_interval_settings(self):
        self._dialogs.open_interval_settings()

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

    def _import_search_results(self, videos: list):
        self._dialogs.import_search_results(videos)

    # ── 监控列表持久化 ─────────────────────────────

    def _load_watch_list(self):
        load_watch_list(self)

    def _restore_video(self, video):
        """从 watch_list 恢复视频到界面"""
        bvid = video.get("bvid", "")
        if bvid in self._video_index:
            return
        self.monitored_videos.append(video)
        self._video_index[bvid] = video
        self.video_list.make_card(video)
        self.video_list.update_video_count()
        self._sb("videos", f"监控: {len(self.monitored_videos)} 个")
        self._register_video_timer(bvid)

    @staticmethod
    def _map_api_to_video_dict(bvid: str, info: dict, fallback: dict = None) -> dict:
        """将 B站 API 返回的数据映射为统一的视频字典格式"""
        fb = fallback or {}
        stat = info.get("stat", {})
        owner = info.get("owner", {})
        return {
            "bvid": bvid,
            "title": info.get("title", fb.get("title", "未知标题")),
            "author": owner.get("name", fb.get("author", "未知UP主")),
            "pic": info.get("pic", fb.get("pic", "")),
            "view_count": stat.get("view", fb.get("play", 0)),
            "like_count": stat.get("like", fb.get("like", 0)),
            "coin_count": stat.get("coin", 0),
            "share_count": stat.get("share", 0),
            "favorite_count": stat.get("favorite", 0),
            "danmaku_count": stat.get("danmaku", 0),
            "reply_count": stat.get("reply", 0),
            "duration": info.get("duration", 0),
            "pubdate": info.get("pubdate", 0),
            "desc": info.get("desc", ""),
            "aid": info.get("aid", 0),
            "viewers_total": 0,
            "viewers_web": 0,
            "viewers_app": 0,
        }

    def _register_video_to_monitor(self, video: dict) -> None:
        """注册视频到监控系统：初始化数据库 + 创建卡片 + 启动 Worker"""
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
                rec = MonitorRecord(
                    bvid=bvid,
                    timestamp=now.isoformat(),
                    view_count=video["view_count"],
                    like_count=video["like_count"],
                    coin_count=video["coin_count"],
                    share_count=video["share_count"],
                    favorite_count=video["favorite_count"],
                    danmaku_count=video["danmaku_count"],
                    reply_count=video["reply_count"],
                )
                video_db.add_monitor_record(rec)
                self._save_weekly_score(bvid, video, now.isoformat())
                self._save_yearly_score(bvid, video, now.isoformat())
        except Exception as e:
            self.log_panel.add_log("WARNING", f"数据库初始化失败: {bvid}: {e}")
        self.monitored_videos.append(video)
        self._video_index[bvid] = video
        self.video_list.make_card(video)
        self.video_list.update_video_count()
        self._sb("videos", f"监控: {len(self.monitored_videos)} 个")
        self._register_video_timer(bvid)
        # 启动独立 Worker 线程，立即开始监控
        interval = self._get_video_interval(video)
        _start_worker(self, bvid, video, interval, self.FAST_INTERVAL)

    def _save_weekly_score(self, bvid, video, timestamp):
        """保存周刊分数到数据库"""
        try:
            ws = _calc_ws(video)
            if ws and bvid in self.video_dbs:
                score_data = asdict(ws)
                self.video_dbs[bvid].add_weekly_score(timestamp, score_data)
        except Exception as e:
            logger.warning("保存周刊分数失败 %s: %s", bvid, e)

    def _save_yearly_score(self, bvid, video, timestamp):
        """保存年刊分数到数据库"""
        try:
            ys = _calc_ys(video)
            if ys and bvid in self.video_dbs:
                score_data = asdict(ys)
                self.video_dbs[bvid].add_yearly_score(timestamp, score_data)
        except Exception as e:
            logger.warning("保存年刊分数失败 %s: %s", bvid, e)

    def _save_watch_list(self):
        """保存监控列表到配置"""
        config = load_config()
        config["watch_list"] = [v.get("bvid", "") for v in self.monitored_videos]
        save_config(config)

    # ── 退出 ─────────────────────────────────────

    def _on_exit(self):
        """应用退出时的清理工作"""
        self._save_watch_list()
        self.log_panel.cleanup()
        self._stop_global_tick()
        self._file_logger.cancel_midnight_checker(self.root)
        self._file_logger.close()
        # 停止所有监控线程
        from ui.monitor_service import _stop_all_workers

        _stop_all_workers()
        # 直接关闭各视频数据库（已有每小时定时同步，退出不重复同步）
        for bvid in self.video_dbs:
            try:
                self.video_dbs[bvid].close()
            except Exception as e:
                logger.debug("关闭视频数据库失败 %s: %s", bvid, e)
        # 关闭中央库
        db.close()
        bilibili_api.close()
        # 关闭算法线程池
        from algorithms.registry import AlgorithmRegistry

        AlgorithmRegistry.shutdown()
        self.root.destroy()
        # 强制退出进程（ThreadPoolExecutor 非 daemon 线程会导致进程挂起）
        os._exit(0)

    def run(self):
        """启动主循环"""
        self.root.mainloop()


def main():
    """主入口函数"""
    app = BilibiliMonitorGUI()
    app.run()


if __name__ == "__main__":
    main()
