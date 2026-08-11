"""
账号设置 — 对话框类

从 settings_account.py 提取的独立对话框：
  - _CookieEditorDialog: Cookie-Editor JSON 导入
  - _QRCodeLoginDialog: 扫码登录
  - _PasswordLoginDialog: 账号密码登录（含验证码+极验）
  - _AddAccountDialog: 添加账号
"""
import json
import logging
import threading

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QPlainTextEdit, QMessageBox, QDialog, QDialogButtonBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QPixmap

from ui.theme import C
from ui.helpers import FONT, FONT_SM
from ui.invoker import invoke
from core.bilibili_api import get_bilibili_api

logger = logging.getLogger(__name__)


# ── 对话框：Cookie-Editor 导入 ──────────────────────────────

class _CookieEditorDialog(QDialog):
    """Cookie-Editor JSON 导入对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入 Cookie-Editor JSON ♪")
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

        title = QLabel("粘贴 Cookie-Editor 导出的 JSON 内容哦 ♪")
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

        self._import_btn = QPushButton("导入并应用 ♪")
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
            QMessageBox.warning(self, "要注意哦…", "要先粘贴 JSON 内容哦…♪")
            return
        try:
            entries = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("解析 Cookie-Editor JSON 失败", exc_info=True)
            QMessageBox.critical(self, "呜…出错了", "呜…JSON 格式好像不太对呢，检查一下再试试哦 ♪")
            return
        if not isinstance(entries, list):
            QMessageBox.critical(self, "呜…出错了", "呜…JSON 需要是数组格式哦 ♪")
            return
        cookies = {}
        for entry in entries:
            name = entry.get("name", "")
            value = entry.get("value", "")
            domain = entry.get("domain", "")
            if name and value and ("bilibili.com" in domain or not domain):
                cookies[name] = value
        if not cookies:
            QMessageBox.warning(self, "要注意哦…", "呜…JSON 里没有找到 B站 相关的 Cookie 呢…♪")
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
        self.setWindowTitle("扫码登录 B站 ♪")
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

        title = QLabel("请用 B站 手机客户端扫码哦 ♪")
        title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C['text_1']};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self._qr_label = QLabel("正在生成二维码哦…♪")
        self._qr_label.setFont(FONT)
        self._qr_label.setStyleSheet(f"color: {C['text_1']};")
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setFixedSize(220, 220)
        layout.addWidget(self._qr_label, 0, Qt.AlignmentFlag.AlignCenter)

        self._status_label = QLabel("等你扫码哦…♪")
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
            self._login_failed.emit("呜…获取二维码失败啦，请稍后再试哦 ♪")
            return
        self._qrcode_key = qr_data.get("qrcode_key", "")
        qr_url = qr_data.get("url", "")

        t = threading.Thread(target=self._gen_qr, args=(qr_url,), daemon=True)
        t.start()

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
                invoke(lambda p=pixmap: self._qr_label.setPixmap(p))
        except Exception:
            invoke(lambda u=qr_url: self._qr_label.setText(f"呜…二维码生成失败啦，用这个链接扫码哦:\n{u}"))

    def _poll(self):
        def _worker():
            try:
                result = get_bilibili_api().poll_qrcode_login(self._qrcode_key)
            except Exception as e:
                logger.warning("轮询二维码登录状态异常", exc_info=True)
                result = {"status": 0, "message": "呜…轮询登录状态出问题啦，请稍后再试哦 ♪"}
            invoke(lambda r=result: self._status_label.setText(r.get("message", "")))
            if result.get("status") == 2:
                invoke(self._poll_timer.stop)
                cookies = result.get("cookies", {})
                if cookies:
                    get_bilibili_api().set_cookies(cookies)
                self._login_done.emit(cookies)
            elif result.get("status") == -1:
                invoke(self._poll_timer.stop)
                invoke(lambda: self._status_label.setStyleSheet(f"color: {C['danger']};"))

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

    _result_signal = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("密码登录 B站 ♪")
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

        title = QLabel("B站 账号密码登录 ♪")
        title.setFont(QFont("Microsoft YaHei UI", 13, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C['text_1']};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("部分账号需要手机验证码，建议使用扫码登录哦 ♪")
        subtitle.setFont(FONT_SM)
        subtitle.setStyleSheet(f"color: {C['text_3']};")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        form = QWidget()
        form.setStyleSheet(f"background-color: {C['bg_surface']};")
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(0, 12, 0, 0)

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

        self._status_label = QLabel("")
        self._status_label.setFont(FONT_SM)
        self._status_label.setStyleSheet(f"color: {C['text_2']};")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        layout.addStretch()

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
            QMessageBox.warning(self, "要注意哦…", "要先输入账号和密码哦…♪")
            return

        self._login_btn.setEnabled(False)
        self._status_label.setText("登录中哦…♪" if not captcha_code else "验证中哦…♪")
        self._status_label.setStyleSheet(f"color: {C['text_2']};")

        def _worker():
            try:
                result = get_bilibili_api().login_with_password(
                    uname, pwd, captcha=captcha_code, captcha_type=self._captcha_type
                )
                self._result_signal.emit(result)
            except Exception as e:
                logger.error("密码登录异常", exc_info=True)
                self._result_signal.emit({"code": -1, "message": "呜…登录失败啦，请稍后再试哦 ♪"})

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_result(self, result: dict):
        self._login_result = result
        code = result.get("code", -1)
        if code == 0:
            self._status_label.setText("登录成功啦 ♪")
            self._status_label.setStyleSheet(f"color: {C['success']};")
            QTimer.singleShot(500, self.accept)
        elif result.get("need_captcha") or code in (-629, -352):
            self._show_captcha(result)
        else:
            self._status_label.setText(result.get("message", "呜…登录失败啦，请稍后再试哦 ♪"))
            self._status_label.setStyleSheet(f"color: {C['danger']};")
            self._login_btn.setEnabled(True)

    def _show_captcha(self, result: dict):
        self._captcha_type = result.get("captcha_type", 0)
        if self._captcha_type == 6:
            phone = result.get("captcha_phone", "")
            hint = f"验证码已发送到 {phone} 哦 ♪" if phone else "输入手机收到的验证码哦 ♪"
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
            self._status_label.setText("需要极验滑块验证哦，请在浏览器中完成 ♪")
            self._status_label.setStyleSheet(f"color: {C['danger']};")
            self._geetest_widget.setVisible(True)
            self._submit_captcha_btn.setText("提交极验结果 ♪")
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
            QMessageBox.warning(self, "要注意哦…", "要先输入验证码哦…♪")
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
        self.setWindowTitle("添加账号 ♪")
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
            QMessageBox.warning(self, "要注意哦…", "要先填写账号名称和 Cookie 哦…♪")
            return
        if hasattr(self.parent(), "_parse_cookie_input"):
            cookies = self.parent()._parse_cookie_input(raw)  # type: ignore
        else:
            cookies = {}
        if not cookies:
            QMessageBox.critical(self, "呜…出错了", "呜…解析不了 Cookie 呢，检查一下格式哦 ♪")
            return
        get_bilibili_api().add_account(name, cookies)
        get_bilibili_api().switch_account(name)
        get_bilibili_api()._persist_cookies(cookies)
        self.accept()
