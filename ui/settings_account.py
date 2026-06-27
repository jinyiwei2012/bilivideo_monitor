"""
账号 / Cookie 设置 — PyQt6 版
"""

import json
import logging
import threading
from typing import Optional, Dict

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QPlainTextEdit, QMessageBox, QDialog,
    QFrame, QDialogButtonBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QPixmap

from ui.theme import C
from ui.helpers import FONT, FONT_SM
from ui.invoker import invoke
from ui.settings_account_dialogs import (
    _CookieEditorDialog,
    _QRCodeLoginDialog,
    _PasswordLoginDialog,
    _AddAccountDialog,
)
from core.bilibili_api import get_bilibili_api
from utils.update_checker import _s

logger = logging.getLogger(__name__)


class SettingsAccountMixin:
    """Account / Cookie settings tab."""

    def _build_account_tab(self, nb):
        page = QWidget()
        page.setStyleSheet(f"background-color: {C['bg_base']};")

        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 12, 16, 12)

        sec = QWidget()
        sec.setStyleSheet(f"""
            QWidget#acctSec {{
                background-color: {C['bg_elevated']};
                border: 1px solid {C['border_sub']};
                border-radius: 6px;
            }}
        """)
        sec.setObjectName("acctSec")
        sec_layout = QVBoxLayout(sec)
        sec_layout.setContentsMargins(10, 8, 10, 8)

        # 导入按钮行
        import_row = QWidget()
        import_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        import_layout = QHBoxLayout(import_row)
        import_layout.setContentsMargins(0, 0, 0, 6)

        import_lbl = QLabel("导入方式:")
        import_lbl.setFont(FONT)
        import_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        import_layout.addWidget(import_lbl)

        ce_btn = QPushButton("📋 Cookie-Editor JSON")
        ce_btn.clicked.connect(self._import_cookie_editor)
        import_layout.addWidget(ce_btn)

        qr_btn = QPushButton("📱 扫码登录")
        qr_btn.clicked.connect(self._qrcode_login)
        import_layout.addWidget(qr_btn)

        pwd_btn = QPushButton("🔑 密码登录")
        pwd_btn.setEnabled(_s() == "normal")
        pwd_btn.clicked.connect(self._password_login)
        import_layout.addWidget(pwd_btn)

        browser_btn = QPushButton("🌐 从浏览器提取")
        browser_btn.clicked.connect(self._import_from_browser)
        import_layout.addWidget(browser_btn)

        import_layout.addStretch()
        sec_layout.addWidget(import_row)

        # 账号切换行
        acct_row = QWidget()
        acct_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        acct_layout = QHBoxLayout(acct_row)
        acct_layout.setContentsMargins(0, 2, 0, 4)

        acct_lbl = QLabel("当前账号:")
        acct_lbl.setFont(FONT)
        acct_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        acct_layout.addWidget(acct_lbl)

        self._acct_combo = QComboBox()
        self._acct_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 2px 6px;
            }}
        """)
        self._acct_combo.currentTextChanged.connect(self._switch_account)
        acct_layout.addWidget(self._acct_combo)

        add_acct_btn = QPushButton("➕")
        add_acct_btn.setFixedWidth(30)
        add_acct_btn.clicked.connect(self._add_account_dialog)
        acct_layout.addWidget(add_acct_btn)

        rm_acct_btn = QPushButton("✕")
        rm_acct_btn.setFixedWidth(30)
        rm_acct_btn.clicked.connect(self._remove_account)
        acct_layout.addWidget(rm_acct_btn)

        acct_layout.addStretch()
        sec_layout.addWidget(acct_row)

        # Cookie 文本编辑（只读显示，应用按钮写入）
        self._cookie_text = QPlainTextEdit()
        self._cookie_text.setReadOnly(True)
        self._cookie_text.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                font-family: Consolas; font-size: 10pt;
                border: 1px solid {C['border']};
            }}
        """)
        sec_layout.addWidget(self._cookie_text)

        # 按钮行
        btn_row = QWidget()
        btn_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 4, 0, 0)

        apply_btn = QPushButton("应用Cookie")
        apply_btn.clicked.connect(self._apply_cookies)
        btn_layout.addWidget(apply_btn)

        self._cookie_unlock_btn = QPushButton("🔒 解锁查看")
        self._cookie_unlock_btn.clicked.connect(self._toggle_cookie_unlock)
        btn_layout.addWidget(self._cookie_unlock_btn)

        clear_btn = QPushButton("清空Cookie")
        clear_btn.setEnabled(_s() == "normal")
        clear_btn.clicked.connect(self._clear_cookies)
        btn_layout.addWidget(clear_btn)

        btn_layout.addStretch()
        sec_layout.addWidget(btn_row)

        # 提示
        tip = QLabel(
            "支持直接粘贴 Cookie 字符串 (key=value; key2=value2) 或 Cookie-Editor JSON 格式，自动识别解析。"
        )
        tip.setFont(FONT_SM)
        tip.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        tip.setWordWrap(True)
        sec_layout.addWidget(tip)

        layout.addWidget(sec)

        self._refresh_cookie_display()
        self._refresh_account_list()

        tab_idx = nb.addTab(page, "  账号设置  ")
        return tab_idx


    def _refresh_cookie_display(self):
        self._cookie_text.clear()
        cookies = {}
        for cookie in get_bilibili_api().session.cookies:
            if "bilibili.com" in (cookie.domain or ""):
                cookies[cookie.name] = cookie.value
        if not cookies:
            cookies = self._net_cfg.get("cookies", {})
        if cookies:
            show_raw = getattr(self, "_cookie_unlocked", False)
            self._cookie_unlock_btn.setText("🔓 已解锁" if show_raw else "🔒 解锁查看")
            parts = []
            for k, v in cookies.items():
                if show_raw:
                    parts.append(f"{k}={v}")
                else:
                    masked = v[:4] + "****" + v[-4:] if len(v) > 8 else "********"
                    parts.append(f"{k}={masked}")
            self._cookie_text.setPlainText("; ".join(parts))


    def _toggle_cookie_unlock(self):
        self._cookie_unlocked = not getattr(self, "_cookie_unlocked", False)
        self._refresh_cookie_display()


    def _apply_cookies(self):
        text = self._cookie_text.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "警告", "Cookie不能为空")
            return
        cookies = self._parse_cookie_input(text)
        if not cookies:
            QMessageBox.critical(self, "错误", "无法解析输入内容，请检查格式")
            return
        api = get_bilibili_api()
        api.set_cookies(cookies)
        api.add_account(api.get_active_account(), cookies, api.get_refresh_token())
        api._persist_cookies(cookies)
        self._net_cfg["cookies"] = cookies
        self._save_net_config()
        self._refresh_account_list()
        self._refresh_status()
        QTimer.singleShot(500, self._verify_login)
        QMessageBox.information(self, "成功", "已应用 Cookie，正在验证登录状态...")


    def _parse_cookie_input(self, text: str) -> Dict[str, str]:
        import json as _json

        stripped = text.strip()
        if stripped.startswith("["):
            try:
                entries = _json.loads(stripped)
                if isinstance(entries, list) and entries:
                    cookies = {}
                    for entry in entries:
                        if isinstance(entry, dict):
                            name = entry.get("name", "")
                            value = entry.get("value", "")
                            if name and value:
                                cookies[name] = value
                    if cookies:
                        return cookies
            except _json.JSONDecodeError:
                pass
        elif stripped.startswith("{"):
            try:
                obj = _json.loads(stripped)
                if isinstance(obj, dict):
                    valid_keys = {"SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid", "buvid3", "buvid4"}
                    return {k: v for k, v in obj.items() if k in valid_keys or not k.startswith("_")}
            except _json.JSONDecodeError:
                pass
        cookies = {}
        for item in stripped.split(";"):
            item = item.strip()
            if "=" in item:
                key, value = item.split("=", 1)
                cookies[key.strip()] = value.strip()
        return cookies


    def _verify_login(self):
        def _worker():
            try:
                status = get_bilibili_api().get_status()
                is_login = status.get("is_login", False)
                login_name = status.get("login_name", "")
                if is_login and hasattr(self, "gui") and self.gui:
                    invoke(lambda name=login_name: self.gui.log_panel.add_log("INFO", f"Cookie 登录验证成功: {name}"))
            except Exception as e:
                logger.debug("检查Cookie登录状态失败: %s", e)
            invoke(lambda: self._refresh_status())

        threading.Thread(target=_worker, daemon=True).start()


    def _clear_cookies(self):
        reply = QMessageBox.question(
            self, "确认", "确定要清空所有Cookie吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for name in (
            "SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5",
            "sid", "buvid3", "buvid4", "buvid_fp",
        ):
            get_bilibili_api().session.cookies.set(name, "", domain=".bilibili.com")
        get_bilibili_api()._cookies = {}
        get_bilibili_api()._refresh_token = ""
        self._net_cfg["cookies"] = {}
        self._net_cfg["refresh_token"] = ""
        self._save_net_config()
        self._refresh_cookie_display()
        self._refresh_status()
        QMessageBox.information(self, "成功", "Cookie 已清空")


    def _import_from_browser(self):
        def _worker():
            try:
                from utils.browser_cookies import extract_from_all_browsers

                cookies = extract_from_all_browsers()
                if cookies:
                    api = get_bilibili_api()
                    api.set_cookies(cookies)
                    api.add_account(api.get_active_account(), cookies, api.get_refresh_token())
                    api._persist_cookies(cookies)
                    invoke(lambda c=cookies: self._on_browser_cookies(c))
                else:
                    invoke(lambda: QMessageBox.critical(
                        self, "失败", "未从浏览器中找到 B 站 Cookie，请确认已登录 bilibili.com"
                    ))
            except Exception as e:
                invoke(lambda err=str(e): QMessageBox.critical(self, "错误", f"提取失败: {err}"))

        threading.Thread(target=_worker, daemon=True).start()


    def _on_browser_cookies(self, cookies: dict):
        self._refresh_account_list()
        self._refresh_cookie_display()
        self._refresh_status()
        QTimer.singleShot(500, self._verify_login)
        QMessageBox.information(self, "成功", f"已从浏览器提取 Cookie:\n{', '.join(cookies.keys())}")


    def _import_cookie_editor(self):
        dlg = _CookieEditorDialog(self.dlg)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            cookies = dlg.get_cookies()
            if cookies:
                get_bilibili_api().set_cookies(cookies)
                self._net_cfg["cookies"] = cookies
                self._net_cfg["refresh_token"] = get_bilibili_api().get_refresh_token()
                self._save_net_config()
                self._refresh_cookie_display()
                self._refresh_status()
                QTimer.singleShot(500, self._verify_login)
                QMessageBox.information(self, "成功", f"已导入 {len(cookies)} 个 Cookie，正在验证登录状态...")


    def _qrcode_login(self):
        dlg = _QRCodeLoginDialog(self.dlg)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            cookies = get_bilibili_api()._cookies
            get_bilibili_api().add_account(
                get_bilibili_api().get_active_account(),
                cookies,
                get_bilibili_api().get_refresh_token(),
            )
            self._refresh_account_list()
            self._refresh_cookie_display()
            self._refresh_status()
            QTimer.singleShot(1000, self._verify_login)
            if cookies:
                QMessageBox.information(self, "登录成功", f"已获取 Cookie: {', '.join(cookies.keys())}")
            else:
                QMessageBox.information(self, "登录成功", "扫码成功！Cookie 已通过浏览器同步。")


    def _refresh_account_list(self):
        api = get_bilibili_api()
        names = api.get_account_names()
        self._acct_combo.blockSignals(True)
        self._acct_combo.clear()
        self._acct_combo.addItems(names)
        current = api.get_active_account()
        if current in names:
            self._acct_combo.setCurrentText(current)
        elif names:
            self._acct_combo.setCurrentIndex(0)
        self._acct_combo.blockSignals(False)


    def _switch_account(self):
        name = self._acct_combo.currentText()
        if name:
            get_bilibili_api().switch_account(name)
            self._refresh_cookie_display()
            self._refresh_status()


    def _add_account_dialog(self, _parent=None):
        dlg = _AddAccountDialog(self.dlg)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refresh_account_list()
            self._refresh_cookie_display()
            self._refresh_status()


    def _remove_account(self):
        name = self._acct_combo.currentText()
        if not name:
            return
        reply = QMessageBox.question(
            self, "确认", f"确定要删除账号「{name}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        get_bilibili_api().remove_account(name)
        self._refresh_account_list()
        self._refresh_cookie_display()
        self._refresh_status()


    def _password_login(self):
        dlg = _PasswordLoginDialog(self.dlg)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            result = dlg.get_result()
            if result.get("code") == 0:
                cookies = result.get("cookies", {})
                get_bilibili_api().set_cookies(cookies)
                get_bilibili_api().add_account(
                    get_bilibili_api().get_active_account(),
                    cookies,
                    get_bilibili_api().get_refresh_token(),
                )
                self._net_cfg["cookies"] = cookies
                self._net_cfg["refresh_token"] = result.get("refresh_token", "")
                self._save_net_config()
                self._refresh_cookie_display()
                self._refresh_status()
                QTimer.singleShot(1000, self._verify_login)
                QMessageBox.information(self, "成功", f"已获取 Cookie: {', '.join(cookies.keys())}")
