"""
设置面板通用辅助组件

提供跨 settings_*.py 标签页复用的 widget 构建函数，
避免各子模块重复定义相同的辅助函数。
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QDoubleSpinBox, QFrame,
)

from ui.theme import C
from ui.helpers import FONT


# ═══════════════ 标签与布局 ════════════════════════════════

def styled_label(text, color_key="text_2", bold=False, font_=FONT):
    """创建统一风格的 QLabel，支持颜色和粗体选项"""
    lbl = QLabel(text)
    style = f"color: {C[color_key]}; background: transparent;"
    if bold:
        style += " font-weight: bold;"
    lbl.setStyleSheet(style)
    lbl.setFont(font_)
    return lbl


def field_wrapper(parent, label_text):
    """创建一行：标签(120px) + 输入框(240px)"""
    row = QWidget(parent)
    row.setStyleSheet(f"background-color: {C['bg_elevated']};")
    rl = QHBoxLayout(row)
    rl.setContentsMargins(0, 3, 0, 3)
    lbl = styled_label(label_text, font_=FONT)
    lbl.setFixedWidth(120)
    rl.addWidget(lbl)
    entry = QLineEdit()
    entry.setMinimumWidth(240)
    entry.setStyleSheet(
        f"background-color: {C['bg_base']}; color: {C['text_1']}; "
        f"border: 1px solid {C['border']}; border-radius: 2px; padding: 2px 4px;"
    )
    entry.setFont(FONT)
    rl.addWidget(entry)
    rl.addStretch()
    return entry


# ═══════════════ 表单字段构建 ════════════════════════════════

def make_field(parent, label, default, show=None):
    """创建一行标签(130px) + QLineEdit"""
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 2, 0, 2)

    lbl = QLabel(label)
    lbl.setStyleSheet(f"color: {C['text_2']};")
    lbl.setFixedWidth(130)
    layout.addWidget(lbl)

    entry = QLineEdit(default)
    entry.setStyleSheet(f"background-color: {C['bg_base']}; color: {C['text_1']};")
    if show:
        entry.setEchoMode(QLineEdit.EchoMode.Password)
    layout.addWidget(entry, 1)
    return entry


def make_spin_field(parent, label, default, fr, to):
    """创建一行标签(130px) + QSpinBox(整数)"""
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 2, 0, 2)

    lbl = QLabel(label)
    lbl.setStyleSheet(f"color: {C['text_2']};")
    lbl.setFixedWidth(130)
    layout.addWidget(lbl)

    spin = QSpinBox()
    spin.setRange(fr, to)
    spin.setValue(int(default))
    layout.addWidget(spin)
    layout.addStretch()
    return spin


def make_spin_field_float(parent, label, default, fr, to):
    """创建一行标签(130px) + QDoubleSpinBox(浮点数)"""
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 2, 0, 2)

    lbl = QLabel(label)
    lbl.setStyleSheet(f"color: {C['text_2']};")
    lbl.setFixedWidth(130)
    layout.addWidget(lbl)

    spin = QDoubleSpinBox()
    spin.setRange(fr, to)
    spin.setValue(default)
    spin.setSingleStep(0.1)
    spin.setDecimals(2)
    layout.addWidget(spin)
    layout.addStretch()
    return spin


def make_section_widget(parent, title):
    """创建一个卡片分段的 QFrame"""
    sec = QFrame(parent)
    sec.setStyleSheet(f"""
        QFrame {{
            background-color: {C['bg_elevated']};
            border: 1px solid {C['border_sub']};
            border-radius: {C['radius_md']}px;
        }}
    """)
    layout = QVBoxLayout(sec)
    if title:
        lbl = QLabel(title)
        lbl.setStyleSheet(f"color: {C['text_2']}; font-weight: bold; font-size: 8pt;")
        layout.addWidget(lbl)
    return sec
