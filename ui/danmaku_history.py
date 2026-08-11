"""
历史弹幕拉取对话框
从 B站 API 拉取指定月份的历史弹幕并存入本地数据库
"""
import logging
import threading
from datetime import datetime
from typing import List

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTextEdit, QMessageBox, QProgressBar, QFrame,
)
from PyQt6.QtCore import Qt, QTimer

from ui.theme import C
from ui.dialog_base import DialogBase

logger = logging.getLogger(__name__)

# 可选月份（当前月 + 过去 11 个月）
def _available_months() -> List[str]:
    now = datetime.now()
    months = []
    for i in range(12):
        m = now.month - i
        y = now.year
        if m <= 0:
            m += 12
            y -= 1
        months.append(f"{y}-{m:02d}")
    return months


class DanmakuHistoryWindow:
    """历史弹幕拉取窗口"""

    def __init__(self, parent=None, gui=None):
        self.dlg = DialogBase(parent, "历史弹幕拉取", "520x440", modal=False)
        self.gui = gui
        self._fetching = False
        self._setup_ui()

    def _setup_ui(self):
        dlg = self.dlg
        dlg.header("历史弹幕拉取", "按月份把大家的弹幕收集回来,存进天依的收藏 ♪")

        # ── 视频选择 ──
        video_sec = dlg.section(title="选择视频")
        self._video_cb = QComboBox()
        self._video_cb.setMinimumWidth(300)
        self._refresh_video_list()
        video_sec.layout().addWidget(self._video_cb)

        # ── 月份选择 ──
        month_sec = dlg.section(title="选择月份")
        month_row = QWidget()
        month_layout = QHBoxLayout(month_row)
        month_layout.setContentsMargins(0, 0, 0, 0)

        self._month_cb = QComboBox()
        self._month_cb.addItems(_available_months())
        month_layout.addWidget(self._month_cb)
        month_layout.addStretch()

        self._fetch_btn = QPushButton("开始拉取")
        self._fetch_btn.setProperty("primary", True)
        self._fetch_btn.clicked.connect(self._start_fetch)
        month_layout.addWidget(self._fetch_btn)
        month_sec.layout().addWidget(month_row)

        # ── 进度 ──
        prog_sec = dlg.section(title="拉取进度")
        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {C['border']};
                border-radius: 4px;
                background-color: {C['bg_base']};
                text-align: center;
                color: {C['text_1']};
            }}
            QProgressBar::chunk {{
                background-color: {C['accent']};
                border-radius: 3px;
            }}
        """)
        prog_sec.layout().addWidget(self._progress_bar)

        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(200)
        self._log_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {C['bg_base']};
                color: {C['text_1']};
                font-family: Consolas;
                font-size: 9pt;
                border: 1px solid {C['border']};
            }}
        """)
        prog_sec.layout().addWidget(self._log_text)

        # ── 底部按钮 ──
        dlg.button_row([
            ("关闭", self.dlg.close, ""),
        ])

    def _refresh_video_list(self):
        self._video_cb.clear()
        self._bvid_map = []
        videos = getattr(self.gui, 'monitored_videos', []) or []
        for v in videos:
            bvid = v.get("bvid", "")
            title = v.get("title", bvid)[:40]
            self._video_cb.addItem(f"[{bvid}] {title}")
            self._bvid_map.append(bvid)
        if not videos:
            self._video_cb.addItem("(无监控视频)")

    def _log(self, msg: str):
        now = datetime.now().strftime("%H:%M:%S")
        self._log_text.append(f"[{now}] {msg}")

    def _start_fetch(self):
        if self._fetching:
            return

        idx = self._video_cb.currentIndex()
        if idx < 0 or idx >= len(self._bvid_map):
            QMessageBox.warning(self.dlg, "提示", "呜…先选一个视频哦,天依才好帮你去捞弹幕 ♪")
            return

        bvid = self._bvid_map[idx]
        month = self._month_cb.currentText()

        self._fetching = True
        self._fetch_btn.setEnabled(False)
        self._progress_bar.setValue(0)
        self._log_text.clear()
        self._log(f"天依开始收集 {bvid} 在 {month} 的弹幕啦…像捞起银河里的星光 ♪")

        from core.bilibili_danmaku import get_danmaku_monitor
        monitor = get_danmaku_monitor()

        # 获取 cid
        video_info = None
        for v in (self.gui.monitored_videos or []):
            if v.get("bvid") == bvid:
                video_info = v
                break

        cid = video_info.get("cid", 0) if video_info else 0
        if not cid:
            from core import get_bilibili_api
            try:
                info = get_bilibili_api().get_video_info(bvid)
                cid = info.get("cid", 0) if info else 0
            except Exception:
                pass

        if not cid:
            self._log("呜…天依找不到这个视频的cid呢,换个视频试试哦 ♪")
            self._fetching = False
            self._fetch_btn.setEnabled(True)
            return

        video_db = None
        if self.gui and hasattr(self.gui, 'video_dbs'):
            video_db = self.gui.video_dbs.get(bvid)

        # 后台线程拉取
        def _worker():
            try:
                def progress(date, count, total):
                    pct = int((progress._idx + 1) / total * 100) if total > 0 else 0
                    progress._idx += 1
                    QTimer.singleShot(0, lambda: self._progress_bar.setValue(pct))
                    QTimer.singleShot(0, lambda: self._log(
                        f"  {date}: {count} 条弹幕"
                    ))

                progress._idx = 0

                total = monitor.fetch_history_danmaku(
                    bvid, cid, video_db=video_db,
                    month=month, on_progress=progress,
                )
                QTimer.singleShot(0, lambda: self._log(
                    f"\n完成啦!♪ 天依收集了 {total} 条弹幕,大家的歌声都被好好收下了"
                ))
            except Exception as e:
                logger.warning("历史弹幕拉取失败 %s: %s", bvid, e)
                QTimer.singleShot(0, lambda: self._log(
                    "呜…拉取的时候出了点小状况,天依会再试试的哦 ♪"
                ))
            finally:
                QTimer.singleShot(0, lambda: self._fetch_btn.setEnabled(True))
                QTimer.singleShot(0, lambda: setattr(self, '_fetching', False))

        threading.Thread(target=_worker, daemon=True).start()
