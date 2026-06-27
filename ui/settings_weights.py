"""
权重设置标签页
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


class SettingsWeightsMixin:
    """Algorithm weight configuration settings tab."""

    def _build_weights_tab(self, nb):
        page = QWidget()
        page.setStyleSheet(f"background-color: {C['bg_base']};")
        nb.addTab(page, "  权重设置  ")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        info_sec = QWidget()
        info_sec.setStyleSheet(
            f"background-color: {C['bg_elevated']}; "
            f"border: 1px solid {C['border_sub']}; border-radius: 2px;"
        )
        info_layout = QVBoxLayout(info_sec)
        info_layout.setContentsMargins(14, 10, 14, 8)
        for line in [
            "• 用户自定义权重优先级最高，机器学习不会修改已自定义的权重",
            "• 权重范围：0.01 ~ 10.0",
            "• 权重越高，该算法在综合预测中占比越大",
        ]:
            info_layout.addWidget(_styled_label(line, "text_2", font_=FONT_SM))
        page_layout.addWidget(info_sec)

        # 表头
        hdr = QWidget()
        hdr.setStyleSheet(
            f"background-color: {C['bg_surface']}; "
            f"border: 1px solid {C['border_sub']};"
        )
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(6, 4, 6, 4)
        col_defs = [("算法", 200), ("自定义", 70), ("权重值", 100), ("ML权重", 100), ("准确率", 100), ("样本数", 80)]
        for text, w in col_defs:
            lbl = _styled_label(text, "text_2", bold=True, font_=FONT_SM)
            lbl.setFixedWidth(w)
            hdr_layout.addWidget(lbl)
        hdr_layout.addStretch()
        page_layout.addWidget(hdr)

        # 可滚动算法列表
        sf = ScrollableFrame(bg=C["bg_elevated"])
        page_layout.addWidget(sf, stretch=1)
        self._weight_vars = {}
        self._weight_check_vars = {}

        # 确保 algo_frame 有 layout
        algo_frame = sf.inner
        algo_frame.setStyleSheet(f"background-color: {C['bg_elevated']};")
        if algo_frame.layout() is None:
            QVBoxLayout(algo_frame)

        algo_info = AlgorithmRegistry.get_weights_info()
        for info in algo_info:
            row = QWidget()
            row.setStyleSheet(
                f"background-color: {C['bg_surface']}; "
                f"border-bottom: 1px solid {C['border_sub']};"
            )
            rl = QHBoxLayout(row)
            rl.setContentsMargins(4, 2, 4, 2)

            name = info["name"]
            name_lbl = _styled_label(name, "text_1", font_=FONT)
            name_lbl.setFixedWidth(200)
            rl.addWidget(name_lbl)

            cb = QCheckBox()
            cb.setChecked(info["is_customized"])
            self._weight_check_vars[name] = cb
            rl.addWidget(cb)
            rl.addSpacing(30)

            sb = QDoubleSpinBox()
            sb.setRange(0.01, 10.0)
            sb.setSingleStep(0.01)
            sb.setDecimals(2)
            sb.setValue(info.get("user_weight") or info.get("final_weight", 1.0))
            sb.setFixedWidth(90)
            self._weight_vars[name] = sb
            rl.addWidget(sb)
            rl.addSpacing(10)

            ml_w = info.get("ml_weight", 1.0)
            rl.addWidget(_styled_label(f"{ml_w:.2f}", "text_3", font_=FONT_MONO))
            rl.addSpacing(10)

            acc = info.get("accuracy", 0)
            acc_lbl = _styled_label(f"{acc * 100:.1f}%", "success" if acc > 0 else "text_3", font_=FONT_MONO)
            acc_lbl.setFixedWidth(80)
            rl.addWidget(acc_lbl)

            samples = info.get("samples", 0)
            samples_lbl = _styled_label(str(samples), "text_2", font_=FONT_MONO)
            samples_lbl.setFixedWidth(80)
            rl.addWidget(samples_lbl)

            rl.addStretch()
            layout = algo_frame.layout()
            if layout:
                layout.addWidget(row)

        # 按钮行
        btn_row = QWidget()
        btn_row.setStyleSheet(f"background-color: {C['bg_base']};")
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(16, 8, 16, 12)

        reset_btn = QPushButton("重置所有权重")
        reset_btn.clicked.connect(lambda: self._reset_all_weights() if _confirm_risky("重置算法权重") else None)
        btn_layout.addWidget(reset_btn)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._refresh_weights)
        btn_layout.addWidget(refresh_btn)

        btn_layout.addStretch()

        save_weight_btn = QPushButton("💾 保存权重")
        save_weight_btn.clicked.connect(lambda: _confirm_risky("保存算法权重") and self._save_weights())
        btn_layout.addWidget(save_weight_btn)

        page_layout.addWidget(btn_row)


    def _reset_all_weights(self):
        if QMessageBox.question(self.dlg, "确认", "确定要重置所有自定义权重吗？",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            get_weight_manager().reset_weights()
            self._refresh_weights()
            QMessageBox.information(self.dlg, "成功", "已重置所有权重")


    def _refresh_weights(self):
        algo_info = AlgorithmRegistry.get_weights_info()
        for info in algo_info:
            name = info["name"]
            if name in self._weight_vars:
                self._weight_vars[name].setValue(info.get("user_weight") or info.get("final_weight", 1.0))
            if name in self._weight_check_vars:
                self._weight_check_vars[name].setChecked(info["is_customized"])


    def _save_weights(self):
        for name, cb in self._weight_check_vars.items():
            sb = self._weight_vars.get(name)
            if not sb:
                continue
            weight = max(0.01, min(10.0, sb.value()))
            if cb.isChecked():
                get_weight_manager().set_user_weight(name, weight)
            else:
                get_weight_manager().clear_user_weight(name)
        QMessageBox.information(self.dlg, "成功", "权重设置已保存")
