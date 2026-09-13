"""Monitor CRUD, selection, and video lookup event handlers."""

import logging
import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.helpers import fmt_num
from ui.invoker import invoke
from ui.lty_voice import add_video_success, confirm_delete, warning
from ui.theme import C
from utils.thread_utils import fire_and_forget

logger = logging.getLogger(__name__)


def show_video_detail(gui, video):
    """显示视频详情 — 先刷新预测面板（瞬时），再刷新详情（可能有渲染延迟）"""
    bvid = video.get("bvid", "")
    # 立即用缓存刷新预测面板
    cached = gui.prediction_results.get(bvid)
    if cached:
        gui.prediction.build_pred_hero(
            cached["prediction"],
            cached["current_view"],
            cached.get("rate_per_sec", 0),
            bias_info=cached.get("bias_info"),
            eta_info=cached.get("eta_info"),
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


def add_monitor(gui):
    """添加监控对话框"""
    dialog = QDialog(gui)
    dialog.setWindowTitle("添加监控 ♪")
    screen = QApplication.primaryScreen()
    if screen:
        geo = screen.geometry()
        dialog.resize(int(geo.width() * 0.28), int(geo.height() * 0.22))
    dialog.setStyleSheet(f"background-color: {C['bg_surface']};")
    dialog.setModal(True)

    layout = QVBoxLayout(dialog)
    layout.setSpacing(8)

    prompt = QLabel("输入BV号或视频链接,天依帮你找找看 ♪")
    prompt.setStyleSheet(f"color: {C['text_1']}; font-size: 10pt; padding: 18px 0 4px 0;")
    prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(prompt)

    entry = QLineEdit()
    entry.setPlaceholderText("格式: BV1xxx 或完整链接,天依认得它们 ♪")
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

    confirm_btn = QPushButton("确认添加 ♪")
    confirm_btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {C['accent']}; color: white;
            border: none; padding: 6px 20px; font-size: 10pt;
        }}
        QPushButton:hover {{ background-color: {C['accent_hover']}; }}
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
        QMessageBox.warning(dialog, warning(""), "要先输入BV号哦,不然天依不知道要追哪束光呢…♪")
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
            QMessageBox.critical(gui, "呜…出错了", "呜…链接里没有BV号呢,天依的耳朵没听见,再检查一下哦 ♪")
            return None
    return bvid


def check_video_in_monitor_list(gui, bvid, dialog):
    """检查视频是否已在监控列表"""
    if bvid in gui._video_index:
        QMessageBox.information(dialog, "知道啦 ♪", f"{bvid} 已经在歌单里啦,不用重复点播哦 ♪")
        dialog.accept()
        return True
    return False


def fetch_video_info_and_add(gui, bvid, dialog, status_lbl):
    """获取视频信息并添加到监控"""
    from core import bilibili_api
    from ui.main_gui_data import map_api_to_video_dict, register_video_to_monitor, save_watch_list

    status_lbl.setText("天依正在听视频的自我介绍哦…♪")

    def _fetch():
        info = bilibili_api.get_video_info(bvid)
        invoke(lambda: _done(info))

    def _done(info):
        if not info:
            status_lbl.setText("呜…没能听见它的歌声,检查一下BV号对不对哦 ♪")
            status_lbl.setStyleSheet(f"color: {C['danger']}; font-size: 9pt;")
            return
        video = map_api_to_video_dict(bvid, info)
        register_video_to_monitor(gui, video)
        save_watch_list(gui)
        QMessageBox.information(
            dialog,
            "完成啦 ♪",
            f"{add_video_success(video['title'][:40])}\nUP主：{video['author']}\n播放：{fmt_num(video['view_count'])}",
        )
        dialog.accept()

    fire_and_forget(_fetch, name="fetch-video")


def get_video(gui, bvid):
    """O(1) 按 bvid 查找视频对象"""
    return gui._video_index.get(bvid)


def remove_monitor(gui):
    """删除当前选中视频的监控（支持 30s 撤销）"""
    if not gui.selected_bvid:
        QMessageBox.warning(gui, warning(""), "先在左侧选中要删的视频哦,天依才知道要划掉哪一首 ♪")
        return
    bvid = gui.selected_bvid
    video = get_video(gui, bvid)
    title = video.get("title", bvid) if video else bvid
    if (
        not QMessageBox.question(
            gui,
            warning(""),
            f"{title[:50]}\n\n{confirm_delete()}\n(30 秒内还能从状态栏撤销哦) ♪",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        == QMessageBox.StandardButton.Yes
    ):
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
    # 停止该视频的预测线程，避免线程泄漏 / 重加同 bvid 时复用过期 dict
    from ui.monitor import _stop_predictor

    _stop_predictor(bvid)
    gui.selected_bvid = None
    gui.detail._build_header_empty()
    gui.detail._rebuild_stat_bar({})
    gui.prediction._build_pred_hero_empty()
    gui.prediction._clear_info()
    gui.video_list.update_video_count()
    gui._sb("videos", f"监控: {len(gui.monitored_videos)} 个视频 ♪")
    from ui.main_gui_data import save_watch_list

    fire_and_forget(save_watch_list, gui, name="save-watchlist")

    # 撤销提示（状态栏）
    gui._sb("alert", f"已把 {title[:20]} 移出歌单啦(30 秒内可以反悔哦) ♪", C["warning"])

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
        QMessageBox.information(gui, "知道啦 ♪", "现在没有可以撤销的删除哦…像间奏一样安静,先安心吧 ♪")
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
    # 重建预测线程（删除时已停止，撤销后需重新绑定新的视频 dict）
    from ui.monitor._service import _ensure_predictor

    _ensure_predictor(gui, bvid, removed["video"])
    gui._sb("alert", f"把 {removed['video'].get('title', bvid)[:20]} 请回歌单啦!♪ 旋律又接上了~", C["success"])
    gui._sb("videos", f"监控: {len(gui.monitored_videos)} 个视频 ♪")
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
        # A3: 真删除时清理弹幕情绪缓存
        try:
            from ui.danmaku_sentiment import remove_bvid

            remove_bvid(gui, bvid)
        except Exception:
            pass
        gui._sb("alert", "", C["text_3"])
        if not gui._pending_deletes:
            gui.bottom_bar.hide_undo_button()


def copy_bvid(gui, bvid):
    """复制 BV 号到剪贴板"""
    cb = QApplication.clipboard()
    cb.setText(bvid)
    gui._sb("status", f"已把 {bvid} 抄进小本本啦 ♪ 天依记得住哦~", C["success"])


def add_bvid_to_monitor(gui, bvid: str):
    gui._dialogs.add_bvid_to_monitor(bvid)
