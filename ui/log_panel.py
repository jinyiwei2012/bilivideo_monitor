"""
日志面板模块 - PyQt6 版
"""

import logging
from datetime import datetime
from collections import deque
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QPushButton, QLabel, QComboBox, QFrame,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor, QFont

from ui.theme import C
from ui.invoker import invoke

logger = logging.getLogger(__name__)


class LogPanelHandler(logging.Handler):
    """将 Python logging 标准库的日志接入 GUI 日志面板"""

    LEVEL_MAP = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARNING",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "ERROR",
    }

    def __init__(self, log_panel: "LogPanel"):
        super().__init__()
        self._log_panel = log_panel

    def emit(self, record: logging.LogRecord):
        level = self.LEVEL_MAP.get(record.levelno, "INFO")
        msg = self.format(record)
        try:
            self._log_panel.add_log(level, msg)
        except Exception:
            import sys
            sys.stderr.write(f"LogPanelHandler.emit 失败: {record.getMessage()}\n")


_LOGGER_HANDLER_INSTALLED = False


def install_logging_bridge(log_panel: "LogPanel", level=logging.INFO):
    """将核心模块的 logging 输出桥接到 GUI 日志面板"""
    global _LOGGER_HANDLER_INSTALLED
    if _LOGGER_HANDLER_INSTALLED:
        return

    handler = LogPanelHandler(log_panel)
    handler.setLevel(level)
    fmt = logging.Formatter("%(name)s:%(message)s")
    handler.setFormatter(fmt)

    for name in ("core.bilibili_api", "core.proxy_manager", "core.database", "algorithms", "utils"):
        lg = logging.getLogger(name)
        lg.addHandler(handler)
        lg.setLevel(level)

    _LOGGER_HANDLER_INSTALLED = True


class LogPanel(QWidget):
    """日志面板 — 构建和管理应用日志显示，支持等级筛选、线程安全添加"""

    _MAX_ENTRIES = 1000
    _MAX_TEXT_LINES = 3000

    def __init__(self, parent, file_logger):
        super().__init__(parent)
        self._file_logger = file_logger
        self._log_entries = []  # [(level, timestamp_str, message), ...]
        self._log_level = "ALL"
        self._refresh_timer = None
        self._pending_logs = []  # 批量缓存
        self._flush_scheduled = False  # 防止重复 invoke
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(300)
        self._flush_timer.timeout.connect(self._flush_pending)

        self.frame = QWidget(parent)
        self._build()

    def _build(self):
        """构建日志面板 UI"""
        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部控制栏
        bar = QWidget()
        bar.setStyleSheet(f"background-color: {C['bg_surface']};")
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 8, 12, 8)

        lbl = QLabel("📋 日志")
        lbl.setStyleSheet(f"color: {C['text_2']}; font-weight: bold;")
        h.addWidget(lbl)

        h.addStretch()

        self._level_combo = QComboBox()
        self._level_combo.addItems(["ALL", "INFO", "WARNING", "ERROR", "DEBUG"])
        self._level_combo.currentTextChanged.connect(self._on_level_change)
        self._level_combo.setFixedWidth(100)
        h.addWidget(self._level_combo)

        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear_log)
        clear_btn.setFixedWidth(60)
        h.addWidget(clear_btn)

        layout.addWidget(bar)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {C['border']}; max-height: 1px;")
        layout.addWidget(sep)

        # 日志文本区域
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(self._MAX_TEXT_LINES)
        self._text.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {C['bg_base']};
                color: {C['text_1']};
                border: none;
                font-family: Consolas, "Microsoft YaHei UI";
                font-size: 9pt;
                padding: 8px;
            }}
        """)
        layout.addWidget(self._text, 1)

    def add_log(self, level, message):
        """线程安全地添加日志 — 不直接触碰 QTimer，通过 invoke 调度到主线程"""
        now = datetime.now().strftime("%H:%M:%S")
        self._log_entries.append((level, now, message))
        if len(self._log_entries) > self._MAX_ENTRIES:
            self._log_entries.pop(0)

        # 追加到待刷新缓存
        self._pending_logs.append((level, now, message))
        if not self._flush_scheduled:
            self._flush_scheduled = True
            invoke(self._schedule_flush)

    def _schedule_flush(self):
        """在主线程启动 flush 定时器（线程安全）"""
        if self._pending_logs:
            self._flush_timer.start()

    def _flush_pending(self):
        """批量刷新日志到文本控件（主线程安全）"""
        if not self._pending_logs:
            self._flush_timer.stop()
            return

        entries = self._pending_logs[:]
        self._pending_logs.clear()

        for level, now, msg in entries:
            if self._log_level != "ALL" and level != self._log_level:
                continue
            self._append_text(level, now, msg)

        if len(self._log_entries) > self._MAX_ENTRIES:
            self._log_entries = self._log_entries[-self._MAX_ENTRIES:]

        self._flush_timer.stop()
        self._flush_scheduled = False

    def _append_text(self, level, timestamp, message):
        """在文本控件中追加一行带颜色的日志"""
        color_map = {
            "DEBUG": C["log_debug"],
            "INFO": C["log_info"],
            "WARNING": C["log_warn"],
            "ERROR": C["log_error"],
        }
        color = color_map.get(level, C["text_1"])

        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # 时间戳 - 灰色
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C["log_time"]))
        cursor.insertText(f"[{timestamp}] ", fmt)

        # 等级 - 带颜色
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        fmt.setFontWeight(QFont.Weight.Bold)
        cursor.insertText(f"[{level:<7}] ", fmt)

        # 消息 - 默认色
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C["text_1"]))
        cursor.insertText(f"{message}\n", fmt)

        # 自动滚动到底部
        self._text.verticalScrollBar().setValue(
            self._text.verticalScrollBar().maximum()
        )

    def _on_level_change(self, level):
        """切换日志等级筛选"""
        self._log_level = level
        self._refresh_log_view()

    def _refresh_log_view(self):
        """重新加载日志视图（切换等级时）"""
        self._text.clear()
        for level, ts, msg in self._log_entries:
            if self._log_level == "ALL" or level == self._log_level:
                self._append_text(level, ts, msg)

    def _clear_log(self):
        """清空日志"""
        self._text.clear()
        self._log_entries.clear()

    def stop_auto_refresh(self):
        """停止自动刷新"""
        self._flush_timer.stop()

    def start_auto_refresh(self, parent):
        """启动自动刷新（PyQt6 中由 flush_timer 处理）"""
        pass

    def refresh_log_view(self):
        """手动刷新日志视图"""
        self._refresh_log_view()
