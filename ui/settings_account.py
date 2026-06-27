"""
账号 / Cookie 设置 — PyQt6 版

Mixin functions for SettingsWindow.
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
from core.bilibili_api import get_bilibili_api
from utils.update_checker import _s

logger = logging.getLogger(__name__)


# ── 对话框：Cookie-Editor 导入 ──────────────────────────────
class _CookieEditorDialog(QDialog):
    """Cookie-Editor JSON 导入对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入 Cookie-Editor JSON")
        if parent:
            screen = parent.screen()
            geo = screen.geometry() if screen else None
            sw, sh = (geo.width(), geo.height()) if geo else (1920, 1080)
        else:
            sw, sh = 1920, 1080
        self.resize(int(sw * 0.36), int(sh * 0.42))
        self.setStyleSheet(f"background-color: {C['bg_surface']};")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 12)

        title = QLabel("粘贴 Cookie-Editor 导出的 JSON 内容：")
        title.setFont(FONT)
        title.setStyleSheet(f"color: {C['text_1']};")
        layout.addWidget(title)

        hint = QLabel('格式: [{"domain": ".bilibili.com", "name": "SESSDATA", ...}]')
        hint.setFont(FONT_SM)
        hint.setStyleSheet(f"color: {C['text_3']};")
        layout.addWidget(hint)

        self._text = QPlainTextEdit()
        self._text.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                font-family: Consolas; font-size: 10pt;
                border: 1px solid {C['border']};
            }}
        """)
        layout.addWidget(self._text, 1)

        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addStretch()

        self._import_btn = QPushButton("导入并应用")
        self._import_btn.setProperty("primary", True)
        s = self._import_btn.style()
        if s is not None:
            s.unpolish(self._import_btn)
            s.polish(self._import_btn)
        self._import_btn.clicked.connect(self._do_import)
        btn_layout.addWidget(self._import_btn)

        layout.addLayout(btn_layout)

    def _do_import(self):
        raw = self._text.toPlainText().strip()
        if not raw:
            QMessageBox.warning(self, "提示", "请粘贴 JSON 内容")
            return
        try:
            entries = json.loads(raw)
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "解析失败", f"JSON 格式错误:\n{e}")
            return
        if not isinstance(entries, list):
            QMessageBox.critical(self, "格式错误", "JSON 应为数组格式")
            return
        cookies = {}
        for entry in entries:
            name = entry.get("name", "")
            value = entry.get("value", "")
            domain = entry.get("domain", "")
            if name and value and ("bilibili.com" in domain or not domain):
                cookies[name] = value
        if not cookies:
            QMessageBox.warning(self, "未找到", "JSON 中未找到 B站 相关 Cookie")
            return
        self._result = cookies
        self.accept()

    def get_cookies(self) -> dict:
        return getattr(self, "_result", {})


# ── 对话框：扫码登录 ──────────────────────────────────────
class _QRCodeLoginDialog(QDialog):
    """扫码登录对话框"""

    _login_done = pyqtSignal(dict)  # cookies
    _login_failed = pyqtSignal(str)  # message

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("扫码登录 B站")
        if parent:
            screen = parent.screen()
            geo = screen.geometry() if screen else None
            sw, sh = (geo.width(), geo.height()) if geo else (1920, 1080)
        else:
            sw, sh = 1920, 1080
        self.resize(int(sw * 0.28), int(sh * 0.45))
        self.setStyleSheet(f"background-color: {C['bg_surface']};")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)

        title = QLabel("请使用 B站 手机客户端扫码")
        title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C['text_1']};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # 二维码/状态图标
        self._qr_label = QLabel("正在生成二维码…")
        self._qr_label.setFont(FONT)
        self._qr_label.setStyleSheet(f"color: {C['text_1']};")
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setFixedSize(220, 220)
        layout.addWidget(self._qr_label, 0, Qt.AlignmentFlag.AlignCenter)

        self._status_label = QLabel("等待扫码...")
        self._status_label.setFont(FONT)
        self._status_label.setStyleSheet(f"color: {C['text_2']};")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)

        layout.addStretch()

        self._login_done.connect(self._on_login_done)
        self._login_failed.connect(self._on_login_failed)

        self._start_qrcode()

    def _start_qrcode(self):
        qr_data = get_bilibili_api().get_qrcode_login_url()
        if not qr_data:
            self._login_failed.emit("获取二维码失败")
            return
        self._qrcode_key = qr_data.get("qrcode_key", "")
        qr_url = qr_data.get("url", "")

        # 后台生成二维码图片
        t = threading.Thread(target=self._gen_qr, args=(qr_url,), daemon=True)
        t.start()

        # 开始轮询
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(1500)

    def _gen_qr(self, qr_url: str):
        try:
            import qrcode
            from PIL import Image
            import io

            img = qrcode.make(qr_url).resize((200, 200))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            pixmap = QPixmap()
            if pixmap.loadFromData(buf.getvalue()):
                self._qr_label.setPixmap(pixmap)
        except Exception:
            self._qr_label.setText(f"扫码链接:\n{qr_url}")

    def _poll(self):
        def _worker():
            try:
                result = get_bilibili_api().poll_qrcode_login(self._qrcode_key)
            except Exception as e:
                result = {"status": 0, "message": f"轮询异常: {e}"}
            self._status_label.setText(result.get("message", ""))
            if result.get("status") == 2:
                self._poll_timer.stop()
                cookies = result.get("cookies", {})
                if cookies:
                    get_bilibili_api().set_cookies(cookies)
                self._login_done.emit(cookies)
            elif result.get("status") == -1:
                self._poll_timer.stop()
                self._status_label.setStyleSheet(f"color: {C['danger']};")

        threading.Thread(target=_worker, daemon=True).start()

    def _on_login_done(self, cookies: dict):
        self._status_label.setStyleSheet(f"color: {C['success']};")
        QTimer.singleShot(800, self.accept)

    def _on_login_failed(self, msg: str):
        self._status_label.setText(msg)
        self._status_label.setStyleSheet(f"color: {C['danger']};")


# ── 对话框：密码登录 ──────────────────────────────────────
class _PasswordLoginDialog(QDialog):
    """账号密码登录对话框，支持验证码 + 极验"""

    _result_signal = pyqtSignal(object)  # result dict

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("密码登录 B站")
        if parent:
            screen = parent.screen()
            geo = screen.geometry() if screen else None
            sw, sh = (geo.width(), geo.height()) if geo else (1920, 1080)
        else:
            sw, sh = 1920, 1080
        self.resize(int(sw * 0.28), int(sh * 0.36))
        self.setStyleSheet(f"background-color: {C['bg_surface']};")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)

        title = QLabel("B站 账号密码登录")
        title.setFont(QFont("Microsoft YaHei UI", 13, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C['text_1']};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("部分账号需要手机验证码，建议使用扫码登录")
        subtitle.setFont(FONT_SM)
        subtitle.setStyleSheet(f"color: {C['text_3']};")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        form = QWidget()
        form.setStyleSheet(f"background-color: {C['bg_surface']};")
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(0, 12, 0, 0)

        # 用户名
        uname_row = QHBoxLayout()
        uname_lbl = QLabel("账号:")
        uname_lbl.setFont(FONT)
        uname_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        uname_lbl.setFixedWidth(50)
        uname_row.addWidget(uname_lbl)
        self._username_entry = QLineEdit()
        self._username_entry.setFont(FONT)
        self._username_entry.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 4px 8px;
            }}
        """)
        uname_row.addWidget(self._username_entry)
        form_layout.addLayout(uname_row)

        # 密码
        pwd_row = QHBoxLayout()
        pwd_lbl = QLabel("密码:")
        pwd_lbl.setFont(FONT)
        pwd_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        pwd_lbl.setFixedWidth(50)
        pwd_row.addWidget(pwd_lbl)
        self._password_entry = QLineEdit()
        self._password_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_entry.setFont(FONT)
        self._password_entry.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 4px 8px;
            }}
        """)
        pwd_row.addWidget(self._password_entry)
        form_layout.addLayout(pwd_row)

        layout.addWidget(form)

        # 验证码区域（初始隐藏）
        self._captcha_widget = QWidget()
        self._captcha_widget.setStyleSheet(f"background-color: {C['bg_surface']};")
        self._captcha_widget.setVisible(False)
        captcha_layout = QVBoxLayout(self._captcha_widget)
        captcha_layout.setContentsMargins(0, 4, 0, 0)

        captcha_row = QHBoxLayout()
        captcha_lbl = QLabel("验证码:")
        captcha_lbl.setFont(FONT)
        captcha_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        captcha_row.addWidget(captcha_lbl)
        self._captcha_entry = QLineEdit()
        self._captcha_entry.setFont(FONT)
        self._captcha_entry.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 4px 8px;
            }}
        """)
        captcha_row.addWidget(self._captcha_entry)
        captcha_layout.addLayout(captcha_row)

        self._geetest_widget = QWidget()
        self._geetest_widget.setStyleSheet(f"background-color: {C['bg_surface']};")
        self._geetest_widget.setVisible(False)
        geetest_layout = QVBoxLayout(self._geetest_widget)
        geetest_layout.setContentsMargins(0, 4, 0, 0)
        self._geetest_validate_entry = QLineEdit()
        self._geetest_validate_entry.setPlaceholderText("validate")
        self._geetest_seccode_entry = QLineEdit()
        self._geetest_seccode_entry.setPlaceholderText("seccode")
        for e in (self._geetest_validate_entry, self._geetest_seccode_entry):
            e.setFont(FONT_SM)
            e.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {C['bg_base']}; color: {C['text_1']};
                    border: 1px solid {C['border']}; padding: 4px 8px;
                }}
            """)
        geetest_layout.addWidget(QLabel("validate:"))
        geetest_layout.addWidget(self._geetest_validate_entry)
        geetest_layout.addWidget(QLabel("seccode:"))
        geetest_layout.addWidget(self._geetest_seccode_entry)

        layout.addWidget(self._captcha_widget)
        layout.addWidget(self._geetest_widget)

        # 状态
        self._status_label = QLabel("")
        self._status_label.setFont(FONT_SM)
        self._status_label.setStyleSheet(f"color: {C['text_2']};")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        layout.addStretch()

        # 按钮
        btn_row = QHBoxLayout()
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch()

        self._login_btn = QPushButton("登录")
        self._login_btn.setProperty("primary", True)
        s = self._login_btn.style()
        if s is not None:
            s.unpolish(self._login_btn)
            s.polish(self._login_btn)
        self._login_btn.clicked.connect(self._do_login)
        btn_row.addWidget(self._login_btn)

        self._submit_captcha_btn = QPushButton("提交验证码")
        self._submit_captcha_btn.setVisible(False)
        btn_row.addWidget(self._submit_captcha_btn)

        layout.addLayout(btn_row)

        self._result_signal.connect(self._handle_result)
        self._captcha_type = 0
        self._login_result: dict = {}

    def _do_login(self, captcha_code: str = ""):
        uname = self._username_entry.text().strip()
        pwd = self._password_entry.text()
        if not uname or not pwd:
            QMessageBox.warning(self, "提示", "请输入账号和密码")
            return

        self._login_btn.setEnabled(False)
        self._status_label.setText("登录中..." if not captcha_code else "验证中...")
        self._status_label.setStyleSheet(f"color: {C['text_2']};")

        def _worker():
            try:
                result = get_bilibili_api().login_with_password(
                    uname, pwd, captcha=captcha_code, captcha_type=self._captcha_type
                )
                self._result_signal.emit(result)
            except Exception as e:
                self._result_signal.emit({"code": -1, "message": str(e)})

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_result(self, result: dict):
        self._login_result = result
        code = result.get("code", -1)
        if code == 0:
            self._status_label.setText("登录成功！")
            self._status_label.setStyleSheet(f"color: {C['success']};")
            QTimer.singleShot(500, self.accept)
        elif result.get("need_captcha") or code in (-629, -352):
            self._show_captcha(result)
        else:
            self._status_label.setText(result.get("message", "未知错误"))
            self._status_label.setStyleSheet(f"color: {C['danger']};")
            self._login_btn.setEnabled(True)

    def _show_captcha(self, result: dict):
        self._captcha_type = result.get("captcha_type", 0)
        if self._captcha_type == 6:
            phone = result.get("captcha_phone", "")
            hint = f"验证码已发送至 {phone}" if phone else "请输入手机收到的验证码"
            self._status_label.setText(hint)
            self._status_label.setStyleSheet(f"color: {C['warning']};")
            self._captcha_widget.setVisible(True)
            self._captcha_entry.setFocus()
            self._submit_captcha_btn.setVisible(True)
            try:
                self._submit_captcha_btn.clicked.disconnect()
            except TypeError:
                pass
            self._submit_captcha_btn.clicked.connect(self._submit_captcha)
            self._login_btn.setVisible(False)
        else:
            import webbrowser
            gt = result.get("gt", "")
            challenge = result.get("challenge", "")
            url = f"https://api.geetest.com/get.php?gt={gt}&challenge={challenge}&lang=zh-cn&product=embed"
            self._status_label.setText("需要极验滑块验证，请在浏览器中完成")
            self._status_label.setStyleSheet(f"color: {C['danger']};")
            self._geetest_widget.setVisible(True)
            self._submit_captcha_btn.setText("提交极验结果")
            self._submit_captcha_btn.setVisible(True)
            try:
                self._submit_captcha_btn.clicked.disconnect()
            except TypeError:
                pass
            self._submit_captcha_btn.clicked.connect(self._submit_geetest)
            webbrowser.open(url)

    def _submit_captcha(self):
        code = self._captcha_entry.text().strip()
        if not code:
            QMessageBox.warning(self, "提示", "请输入验证码")
            return
        self._captcha_type = 6
        self._do_login(captcha_code=code)

    def _submit_geetest(self):
        validate = self._geetest_validate_entry.text().strip()
        seccode = self._geetest_seccode_entry.text().strip()
        if validate and seccode:
            self._captcha_type = -1
            self._do_login(captcha_code=f"{validate}:{seccode}")

    def get_result(self) -> dict:
        return self._login_result


# ── 对话框：添加账号 ──────────────────────────────────────
class _AddAccountDialog(QDialog):
    """添加账号对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加账号")
        self.resize(400, 240)
        self.setStyleSheet(f"background-color: {C['bg_surface']};")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 12, 24, 12)

        layout.addWidget(QLabel("账号名称:"))
        self._name_entry = QLineEdit()
        self._name_entry.setFont(FONT)
        self._name_entry.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 4px 8px;
            }}
        """)
        layout.addWidget(self._name_entry)

        layout.addWidget(QLabel("Cookie (SESSDATA=xxx; bili_jct=xxx):"))
        self._cookie_text = QPlainTextEdit()
        self._cookie_text.setMaximumBlockCount(10)
        self._cookie_text.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                font-family: Consolas; font-size: 9pt;
                border: 1px solid {C['border']};
            }}
        """)
        layout.addWidget(self._cookie_text)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._save)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _save(self):
        name = self._name_entry.text().strip()
        raw = self._cookie_text.toPlainText().strip()
        if not name or not raw:
            QMessageBox.warning(self, "提示", "请填写账号名称和 Cookie")
            return
        # 调用 settings_window 的 parse method
        if hasattr(self.parent(), "_parse_cookie_input"):
            cookies = self.parent()._parse_cookie_input(raw)  # type: ignore
        else:
            cookies = {}
        if not cookies:
            QMessageBox.critical(self, "错误", "无法解析 Cookie，请检查格式")
            return
        get_bilibili_api().add_account(name, cookies)
        get_bilibili_api().switch_account(name)
        get_bilibili_api()._persist_cookies(cookies)
        self.accept()


# ═══════════════════════════════════════════════════
#  SettingsWindow Mixin Functions
# ═══════════════════════════════════════════════════


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
                self.gui.log_panel.add_log("INFO", f"Cookie 登录验证成功: {login_name}")
        except Exception as e:
            logger.debug("检查Cookie登录状态失败: %s", e)
        self._refresh_status()

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
                self._on_browser_cookies(cookies)
            else:
                QMessageBox.critical(
                    self, "失败", "未从浏览器中找到 B 站 Cookie，请确认已登录 bilibili.com"
                )
        except Exception as e:
            QMessageBox.critical(self, "错误", f"提取失败: {e}")

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
            QMessageBox.information(self, "登录成功", f"已获取 Cookie: {', '.join(cookies.keys())}")
