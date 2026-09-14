"""
现代化对话框基类 — PyQt6 版

统一的 QDialog 样式：头部标题、卡片分段、按钮栏、字段行等。
"""

import logging
import re

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QPushButton,
    QWidget,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from ui.theme import C

logger = logging.getLogger(__name__)


class DialogBase(QDialog):
    """现代化对话框基类

    提供统一的头部、卡片分段、按钮栏与间距控制。
    """

    # "WxH" 解析用（非法输入不抛异常）
    _GEOMETRY_RE = re.compile(r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$")
    # 尺寸上限：拦住会让 QWidget.resize() 抛 OverflowError 的天文数字
    _MAX_DIM = 100000
    # 字号/粗体 → QFont 缓存：字体仅由 family+size+bold 决定，同键等价，可安全复用
    _FONT_CACHE: dict = {}

    def __init__(self, parent=None, title="", geometry=(480, 360), modal=True, icon=True):
        """初始化对话框窗口

        :param parent: 父窗口
        :param title: 窗口标题
        :param geometry: (width, height) 元组 或 "WxH" 字符串；非法输入回退 (480, 360)
        :param modal: 是否为模态对话框
        :param icon: 是否套用主程序窗口图标（资源缺失则静默跳过）
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        parsed = self._parse_geometry(geometry)
        if parsed:
            self.resize(*parsed)
        self.setMinimumSize(300, 200)
        if icon:
            self._apply_window_icon()

        if modal and parent:
            self.setWindowModality(Qt.WindowModality.ApplicationModal)

        # ESC 关闭：QDialog 原生已处理（Esc → reject()），此处**不能**再
        # `self.rejected.connect(self.reject)` —— reject() 自身会 emit rejected，
        # 该自反连接会造成无限递归，实测关闭窗口即栈溢出崩溃（0xC00000FD）。

        # 主容器
        self.container = QWidget(self)
        self._main_layout = QVBoxLayout(self.container)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.container)

    # ── 尺寸 / 字体 / 图标 ────────────────────────────────

    @classmethod
    def _parse_geometry(cls, geometry):
        """解析 geometry；非法/越界输入回退默认尺寸 ``(480, 360)``，绝不抛异常。

        上限 ``_MAX_DIM`` 用于拦住 ``"999999999999999999999x1"`` 这类能通过正则、
        却会让 ``QWidget.resize()`` 抛 ``OverflowError`` 的输入。
        """
        fallback = (480, 360)
        if isinstance(geometry, str):
            m = cls._GEOMETRY_RE.match(geometry)
            if m is None:
                logger.warning("非法 geometry 字符串 %r，回退默认尺寸", geometry)
                return fallback
            candidate = (int(m.group(1)), int(m.group(2)))
        elif not geometry:
            return fallback
        else:
            try:
                candidate = (int(geometry[0]), int(geometry[1]))
            except Exception:
                logger.warning("非法 geometry %r，回退默认尺寸", geometry)
                return fallback
        width, height = candidate
        if not (1 <= width <= cls._MAX_DIM and 1 <= height <= cls._MAX_DIM):
            logger.warning("geometry 尺寸越界 %r，回退默认尺寸", geometry)
            return fallback
        return candidate

    @classmethod
    def _font(cls, size: int, bold: bool = False) -> QFont:
        """取 ``"Microsoft YaHei UI"`` 字号的 QFont（缓存原型 + 隐式共享副本）。

        返回**副本**：调用方可以安全地改字号/字重而不污染后续调用者。
        """
        key = (size, bold)
        proto = cls._FONT_CACHE.get(key)
        if proto is None:
            proto = QFont("Microsoft YaHei UI", size)
            proto.setBold(bold)
            cls._FONT_CACHE[key] = proto
        return QFont(proto)

    def _apply_window_icon(self) -> None:
        """套用主程序窗口图标（资源缺失或导入失败时静默跳过，不影响弹窗显示）。"""
        try:
            import os

            from PyQt6.QtGui import QIcon

            from utils import project_path

            path = project_path("assets", "app_icon.png")
            if os.path.exists(path):
                self.setWindowIcon(QIcon(path))
        except Exception as e:
            logger.debug("设置弹窗图标失败: %s", e)

    # ── 头部 ────────────────────────────────────────────

    def header(self, title, subtitle=None):
        """带分隔线的标题栏"""
        w = QWidget()
        w.setStyleSheet(f"background-color: {C['bg_surface']};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(24, 20, 24, 0)

        lbl = QLabel(title)
        lbl.setFont(self._font(14, bold=True))
        lbl.setStyleSheet(f"color: {C['text_1']};")
        layout.addWidget(lbl)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setFont(self._font(9))
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
        """创建一个卡片风格的 Frame 分段。

        ``parent`` 非空时挂到 **parent 自己的布局**（parent 无布局则退回主布局），
        使调用方能把握分段放进自己的容器（如 health_probe 的 bottom 区）；
        ``parent`` 为空时行为与原先一致（挂主布局）。
        """
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
            lbl.setFont(self._font(8, bold=True))
            lbl.setStyleSheet(f"color: {C['text_2']};")
            layout.addWidget(lbl)

        host_layout = self._main_layout
        if parent is not None:
            parent_layout = parent.layout()
            if parent_layout is not None:
                host_layout = parent_layout
        host_layout.addWidget(sec)
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
            style_obj = btn.style()
            if style_obj is not None:
                style_obj.unpolish(btn)
                style_obj.polish(btn)
            layout.addWidget(btn)

        self._main_layout.addWidget(bar)
        return bar

    # ── 内容区（充满剩余空间，用于 Text / Treeview）────────

    def content_area(self, parent=None):
        """填充分段，适合放 QTextEdit / QTreeWidget"""
        p = parent or self.container
        w = QWidget(p)
        w.setStyleSheet(f"background-color: {C['bg_base']};")
        self._main_layout.addWidget(w, 1)  # stretch=1 fills space
        return w
