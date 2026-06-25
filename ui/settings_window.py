"""
系统设置主窗口 — PyQt6 版

组合各子模块的 mixin 函数构建完整 SettingsWindow 类。
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
from ui.helpers import FONT, project_path, auto_threshold_name
from ui.dialog_base import DialogBase

logger = logging.getLogger(__name__)

# ── 导入各子模块 mixin ──
from ui.settings_notification import (
    _build_notification_tab,
    _test_connection,
    _show_test_result,
)
from ui.settings_monitor import (
    _build_monitor_tab,
    _add_threshold_row,
)
from ui.settings_general import (
    _build_general_tab,
    _build_general_predict_section,
    _build_general_retry_section,
    _build_general_status_section,
    _apply_retry_settings,
    _refresh_status,
    _apply_status,
    _reset_status,
)
from ui.settings_proxy import (
    _build_proxy_tab,
    _auto_fetch_proxies,
    _auto_fetch_worker,
    _update_proxy_text,
    _add_proxy_source,
    _add_proxy_entry,
    _batch_import_proxies,
    _apply_proxies,
    _verify_proxy_persisted,
    _check_proxies,
    _auto_remove_failed_proxies,
    _sync_proxy_text_to_cfg,
)
from ui.settings_account import (
    _build_account_tab,
    _refresh_cookie_display,
    _toggle_cookie_unlock,
    _apply_cookies,
    _parse_cookie_input,
    _verify_login,
    _clear_cookies,
    _import_from_browser,
    _on_browser_cookies,
    _import_cookie_editor,
    _qrcode_login,
    _refresh_account_list,
    _switch_account,
    _add_account_dialog,
    _remove_account,
    _password_login,
)
from ui.settings_ai import (
    _build_ai_tab,
    _on_ai_profile_selected,
    _save_ai_profile,
    _delete_ai_profile,
    _new_ai_profile,
    _test_ai_connection,
)
from ui.settings_weights import (
    _build_weights_tab,
    _reset_all_weights,
    _refresh_weights,
    _save_weights,
)
from ui.settings_training import (
    _build_training_tab,
    _refresh_device_info,
    _on_infer_device_changed,
    _refresh_data_size,
    _refresh_algo_list,
    _tr_select_all,
    _tr_select_untrained,
    _on_train_start,
    _on_train_cancel,
    _on_export_checkpoints,
    _on_import_checkpoints,
    _poll_training_progress,
    _open_version_manager,
)
from ui.settings_about import (
    _build_about_tab,
)


# ── 辅助函数：创建标签式字段行 ──

def _field(parent, label, default, show=None):
    """创建一行标签+输入框"""
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 2, 0, 2)

    lbl = QLabel(label)
    lbl.setStyleSheet(f"color: {C['text_2']};")
    lbl.setFixedWidth(130)
    layout.addWidget(lbl)

    entry = QLineEdit(default)
    entry.setStyleSheet(f"background-color: {C['bg_base']}; color: {C['text_1']};")
    if show:
        entry.setEchoMode(QLineEdit.EchoMode.Password)
    layout.addWidget(entry, 1)
    return entry


def _spin_field(parent, label, default, fr, to):
    """创建一行标签+整数微调框"""
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 2, 0, 2)

    lbl = QLabel(label)
    lbl.setStyleSheet(f"color: {C['text_2']};")
    lbl.setFixedWidth(130)
    layout.addWidget(lbl)

    spin = QSpinBox()
    spin.setRange(fr, to)
    spin.setValue(int(default))
    layout.addWidget(spin)
    layout.addStretch()
    return spin


def _spin_field_float(parent, label, default, fr, to):
    """创建一行标签+浮点数微调框"""
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 2, 0, 2)

    lbl = QLabel(label)
    lbl.setStyleSheet(f"color: {C['text_2']};")
    lbl.setFixedWidth(130)
    layout.addWidget(lbl)

    spin = QDoubleSpinBox()
    spin.setRange(fr, to)
    spin.setValue(default)
    spin.setSingleStep(0.1)
    spin.setDecimals(2)
    layout.addWidget(spin)
    layout.addStretch()
    return spin


def _section_widget(parent, title):
    """创建一个卡片分段的 QFrame"""
    sec = QFrame(parent)
    sec.setStyleSheet(f"""
        QFrame {{
            background-color: {C['bg_elevated']};
            border: 1px solid {C['border_sub']};
            border-radius: {C['radius_md']}px;
        }}
    """)
    layout = QVBoxLayout(sec)
    if title:
        lbl = QLabel(title)
        lbl.setStyleSheet(f"color: {C['text_2']}; font-weight: bold; font-size: 8pt;")
        layout.addWidget(lbl)
    return sec


class SettingsWindow:
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
        return {"proxies": [], "cookies": {}, "accounts": []}

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

    def setup_ui(self):
        self.dlg.header("系统设置", "配置通知、监控、AI、代理、Cookie 等全部参数")

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {C['border']};
                border-top: none;
                background-color: {C['bg_base']};
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

        self.dlg.button_row(
            [
                ("取消", self._on_close, ""),
                ("保存设置", self._save_settings, "primary"),
            ]
        )

    # ──── 关闭 ────
    def _on_close(self):
        self._sync_proxy_text_to_cfg()
        self._save_net_config()
        self._verify_proxy_persisted()
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

        self._cfg["ai"] = {
            "enabled": any(p.get("api_key") for p in self._profiles),
            "profiles": self._profiles,
            "selected_profile": self._ai_profile_var,
        }
        save_config(self._cfg)

    def _apply_settings(self):
        from core.notification import notification_manager

        notification_manager.configure(self._cfg)

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


# ── 将 mixin 函数附加到 SettingsWindow ──

# Notification
SettingsWindow._build_notification_tab = _build_notification_tab
SettingsWindow._test_connection = _test_connection
SettingsWindow._show_test_result = _show_test_result

# Monitor
SettingsWindow._build_monitor_tab = _build_monitor_tab
SettingsWindow._add_threshold_row = _add_threshold_row

# General
SettingsWindow._build_general_tab = _build_general_tab
SettingsWindow._build_general_predict_section = _build_general_predict_section
SettingsWindow._build_general_retry_section = _build_general_retry_section
SettingsWindow._build_general_status_section = _build_general_status_section
SettingsWindow._apply_retry_settings = _apply_retry_settings
SettingsWindow._refresh_status = _refresh_status
SettingsWindow._apply_status = _apply_status
SettingsWindow._reset_status = _reset_status

# Proxy
SettingsWindow._build_proxy_tab = _build_proxy_tab
SettingsWindow._auto_fetch_proxies = _auto_fetch_proxies
SettingsWindow._auto_fetch_worker = _auto_fetch_worker
SettingsWindow._update_proxy_text = _update_proxy_text
SettingsWindow._add_proxy_source = _add_proxy_source
SettingsWindow._add_proxy_entry = _add_proxy_entry
SettingsWindow._batch_import_proxies = _batch_import_proxies
SettingsWindow._apply_proxies = _apply_proxies
SettingsWindow._verify_proxy_persisted = _verify_proxy_persisted
SettingsWindow._check_proxies = _check_proxies
SettingsWindow._auto_remove_failed_proxies = _auto_remove_failed_proxies
SettingsWindow._sync_proxy_text_to_cfg = _sync_proxy_text_to_cfg

# Account
SettingsWindow._build_account_tab = _build_account_tab
SettingsWindow._refresh_cookie_display = _refresh_cookie_display
SettingsWindow._toggle_cookie_unlock = _toggle_cookie_unlock
SettingsWindow._apply_cookies = _apply_cookies
SettingsWindow._parse_cookie_input = _parse_cookie_input
SettingsWindow._verify_login = _verify_login
SettingsWindow._clear_cookies = _clear_cookies
SettingsWindow._import_from_browser = _import_from_browser
SettingsWindow._on_browser_cookies = _on_browser_cookies
SettingsWindow._import_cookie_editor = _import_cookie_editor
SettingsWindow._qrcode_login = _qrcode_login
SettingsWindow._refresh_account_list = _refresh_account_list
SettingsWindow._switch_account = _switch_account
SettingsWindow._add_account_dialog = _add_account_dialog
SettingsWindow._remove_account = _remove_account
SettingsWindow._password_login = _password_login

# Advanced
SettingsWindow._build_ai_tab = _build_ai_tab
SettingsWindow._on_ai_profile_selected = _on_ai_profile_selected
SettingsWindow._save_ai_profile = _save_ai_profile
SettingsWindow._delete_ai_profile = _delete_ai_profile
SettingsWindow._new_ai_profile = _new_ai_profile
SettingsWindow._test_ai_connection = _test_ai_connection

SettingsWindow._build_weights_tab = _build_weights_tab
SettingsWindow._reset_all_weights = _reset_all_weights
SettingsWindow._refresh_weights = _refresh_weights
SettingsWindow._save_weights = _save_weights

SettingsWindow._build_training_tab = _build_training_tab
SettingsWindow._refresh_device_info = _refresh_device_info
SettingsWindow._on_infer_device_changed = _on_infer_device_changed
SettingsWindow._refresh_data_size = _refresh_data_size
SettingsWindow._refresh_algo_list = _refresh_algo_list
SettingsWindow._tr_select_all = _tr_select_all
SettingsWindow._tr_select_untrained = _tr_select_untrained
SettingsWindow._on_train_start = _on_train_start
SettingsWindow._on_train_cancel = _on_train_cancel
SettingsWindow._on_export_checkpoints = _on_export_checkpoints
SettingsWindow._on_import_checkpoints = _on_import_checkpoints
SettingsWindow._poll_training_progress = _poll_training_progress
SettingsWindow._open_version_manager = _open_version_manager

SettingsWindow._build_about_tab = _build_about_tab

# 基础 widget 工具函数（模块内定义，需绑定到类）
SettingsWindow._field = _field
SettingsWindow._spin_field = _spin_field
SettingsWindow._spin_field_float = _spin_field_float
