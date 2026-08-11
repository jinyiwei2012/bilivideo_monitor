"""
关于作者标签页
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

from ui.settings_common import styled_label as _styled_label, field_wrapper as _field_wrapper

logger = logging.getLogger(__name__)


class SettingsAboutMixin:
    """About author settings tab."""

    def _build_about_tab(self, nb):
        page = QWidget()
        page.setStyleSheet(f"background-color: {C['bg_base']};")
        nb.addTab(page, "  关于作者  ")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(16, 16, 16, 16)

        from __init__ import __version__, __author__

        # 洛天依主题区 (品牌致敬)
        hero = QWidget()
        hero.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {C['lty_wave_a']}, stop:1 {C['lty_wave_b']}); "
            "border: none; border-radius: 6px;"
        )
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(14, 12, 14, 12)
        hero_layout.setSpacing(10)

        feather = QLabel("羽")
        feather.setAlignment(Qt.AlignmentFlag.AlignCenter)
        feather.setFixedSize(34, 34)
        feather.setStyleSheet(
            "color: white; background-color: rgba(255,255,255,60); "
            "font-size: 16px; font-weight: bold; border-radius: 17px;"
        )
        hero_layout.addWidget(feather)

        hero_text = QWidget()
        hero_text.setStyleSheet("background: transparent;")
        ht = QVBoxLayout(hero_text)
        ht.setContentsMargins(0, 0, 0, 0)
        ht.setSpacing(2)
        t1 = _styled_label("♪ 天依陪你一起看播放量", "white" if False else "text_1", bold=True)
        t1.setStyleSheet("color: white; font-size: 13px; background: transparent;")
        ht.addWidget(t1)
        t2 = _styled_label("「华风夏韵, 洛水天依」· 追着光, 一起向前吧 ♪", "text_3")
        t2.setStyleSheet("color: rgba(255,255,255,200); font-size: 9px; background: transparent;")
        ht.addWidget(t2)
        hero_layout.addWidget(hero_text, 1)
        page_layout.addWidget(hero)

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
            ("GitHub", "https://github.com/jinyiwei2012/bilivideo_monitor", "项目源代码，欢迎 Star ★"),
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
            link_lbl.mouseReleaseEvent = lambda ev: webbrowser.open(link_url)
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
