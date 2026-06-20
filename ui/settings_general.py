"""
常规设置（预测参数 + 重试参数 + 运行状态）— PyQt6 版

Mixin functions for SettingsWindow.
"""

import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QMessageBox, QFrame,
)
from PyQt6.QtCore import Qt, QTimer
from ui.theme import C
from ui.helpers import FONT
from core.bilibili_api import get_bilibili_api
from utils.update_checker import _confirm_risky

logger = logging.getLogger(__name__)


def _build_general_tab(self, nb):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    nb.addTab(page, "  常规设置  ")

    self._build_general_predict_section(page)
    self._build_general_retry_section(page)
    self._build_general_status_section(page)


def _build_general_predict_section(self, page):
    sec = self._section(page, "预测参数")
    self.predict_hours = self._spin_field(
        sec, "预测时长(小时)", self._cfg.get("prediction", {}).get("prediction_hours", 168), 24, 720
    )
    self.min_confidence = self._spin_field_float(
        sec, "最小置信度", self._cfg.get("prediction", {}).get("min_confidence", 0.5), 0.1, 1.0
    )


def _build_general_retry_section(self, page):
    sec = QFrame(page)
    sec.setStyleSheet(
        f"background-color: {C['bg_elevated']}; border: 1px solid {C['border_sub']}; border-radius: 4px;"
    )
    sec_layout = QVBoxLayout(sec)
    page.layout().addWidget(sec)

    title = QLabel("重试参数")
    title.setStyleSheet(f"color: {C['text_2']}; font-weight: bold; font-size: 8pt;")
    sec_layout.addWidget(title)

    def _spin_r(parent, label, default, fr, to):
        f = QWidget(parent)
        fl = QHBoxLayout(f)
        fl.setContentsMargins(0, 2, 0, 2)
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {C['text_2']};")
        lbl.setFixedWidth(160)
        fl.addWidget(lbl)
        sp = QDoubleSpinBox()
        sp.setRange(fr, to)
        sp.setValue(default)
        sp.setDecimals(0 if isinstance(default, int) else 1)
        fl.addWidget(sp)
        fl.addStretch()
        sec_layout.addWidget(f)
        return sp

    self.retry_count_var = _spin_r(sec, "最大重试次数", get_bilibili_api().max_retries, 1, 10)
    self.base_delay_var = _spin_r(sec, "基础重试延迟(秒)", get_bilibili_api().base_retry_delay, 1, 30)
    self.min_interval_var = _spin_r(sec, "最小请求间隔(秒)", get_bilibili_api()._min_request_interval, 0.1, 10)

    apply_btn = QPushButton("应用重试设置")
    apply_btn.clicked.connect(self._apply_retry_settings)
    sec_layout.addWidget(apply_btn)


def _build_general_status_section(self, page):
    sec = QFrame(page)
    sec.setStyleSheet(
        f"background-color: {C['bg_elevated']}; border: 1px solid {C['border_sub']}; border-radius: 4px;"
    )
    sec_layout = QVBoxLayout(sec)
    page.layout().addWidget(sec)

    title = QLabel("运行状态")
    title.setStyleSheet(f"color: {C['text_2']}; font-weight: bold; font-size: 8pt;")
    sec_layout.addWidget(title)

    self.status_labels = {}
    fields = [
        ("is_login", "登录状态"),
        ("login_name", "登录账号"),
        ("has_cookies", "Cookie已配置"),
        ("consecutive_412_errors", "连续412错误"),
        ("min_request_interval", "请求间隔(秒)"),
        ("proxy_count", "代理数量"),
    ]
    for key, field_label in fields:
        f = QWidget(sec)
        fl = QHBoxLayout(f)
        fl.setContentsMargins(0, 2, 0, 2)
        lbl = QLabel(field_label)
        lbl.setStyleSheet(f"color: {C['text_2']};")
        lbl.setFixedWidth(130)
        fl.addWidget(lbl)
        vl = QLabel("-")
        vl.setStyleSheet(f"color: {C['success']};")
        fl.addWidget(vl)
        fl.addStretch()
        sec_layout.addWidget(f)
        self.status_labels[key] = vl

    btn_s = QWidget(sec)
    btn_sl = QHBoxLayout(btn_s)
    btn_sl.setContentsMargins(0, 4, 0, 0)
    refresh_btn = QPushButton("刷新状态")
    refresh_btn.clicked.connect(self._refresh_status)
    btn_sl.addWidget(refresh_btn)
    reset_btn = QPushButton("重置状态")
    reset_btn.clicked.connect(lambda: _confirm_risky("重置 API 状态") and self._reset_status())
    btn_sl.addWidget(reset_btn)
    btn_sl.addStretch()
    sec_layout.addWidget(btn_s)

    self._refresh_status()


def _apply_retry_settings(self):
    get_bilibili_api().max_retries = int(self.retry_count_var.value())
    get_bilibili_api().base_retry_delay = self.base_delay_var.value()
    get_bilibili_api()._min_request_interval = self.min_interval_var.value()
    QMessageBox.information(self.window, "成功", "重试设置已更新")


def _refresh_status(self):
    import threading

    def _worker():
        try:
            status = get_bilibili_api().get_status()
        except Exception as e:
            logger.debug("获取状态失败: %s", e)
            status = {}
        QTimer.singleShot(0, lambda s=status: self._apply_status(s))

    threading.Thread(target=_worker, daemon=True).start()


def _apply_status(self, status: dict):
    for key, label in self.status_labels.items():
        value = status.get(key, "N/A")
        if key == "is_login":
            v = "✅ 已登录" if value else "❌ 未登录"
            label.setStyleSheet(f"color: {C['success'] if value else C['danger']};")
        elif key == "login_name":
            v = str(value) if value else "—"
            label.setStyleSheet(f"color: {C['text_1'] if value else C['text_3']};")
        elif key == "has_cookies":
            v = "是" if value else "否"
            label.setStyleSheet(f"color: {C['success'] if value else C['danger']};")
        elif key == "consecutive_412_errors":
            v = str(value)
            label.setStyleSheet(f"color: {C['danger'] if value and value > 0 else C['success']};")
        else:
            v = str(value)
            label.setStyleSheet(f"color: {C['success']};")
        label.setText(v)


def _reset_status(self):
    reply = QMessageBox.question(
        self.window, "确认", "确定要重置所有状态吗？",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    if reply == QMessageBox.StandardButton.Yes:
        get_bilibili_api().reset_status()
        self._refresh_status()
