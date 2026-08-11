"""
系统设置主窗口 — PyQt6 版

组合各子模块的 Mixin 类构建完整 SettingsWindow 类。
所有 tab 统一使用 QTabWidget，mixins 接收 QWidget parent 构建内容。
"""

import json
import os
import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox,
    QMessageBox, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from ui.theme import C
from ui.helpers import FONT, project_path, auto_threshold_name, SPACE_MD, SPACE_LG
from ui.widgets import SectionHeader, WaveDivider
from ui.dialog_base import DialogBase
from ui.settings_common import (
    styled_label,
    field_wrapper,
    make_field,
    make_spin_field,
    make_spin_field_float,
    make_section_widget as _section_widget,
)

logger = logging.getLogger(__name__)

# ── 导入各子模块 Mixin ──
from ui.settings_notification import SettingsNotificationMixin
from ui.settings_monitor import SettingsMonitorMixin
from ui.settings_general import SettingsGeneralMixin
from ui.settings_proxy import SettingsProxyMixin
from ui.settings_account import SettingsAccountMixin
from ui.settings_ai import SettingsAIMixin
from ui.settings_weights import SettingsWeightsMixin
from ui.settings_training import SettingsTrainingMixin
from ui.settings_about import SettingsAboutMixin


class SettingsWindow(
    SettingsNotificationMixin,
    SettingsMonitorMixin,
    SettingsGeneralMixin,  # MUST come before SettingsAccountMixin — provides _refresh_status
    SettingsProxyMixin,
    SettingsAccountMixin,  # depends on SettingsGeneralMixin._refresh_status
    SettingsAIMixin,
    SettingsWeightsMixin,
    SettingsTrainingMixin,
    SettingsAboutMixin,
):
    """统一设置窗口 — PyQt6 版"""

    def __init__(self, parent=None, gui=None):
        self.dlg = DialogBase(
            parent, "系统设置", (0, 0), modal=False
        )
        # Restore the geometry calcs from DialogBase
        screen = None
        if parent and hasattr(parent, 'screen'):
            screen = parent.screen()
        elif hasattr(self.dlg, 'screen'):
            screen = self.dlg.screen()
        if screen:
            geo = screen.geometry()
            w = int(geo.width() * 0.48)
            h = int(geo.height() * 0.68)
            self.dlg.resize(w, h)

        self.gui = gui

        from config import load_config
        self._cfg = load_config()

        self._net_cfg_file = project_path("data", "network_config.json")
        self._net_cfg = self._load_net_config()

        self._profiles = []  # AI profiles, set by _build_ai_tab
        self._thresh_rows = []  # threshold row widgets

        self.setup_ui()

    # ── 网络配置持久化 ──
    def _load_net_config(self) -> dict:
        if os.path.exists(self._net_cfg_file):
            try:
                with open(self._net_cfg_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                from utils.crypto import decrypt_dict
                cookies = cfg.get("cookies", {})
                if cookies:
                    decrypt_dict(cookies, "SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")
                for acc in cfg.get("accounts", []):
                    acc_cookies = acc.get("cookies", {})
                    if acc_cookies:
                        decrypt_dict(acc_cookies, "SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")
                return cfg
            except Exception as e:
                logger.debug("加载网络配置失败: %s", e)
        return {"proxies": [], "cookies": {}, "accounts": [], "ssl_verify": False}

    def _save_net_config(self):
        os.makedirs(os.path.dirname(self._net_cfg_file), exist_ok=True)
        cookies = self._net_cfg.get("cookies", {})
        if cookies:
            from utils.crypto import encrypt_dict
            encrypt_dict(cookies, "SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")
        with open(self._net_cfg_file, "w", encoding="utf-8") as f:
            json.dump(self._net_cfg, f, ensure_ascii=False, indent=2)
        if cookies:
            from utils.crypto import decrypt_dict
            decrypt_dict(cookies, "SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")

    # ═══════════════ UI 构建 ═══════════════════════════════
    def _section(self, parent, title, padding=None):
        """创建一个卡片分段，添加到 parent 的布局中"""
        sec = _section_widget(parent, title)
        if padding:
            sec.layout().setContentsMargins(*padding)
        parent.layout().addWidget(sec)
        return sec

    def _field(self, parent, label, default, show=None, show_password=None):
        """Create a label + QLineEdit row (delegates to settings_common.make_field)."""
        if show_password is not None:
            show = show_password
        return make_field(parent, label, default, show)

    def _spin_field(self, parent, label, default, fr, to):
        """Create a label + QSpinBox row (delegates to settings_common.make_spin_field)."""
        return make_spin_field(parent, label, default, fr, to)

    def _spin_field_float(self, parent, label, default, fr, to):
        """Create a label + QDoubleSpinBox row (delegates to settings_common.make_spin_field_float)."""
        return make_spin_field_float(parent, label, default, fr, to)

    def setup_ui(self):
        self.dlg.header("系统设置", "配置通知、监控、AI、代理、Cookie 等全部参数")

        # Tab widget (洛天依: 导航选中态天依蓝)
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {C['border']};
                border-top: none;
                background-color: {C['bg_base']};
            }}
            QTabBar::tab {{
                background-color: {C['bg_surface']};
                color: {C['text_2']};
                border: 1px solid {C['border']};
                border-bottom: none;
                padding: 6px 16px;
                margin-right: 2px;
                border-top-left-radius: {C['radius_sm']}px;
                border-top-right-radius: {C['radius_sm']}px;
            }}
            QTabBar::tab:selected {{
                background-color: {C['lty_blue']};
                color: #ffffff;
                border: 1px solid {C['lty_blue']};
                border-bottom: 1px solid {C['lty_blue']};
                font-weight: bold;
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {C['lty_blue_light']};
                color: {C['lty_blue_deep']};
            }}
        """)
        self.dlg._main_layout.addWidget(self._tabs, 1)

        self._build_notification_tab(self._tabs)
        self._build_monitor_tab(self._tabs)
        self._build_general_tab(self._tabs)
        self._build_ai_tab(self._tabs)
        self._build_weights_tab(self._tabs)
        self._build_training_tab(self._tabs)
        self._build_proxy_tab(self._tabs)
        self._build_account_tab(self._tabs)
        self._build_about_tab(self._tabs)

        # 统一各标签页顶部标题 (洛天依排版: SectionHeader + 水波分隔线)
        for i in range(self._tabs.count()):
            page = self._tabs.widget(i)
            layout = page.layout()
            if layout is None or not isinstance(layout, QVBoxLayout):
                continue
            head_wrap = QWidget(page)
            head_layout = QVBoxLayout(head_wrap)
            head_layout.setContentsMargins(SPACE_LG, SPACE_LG, SPACE_LG, SPACE_MD)
            head_layout.setSpacing(SPACE_MD)
            head_layout.addWidget(SectionHeader(self._tabs.tabText(i).strip()))
            head_layout.addWidget(WaveDivider())
            layout.insertWidget(0, head_wrap)

        self.dlg.button_row(
            [
                ("取消", self._on_close, ""),
                ("保存设置", self._save_settings, "primary"),
            ]
        )

    # ──── 关闭 ────
    def _on_close(self):
        self.dlg.close()

    # ──── 保存系统设置 ────
    def _save_settings(self):
        if not self._validate_settings():
            return
        self._persist_settings()
        self._apply_settings()

    def _validate_settings(self):
        try:
            max_m = int(self.max_monitors.text() if hasattr(self.max_monitors, 'text') else self.max_monitors)
            if not (10 <= max_m <= 500):
                QMessageBox.critical(self.dlg, "验证失败", "最大监控数必须在 10 ~ 500 之间")
                return False
        except ValueError:
            QMessageBox.critical(self.dlg, "验证失败", "最大监控数必须为整数")
            return False
        try:
            val = self.predict_hours.text() if hasattr(self.predict_hours, 'text') else str(self.predict_hours.value())
            pred_hours = int(val)
            if not (24 <= pred_hours <= 720):
                QMessageBox.critical(self.dlg, "验证失败", "预测时长必须在 24 ~ 720 小时之间")
                return False
        except ValueError:
            QMessageBox.critical(self.dlg, "验证失败", "预测时长必须为整数")
            return False
        try:
            val = self.min_confidence.text() if hasattr(self.min_confidence, 'text') else str(self.min_confidence.value())
            confidence = float(val)
            if not (0.1 <= confidence <= 1.0):
                QMessageBox.critical(self.dlg, "验证失败", "最小置信度必须在 0.1 ~ 1.0 之间")
                return False
        except ValueError:
            QMessageBox.critical(self.dlg, "验证失败", "最小置信度必须为数字")
            return False
        return True

    def _persist_settings(self):
        from config import save_config
        from utils.crypto import encrypt, decrypt

        max_m = int(self.max_monitors.text() if hasattr(self.max_monitors, 'text') else self.max_monitors)
        pred_hours = int(self.predict_hours.text() if hasattr(self.predict_hours, 'text') else self.predict_hours.value())
        confidence = float(self.min_confidence.text() if hasattr(self.min_confidence, 'text') else self.min_confidence.value())

        self._cfg["onebot"] = {
            "enabled": self.onebot_enabled.isChecked() if hasattr(self.onebot_enabled, 'isChecked') else False,
            "http_url": self.onebot_http.text().strip() if hasattr(self.onebot_http, 'text') else "",
            "ws_url": self.onebot_ws.text().strip() if hasattr(self.onebot_ws, 'text') else "",
            "access_token": self.onebot_token.text().strip() if hasattr(self.onebot_token, 'text') else "",
            "private_qq": self.qq_private.text().strip() if hasattr(self.qq_private, 'text') else "",
            "group_qq": self.qq_group.text().strip() if hasattr(self.qq_group, 'text') else "",
        }
        self._cfg["monitor"]["max_monitor_count"] = max_m
        self._cfg["prediction"]["prediction_hours"] = pred_hours
        self._cfg["prediction"]["min_confidence"] = confidence

        th_data = []
        for v_widget, n_widget, _ in getattr(self, "_thresh_rows", []):
            try:
                v = int(v_widget.text() if hasattr(v_widget, 'text') else v_widget.value())
                n = n_widget.text().strip() if hasattr(n_widget, 'text') else str(n_widget)
                if not n:
                    n = auto_threshold_name(v)
                if v > 0:
                    th_data.append([v, n])
            except (ValueError, TypeError):
                continue
        if th_data:
            self._cfg["prediction"]["thresholds"] = th_data

        # 加密 AI profiles 中的 api_key
        for p in self._profiles:
            key = p.get("api_key", "")
            if key:
                p["api_key"] = encrypt(key)
        # 加密 OneBot access_token
        token = self._cfg["onebot"].get("access_token", "")
        if token:
            self._cfg["onebot"]["access_token"] = encrypt(token)

        self._cfg["ai"] = {
            "enabled": any(p.get("api_key") for p in self._profiles),
            "profiles": self._profiles,
            "selected_profile": self._ai_profile_cb.currentText() if hasattr(self, '_ai_profile_cb') else "",
        }
        save_config(self._cfg)

        # 恢复明文值，避免 UI 显示密文
        for p in self._profiles:
            key = p.get("api_key", "")
            if key:
                try:
                    p["api_key"] = decrypt(key)
                except Exception:
                    pass
        if token:
            try:
                self._cfg["onebot"]["access_token"] = decrypt(token)
            except Exception:
                pass

    def _apply_settings(self):
        from core.notification import notification_manager
        from core.proxy_manager import ProxyManager

        notification_manager.configure(self._cfg)

        # 同步 SSL 验证设置
        ProxyManager.ssl_verify = self._net_cfg.get("ssl_verify", False)

        try:
            from ui.helpers import reload_thresholds
            reload_thresholds()
        except Exception as e:
            logger.debug("忽略异常: %s", e)

        self._sync_proxy_text_to_cfg()
        self._save_net_config()
        self._verify_proxy_persisted()

        QMessageBox.information(self.dlg, "成功", "设置已保存")
        self.dlg.close()
