"""
OneBot / Notification / Webhook 通知设置 — PyQt6 版
"""

import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QMessageBox, QComboBox,
)
from PyQt6.QtCore import Qt
from ui.theme import C

logger = logging.getLogger(__name__)

_WEBHOOK_TYPES = [
    ("自定义", "generic"),
    ("企业微信", "wecom"),
    ("钉钉", "dingtalk"),
    ("Slack", "slack"),
    ("Discord", "discord"),
]


class SettingsNotificationMixin:
    """OneBot / Webhook notification settings tab."""

    def _build_notification_tab(self, nb):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        nb.addTab(page, "  通知设置  ")

        self._webhook_rows = []  # (name_entry, type_combo, url_entry, row_widget)
        self._webhook_sec_layout = None  # Webhook section 卡片布局

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

        # ── Webhook 机器人 ──
        self._build_webhook_section(page)

    def _build_webhook_section(self, page):
        """Webhook 机器人：企业微信 / 钉钉 / Slack / Discord / 自定义"""
        sec = self._section(page, "Webhook 机器人")
        self._webhook_sec_layout = sec.layout()

        saved = self._cfg.get("notification", {}).get("webhooks", []) or []
        for wh in saved:
            if isinstance(wh, dict) and wh.get("url"):
                self._add_webhook_row(
                    wh.get("name", ""), wh.get("type", "generic"), wh.get("url", "")
                )

        add_btn = QPushButton("＋ 添加机器人")
        add_btn.clicked.connect(lambda: self._add_webhook_row())
        self._webhook_sec_layout.addWidget(add_btn)

        hint = QLabel("支持 企业微信/钉钉/Slack/Discord/自定义。填入机器人 Webhook 地址后,阈值突破、告警、报告都会同步推送 ♪ (仅限公网 http/https 地址,内网/回环地址会被安全策略拦截)")
        hint.setStyleSheet(f"color: {C['text_3']}; font-size: 8pt;")
        hint.setWordWrap(True)
        self._webhook_sec_layout.addWidget(hint)

    def _add_webhook_row(self, name="", wh_type="generic", url=""):
        """添加一行 Webhook 配置 (名称, 类型, URL, 测试, 移除)"""
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)

        name_entry = QLineEdit(name)
        name_entry.setPlaceholderText("名称")
        name_entry.setFixedWidth(90)
        rl.addWidget(name_entry)

        type_combo = QComboBox()
        for label, val in _WEBHOOK_TYPES:
            type_combo.addItem(label, val)
        ti = type_combo.findData(wh_type)
        type_combo.setCurrentIndex(ti if ti >= 0 else 0)
        rl.addWidget(type_combo)

        url_entry = QLineEdit(url)
        url_entry.setPlaceholderText("https://…/webhook 地址")
        rl.addWidget(url_entry, 1)

        test_btn = QPushButton("测试")
        test_btn.clicked.connect(lambda _, w=row: self._test_webhook_row(w))
        rl.addWidget(test_btn)

        rm_btn = QPushButton("✕")
        rm_btn.setFixedWidth(28)
        rm_btn.clicked.connect(lambda _, w=row: self._remove_webhook_row(w))
        rl.addWidget(rm_btn)

        self._webhook_rows.append((name_entry, type_combo, url_entry, row))
        # 插到「＋ 添加机器人」按钮之前（该按钮与提示文字位于列表末尾）
        if self._webhook_sec_layout is not None:
            insert_idx = self._webhook_sec_layout.count() - 2
            self._webhook_sec_layout.insertWidget(max(0, insert_idx), row)

    def _remove_webhook_row(self, row_widget):
        """移除一行 Webhook 配置"""
        for entry in list(self._webhook_rows):
            if entry[3] is row_widget:
                self._webhook_rows.remove(entry)
                break
        if self._webhook_sec_layout is not None:
            self._webhook_sec_layout.removeWidget(row_widget)
        row_widget.deleteLater()

    def _test_webhook_row(self, row_widget):
        """测试单行 Webhook 配置（后台线程,避免阻塞 UI）"""
        entry = next((e for e in self._webhook_rows if e[3] is row_widget), None)
        if entry is None:
            return
        name_entry, type_combo, url_entry, _ = entry
        url = url_entry.text().strip()
        if not url:
            QMessageBox.warning(self.dlg, "要注意哦…", "呜…Webhook 地址还是空的呢,先填上才能试音哦 ♪")
            return
        wh = {"name": name_entry.text().strip() or "webhook", "type": type_combo.currentData(), "url": url}
        from core.notification import notification_manager

        def _do_test():
            result = notification_manager.test_webhook(wh)
            from PyQt6.QtCore import QTimer

            QTimer.singleShot(0, lambda: self._show_webhook_test_result(result, wh["name"]))

        from threading import Thread

        Thread(target=_do_test, daemon=True).start()

    def _show_webhook_test_result(self, result: dict, name: str):
        if result.get("ok"):
            QMessageBox.information(
                self.dlg,
                "连接成功啦 ♪",
                f"「{name}」Webhook 试音成功!♪ 天依的声音传过去啦~",
            )
        else:
            logger.warning("Webhook 测试失败: %s", result.get("error", "未知错误"))
            QMessageBox.critical(
                self.dlg,
                "呜…连接失败了",
                f"「{name}」Webhook 没连上呢…\n{result.get('error', '未知错误')}\n\n像天使鱼在冰海里迷了路,检查一下地址哦 ♪",
            )

    def _test_connection(self):
        http_url = self.onebot_http.text().strip()
        ws_url = self.onebot_ws.text().strip()
        token = self.onebot_token.text().strip()

        if not http_url:
            QMessageBox.warning(self.dlg, "要注意哦…", "呜…HTTP 地址还是空的呢,先填上才能听到 OneBot 的歌声哦 ♪")
            return

        from core.notification import notification_manager
        from threading import Thread

        # 测试参数直接传入 test_connection,不改写全局单例(避免与真实发送竞争)
        def _do_test():
            try:
                result = notification_manager.test_connection(
                    http_url=http_url, ws_url=ws_url, token=token
                )
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, lambda: self._show_test_result(result))
            except Exception as e:
                logger.warning("OneBot 连接测试异常: %s", e)
                err = str(e)  # 绑定到局部变量：except 块结束后 e 会被删除，闭包需捕获 err
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, lambda: self._show_test_result({"ok": False, "error": err}))

        Thread(target=_do_test, daemon=True).start()

    def _show_test_result(self, result: dict):
        if result["ok"]:
            ver = result.get("version", "") or "未知版本"
            channel = result.get("channel", "HTTP")
            QMessageBox.information(
                self.dlg,
                "连接成功啦 ♪",
                f"连接成功啦!♪ 天依听到远方的歌声了\n\n通道: {channel}\n版本: {ver}",
            )
        else:
            logger.warning("OneBot 服务连接失败: %s", result.get("error", "未知错误"))
            QMessageBox.critical(
                self.dlg,
                "呜…连接失败了",
                "呜…连接不上呢,像天使鱼在冰海里迷了路,检查一下配置哦 ♪",
            )
