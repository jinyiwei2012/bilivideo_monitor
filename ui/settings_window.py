"""
系统设置主窗口 — PyQt6 版

组合各子模块的 Mixin 类构建完整 SettingsWindow 类。
所有 tab 统一使用 QTabWidget，mixins 接收 QWidget parent 构建内容。
"""

import json
import os
import logging

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTabWidget,
    QMessageBox,
)

from ui.theme import C
from ui.helpers import project_path, auto_threshold_name, SPACE_MD, SPACE_LG
from ui.widgets import SectionHeader, WaveDivider
from ui.dialog_base import DialogBase
from ui.settings_common import (
    make_field,
    make_spin_field,
    make_spin_field_float,
    make_section_widget as _section_widget,
)

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

logger = logging.getLogger(__name__)


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
        self.dlg = DialogBase(parent, "系统设置", (0, 0), modal=False)
        # Restore the geometry calcs from DialogBase
        screen = None
        if parent and hasattr(parent, "screen"):
            screen = parent.screen()
        elif hasattr(self.dlg, "screen"):
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
            pad = list(padding)
            # 兼容 3 元组 (left, top, bottom)：右侧沿用左侧边距（左右对称）
            if len(pad) == 3:
                pad = [pad[0], pad[1], pad[0], pad[2]]
            sec.layout().setContentsMargins(*pad)
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
        self.dlg.header("系统设置", "配置通知、监控、AI、代理、Cookie 等全部参数 ♪ 天依陪你一起把每个细节都调好~")

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
            max_m = int(self.max_monitors.text() if hasattr(self.max_monitors, "text") else self.max_monitors)
            if not (10 <= max_m <= 500):
                QMessageBox.critical(
                    self.dlg, "呜…没通过验证", "最大监控数要在 10 ~ 500 之间哦,像天依的歌也有音域范围呢 ♪"
                )
                return False
        except ValueError:
            QMessageBox.critical(self.dlg, "呜…没通过验证", "最大监控数要填整数哦,小数可唱不成歌呢 ♪")
            return False
        try:
            val = self.predict_hours.text() if hasattr(self.predict_hours, "text") else str(self.predict_hours.value())
            pred_hours = int(val)
            if not (24 <= pred_hours <= 720):
                QMessageBox.critical(
                    self.dlg, "呜…没通过验证", "预测时长要在 24 ~ 720 小时之间哦,太长了天依的歌声会够不到呢 ♪"
                )
                return False
        except ValueError:
            QMessageBox.critical(self.dlg, "呜…没通过验证", "预测时长要填整数哦 ♪")
            return False
        try:
            val = (
                self.min_confidence.text() if hasattr(self.min_confidence, "text") else str(self.min_confidence.value())
            )
            confidence = float(val)
            if not (0.1 <= confidence <= 1.0):
                QMessageBox.critical(
                    self.dlg, "呜…没通过验证", "最小置信度要在 0.1 ~ 1.0 之间哦,天依需要一点点信任才敢唱呢 ♪"
                )
                return False
        except ValueError:
            QMessageBox.critical(self.dlg, "呜…没通过验证", "最小置信度要填数字哦 ♪")
            return False
        return True

    @staticmethod
    def _text_or_value(widget, cast):
        """兼容 QLineEdit(.text) / QSpinBox(.value) / 裸值 的取值转换。"""
        if hasattr(widget, "text"):
            raw = widget.text()
        elif hasattr(widget, "value"):
            raw = widget.value()
        else:
            raw = widget
        return cast(raw)

    def _collect_onebot_cfg(self):
        """收集 OneBot / QQ 通知配置。"""
        return {
            "enabled": self.onebot_enabled.isChecked() if hasattr(self.onebot_enabled, "isChecked") else False,
            "http_url": self.onebot_http.text().strip() if hasattr(self.onebot_http, "text") else "",
            "ws_url": self.onebot_ws.text().strip() if hasattr(self.onebot_ws, "text") else "",
            "access_token": self.onebot_token.text().strip() if hasattr(self.onebot_token, "text") else "",
            "private_qq": self.qq_private.text().strip() if hasattr(self.qq_private, "text") else "",
            "group_qq": self.qq_group.text().strip() if hasattr(self.qq_group, "text") else "",
        }

    def _collect_webhooks(self):
        """收集 webhook 机器人列表（url 为空的行忽略）。"""
        webhooks = []
        for name_entry, type_combo, url_entry, _ in getattr(self, "_webhook_rows", []):
            url = url_entry.text().strip()
            if url:
                webhooks.append(
                    {
                        "name": name_entry.text().strip() or "webhook",
                        "type": str(type_combo.currentData() or "generic"),
                        "url": url,
                    }
                )
        return webhooks

    def _collect_thresholds(self):
        """收集阈值表（非法行跳过；名称为空时按数值自动命名）。"""
        thresholds = []
        for v_widget, n_widget, _ in getattr(self, "_thresh_rows", []):
            try:
                value = int(v_widget.text() if hasattr(v_widget, "text") else v_widget.value())
                name = n_widget.text().strip() if hasattr(n_widget, "text") else str(n_widget)
                if not name:
                    name = auto_threshold_name(value)
                if value > 0:
                    thresholds.append([value, name])
            except (ValueError, TypeError):
                continue
        return thresholds

    def _encrypt_secrets(self, profiles, token, encrypt):
        """写盘前加密 AI profiles 的 api_key 与 OneBot access_token。"""
        for profile in profiles:
            key = profile.get("api_key", "")
            if key:
                profile["api_key"] = encrypt(key)
        if token:
            self._cfg["onebot"]["access_token"] = encrypt(token)

    def _restore_secrets(self, profiles, encrypted_token, decrypt):
        """写盘后恢复明文，避免 UI / 通知模块拿到密文。

        Args:
            profiles: AI 配置列表（其 api_key 此时已是密文，原地还原）
            encrypted_token: OneBot access_token 的**落盘密文**（非明文）
            decrypt: 解密函数
        """
        for profile in profiles:
            key = profile.get("api_key", "")
            if key:
                try:
                    profile["api_key"] = decrypt(key)
                except Exception:
                    pass
        if encrypted_token:
            try:
                self._cfg["onebot"]["access_token"] = decrypt(encrypted_token)
            except Exception:
                pass

    def _persist_settings(self):
        from config import save_config
        from utils.crypto import decrypt, encrypt

        max_m = self._text_or_value(self.max_monitors, int)
        pred_hours = self._text_or_value(self.predict_hours, int)
        confidence = self._text_or_value(self.min_confidence, float)

        self._cfg["onebot"] = self._collect_onebot_cfg()
        self._cfg.setdefault("notification", {})["webhooks"] = self._collect_webhooks()
        self._cfg["monitor"]["max_monitor_count"] = max_m
        self._cfg["prediction"]["prediction_hours"] = pred_hours
        self._cfg["prediction"]["min_confidence"] = confidence

        # 可选开关（部分设置页可能未构建对应控件）
        if hasattr(self, "auto_escalate"):
            self._cfg["prediction"]["auto_escalate"] = bool(self.auto_escalate.isChecked())
        if hasattr(self, "escalate_factor"):
            self._cfg["prediction"]["escalate_factor"] = float(self.escalate_factor.value())
        if hasattr(self, "close_to_tray"):
            self._cfg.setdefault("ui", {})["close_to_tray"] = bool(self.close_to_tray.isChecked())
        if hasattr(self, "theme_combo"):
            self._cfg.setdefault("ui", {})["theme"] = str(self.theme_combo.currentData() or "darkly")

        thresholds = self._collect_thresholds()
        if thresholds:
            self._cfg["prediction"]["thresholds"] = thresholds

        profiles = self._profiles
        token = self._cfg["onebot"].get("access_token", "")
        self._encrypt_secrets(profiles, token, encrypt)
        # 记录**落盘密文**用于还原：此前实现误把明文 token 再解密一次（异常被吞），
        # 导致保存后内存里仍是密文，_apply_settings 会把密文交给通知模块
        encrypted_token = self._cfg["onebot"].get("access_token", "")

        self._cfg["ai"] = {
            "enabled": any(p.get("api_key") for p in profiles),
            "profiles": profiles,
            "selected_profile": self._ai_profile_cb.currentText() if hasattr(self, "_ai_profile_cb") else "",
        }
        save_config(self._cfg)
        self._restore_secrets(profiles, encrypted_token, decrypt)

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

        # 即时应用主题偏好（新开窗口/动态取 C 的组件立即生效；主界面需重启全量换装）
        if hasattr(self, "theme_combo") and self.gui is not None:
            try:
                from ui.theme import C, THEME_DARK, init_theme, qapp

                chosen = str(self.theme_combo.currentData() or "darkly")
                is_dark = C.get("bg_base") == THEME_DARK.get("bg_base")
                if (chosen == "light" and is_dark) or (chosen != "light" and not is_dark):
                    init_theme(qapp, dark=chosen != "light")
                # 同步标题栏切换按钮提示
                if hasattr(self.gui, "_theme_btn"):
                    self.gui._theme_btn.setToolTip("◐ 当前为亮色主题" if chosen == "light" else "◐ 当前为深色主题")
            except Exception as e:
                logger.debug("应用主题偏好失败: %s", e)

        QMessageBox.information(self.dlg, "存好啦 ♪", "设置都存好啦 ♪ 天依记在心里了哦~")
        self.dlg.close()
