"""
主GUI界面 - PyQt6 版

QMainWindow + QSplitter 三栏布局 + QStackedWidget 导航
左侧视频卡片 / 中间图表详情 / 右侧预测分析
"""

import sys
import os
import logging
import threading

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QPushButton, QFrame, QStackedWidget, QStatusBar,
    QSizePolicy, QApplication, QMenu, QSplashScreen,
)
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QAction, QFont, QPixmap, QIcon, QColor

from ui.theme import C, init_theme
from ui.helpers import (
    FONT, FONT_MONO, FONT_BOLD, DEFAULT_INTERVAL,
    FAST_INTERVAL, FAST_GAP, PREDICT_INTERVAL, project_path,
)
from ui.log_panel import LogPanel, install_logging_bridge
from ui.video_list_panel import VideoListPanel
from ui.detail_panel import DetailPanel
from ui.prediction_panel import PredictionPanel
from ui.bottom_bar import BottomBar
from ui.dialogs import Dialogs
from core import notification_manager
from config import load_config
from utils.file_logger import FileLogger
from ui.main_gui_events import (
    on_channel_switch, show_download_progress, check_update,
    show_update_dialog, on_exit, refresh_model_status,
    activate_models, auto_activate_on_startup, preload_algorithms,
    get_video_interval, register_video_timer, start_auto_refresh,
    toggle_auto_refresh, do_fetch, post_fetch, show_video_detail,
    select_video, add_monitor, remove_monitor, push_single,
    manual_push, on_training_completed, update_trained_weights,
    run_post_training_predict, schedule_daily_push, daily_push,
    build_daily_push_msg, build_push_msg, prediction_done,
    copy_bvid, open_interval_settings, open_database_query,
    open_video_search, open_data_comparison, open_crossover_analysis,
    open_weekly_score, open_milestone_stats, add_bvid_to_monitor,
    import_search_results,
)
from ui.main_gui_tick import (
    start_global_tick as _start_global_tick_impl,
    stop_global_tick as _stop_global_tick_impl,
    global_tick as _global_tick_impl,
    do_periodic_sync as _do_periodic_sync_impl,
    wal_checkpoint_worker as _wal_checkpoint_worker_impl,
    scan_alerts_background as _scan_alerts_background_impl,
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

logger = logging.getLogger(__name__)


class BilibiliMonitorGUI(QMainWindow):
    """主界面 - PyQt6 三栏布局"""

    DEFAULT_INTERVAL = DEFAULT_INTERVAL
    FAST_INTERVAL = FAST_INTERVAL
    PREDICT_INTERVAL = PREDICT_INTERVAL
    THRESHOLD_GAP = FAST_GAP

    def __init__(self):
        super().__init__()
        self._set_window_config()
        init_theme(QApplication.instance())

        self.auto_refresh_enabled = True
        self._global_tick_timer = None
        self._video_timers = {}
        self._data_lock = threading.Lock()
        self._viewers_lock = threading.Lock()
        self._tick_counter = 0
        self._last_countdown_text = ""
        self._last_mode_text = ""
        self._last_interval_text = ""

        self.monitored_videos = []
        self.history_data = {}
        self.prediction_results = {}
        self.video_dbs = {}
        self.selected_bvid = None
        self._video_index = {}

        self._file_logger = FileLogger(project_path("data", "log"))
        if not logging.root.handlers:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s.%(msecs)03d [%(levelname)-7s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        logging.getLogger("prophet.plot").setLevel(logging.CRITICAL)
        logging.getLogger("prophet").setLevel(logging.WARNING)

        self._dialogs = Dialogs(self)
        self._build_ui()
        self._setup_shortcuts()

        # 启动后延迟初始化
        QTimer.singleShot(500, self._auto_activate_on_startup)
        self._load_watch_list()
        self._preload_algorithms()
        notification_manager.configure(load_config())
        self._schedule_daily_push()
        self._start_auto_refresh()
        self._file_logger.start_midnight_checker(self)
        QTimer.singleShot(3000, self._check_update)

    def closeEvent(self, event):
        """窗口关闭时触发完整清理流程 — 等价于 Tkinter 的 WM_DELETE_WINDOW"""
        on_exit(self)
        event.accept()

    def _set_window_config(self):
        """设置窗口配置"""
        from __init__ import __version__
        from utils.update_checker import _x as _z

        suffix = " dev 开发中" if _z() else ""
        self.setWindowTitle(f"B站视频监控与播放量预测系统 v{__version__}{suffix}")

        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            width = int(geo.width() * 0.85)
            height = int(geo.height() * 0.85)
            self.resize(width, height)
            self.setMinimumSize(int(geo.width() * 0.50), int(geo.height() * 0.55))

        self._set_window_icon()

    def _set_window_icon(self):
        """设置窗口图标"""
        try:
            icon_path = project_path("assets", "app_icon.png")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception as e:
            logger.debug("设置窗口图标失败: %s", e)

    def _setup_shortcuts(self):
        """注册全局键盘快捷键"""
        from PyQt6.QtGui import QKeySequence, QShortcut

        QShortcut(QKeySequence("Ctrl+N"), self, self._add_monitor)
        QShortcut(QKeySequence("Ctrl+R"), self, self._refresh_data)
        QShortcut(QKeySequence("Ctrl+F"), self, lambda: self._dialogs.open_video_search())
        QShortcut(QKeySequence("Ctrl+Z"), self, self._undo_delete)
        QShortcut(QKeySequence(Qt.Key.Key_F11), self, lambda: self._dialogs.open_dashboard())
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, self._remove_monitor)

    def _build_ui(self):
        """构建整体 UI"""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._build_titlebar(main_layout)

        # Log panel (hidden by default, shown on nav)
        self.log_panel = LogPanel(central, self._file_logger)
        install_logging_bridge(self.log_panel)

        # Stacked widget for navigation
        self._stack = QStackedWidget()
        main_layout.addWidget(self._stack, 1)

        # Page 0: Main layout (3-column)
        self._main_page = QWidget()
        self._build_main_layout(self._main_page)
        self._stack.addWidget(self._main_page)

        # Page 1: Log
        self._stack.addWidget(self.log_panel.frame)
        self.log_panel.frame.setParent(self._stack)

        # Training panels (lazy init)
        self.training_panel = None
        self.finetune_panel = None
        self._training_page = None
        self._finetune_page = None

        # Bottom bar
        self.bottom_bar = BottomBar(central, self)
        main_layout.addWidget(self.bottom_bar)

        # Status bar
        self._build_status_bar()

    def _build_titlebar(self, parent_layout):
        """构建自定义标题栏"""
        bar = QWidget()
        bar.setFixedHeight(46)
        bar.setStyleSheet(f"background-color: {C['bg_surface']};")
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 0, 14, 0)

        # Logo
        logo_lbl = QLabel("B")
        logo_lbl.setStyleSheet(f"""
            color: white; background-color: {C['bilibili']};
            font-size: 14px; font-weight: bold; border-radius: 14px;
            padding: 4px 10px; min-width: 28px; min-height: 28px;
        """)
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(logo_lbl)

        title_f = QWidget()
        title_f.setStyleSheet(f"background-color: {C['bg_surface']};")
        tf = QVBoxLayout(title_f)
        tf.setContentsMargins(8, 0, 0, 0)
        tf.setSpacing(0)

        t1 = QLabel("B站监控")
        t1.setStyleSheet(f"color: {C['bilibili']}; font-size: 13px; font-weight: bold;")
        tf.addWidget(t1)
        t2 = QLabel("播放量预测系统")
        t2.setStyleSheet(f"color: {C['text_3']}; font-size: 10px;")
        tf.addWidget(t2)
        h.addWidget(title_f)

        # Navigation buttons
        nav_f = QWidget()
        nav_f.setStyleSheet(f"background-color: {C['bg_surface']};")
        nh = QHBoxLayout(nav_f)
        nh.setContentsMargins(16, 0, 0, 0)
        nh.setSpacing(4)

        self._nav_btns = {}
        self._current_nav = "监控列表"
        self._page_views = ["监控列表", "日志", "模型训练", "微调训练"]

        nav_items = [
            ("📊", "监控列表"),
            ("📋", "日志"),
            ("🧠", "模型训练"),
            ("🎯", "微调训练"),
        ]

        for icon, label in nav_items:
            btn = QPushButton(f"{icon} {label}")
            btn.setCheckable(True)
            btn.setChecked(label == self._current_nav)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {C['bg_surface']};
                    color: {C['text_secondary']};
                    border: none;
                    padding: 6px 12px;
                    border-bottom: 2px solid transparent;
                }}
                QPushButton:hover {{
                    color: {C['text_1']};
                    background-color: {C['bg_hover']};
                }}
                QPushButton:checked {{
                    color: {C['bilibili']};
                    border-bottom: 2px solid {C['bilibili']};
                }}
            """)
            btn.clicked.connect(lambda checked, n=label: self._switch_nav(n))
            nh.addWidget(btn)
            self._nav_btns[label] = btn

        h.addWidget(nav_f)
        h.addStretch()

        # Right buttons
        right_f = QWidget()
        right_f.setStyleSheet(f"background-color: {C['bg_surface']};")
        rh = QHBoxLayout(right_f)
        rh.setContentsMargins(0, 0, 0, 0)

        # Countdown badge
        self._countdown_badge = QLabel("-- s")
        self._countdown_badge.setStyleSheet(f"color: {C['accent']}; padding: 2px 8px;")
        rh.addWidget(self._countdown_badge)

        # Mode pill
        self._mode_pill = QLabel("● 正常模式")
        self._mode_pill.setStyleSheet(f"color: {C['success']}; font-weight: bold; font-size: 9px;")
        rh.addWidget(self._mode_pill)

        # Model activation
        self._model_act_btn = QPushButton("🧠 激活模型")
        self._model_act_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C['bg_elevated']}; color: {C['accent']};
                border: none; padding: 4px 8px;
            }}
            QPushButton:hover {{ background-color: {C['bg_hover']}; }}
        """)
        self._model_act_btn.clicked.connect(self._on_activate_models)
        rh.addWidget(self._model_act_btn)

        self._model_act_status = QLabel("")
        self._model_act_status.setStyleSheet(f"color: {C['text_3']}; font-size: 9px;")
        rh.addWidget(self._model_act_status)

        # Gear menu
        self._gear_btn = QPushButton("⚙️")
        self._gear_btn.setToolTip("设置")
        self._gear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C['bg_elevated']}; color: {C['text_2']};
                border: none; padding: 4px 8px;
            }}
            QPushButton:hover {{ background-color: {C['bg_hover']}; }}
        """)
        self._gear_btn.clicked.connect(self._popup_settings_menu)
        rh.addWidget(self._gear_btn)

        # Search
        self._search_btn = QPushButton("🔍")
        self._search_btn.setToolTip("搜索")
        self._search_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C['bg_elevated']}; color: {C['text_2']};
                border: none; padding: 4px 8px;
            }}
            QPushButton:hover {{ background-color: {C['bg_hover']}; }}
        """)
        self._search_btn.clicked.connect(self._dialogs.open_video_search)
        rh.addWidget(self._search_btn)

        h.addWidget(right_f)

        # Settings menu
        self._settings_menu = QMenu(self)
        self._settings_menu.setStyleSheet(f"""
            QMenu {{
                background-color: {C['bg_elevated']};
                color: {C['text_1']};
                border: 1px solid {C['border']};
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 24px;
            }}
            QMenu::item:selected {{
                background-color: {C['bg_hover']};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {C['border']};
                margin: 4px 8px;
            }}
        """)

        menu_items = [
            ("⏱  刷新间隔", lambda: self._dialogs.open_interval_settings()),
            ("🧠  算法信息", lambda: self._dialogs.open_algorithm_info()),
            None,  # separator
            ("📊  数据对比", lambda: self._dialogs.open_data_comparison()),
            ("🔄  交叉计算", lambda: self._dialogs.open_crossover_analysis()),
            ("📅  周刊分数", lambda: self._dialogs.open_weekly_score()),
            ("🏆  里程碑", lambda: self._dialogs.open_milestone_stats()),
            ("🆙  UP主追踪", lambda: self._dialogs.open_up_tracker()),
            ("💬  弹幕分析", lambda: self._dialogs.open_danmaku_analysis()),
            ("📜  历史弹幕", lambda: self._dialogs.open_danmaku_history()),
            ("🔥  热门发现", lambda: self._dialogs.open_trending_discovery()),
            ("🎫  视频标签", lambda: self._dialogs.open_tag_manager()),
            ("🚨  异常检测", lambda: self._dialogs.open_anomaly_detection()),
            ("🏆  视频排行", lambda: self._dialogs.open_ranking()),
            ("📊  预测回测", lambda: self._dialogs.open_backtest()),
            ("📈  预测回看", lambda: self._dialogs.open_prediction_accuracy()),
            ("⏰  时段分析", lambda: self._dialogs.open_time_analysis()),
            ("📊  视频对比增强", lambda: self._dialogs.open_video_compare_enhanced()),
            None,
            ("🤖  AI智能问答", lambda: self._dialogs.open_ai_qa()),
            ("📊  数据大屏", lambda: self._dialogs.open_dashboard()),
            ("📋  导出报告", lambda: self._dialogs.open_report_scheduler()),
            None,
            ("🗄  数据库查询", lambda: self._dialogs.open_database_query()),
            ("⚙️  系统设置", lambda: self._dialogs.open_settings()),
        ]

        for item in menu_items:
            if item is None:
                self._settings_menu.addSeparator()
            else:
                text, callback = item
                action = QAction(text, self)
                action.triggered.connect(callback)
                self._settings_menu.addAction(action)

        # Separator after titlebar
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {C['border']}; max-height: 1px;")
        parent_layout.addWidget(bar)
        parent_layout.addWidget(sep)

    def _build_main_layout(self, parent):
        """构建三栏主体布局"""
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Main 3-column via QSplitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {C['border']};
            }}
        """)

        # Left: video list
        self.video_list = VideoListPanel(splitter, self)
        splitter.addWidget(self.video_list)

        # Center: detail + chart
        self.detail = DetailPanel(splitter, self)
        splitter.addWidget(self.detail.frame)

        # Right: prediction
        self.prediction = PredictionPanel(splitter, self)
        splitter.addWidget(self.prediction.frame)

        # Proportions: 22 : 58 : 20
        splitter.setStretchFactor(0, 22)
        splitter.setStretchFactor(1, 58)
        splitter.setStretchFactor(2, 20)
        splitter.setSizes([220, 580, 200])

        layout.addWidget(splitter)

    def _build_status_bar(self):
        """构建底部状态栏"""
        sb = QStatusBar()
        sb.setStyleSheet(f"""
            QStatusBar {{
                background-color: {C['bg_surface']};
                color: {C['text_3']};
                font-size: 8pt;
                border-top: 1px solid {C['border']};
            }}
        """)
        self.setStatusBar(sb)

    # ── 导航切换 ─────────────────────────────

    def _switch_nav(self, name):
        """切换导航页面"""
        if name == self._current_nav:
            return
        self._current_nav = name

        for label, btn in self._nav_btns.items():
            btn.setChecked(label == name)

        self.log_panel.stop_auto_refresh()

        if name == "日志":
            self._stack.setCurrentWidget(self.log_panel.frame)
            self.log_panel.refresh_log_view()
        elif name == "模型训练":
            if self.training_panel is None:
                from ui.training_panel import TrainingPanel
                self.training_panel = TrainingPanel(self, self)
                self._stack.addWidget(self.training_panel)
            self._stack.setCurrentWidget(self.training_panel)
            self.training_panel.on_show()
        elif name == "微调训练":
            if self.finetune_panel is None:
                from ui.finetune_panel import FinetunePanel
                self.finetune_panel = FinetunePanel(self, self)
                self._stack.addWidget(self.finetune_panel)
            self._stack.setCurrentWidget(self.finetune_panel)
            self.finetune_panel.on_show()
        else:
            self._stack.setCurrentWidget(self._main_page)

    def _popup_settings_menu(self):
        """弹出设置菜单"""
        self._settings_menu.exec(
            self._gear_btn.mapToGlobal(self._gear_btn.rect().bottomLeft())
        )

    # ── 薄委托包装器 ──

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

    def _check_update(self):
        check_update(self)

    def _show_update_dialog(self, latest, current, url, changelog, channel="stable"):
        show_update_dialog(self, latest, current, url, changelog, channel)

    def _on_channel_switch(self, new_channel, dlg):
        on_channel_switch(self, new_channel, dlg)

    def _show_download_progress(self, title, download_fn):
        show_download_progress(self, title, download_fn)

    def _on_exit(self):
        on_exit(self)

    def _refresh_model_status(self):
        refresh_model_status(self)

    def _on_activate_models(self):
        activate_models(self)

    def _auto_activate_on_startup(self):
        auto_activate_on_startup(self)

    def _preload_algorithms(self):
        preload_algorithms(self)

    def _get_video_interval(self, video):
        return get_video_interval(self, video)

    def _register_video_timer(self, bvid):
        register_video_timer(self, bvid)

    def _start_auto_refresh(self):
        start_auto_refresh(self)

    def _toggle_auto_refresh(self, checked=None):
        """切换自动刷新（从 bottom_bar checkbox 接收 bool 或 None）"""
        if checked is not None:
            self.auto_refresh_enabled = checked
        else:
            self.auto_refresh_enabled = not self.auto_refresh_enabled
        toggle_auto_refresh(self)

    def _do_fetch(self):
        do_fetch(self)

    def _post_fetch(self):
        post_fetch(self)

    def _show_video_detail(self, video):
        show_video_detail(self, video)

    def _select_video(self, bvid):
        select_video(self, bvid)

    def _add_monitor(self):
        add_monitor(self)

    def _get_video(self, bvid):
        from ui.main_gui_events import get_video
        return get_video(self, bvid)

    def _remove_monitor(self):
        remove_monitor(self)

    def _push_single(self, bvid):
        push_single(self, bvid)

    def _manual_push(self):
        manual_push(self)

    def _on_training_completed(self, mode="训练", count=0, detail="", trained_ids=None):
        on_training_completed(self, mode, count, detail, trained_ids)

    def _update_trained_weights(self, algo_ids):
        update_trained_weights(self, algo_ids)

    def _run_post_training_predict(self):
        run_post_training_predict(self)

    def _schedule_daily_push(self):
        schedule_daily_push(self)

    def _daily_push(self):
        daily_push(self)

    def _build_daily_push_msg(self):
        return build_daily_push_msg(self)

    def _build_push_msg(self, videos):
        return build_push_msg(self, videos)

    def _prediction_done(
        self, w_pred, current_view, growth, rate_per_sec,
        success_list, fail_list, valid, total, surge_info=None,
    ):
        prediction_done(
            self, w_pred, current_view, growth, rate_per_sec,
            success_list, fail_list, valid, total, surge_info,
        )

    def _copy_bvid(self, bvid):
        copy_bvid(self, bvid)

    def _open_interval_settings(self):
        open_interval_settings(self)

    def _open_database_query(self):
        open_database_query(self)

    def _open_video_search(self):
        open_video_search(self)

    def _open_data_comparison(self):
        open_data_comparison(self)

    def _open_crossover_analysis(self):
        open_crossover_analysis(self)

    def _open_weekly_score(self):
        open_weekly_score(self)

    def _open_milestone_stats(self):
        open_milestone_stats(self)

    def _add_bvid_to_monitor(self, bvid: str):
        add_bvid_to_monitor(self, bvid)

    def _import_search_results(self, videos: list):
        import_search_results(self, videos)

    def _load_watch_list(self):
        _load_watch_list_impl(self)

    def _restore_video(self, video):
        _restore_video_impl(self, video)

    @staticmethod
    def _map_api_to_video_dict(bvid: str, info: dict, fallback: dict = None) -> dict:
        return _map_api_to_video_dict_impl(bvid, info, fallback)

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

    def _sb(self, key, text, color=None):
        """更新状态栏"""
        self.bottom_bar.update_sb(key, text, color)

    def _undo_delete(self):
        """撤销最近一次删除"""
        from ui.main_gui_events import undo_delete
        undo_delete(self)

    def set_finetune_status(self, text: str, color=None):
        """更新主界面底部状态栏的微调状态"""
        self._sb("finetune", text, color=color or C.get("accent", "#4A90D9"))


def main():
    """主入口函数"""
    app = QApplication(sys.argv)

    # 启动画面
    splash = QSplashScreen()
    splash.setWindowFlags(Qt.WindowType.SplashScreen | Qt.WindowType.WindowStaysOnTopHint)
    splash_pm = QPixmap(480, 160)
    splash_pm.fill(QColor("#161b22"))
    splash.setPixmap(splash_pm)
    splash.show()
    splash.showMessage("  B站监控\n  加载中...", Qt.AlignmentFlag.AlignCenter, QColor("#fb7299"))
    app.processEvents()

    window = BilibiliMonitorGUI()
    window.show()
    splash.finish(window)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
