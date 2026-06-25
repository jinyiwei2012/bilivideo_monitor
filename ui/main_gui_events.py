"""
事件处理器 - PyQt6 版

更新检查、下载、退出、监控管理、推送等回调函数。
所有函数接收 gui (BilibiliMonitorGUI) 作为第一个参数。
"""

import sys
import threading
import math
import re
import time
import logging
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QProgressBar, QWidget, QFrame, QRadioButton, QMessageBox,
    QLineEdit, QApplication,
)
from PyQt6.QtCore import Qt, QTimer, QSize

from ui.theme import C
from ui.invoker import invoke, invoke_later
from ui.helpers import (
    FONT, FONT_SM, THRESHOLD_NAMES, fmt_num,
    nearest_threshold_gap, fmt_eta,
)
from ui.chart import draw_chart_placeholder
from utils.time_utils import safe_timestamp
from utils.thread_utils import fire_and_forget

logger = logging.getLogger(__name__)


# ── 更新 / 通道 ────────────────────────────────


def on_channel_switch(gui, new_channel, dlg):
    """切换更新通道"""
    from utils.update_checker import set_update_channel

    set_update_channel(new_channel)
    dlg.accept()
    gui._sb("status", f"已切换到 {'稳定版' if new_channel == 'stable' else '测试版'} 更新通道，重新检查更新…", C["text_2"])
    QTimer.singleShot(500, lambda: check_update(gui))


def show_download_progress(gui, title, download_fn):
    """显示 aria2 下载进度窗口"""
    from utils.update_checker import is_frozen

    dlg = QDialog(gui)
    dlg.setWindowTitle(title)
    dlg.setFixedSize(400, 150)
    dlg.setStyleSheet(f"background-color: {C['bg_base']};")

    layout = QVBoxLayout(dlg)
    layout.setSpacing(8)

    title_lbl = QLabel(title)
    title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    title_lbl.setStyleSheet(f"color: {C['text_1']}; font-size: 12pt; padding: 16px 0 8px 0;")
    layout.addWidget(title_lbl)

    progress = QProgressBar()
    progress.setFixedWidth(320)
    progress.setTextVisible(False)
    progress.setStyleSheet(f"""
        QProgressBar {{ background-color: {C['bg_elevated']}; border: none; }}
        QProgressBar::chunk {{ background-color: {C['accent']}; }}
    """)
    layout.addWidget(progress, 0, Qt.AlignmentFlag.AlignCenter)

    status_lbl = QLabel("准备中…")
    status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    status_lbl.setStyleSheet(f"color: {C['text_3']}; font-size: 9pt;")
    layout.addWidget(status_lbl)
    layout.addStretch()

    dlg.show()

    def on_progress(downloaded, total):
        if total > 0:
            pct = min(100, int(downloaded / total * 100))
            progress.setValue(pct)
            status_lbl.setText(f"已下载 {fmt_num(downloaded)} / {fmt_num(total)}")
        else:
            status_lbl.setText("已下载…")

    def on_done(success, msg):
        dlg.close()
        if success:
            gui._sb("status", "下载完成", C["success"])
            gui.log_panel.add_log("INFO", f"下载完成: {title}")
            if is_frozen() and "更新" in title:
                QMessageBox.information(gui, "更新", "下载完成，程序将自动重启以完成更新")
        else:
            gui._sb("status", f"下载失败: {msg}", C["danger"])
            gui.log_panel.add_log("ERROR", f"下载失败: {msg}")

    fire_and_forget(download_fn, on_progress, on_done, name="download")


def check_update(gui):
    """异步检查 GitHub Release 更新"""
    from utils.update_checker import check_for_update_async

    def _on_result(has_update, latest, url, changelog, channel):
        if has_update and latest:
            from __init__ import __version__

            invoke(lambda: gui._sb("status", f"发现新版本 v{latest} (当前 v{__version__})", C["warning"]))
            logger.info("有新版本可用: v%s (当前 v%s), %s", latest, __version__, url)
            invoke(lambda: show_update_dialog(gui, latest, __version__, url, changelog, channel))

    check_for_update_async(_on_result)


def show_update_dialog(gui, latest, current, url, changelog, channel="stable"):
    """显示更新弹窗"""
    from utils.update_checker import (
        format_changelog_for_display, is_frozen, perform_source_git_pull,
        perform_source_download_zip, perform_exe_self_update, get_update_channel,
    )

    is_beta = channel == "beta"
    git_branch = "pre-release" if is_beta else "releases"

    dlg = QDialog(gui)
    dlg.setWindowTitle("发现新版本")
    dlg.setMinimumSize(640, 580)
    dlg.setStyleSheet(f"background-color: {C['bg_base']};")

    layout = QVBoxLayout(dlg)
    layout.setSpacing(8)

    mode_label = "打包版" if is_frozen() else "源码版"
    channel_label = "测试版" if is_beta else "稳定版"

    header = QLabel(f"新版本 v{latest} 可用 ({mode_label} · {channel_label})")
    header.setStyleSheet(f"color: {C['text_1']}; font-size: 14pt; font-weight: bold; padding: 16px 0 4px 0;")
    header.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(header)

    cur_ver = QLabel(f"当前版本: v{current}")
    cur_ver.setStyleSheet(f"color: {C['text_3']}; font-size: 10pt;")
    cur_ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(cur_ver)

    if is_beta:
        warn = QWidget()
        warn.setStyleSheet("background-color: #3b1f1f; border: 1px solid #ff4444; border-radius: 4px;")
        wl = QVBoxLayout(warn)
        wl.setContentsMargins(8, 4, 8, 4)
        wt = QLabel("⚠ 测试版警告")
        wt.setStyleSheet("color: #ff6666; font-size: 10pt; font-weight: bold;")
        wl.addWidget(wt)
        wd = QLabel("当前为测试版更新通道，可能存在不稳定或未完成的功能。\n建议在非生产环境中使用。")
        wd.setStyleSheet("color: #ff9999; font-size: 9pt;")
        wd.setWordWrap(True)
        wl.addWidget(wd)
        layout.addWidget(warn)

    # Changelog area
    log_frame = QWidget()
    log_frame.setStyleSheet(f"background-color: {C['bg_elevated']}; border: 1px solid {C['border_sub']}; border-radius: 4px;")
    log_layout = QVBoxLayout(log_frame)
    log_layout.setContentsMargins(8, 8, 8, 8)

    log_header = QLabel("更新内容")
    log_header.setStyleSheet(f"color: {C['text_2']}; font-size: 10pt; font-weight: bold;")
    log_layout.addWidget(log_header)

    text_edit = QTextEdit()
    text_edit.setReadOnly(True)
    text_edit.setPlainText(format_changelog_for_display(changelog))
    text_edit.setStyleSheet(f"""
        QTextEdit {{
            background-color: {C['bg_surface']}; color: {C['text_1']};
            font-family: Consolas; font-size: 9pt; border: none; padding: 8px;
        }}
    """)
    log_layout.addWidget(text_edit, 1)

    layout.addWidget(log_frame, 1)

    # Channel selection
    channel_widget = QWidget()
    channel_widget.setStyleSheet(f"background-color: {C['bg_base']};")
    ch_layout = QHBoxLayout(channel_widget)
    ch_layout.setContentsMargins(16, 0, 16, 8)

    ch_label = QLabel("更新通道:")
    ch_label.setStyleSheet(f"color: {C['text_3']}; font-size: 9pt;")
    ch_layout.addWidget(ch_label)

    current_channel = get_update_channel()
    rb_stable = QRadioButton("稳定版 (推荐)")
    rb_stable.setStyleSheet(f"color: {C['text_1']}; font-size: 9pt;")
    rb_stable.setChecked(current_channel == "stable")
    rb_stable.toggled.connect(lambda checked: on_channel_switch(gui, "stable", dlg) if checked else None)
    ch_layout.addWidget(rb_stable)

    rb_beta = QRadioButton("测试版")
    rb_beta.setStyleSheet(f"color: {C['text_1']}; font-size: 9pt;")
    rb_beta.setChecked(current_channel == "beta")
    rb_beta.toggled.connect(lambda checked: on_channel_switch(gui, "beta", dlg) if checked else None)
    ch_layout.addWidget(rb_beta)
    ch_layout.addStretch()

    layout.addWidget(channel_widget)

    # Buttons
    btn_widget = QWidget()
    btn_widget.setStyleSheet(f"background-color: {C['bg_base']};")
    btn_layout = QHBoxLayout(btn_widget)
    btn_layout.setContentsMargins(16, 0, 16, 16)

    def _make_btn(text, click_handler):
        btn = QPushButton(text)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C['bg_elevated']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 6px 14px; font-size: 9pt;
            }}
            QPushButton:hover {{ background-color: {C['bg_hover']}; }}
        """)
        btn.clicked.connect(click_handler)
        return btn

    cancel_btn = QPushButton("稍后提醒")
    cancel_btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {C['bg_elevated']}; color: {C['text_1']};
            border: 1px solid {C['border']}; padding: 6px 14px; font-size: 9pt;
        }}
        QPushButton:hover {{ background-color: {C['bg_hover']}; }}
    """)
    cancel_btn.clicked.connect(dlg.accept)
    btn_layout.addWidget(cancel_btn)
    btn_layout.addStretch()

    if is_frozen() and is_beta:
        info_lbl = QLabel("测试版暂不提供 EXE 下载，请切换到稳定版通道。\n也可以使用源码版通过 Git/ZIP 更新。")
        info_lbl.setStyleSheet(f"color: {C['warning']}; font-size: 9pt;")
        info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_layout.addWidget(info_lbl)
    elif is_frozen():
        dl_btn = _make_btn("⬇ aria2 下载更新", lambda: (dlg.accept(), show_download_progress(gui, "正在下载新版本…", perform_exe_self_update)))
        btn_layout.addWidget(dl_btn)
    else:
        git_btn = _make_btn("📥 Git Pull 自动拉取", lambda: _on_git_pull())
        zip_btn = _make_btn("⬇ aria2 下载 ZIP", lambda: (dlg.accept(), show_download_progress(gui, "正在下载最新源码…", perform_source_download_zip)))
        btn_layout.addWidget(git_btn)
        btn_layout.addWidget(zip_btn)

    layout.addWidget(btn_widget)

    def _on_git_pull():
        ok, msg = perform_source_git_pull(branch=git_branch)
        if ok:
            gui.log_panel.add_log("INFO", "git pull 更新成功")
            gui._sb("status", "git pull 更新成功，建议重启应用", C["success"])
        else:
            gui.log_panel.add_log("ERROR", f"git pull 失败: {msg}")
            gui._sb("status", "git pull 失败，请手动更新", C["danger"])
        dlg.accept()

    dlg.exec()


def on_exit(gui):
    """应用退出时的清理工作"""
    from ui.main_gui_data import save_watch_list

    save_watch_list(gui)
    gui.log_panel.cleanup()
    from ui.main_gui_tick import stop_global_tick

    stop_global_tick(gui)
    gui._file_logger.cancel_midnight_checker()
    gui._file_logger.close()
    from ui.monitor import _stop_all_workers

    _stop_all_workers()
    from core import db, bilibili_api

    for bvid in gui.video_dbs:
        try:
            gui.video_dbs[bvid].close()
        except Exception as e:
            logger.debug("关闭视频数据库失败 %s: %s", bvid, e)
    db.close()
    bilibili_api.close()
    try:
        from ui.video_list_panel import _cover_session
        _cover_session.close()
    except Exception as e:
        logger.debug("关闭封面 Session 失败: %s", e)
    from algorithms.registry import AlgorithmRegistry

    AlgorithmRegistry.shutdown()
    try:
        from core.notification import notification_manager
        notification_manager.shutdown()
    except Exception as e:
        logger.debug("关闭 NotificationManager 失败: %s", e)

    try:
        from algorithms.online_learner import get_online_learner
        from ui.helpers import project_path
        learner = get_online_learner()
        learner.save(project_path("data", "online_learner_state.json"))
    except Exception as e:
        logger.debug("保存在线学习状态失败: %s", e)

    try:
        from core.database.connection import close_http_session
        close_http_session()
    except Exception as e:
        logger.debug("关闭 HTTP Session 失败: %s", e)

    QApplication.quit()


# ── 模型激活 ─────────────────────────────────


def refresh_model_status(gui):
    """刷新模型激活状态显示"""
    try:
        from algorithms.training.checkpoint_manager import get_all_activation_status

        status = get_all_activation_status()
        pending = [aid for aid, s in status.items() if s["needs_activation"]]
        trained = len(status)
    except Exception as e:
        logger.debug("刷新模型状态失败: %s", e)
        gui._model_act_status.setText("")
        return
    if pending:
        gui._model_act_status.setText(f"⚡ {len(pending)}/{trained} 待激活")
        gui._model_act_status.setStyleSheet(f"color: {C['danger']}; font-size: 9pt;")
    elif trained > 0:
        gui._model_act_status.setText(f"✓ {trained} 个已最新")
        gui._model_act_status.setStyleSheet(f"color: {C['success']}; font-size: 9pt;")
    else:
        gui._model_act_status.setText("")


def activate_models(gui):
    """手动激活所有算法的最新 checkpoint"""
    from algorithms.training.checkpoint_manager import activate_latest_for_all

    switched = activate_latest_for_all()
    if not switched:
        gui._sb("status", "所有模型已是最新版本", C["success"])
        refresh_model_status(gui)
        return
    names = ", ".join(switched.keys())
    gui._sb("status", f"已激活 {len(switched)} 个模型: {names}", C["success"])
    refresh_model_status(gui)
    gui.log_panel.add_log("INFO", f"手动激活模型: {switched}")


def auto_activate_on_startup(gui):
    """启动时自动激活所有算法的最新 checkpoint（后台线程）"""

    def _worker():
        try:
            from algorithms.training.checkpoint_manager import activate_latest_for_all

            switched = activate_latest_for_all()
            if switched:
                names = ", ".join(switched.keys())
                QTimer.singleShot(0, lambda: gui.log_panel.add_log("INFO", f"启动自动激活模型: {switched}"))
                QTimer.singleShot(0, lambda: gui._sb("status", f"自动激活 {len(switched)} 个模型: {names}", C["success"]))
            QTimer.singleShot(0, lambda: refresh_model_status(gui))
        except Exception as e:
            logger.debug("自动激活模型失败: %s", e)
            QTimer.singleShot(0, lambda: refresh_model_status(gui))

    fire_and_forget(_worker, name="auto-activate")


# ── 初始化 ─────────────────────────────────────


def preload_algorithms(gui):
    """后台线程预加载 AlgorithmRegistry"""

    def _worker():
        from algorithms.registry import AlgorithmRegistry

        AlgorithmRegistry.initialize()
        n = len(AlgorithmRegistry.get_algorithm_names())
        logger.info("后台算法预加载完成，共 %d 个算法", n)

    fire_and_forget(_worker, name="algo-preload")


# ── 视频间隔 / 定时器 ──────────────────────────


def get_video_interval(gui, video):
    """根据视频播放量确定刷新间隔"""
    views = video.get("view_count", 0)
    gap, _ = nearest_threshold_gap(views)
    if 0 < gap < gui.THRESHOLD_GAP:
        return gui.FAST_INTERVAL
    return gui.DEFAULT_INTERVAL


def register_video_timer(gui, bvid):
    """注册视频定时器"""
    video = get_video(gui, bvid)
    if not video:
        return
    interval = get_video_interval(gui, video)
    gui._video_timers[bvid] = {"next": time.time() + interval, "interval": interval}


def start_auto_refresh(gui):
    """启动自动刷新"""
    if gui.auto_refresh_enabled:
        from ui.main_gui_tick import start_global_tick

        start_global_tick(gui)


# ── 刷新 / 拉取 ────────────────────────────────


def toggle_auto_refresh(gui):
    """切换自动刷新开关"""
    cur = gui.auto_refresh_enabled
    gui.auto_refresh_enabled = not cur
    gui.bottom_bar._draw_toggle(not cur)
    if not cur:
        from ui.main_gui_tick import start_global_tick

        start_global_tick(gui)
        gui._sb("status", "自动刷新已启用", C["success"])
    else:
        from ui.main_gui_tick import stop_global_tick

        stop_global_tick(gui)
        gui._countdown_badge.setText("已暂停")
        gui._mode_pill.setText("已暂停")
        gui._mode_pill.setStyleSheet(f"color: {C['text_3']}; font-weight: bold; font-size: 9pt;")
        gui._sb("status", "自动刷新已禁用", C["warning"])


def do_fetch(gui):
    """执行数据拉取"""
    from ui.monitor import fetch_all_video_data

    fetch_all_video_data(gui)


def post_fetch(gui):
    """拉取完成后的回调处理"""
    now_str = datetime.now().strftime("%H:%M:%S")
    gui._sb("status", "刷新完成", C["success"])
    gui._sb("last_ref", f"上次刷新: {now_str}")
    gui._sb("videos", f"监控: {len(gui.monitored_videos)} 个")
    for video in gui.monitored_videos:
        bvid = video.get("bvid", "")
        gui.video_list.update_card(video)
        register_video_timer(gui, bvid)
    if gui.selected_bvid:
        video = get_video(gui, gui.selected_bvid)
        if video:
            gui.detail.update_stat_bar(video)
            if gui.detail.current_tab == "📈 播放量趋势":
                gui.detail._auto_render_chart()
    from ui.monitor import auto_predict_all

    auto_predict_all(gui)


# ── 视频选中 / 详情 ────────────────────────────


def show_video_detail(gui, video):
    """显示视频详情 — 先刷新预测面板（瞬时），再刷新详情（可能有渲染延迟）"""
    bvid = video.get("bvid", "")
    # 立即用缓存刷新预测面板
    cached = gui.prediction_results.get(bvid)
    if cached:
        gui.prediction.build_pred_hero(
            cached["prediction"], cached["current_view"], cached.get("rate_per_sec", 0)
        )
        gui.prediction._update_algo_list(cached.get("success_list", []), cached.get("fail_list", []))
    else:
        gui.prediction._build_pred_hero_empty()
        gui.prediction._clear_info()
    # 刷新详情面板
    gui.detail.build_header(video)
    gui.detail.update_stat_bar(video)
    idx = gui.detail._tabs.currentIndex()
    gui.detail._on_tab_changed(idx)


def select_video(gui, bvid):
    """选中视频"""
    gui.selected_bvid = bvid
    gui.video_list.highlight_card(bvid)
    video = get_video(gui, bvid)
    if video:
        show_video_detail(gui, video)


# ── 添加监控 ────────────────────────────────────


def add_monitor(gui):
    """添加监控对话框"""
    dialog = QDialog(gui)
    dialog.setWindowTitle("添加监控")
    screen = QApplication.primaryScreen()
    if screen:
        geo = screen.geometry()
        dialog.resize(int(geo.width() * 0.28), int(geo.height() * 0.22))
    dialog.setStyleSheet(f"background-color: {C['bg_surface']};")
    dialog.setModal(True)

    layout = QVBoxLayout(dialog)
    layout.setSpacing(8)

    prompt = QLabel("请输入BV号或视频链接：")
    prompt.setStyleSheet(f"color: {C['text_1']}; font-size: 10pt; padding: 18px 0 4px 0;")
    prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(prompt)

    entry = QLineEdit()
    entry.setPlaceholderText("格式：BV1xxx 或完整链接")
    entry.setStyleSheet(f"""
        QLineEdit {{
            background-color: {C['bg_elevated']}; color: {C['text_1']};
            border: 1px solid {C['border']}; padding: 6px 8px; font-size: 10pt;
        }}
        QLineEdit:focus {{ border-color: {C['bilibili']}; }}
    """)
    layout.addWidget(entry)

    status_lbl = QLabel("")
    status_lbl.setStyleSheet(f"color: {C['accent']}; font-size: 9pt;")
    status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(status_lbl)

    layout.addStretch()

    # Buttons
    btn_widget = QWidget()
    btn_widget.setStyleSheet(f"background-color: {C['bg_surface']};")
    btn_layout = QHBoxLayout(btn_widget)
    btn_layout.setContentsMargins(0, 0, 0, 10)

    confirm_btn = QPushButton("确认添加")
    confirm_btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {C.get('accent', '#4A90D9')}; color: white;
            border: none; padding: 6px 20px; font-size: 10pt;
        }}
        QPushButton:hover {{ background-color: {C.get('accent_hover', '#357ABD')}; }}
    """)
    confirm_btn.clicked.connect(lambda: validate_and_add_video(gui, entry.text().strip(), dialog, status_lbl))
    btn_layout.addStretch()
    btn_layout.addWidget(confirm_btn)

    cancel_btn = QPushButton("取消")
    cancel_btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {C['bg_elevated']}; color: {C['text_1']};
            border: none; padding: 6px 20px; font-size: 10pt;
        }}
        QPushButton:hover {{ background-color: {C['bg_hover']}; }}
    """)
    cancel_btn.clicked.connect(dialog.reject)
    btn_layout.addWidget(cancel_btn)
    btn_layout.addStretch()

    layout.addWidget(btn_widget)

    entry.returnPressed.connect(confirm_btn.click)
    dialog.exec()


def validate_and_add_video(gui, raw_input, dialog, status_lbl):
    """验证输入并添加视频"""
    if not raw_input:
        QMessageBox.warning(dialog, "提示", "请输入BV号")
        return

    bvid = extract_bvid_from_input(gui, raw_input)
    if bvid is None:
        return

    if check_video_in_monitor_list(gui, bvid, dialog):
        return

    fetch_video_info_and_add(gui, bvid, dialog, status_lbl)


def extract_bvid_from_input(gui, raw_input):
    """从输入中提取BV号"""
    bvid = raw_input
    if "bilibili.com" in raw_input:
        m = re.search(r"BV[\w]+", raw_input)
        if m:
            bvid = m.group()
        else:
            QMessageBox.critical(gui, "错误", "无法从链接中提取BV号")
            return None
    return bvid


def check_video_in_monitor_list(gui, bvid, dialog):
    """检查视频是否已在监控列表"""
    if bvid in gui._video_index:
        QMessageBox.information(dialog, "提示", f"{bvid} 已在监控列表中")
        dialog.accept()
        return True
    return False


def fetch_video_info_and_add(gui, bvid, dialog, status_lbl):
    """获取视频信息并添加到监控"""
    from core import bilibili_api
    from ui.main_gui_data import map_api_to_video_dict, register_video_to_monitor, save_watch_list

    status_lbl.setText("正在获取视频信息…")

    def _fetch():
        info = bilibili_api.get_video_info(bvid)
        QTimer.singleShot(0, lambda: _done(info))

    def _done(info):
        if not info:
            status_lbl.setText("获取失败，请检查BV号")
            status_lbl.setStyleSheet(f"color: {C['danger']}; font-size: 9pt;")
            return
        video = map_api_to_video_dict(bvid, info)
        register_video_to_monitor(gui, video)
        save_watch_list(gui)
        QMessageBox.information(
            dialog, "成功",
            f"已添加监控\n标题：{video['title'][:40]}\nUP主：{video['author']}\n播放：{fmt_num(video['view_count'])}",
        )
        dialog.accept()

    fire_and_forget(_fetch, name="fetch-video")


# ── 获取视频 ──────────────────────────────────


def get_video(gui, bvid):
    """O(1) 按 bvid 查找视频对象"""
    return gui._video_index.get(bvid)


# ── 删除监控 ──────────────────────────────────


def remove_monitor(gui):
    """删除当前选中视频的监控（支持 30s 撤销）"""
    if not gui.selected_bvid:
        QMessageBox.warning(gui, "提示", "请先在左侧选择要删除的视频")
        return
    bvid = gui.selected_bvid
    video = get_video(gui, bvid)
    title = video.get("title", bvid) if video else bvid
    if not QMessageBox.question(
        gui, "确认删除", f"确定要删除监控：\n{title[:50]}？\n\n（30 秒内可从状态栏撤销）",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    ) == QMessageBox.StandardButton.Yes:
        return

    # 软删除：移入待删除队列
    removed = {
        "bvid": bvid,
        "video": video,
        "history": gui.history_data.pop(bvid, []),
        "vdb": gui.video_dbs.pop(bvid, None),
        "predictions": gui.prediction_results.pop(bvid, None),
        "timer": gui._video_timers.pop(bvid, None),
    }
    gui.monitored_videos = [v for v in gui.monitored_videos if v.get("bvid") != bvid]
    gui._video_index.pop(bvid, None)
    gui.video_list.remove_card(bvid)
    gui.selected_bvid = None
    gui.detail._build_header_empty()
    gui.detail._rebuild_stat_bar({})
    gui.prediction._build_pred_hero_empty()
    gui.prediction._clear_info()
    gui.video_list.update_video_count()
    gui._sb("videos", f"监控: {len(gui.monitored_videos)} 个")
    from ui.main_gui_data import save_watch_list
    fire_and_forget(save_watch_list, gui, name="save-watchlist")

    # 撤销提示（状态栏）
    gui._sb("alert", f"已删除 {title[:20]}（30s 内可撤销）", C["warning"])

    # 存储待删除数据
    if not hasattr(gui, "_pending_deletes"):
        gui._pending_deletes = {}
    gui._pending_deletes[bvid] = removed

    # 30 秒后真删除
    from PyQt6.QtCore import QTimer
    timer = QTimer(gui)
    timer.setSingleShot(True)
    timer.timeout.connect(lambda b=bvid: _finalize_delete(gui, b))
    timer.start(30000)
    if not hasattr(gui, "_delete_timers"):
        gui._delete_timers = {}
    gui._delete_timers[bvid] = timer
    gui.bottom_bar.show_undo_button()


def undo_delete(gui):
    """撤销最近一次删除"""
    if not hasattr(gui, "_pending_deletes") or not gui._pending_deletes:
        QMessageBox.information(gui, "提示", "没有可撤销的删除操作")
        return
    # 撤销最近删除的
    bvid = list(gui._pending_deletes.keys())[-1]
    removed = gui._pending_deletes.pop(bvid)
    timer = gui._delete_timers.pop(bvid, None)
    if timer:
        timer.stop()

    # 恢复数据
    gui.monitored_videos.append(removed["video"])
    gui.history_data[bvid] = removed["history"]
    if removed["vdb"]:
        gui.video_dbs[bvid] = removed["vdb"]
    if removed["predictions"]:
        gui.prediction_results[bvid] = removed["predictions"]
    if removed["timer"]:
        gui._video_timers[bvid] = removed["timer"]

    gui.video_list.make_card(removed["video"])
    gui.video_list.update_video_count()
    gui._sb("alert", f"已恢复 {removed['video'].get('title', bvid)[:20]}", C["success"])
    gui._sb("videos", f"监控: {len(gui.monitored_videos)} 个")
    gui.bottom_bar.hide_undo_button()
    from ui.main_gui_data import save_watch_list
    fire_and_forget(save_watch_list, gui, name="save-watchlist")


def _finalize_delete(gui, bvid):
    """执行真删除（撤销窗口已过）"""
    removed = gui._pending_deletes.pop(bvid, None)
    gui._delete_timers.pop(bvid, None)
    if removed:
        vdb = removed.get("vdb")
        if vdb:
            try:
                vdb.close()
            except Exception as e:
                logger.debug("忽略异常: %s", e)
        gui._sb("alert", "", C["text_3"])
        if not gui._pending_deletes:
            gui.bottom_bar.hide_undo_button()


# ── 推送 ──────────────────────────────────────


def push_single(gui, bvid):
    """推送单个视频状态"""
    from core.notification import notification_manager

    video = get_video(gui, bvid)
    if not video:
        QMessageBox.warning(gui, "提示", f"未找到视频 {bvid}")
        return

    msg = build_push_msg(gui, [video])
    title = video.get("title", bvid)[:30]

    notification_manager.send_qq_private(msg)
    notification_manager.send_qq_group(msg)
    notification_manager.send_windows_notification(f"📊 B站监控 — {title[:20]}", msg[:256])
    gui._sb("status", f"已推送「{title[:20]}」", C["success"])


def manual_push(gui):
    """手动推送所有监控视频状态"""
    from core.notification import notification_manager

    videos = gui.monitored_videos
    if not videos:
        QMessageBox.warning(gui, "提示", "没有监控中的视频可推送")
        return

    msg = build_push_msg(gui, videos)
    now_str = datetime.now().strftime("%H:%M")

    ok_qq_private = notification_manager.send_qq_private(msg)
    ok_qq_group = notification_manager.send_qq_group(msg)
    ok_win = notification_manager.send_windows_notification(f"📊 B站监控报告 ({now_str})", msg[:256])

    if ok_qq_private or ok_qq_group:
        gui._sb("status", f"已推送 {len(videos)} 个视频状态", C["success"])
    elif ok_win:
        gui._sb("status", "仅发送了 Windows 通知", C["warning"])
    else:
        gui._sb("status", "推送失败 (未配置 QQ / 通知服务不可用)", C["danger"])


# ── 训练完成回调 ──────────────────────────────


def on_training_completed(gui, mode="训练", count=0, detail="", trained_ids=None):
    """训练/微调完成后自动刷新预测 + 推送通知 + 更新权重"""
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

    if trained_ids:
        try:
            update_trained_weights(gui, trained_ids)
        except Exception as e:
            logger.debug("更新训练算法权重失败: %s", e)

    try:
        fire_and_forget(lambda: run_post_training_predict(gui), name="post-train-predict")
    except Exception as e:
        logger.debug("启动训练后预测失败: %s", e)


def update_trained_weights(gui, algo_ids):
    """训练完成后提升算法 ML 权重"""
    from algorithms.registry import AlgorithmRegistry
    from ui.helpers import load_algo_confidence

    for algo_id in algo_ids:
        conf = load_algo_confidence(algo_id)
        accuracy = max(0.5, conf)
        AlgorithmRegistry.update_accuracy(algo_id, 1.0, accuracy)
    logger.info("已更新 %d 个训练完成算法的权重", len(algo_ids))


def run_post_training_predict(gui):
    """后台并行重跑所有监控视频的预测"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from ui.monitor import _predict_single

    bvids = [v.get("bvid", "") for v in gui.monitored_videos if v.get("bvid")]
    if not bvids:
        return

    video_map = {v.get("bvid"): v for v in gui.monitored_videos if v.get("bvid")}

    logger.info("训练完成，开始并行预测 %d 个视频…", len(bvids))

    def _predict_one(bvid):
        video = video_map.get(bvid)
        if not video:
            return bvid, None
        try:
            result = _predict_single(gui, bvid, video)
            return bvid, result
        except Exception as e:
            logger.debug("训练后预测 %s 失败: %s", bvid, e)
            return bvid, None

    max_workers = min(len(bvids), 8)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_predict_one, bvid): bvid for bvid in bvids}
        for future in as_completed(futures):
            bvid, result = future.result()
            if result:
                logger.debug("训练后预测 %s 完成: %.0f", bvid, result.get("prediction", 0))

    total_videos = len(gui.monitored_videos)
    status_msg = f"训练后预测完成 ({total_videos} 个视频)"
    try:
        from algorithms.training.npu_inference import get_npu_engine
        engine = get_npu_engine()
        stats = engine.stats
        if stats.total_inferences > 0:
            cache = engine.get_cache_info()
            status_msg += (
                f" | NPU: {stats.total_inferences}次推理"
                f" {stats.avg_latency_ms:.2f}ms/次"
                f" 缓存{cache['memory_models']}模型"
            )
            logger.info(
                "NPU 推理统计: %d次 平均%.3fms 缓存命中%d 编译%d次(%.0fms)",
                stats.total_inferences, stats.avg_latency_ms,
                stats.cache_hits, stats.compile_count, stats.compile_total_ms,
            )
    except Exception:
        pass
    invoke(lambda: gui._sb("status", status_msg, C["success"]))
    if gui.selected_bvid:
        if gui.selected_bvid in gui.prediction_results:
            r = gui.prediction_results[gui.selected_bvid]
            invoke(
                lambda: prediction_done(
                    gui, r["prediction"], r["current_view"],
                    r["growth"], r["rate_per_sec"],
                    r.get("success_list", []), r.get("fail_list", []),
                    r["valid"], r["total"], r.get("surge_info"),
                ),
            )
        invoke_later(100, lambda: gui.detail._manual_render_chart())
    logger.info("训练后预测完成 (%d 个视频)", len(bvids))


# ── 每日推送 ──────────────────────────────────


def schedule_daily_push(gui):
    """计算到下次 23:50 的秒数，用 QTimer.singleShot 排程"""
    now = datetime.now()
    target = now.replace(hour=23, minute=50, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    delay_ms = int((target - now).total_seconds() * 1000)
    QTimer.singleShot(delay_ms, lambda: daily_push(gui))
    logger.info("已安排每日推送: %s", target.strftime("%Y-%m-%d %H:%M"))


def daily_push(gui):
    """每日 23:50 自动推送日报"""
    from core.notification import notification_manager

    try:
        msg = build_daily_push_msg(gui)
        notification_manager.send_qq_private(msg)
        notification_manager.send_qq_group(msg)
        notification_manager.send_windows_notification("📊 B站监控日报", msg[:256])
        logger.info("每日推送完成")
    except Exception as e:
        logger.error("每日推送异常: %s", e)
    finally:
        schedule_daily_push(gui)


def build_daily_push_msg(gui):
    """构建每日日报消息"""
    from datetime import date
    from utils.yearly_score import calculate_yearly_from_dict as _calc_ys

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    today = date.today()
    lines = [f"📊 B站监控日报 ({now_str})", f"监控 {len(gui.monitored_videos)} 个视频：", "─" * 30]

    for i, v in enumerate(gui.monitored_videos, 1):
        bvid = v.get("bvid", "")
        title = v.get("title", bvid)[:30]
        views = v.get("view_count", 0)
        likes = v.get("like_count", 0)
        coins = v.get("coin_count", 0)

        with gui._data_lock:
            history = list(gui.history_data.get(bvid, []))
        history = sorted(history, key=lambda x: safe_timestamp(x[0]))
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

        ys_text = "—"
        try:
            ys = _calc_ys(v)
            if ys:
                ys_text = f"{ys.total_score:,.0f}"
        except Exception:
            pass

        pred_info = ""
        cached = gui.prediction_results.get(bvid)
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


def build_push_msg(gui, videos):
    """构建手动推送消息文本"""
    from utils.yearly_score import calculate_yearly_from_dict as _calc_ys

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"📊 B站监控报告 ({now_str})", f"监控 {len(videos)} 个视频：", "─" * 20]

    for i, v in enumerate(videos, 1):
        bvid = v.get("bvid", "?")
        title = v.get("title", bvid)[:30]
        views = v.get("view_count", 0)
        likes = v.get("like_count", 0)
        coins = v.get("coin_count", 0)

        ys_text = ""
        try:
            ys = _calc_ys(v)
            if ys:
                ys_text = f"  年刊: {ys.total_score:,.0f}"
        except Exception:
            pass

        with gui._data_lock:
            history = list(gui.history_data.get(bvid, []))
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

        algo_lines = []
        cached = gui.prediction_results.get(bvid)
        if cached:
            succ = cached.get("success_list", [])
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


# ── 预测结果回调 ──────────────────────────────


def prediction_done(
    gui, w_pred, current_view, growth, rate_per_sec,
    success_list, fail_list, valid, total, surge_info=None,
):
    """预测完成回调"""
    gui.prediction.build_pred_hero(w_pred, current_view, rate_per_sec, surge_info)
    gui.prediction._update_algo_list(success_list, fail_list)
    gui._sb("algo", f"算法: {valid}/{total}")
    gui._sb("status", "预测完成", C["success"])


def copy_bvid(gui, bvid):
    """复制 BV 号到剪贴板"""
    cb = QApplication.clipboard()
    cb.setText(bvid)
    gui._sb("status", f"已复制 {bvid}", C["success"])


# ── 弹窗透传 ──────────────────────────────────


def open_interval_settings(gui):
    gui._dialogs.open_interval_settings()


def open_database_query(gui):
    gui._dialogs.open_database_query()


def open_video_search(gui):
    gui._dialogs.open_video_search()


def open_data_comparison(gui):
    gui._dialogs.open_data_comparison()


def open_crossover_analysis(gui):
    gui._dialogs.open_crossover_analysis()


def open_weekly_score(gui):
    gui._dialogs.open_weekly_score()


def open_milestone_stats(gui):
    gui._dialogs.open_milestone_stats()


def add_bvid_to_monitor(gui, bvid: str):
    gui._dialogs.add_bvid_to_monitor(bvid)


def import_search_results(gui, videos: list):
    gui._dialogs.import_search_results(videos)
