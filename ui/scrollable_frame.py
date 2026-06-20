"""
可滚动容器 — PyQt6 版

使用 QScrollArea 替代 tkinter Canvas + Scrollbar + Frame 模式。
用法::

    sf = ScrollableFrame(height=200)
    layout = sf.layout()  # 获取内部布局
"""

from PyQt6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from ui.theme import C


class ScrollableFrame(QScrollArea):
    """可垂直滚动的容器，用于在有限空间内展示大量子控件"""

    def __init__(self, parent=None, *, height=None, bg=None, mousewheel=True, **kwargs):
        """
        初始化可滚动容器

        :param parent: 父控件
        :param height: 固定高度（可选）
        :param bg: 背景色（可选）
        :param mousewheel: 是否启用鼠标滚轮滚动
        """
        super().__init__(parent)

        self._bg = bg or C.get("bg_elevated", "#1c2128")

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        if height is not None:
            self.setFixedHeight(height)

        # 样式
        bg_color = self._bg
        self.setStyleSheet(f"""
            QScrollArea {{
                background-color: {bg_color};
                border: none;
            }}
            QScrollBar:vertical {{
                background-color: {C['bg_hover']}; width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {C['border']}; border-radius: 4px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {C['text_3']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)

        # 内部容器
        self._inner = QWidget()
        self._inner.setStyleSheet(f"background-color: {bg_color};")
        self._layout = QVBoxLayout(self._inner)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addStretch()

        self.setWidget(self._inner)

    @property
    def inner(self):
        """获取内部容器 QWidget（可直接添加子控件）"""
        return self._inner

    def layout(self):
        """获取内部容器的 QVBoxLayout"""
        return self._layout

    def addWidget(self, widget):
        """向内部容器添加控件（在伸缩项之前）"""
        self._layout.insertWidget(self._layout.count() - 1, widget)

    def clear(self):
        """清空内部容器中除伸缩项外的所有控件"""
        from PyQt6.QtWidgets import QWidgetItem
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if isinstance(item, QWidgetItem):
                w = item.widget()
                if w is not None:
                    w.deleteLater()
