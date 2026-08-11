"""洛天依设计系统组件库 — 统一区块头 / 空状态 / 水波装饰元素。

设计语言: 清新国风 + 科技感 (源自洛天依品牌视觉)
- 天依蓝 #66CCFF 为主强调色
- 「羽」/ ♪ 音符 / 水波纹为标志性元素
- 统一排版层级: FONT_TITLE / FONT_SECTION / FONT_CAPTION
"""
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame
from PyQt6.QtCore import Qt

from ui.theme import C
from ui.helpers import FONT_TITLE, FONT_SECTION, FONT_CAPTION, SPACE_MD


class SectionHeader(QWidget):
    """天依蓝竖条 + 标题的统一样式区块头。

    用于各面板区块标题, 统一排版层级与视觉节奏:
        │ 区块标题   副标题 (可选)
    """
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        bar = QFrame()
        bar.setFixedSize(3, 14)
        bar.setStyleSheet(
            f"background-color: {C['lty_blue']}; border: none; border-radius: 1px;"
        )
        h.addWidget(bar)

        title_lbl = QLabel(title)
        title_lbl.setFont(FONT_TITLE)
        title_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
        h.addWidget(title_lbl)

        if subtitle:
            sub_lbl = QLabel(subtitle)
            sub_lbl.setFont(FONT_CAPTION)
            sub_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
            h.addWidget(sub_lbl)

        h.addStretch()

    @staticmethod
    def section_label(title: str, parent=None) -> QLabel:
        """小章节标题 (FONT_SECTION, 天依蓝)。"""
        lbl = QLabel(title, parent)
        lbl.setFont(FONT_SECTION)
        lbl.setStyleSheet(f"color: {C['lty_blue_deep']}; background: transparent;")
        return lbl


class EmptyState(QWidget):
    """洛天依风格空状态: ♪ 音符 + 提示文案。

    用于列表/图表无数据时的占位, 替代生硬的"暂无数据"文字。
    """
    def __init__(self, text: str = "暂无数据", parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)

        note = QLabel("♪")
        note.setStyleSheet(
            f"color: {C['lty_blue']}; font-size: 30px; background: transparent;"
        )
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(note)

        tip = QLabel(text)
        tip.setFont(FONT_CAPTION)
        tip.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(tip)


class WaveDivider(QFrame):
    """天依蓝水波渐变分割线 — 呼应「洛水天依」意象。"""
    def __init__(self, height: int = 2, parent=None):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {C['lty_wave_a']}, stop:1 {C['lty_wave_b']}); "
            "border: none;"
        )


class FeatherBadge(QFrame):
    """「羽」字徽章 — 洛天依象征符号 (五音之羽)。"""
    def __init__(self, size: int = 22, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        badge = QLabel("羽", self)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"color: white; background-color: {C['lty_blue']}; "
            f"font-size: {int(size * 0.5)}px; font-weight: bold; "
            f"border-radius: {size // 2}px;"
        )
        badge.setGeometry(0, 0, size, size)
