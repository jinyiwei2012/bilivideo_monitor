"""
OneBot / Notification 通知设置 — PyQt6 版

Mixin functions for SettingsWindow.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QMessageBox,
)
from PyQt6.QtCore import Qt
from ui.theme import C


def _build_notification_tab(self, nb):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    nb.addTab(page, "  通知设置  ")

    sec = self._section(page, "OneBot 连接参数")
    self.onebot_http = self._field(
        sec, "HTTP地址", self._cfg.get("onebot", {}).get("http_url", "http://127.0.0.1:5700")
    )
    self.onebot_ws = self._field(sec, "WebSocket地址", self._cfg.get("onebot", {}).get("ws_url", "ws://127.0.0.1:6700"))
    self.onebot_token = self._field(sec, "Access Token", self._cfg.get("onebot", {}).get("access_token", ""), show_password=True)
    self.qq_private = self._field(sec, "私聊QQ号", self._cfg.get("onebot", {}).get("private_qq", ""))
    self.qq_group = self._field(sec, "群号", self._cfg.get("onebot", {}).get("group_qq", ""))

    enabled = self._cfg.get("onebot", {}).get("enabled", False)
    self.onebot_enabled = QCheckBox("启用 OneBot 通知")
    self.onebot_enabled.setChecked(enabled)
    self.onebot_enabled.setStyleSheet(f"color: {C['text_2']};")
    sec.layout().addWidget(self.onebot_enabled)

    test_btn = QPushButton("测试连接")
    test_btn.clicked.connect(self._test_connection)
    sec.layout().addWidget(test_btn)


def _test_connection(self):
    http_url = self.onebot_http.text().strip()
    token = self.onebot_token.text().strip()

    if not http_url:
        QMessageBox.warning(self.dlg, "提示", "请先填写 HTTP 地址")
        return

    from core.notification import notification_manager
    from threading import Thread

    saved_http = notification_manager.onebot_http
    saved_ws = notification_manager.onebot_ws
    saved_token = notification_manager.token
    notification_manager.onebot_http = http_url
    notification_manager.onebot_ws = self.onebot_ws.text().strip() or saved_ws
    notification_manager.token = token

    def _do_test():
        try:
            result = notification_manager.test_connection()
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._show_test_result(result))
        finally:
            notification_manager.onebot_http = saved_http
            notification_manager.onebot_ws = saved_ws
            notification_manager.token = saved_token

    Thread(target=_do_test, daemon=True).start()


def _show_test_result(self, result: dict):
    if result["ok"]:
        ver = result.get("version", "") or "未知版本"
        channel = result.get("channel", "HTTP")
        QMessageBox.information(
            self.dlg,
            "连接成功",
            f"✅ OneBot 服务连接成功\n\n通道: {channel}\n版本: {ver}",
        )
    else:
        QMessageBox.critical(
            self.dlg,
            "连接失败",
            f"❌ OneBot 服务连接失败\n\n原因: {result.get('error', '未知错误')}",
        )
