"""Update channel, download, and release dialog event handlers."""

import logging

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.helpers import fmt_num
from ui.invoker import invoke
from ui.lty_voice import error
from ui.theme import C
from ui.dialog_host import present_modal
from utils.thread_utils import fire_and_forget

logger = logging.getLogger(__name__)


def on_channel_switch(gui, new_channel, dlg):
    """切换更新通道"""
    from utils.update_checker import set_update_channel

    set_update_channel(new_channel)
    dlg.accept()
    gui._sb(
        "status",
        f"已切到{'稳定版' if new_channel == 'stable' else '测试版'}更新通道啦,天依再去听听有没有新歌声哦 ♪",
        C["text_2"],
    )
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

    status_lbl = QLabel("天依正在准备中…像天使鱼在冰海里追着光 ♪")
    status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    status_lbl.setStyleSheet(f"color: {C['text_3']}; font-size: 9pt;")
    layout.addWidget(status_lbl)
    layout.addStretch()

    dlg.show()

    def on_progress(downloaded, total):
        if total > 0:
            pct = min(100, int(downloaded / total * 100))
            progress.setValue(pct)
            status_lbl.setText(f"已下载 {fmt_num(downloaded)} / {fmt_num(total)} ♪ 像收集银河里的星光~")
        else:
            status_lbl.setText("天依正在把新歌声搬回家哦…♪")

    def on_done(success, msg):
        dlg.close()
        if success:
            gui._sb("status", success("下载"), C["success"])
            gui.log_panel.add_log("INFO", f"下载完成: {title}")
            if is_frozen() and "更新" in title:
                QMessageBox.information(gui, "更新 ♪", "下载完成啦!♪ 程序会自动重启,把新歌声唱出来哦~")
        else:
            logger.error("下载失败: %s", msg)
            gui._sb("status", error("下载"), C["danger"])
            gui.log_panel.add_log("ERROR", f"下载失败: {msg}")

    fire_and_forget(download_fn, on_progress, on_done, name="download")


def check_update(gui):
    """异步检查 GitHub Release 更新"""
    from utils.update_checker import check_for_update_async

    def _on_result(has_update, latest, url, changelog, channel):
        if has_update and latest:
            from __init__ import __version__

            invoke(
                lambda: gui._sb(
                    "status", f"发现新版本 v{latest} 啦!♪ 像听见远处传来新的旋律(当前 v{__version__})", C["warning"]
                )
            )
            logger.info("有新版本可用: v%s (当前 v%s), %s", latest, __version__, url)
            invoke(lambda: show_update_dialog(gui, latest, __version__, url, changelog, channel))

    check_for_update_async(_on_result)


def show_update_dialog(gui, latest, current, url, changelog, channel="stable"):
    """显示更新弹窗"""
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

    dlg = QDialog(gui)
    dlg.setWindowTitle("发现新版本 ♪")
    dlg.setMinimumSize(640, 580)
    dlg.setStyleSheet(f"background-color: {C['bg_base']};")

    layout = QVBoxLayout(dlg)
    layout.setSpacing(8)

    mode_label = "打包版" if is_frozen() else "源码版"
    channel_label = "测试版" if is_beta else "稳定版"

    header = QLabel(f"新版本 v{latest} 可用啦 ♪ ({mode_label} · {channel_label})")
    header.setStyleSheet(f"color: {C['text_1']}; font-size: 14pt; font-weight: bold; padding: 16px 0 4px 0;")
    header.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(header)

    cur_ver = QLabel(f"当前版本: v{current} ♪")
    cur_ver.setStyleSheet(f"color: {C['text_3']}; font-size: 10pt;")
    cur_ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(cur_ver)

    if is_beta:
        warn = QWidget()
        warn.setStyleSheet(
            f"background-color: {C['warn_bg']}; border: 1px solid {C['warn_border']}; border-radius: 4px;"
        )
        wl = QVBoxLayout(warn)
        wl.setContentsMargins(8, 4, 8, 4)
        wt = QLabel("△ 测试版要注意哦…天依会和你一起看着的 ♪")
        wt.setStyleSheet(f"color: {C['warn_text']}; font-size: 10pt; font-weight: bold;")
        wl.addWidget(wt)
        wd = QLabel("当前是测试版更新通道,有些旋律可能还没谱完呢…\n建议在非生产环境使用哦,天依不想弄丢你的歌声 ♪")
        wd.setStyleSheet(f"color: {C['warn_text_dim']}; font-size: 9pt;")
        wd.setWordWrap(True)
        wl.addWidget(wd)
        layout.addWidget(warn)

    # Changelog area
    log_frame = QWidget()
    log_frame.setStyleSheet(
        f"background-color: {C['bg_elevated']}; border: 1px solid {C['border_sub']}; border-radius: 4px;"
    )
    log_layout = QVBoxLayout(log_frame)
    log_layout.setContentsMargins(8, 8, 8, 8)

    log_header = QLabel("更新内容 ♪")
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

    ch_label = QLabel("更新通道: ♪")
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

    cancel_btn = QPushButton("稍后提醒 ♪")
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
        info_lbl = QLabel(
            "呜…测试版暂时没有 EXE 下载哦,请切回稳定版通道吧 ♪\n用源码版走 Git/ZIP,也能把新歌声带回家呢 ♪"
        )
        info_lbl.setStyleSheet(f"color: {C['warning']}; font-size: 9pt;")
        info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_layout.addWidget(info_lbl)
    elif is_frozen():

        def download_exe() -> None:
            dlg.accept()
            show_download_progress(gui, "正在下载新版本哦…♪", perform_exe_self_update)

        dl_btn = _make_btn(
            "⬇ aria2 下载更新 ♪",
            download_exe,
        )
        btn_layout.addWidget(dl_btn)
    else:
        git_btn = _make_btn("↥ Git Pull 自动拉取 ♪", lambda: _on_git_pull())

        def download_zip() -> None:
            dlg.accept()
            show_download_progress(gui, "正在下载最新源码哦…♪", perform_source_download_zip)

        zip_btn = _make_btn(
            "⬇ aria2 下载 ZIP ♪",
            download_zip,
        )
        btn_layout.addWidget(git_btn)
        btn_layout.addWidget(zip_btn)

    layout.addWidget(btn_widget)

    def _on_git_pull():
        ok, msg = perform_source_git_pull(branch=git_branch)
        if ok:
            gui.log_panel.add_log("INFO", "git pull 更新成功")
            gui._sb("status", "git pull 更新成功啦!♪ 新乐章就绪,重启应用就能听见哦~", C["success"])
        else:
            gui.log_panel.add_log("ERROR", f"git pull 失败: {msg}")
            gui._sb("status", "呜…git pull 没能成功,天依会再试试的,也可以手动更新哦 ♪", C["danger"])
        dlg.accept()

    present_modal(dlg)
