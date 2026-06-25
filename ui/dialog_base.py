"""
现代化对话框基类 — PyQt6 版

统一的 QDialog 样式：头部标题、卡片分段、按钮栏、字段行等。
"""

import logging

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QWidget, QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from ui.theme import C

logger = logging.getLogger(__name__)


class DialogBase(QDialog):
    """现代化对话框基类

    提供统一的头部、卡片分段、按钮栏与间距控制。
    """

    def __init__(self, parent=None, title="", geometry=(480, 360), modal=True):
        """初始化对话框窗口

        :param parent: 父窗口
        :param title: 窗口标题
        :param geometry: (width, height) 元组 或 "WxH" 字符串
        :param modal: 是否为模态对话框
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        if isinstance(geometry, str):
            w, h = geometry.split("x")
            geometry = (int(w), int(h))
        if geometry:
            self.resize(*geometry)
        self.setMinimumSize(300, 200)

        if modal and parent:
            self.setWindowModality(Qt.WindowModality.ApplicationModal)

        # ESC 关闭
        self.rejected.connect(self.reject)

        # 主容器
        self.container = QWidget(self)
        self._main_layout = QVBoxLayout(self.container)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.container)

    # ── 头部 ────────────────────────────────────────────

    def header(self, title, subtitle=None):
        """带分隔线的标题栏"""
        w = QWidget()
        w.setStyleSheet(f"background-color: {C['bg_surface']};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(24, 20, 24, 0)

        lbl = QLabel(title)
        font = QFont("Microsoft YaHei UI", 14)
        font.setBold(True)
        lbl.setFont(font)
        lbl.setStyleSheet(f"color: {C['text_1']};")
        layout.addWidget(lbl)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setFont(QFont("Microsoft YaHei UI", 9))
            sub.setStyleSheet(f"color: {C['text_3']};")
            layout.addWidget(sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {C['border']}; max-height: 1px;")
        layout.addWidget(sep)

        self._main_layout.addWidget(w)
        return w

    # ── 卡片分段 ─────────────────────────────────────────

    def section(self, parent=None, title=None, padding=14):
        """创建一个卡片风格的 Frame 分段"""
        p = parent or self.container

        sec = QFrame(p)
        sec.setStyleSheet(f"""
            QFrame {{
                background-color: {C['bg_elevated']};
                border: 1px solid {C['border_sub']};
                border-radius: {C['radius_md']}px;
            }}
        """)
        layout = QVBoxLayout(sec)
        layout.setContentsMargins(14, padding, 14, padding)

        if title:
            lbl = QLabel(title)
            font = QFont("Microsoft YaHei UI", 8)
            font.setBold(True)
            lbl.setFont(font)
            lbl.setStyleSheet(f"color: {C['text_2']};")
            layout.addWidget(lbl)

        self._main_layout.addWidget(sec)
        return sec

    # ── 按钮栏 ───────────────────────────────────────────

    def button_row(self, buttons):
        """底部操作按钮行

        buttons: [(text, callback, style), ...]
            style: "primary" | "danger" | "accent" | "" (default)
        """
        bar = QWidget()
        bar.setStyleSheet(f"background-color: {C['bg_surface']};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 16, 24, 20)

        # 分组：左侧 non-primary / 右侧 primary/danger/accent
        lefts = [b for b in buttons if b[2] in ("", "default")]
        rights = [b for b in buttons if b[2] not in ("", "default")]

        for text, callback, _ in lefts:
            btn = QPushButton(text)
            btn.clicked.connect(callback)
            layout.addWidget(btn)

        layout.addStretch()

        for text, callback, style in reversed(rights):
            btn = QPushButton(text)
            btn.clicked.connect(callback)
            if style == "primary":
                btn.setProperty("primary", True)
            elif style == "danger":
                btn.setProperty("danger", True)
            elif style == "accent":
                btn.setProperty("accent", True)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            layout.addWidget(btn)

        self._main_layout.addWidget(bar)
        return bar

    # ── 标签式行（字段+值）─────────────────────────────

    def field_row(self, parent, label, value_widget, label_width=14):
        """一行：左标签 + 右控件，适合表单"""
        row = QWidget(parent)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 2, 0, 2)

        lbl = QLabel(label)
        lbl.setFont(QFont("Microsoft YaHei UI", 9))
        lbl.setStyleSheet(f"color: {C['text_2']};")
        lbl.setMinimumWidth(label_width * 8)
        layout.addWidget(lbl)

        layout.addWidget(value_widget, 1)
        return row

    # ── 内容区（充满剩余空间，用于 Text / Treeview）────────

    def content_area(self, parent=None):
        """填充分段，适合放 QTextEdit / QTreeWidget"""
        p = parent or self.container
        w = QWidget(p)
        w.setStyleSheet(f"background-color: {C['bg_base']};")
        self._main_layout.addWidget(w, 1)  # stretch=1 fills space
        return w
