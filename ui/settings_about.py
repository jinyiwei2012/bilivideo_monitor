"""
关于作者标签页

Mixin functions for SettingsWindow.
"""

import os
import logging
import webbrowser
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QTextEdit, QCheckBox, QSpinBox,
    QDoubleSpinBox, QGroupBox, QTabWidget, QFrame, QMessageBox,
    QScrollArea, QSizePolicy, QHeaderView, QTreeWidget, QTreeWidgetItem,
    QGridLayout, QProgressBar, QSplitter, QDialog, QFileDialog,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from ui.theme import C
from ui.helpers import FONT, FONT_BOLD, FONT_SM, FONT_MONO, project_path
from algorithms.registry import AlgorithmRegistry
from algorithms.weight_manager import get_weight_manager
from utils.update_checker import _s, _hard, _train, _confirm_risky
from ui.scrollable_frame import ScrollableFrame

logger = logging.getLogger(__name__)


# ═══════════════ 辅助函数 ════════════════════════════════


def _styled_label(text, color_key="text_2", bold=False, font_=FONT):
    lbl = QLabel(text)
    style = f"color: {C[color_key]}; background: transparent;"
    if bold:
        style += " font-weight: bold;"
    lbl.setStyleSheet(style)
    lbl.setFont(font_)
    return lbl


def _field_wrapper(parent, label_text):
    """一行：标签 + 输入框"""
    row = QWidget(parent)
    row.setStyleSheet(f"background-color: {C['bg_elevated']};")
    rl = QHBoxLayout(row)
    rl.setContentsMargins(0, 3, 0, 3)
    lbl = _styled_label(label_text, font_=FONT)
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


# ═══════════════ 关于作者 ═══════════════════════════════


def _build_about_tab(self, nb):
    page = QWidget()
    page.setStyleSheet(f"background-color: {C['bg_base']};")
    nb.addTab(page, "  关于作者  ")
    page_layout = QVBoxLayout(page)
    page_layout.setContentsMargins(16, 16, 16, 16)

    from __init__ import __version__, __author__

    # 项目信息
    sec1 = QWidget()
    sec1.setStyleSheet(
        f"background-color: {C['bg_elevated']}; "
        f"border: 1px solid {C['border_sub']}; border-radius: 2px;"
    )
    sec1_layout = QVBoxLayout(sec1)
    sec1_layout.setContentsMargins(14, 10, 14, 10)

    sec1_title = _styled_label("项目信息", "text_2", bold=True)
    sec1_title.setStyleSheet(sec1_title.styleSheet() + " font-size: 9pt;")
    sec1_layout.addWidget(sec1_title)

    rows = [
        ("项目名称", "B站视频监控与播放量预测系统"),
        ("版本号", f"v{__version__}"),
        ("作者", __author__),
    ]
    for label, value in rows:
        row_w = QWidget()
        row_w.setStyleSheet(f"background-color: {C['bg_elevated']};")
        rl = QHBoxLayout(row_w)
        rl.setContentsMargins(0, 2, 0, 2)
        rl.addWidget(_styled_label(label, "text_3", font_=FONT))
        rl.addWidget(_styled_label(value, "text_1", font_=FONT))
        rl.addStretch()
        sec1_layout.addWidget(row_w)
    page_layout.addWidget(sec1)

    # 相关链接
    sec2 = QWidget()
    sec2.setStyleSheet(
        f"background-color: {C['bg_elevated']}; "
        f"border: 1px solid {C['border_sub']}; border-radius: 2px;"
    )
    sec2_layout = QVBoxLayout(sec2)
    sec2_layout.setContentsMargins(14, 10, 14, 10)

    sec2_title = _styled_label("相关链接", "text_2", bold=True)
    sec2_title.setStyleSheet(sec2_title.styleSheet() + " font-size: 9pt;")
    sec2_layout.addWidget(sec2_title)

    links = [
        ("GitHub", "https://github.com/jinyiwei2012/bilivideo_monitor", "项目源代码，欢迎 Star ⭐"),
        ("B站主页", "https://space.bilibili.com/1610751976", "作者的 Bilibili 个人空间"),
    ]
    for title, url, desc in links:
        row_w = QWidget()
        row_w.setStyleSheet(f"background-color: {C['bg_elevated']};")
        rl = QHBoxLayout(row_w)
        rl.setContentsMargins(0, 2, 0, 2)
        rl.addWidget(_styled_label(title, "text_3", font_=FONT))
        link_lbl = _styled_label(url, "bilibili" if "bilibili" in C else "text_1", font_=FONT)
        link_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        link_url = url
        link_lbl.mouseReleaseEvent = lambda ev: (webbrowser.open(link_url), None)[1]
        rl.addWidget(link_lbl)
        rl.addStretch()
        sec2_layout.addWidget(row_w)
    page_layout.addWidget(sec2)

    # 说明
    sec3 = QWidget()
    sec3.setStyleSheet(
        f"background-color: {C['bg_elevated']}; "
        f"border: 1px solid {C['border_sub']}; border-radius: 2px;"
    )
    sec3_layout = QVBoxLayout(sec3)
    sec3_layout.setContentsMargins(14, 10, 14, 10)

    sec3_title = _styled_label("说明", "text_2", bold=True)
    sec3_title.setStyleSheet(sec3_title.styleSheet() + " font-size: 9pt;")
    sec3_layout.addWidget(sec3_title)

    desc_text = (
        "本系统用于监控 Bilibili 视频播放量增长趋势，"
        "支持 55 种预测算法、多阈值告警、QQ 机器人通知等功能。\n\n"
        "如果您觉得本项目对您有帮助，欢迎在 GitHub 上给项目点一个 Star！"
    )
    desc_lbl = _styled_label(desc_text, "text_2", font_=FONT)
    desc_lbl.setWordWrap(True)
    sec3_layout.addWidget(desc_lbl)

    page_layout.addWidget(sec3)
    page_layout.addStretch()

