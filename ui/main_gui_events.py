"""
事件处理器：更新检查、下载、退出、监控管理、推送等回调
"""

import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import math
import re
import time
import logging
from datetime import datetime, timedelta

from ui.theme import C
from ui.helpers import (
    FONT,
    FONT_SM,
    THRESHOLD_NAMES,
    fmt_num,
    nearest_threshold_gap,
    fmt_eta,
)
from ui.chart import draw_chart_placeholder
from utils.time_utils import safe_timestamp

logger = logging.getLogger(__name__)


# ── 更新 / 通道 ────────────────────────────────


def on_channel_switch(gui, new_channel, dlg):
    """切换更新通道"""
    from utils.update_checker import set_update_channel

    set_update_channel(new_channel)
    dlg.destroy()
    gui._sb("status", f"已切换到 {'稳定版' if new_channel == 'stable' else '测试版'} 通道，重新检查更新…", C["text_2"])
    gui.root.after(500, lambda: check_update(gui))


def show_download_progress(gui, title, download_fn):
    """显示 aria2 下载进度窗口"""
    from utils.update_checker import is_frozen

    win = tk.Toplevel(gui.root)
    win.title(title)
    win.configure(bg=C["bg_base"])
    win.geometry("400x150")
    win.transient(gui.root)
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
            status_lbl.config(text=f"已下载 {fmt_num(downloaded)} / {fmt_num(total)}")
        else:
            status_lbl.config(text="已下载…")

    def on_done(success, msg):
        win.destroy()
        if success:
            gui._sb("status", "下载完成", C["success"])
            gui.log_panel.add_log("INFO", f"下载完成: {title}")
            if is_frozen() and "更新" in title:
                messagebox.showinfo("更新", "下载完成，程序将自动重启以完成更新", parent=gui.root)
        else:
            gui._sb("status", f"下载失败: {msg}", C["danger"])
            gui.log_panel.add_log("ERROR", f"下载失败: {msg}")

    threading.Thread(target=download_fn, args=(on_progress, on_done), daemon=True).start()


def check_update(gui):
    """异步检查 GitHub Release 更新，含 changelog 展示"""
    from utils.update_checker import check_for_update_async

    def _on_result(has_update, latest, url, changelog, channel):
        if has_update and latest:
            from __init__ import __version__

            gui.root.after(0, lambda: gui._sb("status", f"发现新版本 v{latest} (当前 v{__version__})", C["warning"]))
            logger.info("有新版本可用: v%s (当前 v%s), %s", latest, __version__, url)
            gui.root.after(0, lambda: show_update_dialog(gui, latest, __version__, url, changelog, channel))

    check_for_update_async(_on_result)


def show_update_dialog(gui, latest, current, url, changelog, channel="stable"):
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
    dlg = tk.Toplevel(gui.root)
    dlg.title("发现新版本")
    dlg.configure(bg=C["bg_base"])
    dlg.resizable(True, True)
    dlg.geometry("640x580")
    dlg.transient(gui.root)
    dlg.grab_set()

    mode_label = "打包版" if is_frozen() else "源码版"
    channel_label = "测试版" if is_beta else "稳定版"
    tk.Label(
        dlg,
        text=f"新版本 v{latest} 可用 ({mode_label} · {channel_label})",
        font=("Microsoft YaHei UI", 14, "bold"),
        bg=C["bg_base"],
        fg=C["text_1"],
    ).pack(pady=(16, 4))
    tk.Label(dlg, text=f"当前版本: v{current}", font=("Microsoft YaHei UI", 10), bg=C["bg_base"], fg=C["text_3"]).pack(
        pady=(0, 12)
    )

    if is_beta:
        warn_frame = tk.Frame(dlg, bg="#3b1f1f", highlightthickness=1, highlightbackground="#ff4444")
        warn_frame.pack(fill=tk.X, padx=16, pady=(0, 8))
        tk.Label(
            warn_frame, text="⚠ 测试版警告", font=("Microsoft YaHei UI", 10, "bold"), bg="#3b1f1f", fg="#ff6666"
        ).pack(anchor="w", padx=8, pady=(4, 0))
        tk.Label(
            warn_frame,
            text="当前为测试版更新通道，可能存在不稳定或未完成的功能。\n建议在非生产环境中使用。",
            font=("Microsoft YaHei UI", 9),
            bg="#3b1f1f",
            fg="#ff9999",
            justify=tk.LEFT,
        ).pack(anchor="w", padx=8, pady=(0, 4))

    frame = tk.Frame(dlg, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
    frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))

    tk.Label(frame, text="更新内容", font=("Microsoft YaHei UI", 10, "bold"), bg=C["bg_elevated"], fg=C["text_2"]).pack(
        anchor="w", padx=8, pady=(8, 4)
    )

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

    channel_frame = tk.Frame(dlg, bg=C["bg_base"])
    channel_frame.pack(fill=tk.X, padx=16, pady=(0, 8))
    tk.Label(channel_frame, text="更新通道:", font=("Microsoft YaHei UI", 9), bg=C["bg_base"], fg=C["text_3"]).pack(
        side=tk.LEFT, padx=(0, 8)
    )

    current_channel = get_update_channel()
    channel_var = tk.StringVar(value=current_channel)
    gui._channel_var_ref = channel_var
    ttk.Radiobutton(
        channel_frame,
        text="稳定版 (推荐)",
        variable=channel_var,
        value="stable",
        command=lambda: on_channel_switch(gui, channel_var.get(), dlg),
    ).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Radiobutton(
        channel_frame,
        text="测试版",
        variable=channel_var,
        value="beta",
        command=lambda: on_channel_switch(gui, channel_var.get(), dlg),
    ).pack(side=tk.LEFT)

    btn_frame = tk.Frame(dlg, bg=C["bg_base"])
    btn_frame.pack(fill=tk.X, padx=16, pady=(0, 16))

    if is_frozen() and is_beta:
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
            show_download_progress(gui, "正在下载新版本…", perform_exe_self_update)

        ttk.Button(btn_frame, text="⬇ aria2 下载更新", command=_download_exe).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(btn_frame, text="稍后提醒", command=dlg.destroy).pack(side=tk.RIGHT)
    else:

        def _download_zip():
            dlg.destroy()
            show_download_progress(gui, "正在下载最新源码…", perform_source_download_zip)

        def _on_git_pull():
            ok, msg = perform_source_git_pull(branch=git_branch)
            if ok:
                gui.log_panel.add_log("INFO", "git pull 更新成功")
                gui._sb("status", "git pull 更新成功，建议重启应用", C["success"])
            else:
                gui.log_panel.add_log("ERROR", f"git pull 失败: {msg}")
                gui._sb("status", "git pull 失败，请手动更新", C["danger"])
            dlg.destroy()

        ttk.Button(btn_frame, text="📥 Git Pull 自动拉取", command=_on_git_pull).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(btn_frame, text="⬇ aria2 下载 ZIP", command=_download_zip).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(btn_frame, text="稍后提醒", command=dlg.destroy).pack(side=tk.RIGHT)


def on_exit(gui):
    """应用退出时的清理工作"""
    from ui.main_gui_data import save_watch_list

    save_watch_list(gui)
    gui.log_panel.cleanup()
    from ui.main_gui_tick import stop_global_tick

    stop_global_tick(gui)
    gui._file_logger.cancel_midnight_checker(gui.root)
    gui._file_logger.close()
    from ui.monitor_service import _stop_all_workers

    _stop_all_workers()
    from core import db, bilibili_api

    for bvid in gui.video_dbs:
        try:
            gui.video_dbs[bvid].close()
        except Exception as e:
            logger.debug("关闭视频数据库失败 %s: %s", bvid, e)
    db.close()
    bilibili_api.close()
    from algorithms.registry import AlgorithmRegistry

    AlgorithmRegistry.shutdown()
    gui.root.destroy()
    sys.exit(0)


# ── 模型激活 ─────────────────────────────────


def refresh_model_status(gui):
    """刷新模型激活状态显示"""
    try:
        from algorithms.training.checkpoint_manager import get_all_activation_status

        status = get_all_activation_status()
        pending = [aid for aid, s in status.items() if s["needs_activation"]]
        trained = len(status)
    except Exception:
        gui._model_act_status.config(text="")
        return
    if pending:
        gui._model_act_status.config(text=f"⚡ {len(pending)}/{trained} 待激活", fg=C["danger"])
        gui._model_act_btn.config(fg=C["accent"])
    elif trained > 0:
        gui._model_act_status.config(text=f"✓ {trained} 个已最新", fg=C["success"])
        gui._model_act_btn.config(fg=C["text_3"])
    else:
        gui._model_act_status.config(text="")
        gui._model_act_btn.config(fg=C["text_3"])


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
    """启动时自动激活所有算法的最新 checkpoint（后台线程，避免 torch 导入阻塞主线程）"""

    def _worker():
        try:
            from algorithms.training.checkpoint_manager import activate_latest_for_all

            switched = activate_latest_for_all()
            if switched:
                names = ", ".join(switched.keys())
                gui.root.after(0, lambda: gui.log_panel.add_log("INFO", f"启动自动激活模型: {switched}"))
                gui.root.after(0, lambda: gui._sb("status", f"自动激活 {len(switched)} 个模型: {names}", C["success"]))
            gui.root.after(0, lambda: refresh_model_status(gui))
        except Exception as e:
            logger.debug("自动激活模型失败: %s", e)
            gui.root.after(0, lambda: refresh_model_status(gui))

    threading.Thread(target=_worker, daemon=True, name="auto-activate").start()


# ── 初始化 ─────────────────────────────────────


def preload_algorithms(gui):
    """后台线程预加载 AlgorithmRegistry，避免首次预测时等待 8s 扫描"""

    def _worker():
        from algorithms.registry import AlgorithmRegistry

        AlgorithmRegistry.initialize()
        n = len(AlgorithmRegistry.get_algorithm_names())
        logger.info("后台算法预加载完成，共 %d 个算法", n)

    threading.Thread(target=_worker, daemon=True, name="algo-preload").start()


# ── 视频间隔 / 定时器 ──────────────────────────


def get_video_interval(gui, video):
    """根据视频播放量确定刷新间隔（接近阈值时使用快速模式）"""
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
    if gui.auto_refresh_enabled.get():
        from ui.main_gui_tick import start_global_tick

        start_global_tick(gui)


# ── 刷新 / 拉取 ────────────────────────────────


def toggle_auto_refresh(gui, event=None):
    """切换自动刷新开关"""
    cur = gui.auto_refresh_enabled.get()
    gui.auto_refresh_enabled.set(not cur)
    gui.bottom_bar._draw_toggle(not cur)
    if not cur:
        from ui.main_gui_tick import start_global_tick

        start_global_tick(gui)
        gui._sb("status", "自动刷新已启用", C["success"])
    else:
        from ui.main_gui_tick import stop_global_tick

        stop_global_tick(gui)
        gui._countdown_badge.config(text="已暂停")
        gui._mode_pill.config(text="已暂停", fg=C["text_3"])
        gui._sb("status", "自动刷新已禁用", C["warning"])


def do_fetch(gui):
    """执行数据拉取"""
    from ui.monitor_service import fetch_all_video_data

    fetch_all_video_data(gui)


def post_fetch(gui):
    """拉取完成后的回调处理"""
    now_str = datetime.now().strftime("%H:%M:%S")
    gui._sb("status", "刷新完成", C["success"])
    gui._sb("last_ref", f"上次刷新: {now_str}")
    gui._sb("videos", f"监控: {len(gui.monitored_videos)} 个")
    for video in gui.monitored_videos:
        bvid = video.get("bvid", "")
        if bvid in gui.video_list.get_card_widgets():
            gui.video_list.update_card(video)
    if gui.selected_bvid:
        video = get_video(gui, gui.selected_bvid)
        if video:
            gui.detail.update_stat_bar(video)
            if gui.detail.current_tab == "📈 播放量趋势":
                gui.detail._auto_render_chart()
    for video in gui.monitored_videos:
        register_video_timer(gui, video.get("bvid", ""))
    from ui.monitor_service import auto_predict_all

    auto_predict_all(gui)


# ── 视频选中 / 详情 ────────────────────────────


def show_video_detail(gui, video):
    """显示视频详情"""
    gui.detail._build_center_header(video)
    gui.detail._rebuild_stat_bar(video)
    gui.detail._switch_tab(gui.detail.current_tab)


def select_video(gui, bvid):
    """选中视频"""
    gui.selected_bvid = bvid
    gui.video_list.highlight_card(bvid)
    video = get_video(gui, bvid)
    if video:
        show_video_detail(gui, video)
    cached = gui.prediction_results.get(bvid)
    if cached:
        gui.prediction._build_pred_hero(cached["prediction"], cached["current_view"], cached.get("rate_per_sec", 0))
        gui.prediction._update_algo_list(cached.get("success_list", []), cached.get("fail_list", []))


# ── 添加监控 ────────────────────────────────────


def add_monitor(gui):
    """添加监控 - 重构版"""
    dialog = create_add_dialog(gui)
    entry, status_lbl = build_add_dialog_ui(gui, dialog)
    setup_add_dialog_buttons(gui, dialog, entry, status_lbl)


def create_add_dialog(gui):
    """创建添加监控对话框"""
    dialog = tk.Toplevel(gui.root)
    dialog.title("添加监控")
    sw = gui.root.winfo_screenwidth()
    sh = gui.root.winfo_screenheight()
    dialog.geometry(f"{int(sw * 0.28)}x{int(sh * 0.22)}")
    dialog.configure(bg=C["bg_surface"])
    dialog.transient(gui.root)
    dialog.grab_set()
    dialog.resizable(True, True)
    return dialog


def build_add_dialog_ui(gui, dialog):
    """构建对话框UI元素"""
    content = tk.Frame(dialog, bg=C["bg_surface"])
    content.pack(fill=tk.BOTH, expand=True)

    tk.Label(content, text="请输入BV号或视频链接：", bg=C["bg_surface"], fg=C["text_1"], font=FONT).pack(pady=(18, 4))

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


def setup_add_dialog_buttons(gui, dialog, entry, status_lbl):
    """设置对话框按钮和事件绑定"""

    def _confirm():
        validate_and_add_video(gui, entry.get().strip(), dialog, status_lbl)

    btn_f = tk.Frame(dialog, bg=C["bg_surface"])
    btn_f.pack(pady=10)
    ttk.Button(btn_f, text="确认添加", style="Primary.TButton", command=_confirm).pack(side=tk.LEFT, padx=6)
    ttk.Button(btn_f, text="取消", command=dialog.destroy).pack(side=tk.LEFT, padx=6)
    entry.bind("<Return>", lambda e: _confirm())


def validate_and_add_video(gui, raw_input, dialog, status_lbl):
    """验证输入并添加视频"""
    if not raw_input:
        messagebox.showwarning("提示", "请输入BV号", parent=dialog)
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
            messagebox.showerror("错误", "无法从链接中提取BV号", parent=gui.root)
            return None
    return bvid


def check_video_in_monitor_list(gui, bvid, dialog):
    """检查视频是否已在监控列表"""
    if bvid in gui._video_index:
        messagebox.showinfo("提示", f"{bvid} 已在监控列表中", parent=dialog)
        dialog.destroy()
        return True
    return False


def fetch_video_info_and_add(gui, bvid, dialog, status_lbl):
    """获取视频信息并添加到监控"""
    from core import bilibili_api
    from ui.main_gui_data import map_api_to_video_dict, register_video_to_monitor, save_watch_list

    status_lbl.config(text="正在获取视频信息…")
    dialog.update()

    def _fetch():
        info = bilibili_api.get_video_info(bvid)
        dialog.after(0, lambda: _done(info))

    def _done(info):
        if not info:
            status_lbl.config(text="获取失败，请检查BV号", fg=C["danger"])
            return
        video = map_api_to_video_dict(bvid, info)
        register_video_to_monitor(gui, video)
        save_watch_list(gui)
        messagebox.showinfo(
            "成功",
            f"已添加监控\n标题：{video['title'][:40]}\nUP主：{video['author']}\n播放：{fmt_num(video['view_count'])}",
            parent=dialog,
        )
        dialog.destroy()

    threading.Thread(target=_fetch, daemon=True).start()


# ── 获取视频 ──────────────────────────────────


def get_video(gui, bvid):
    """O(1) 按 bvid 查找视频对象。"""
    return gui._video_index.get(bvid)


# ── 删除监控 ──────────────────────────────────


def remove_monitor(gui):
    """删除当前选中视频的监控"""
    if not gui.selected_bvid:
        messagebox.showwarning("提示", "请先在左侧选择要删除的视频")
        return
    bvid = gui.selected_bvid
    video = get_video(gui, bvid)
    title = video.get("title", bvid) if video else bvid
    if not messagebox.askyesno("确认删除", f"确定要删除监控：\n{title[:50]}？"):
        return
    gui.monitored_videos = [v for v in gui.monitored_videos if v.get("bvid") != bvid]
    gui._video_index.pop(bvid, None)
    gui.history_data.pop(bvid, None)
    vdb = gui.video_dbs.pop(bvid, None)
    if vdb:
        try:
            vdb.close()
        except Exception as e:
            logger.debug("忽略异常: %s", e)
    gui.prediction_results.pop(bvid, None)
    gui._video_timers.pop(bvid, None)
    gui.video_list.remove_card(bvid)
    gui.selected_bvid = None
    gui.detail._build_center_header_empty()
    gui.detail._rebuild_stat_bar({})
    draw_chart_placeholder(gui.detail.chart_canvas)
    gui.prediction._build_pred_hero_empty()
    for w in gui.prediction.algo_frame.winfo_children():
        w.destroy()
    gui.video_list.update_video_count()
    gui._sb("videos", f"监控: {len(gui.monitored_videos)} 个")
    from ui.main_gui_data import save_watch_list

    save_watch_list(gui)


# ── 推送 ──────────────────────────────────────


def push_single(gui, bvid):
    """推送单个视频状态"""
    from core.notification import notification_manager

    video = get_video(gui, bvid)
    if not video:
        messagebox.showwarning("提示", f"未找到视频 {bvid}")
        return

    msg = build_push_msg(gui, [video])
    title = video.get("title", bvid)[:30]

    notification_manager.send_qq_private(msg)
    notification_manager.send_qq_group(msg)
    notification_manager.send_windows_notification(f"📊 B站监控 — {title[:20]}", msg[:256])
    gui._sb("status", f"已推送「{title[:20]}」", C["success"])


def manual_push(gui):
    """手动推送所有监控视频状态到 QQ/Windows 通知"""
    from core.notification import notification_manager

    videos = gui.monitored_videos
    if not videos:
        messagebox.showwarning("提示", "没有监控中的视频可推送")
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
        threading.Thread(target=lambda: run_post_training_predict(gui), daemon=True).start()
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
    """后台重跑所有监控视频的预测"""
    from ui.monitor_service import _predict_single

    bvids = [v.get("bvid", "") for v in gui.monitored_videos if v.get("bvid")]
    if not bvids:
        return
    logger.info("训练完成，开始重新预测 %d 个视频…", len(bvids))
    for bvid in bvids:
        video = next((v for v in gui.monitored_videos if v.get("bvid") == bvid), None)
        if not video:
            continue
        try:
            _predict_single(gui, bvid, video)
        except Exception as e:
            logger.debug("训练后预测 %s 失败: %s", bvid, e)
    total_videos = len(gui.monitored_videos)
    gui.root.after(0, lambda: gui._sb("status", f"训练后预测完成 ({total_videos} 个视频)", C["success"]))
    if gui.selected_bvid:
        if gui.selected_bvid in gui.prediction_results:
            r = gui.prediction_results[gui.selected_bvid]
            gui.root.after(
                0,
                lambda: prediction_done(
                    gui,
                    r["prediction"],
                    r["current_view"],
                    r["growth"],
                    r["rate_per_sec"],
                    r.get("success_list", []),
                    r.get("fail_list", []),
                    r["valid"],
                    r["total"],
                    r.get("surge_info"),
                ),
            )
        gui.root.after(100, lambda: gui.detail._manual_render_chart())
    logger.info("训练后预测完成 (%d 个视频)", len(bvids))


# ── 每日推送 ──────────────────────────────────


def schedule_daily_push(gui):
    """计算到下次 23:50 的秒数，用 root.after 排程"""
    now = datetime.now()
    target = now.replace(hour=23, minute=50, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    delay_ms = int((target - now).total_seconds() * 1000)
    gui.root.after(delay_ms, lambda: daily_push(gui))
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
    """构建每日日报消息：日增量 + 年刊分数 + 预测"""
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

        history = gui.history_data.get(bvid, [])
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
        except Exception as e:
            logger.debug("忽略异常: %s", e)

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
    """构建手动推送消息文本（含年刊分数 + 算法预测时间）"""
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
        except Exception as e:
            logger.debug("忽略异常: %s", e)

        history = gui.history_data.get(bvid, [])
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


def prediction_done(gui, w_pred, current_view, growth, rate_per_sec, success_list, fail_list, valid, total, surge_info=None):
    """预测完成回调，更新预测面板状态。"""
    gui.prediction._build_pred_hero(w_pred, current_view, rate_per_sec, surge_info)
    gui.prediction._update_algo_list(success_list, fail_list)
    gui._sb("algo", f"算法: {valid}/{total}")
    gui._sb("status", "预测完成", C["success"])


def copy_bvid(gui, bvid):
    """复制 BV 号到剪贴板"""
    gui.root.clipboard_clear()
    gui.root.clipboard_append(bvid)
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
