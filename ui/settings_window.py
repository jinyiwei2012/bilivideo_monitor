"""
系统设置主窗口

组合各子模块的 mixin 函数构建完整 SettingsWindow 类。
"""

import json
import os
import tkinter as tk
import logging
from typing import Any
from tkinter import ttk, messagebox

from ui.theme import C
from ui.helpers import FONT, FONT_SM, FONT_MONO, project_path, auto_threshold_name
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
from ui.settings_advanced import (
    _build_ai_tab,
    _on_ai_profile_selected,
    _save_ai_profile,
    _delete_ai_profile,
    _new_ai_profile,
    _test_ai_connection,
    _build_weights_tab,
    _reset_all_weights,
    _refresh_weights,
    _save_weights,
    _build_training_tab,
    _discover_torch_algorithms,
    _refresh_device_info,
    _on_force_cpu_changed,
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
    _build_about_tab,
)
from utils.update_checker import _s, _hard, _train, _confirm_risky


class SettingsWindow:
    """统一设置窗口"""

    def __init__(self, parent=None, gui=None):
        self.dlg = DialogBase(
            parent, "系统设置", DialogBase.calc_geometry(parent, 0.48, 0.68), resizable=(True, True), modal=False
        )
        self.window = self.dlg.window
        self.gui = gui

        from config import load_config

        self._cfg = load_config()

        self._net_cfg_file = project_path("data", "network_config.json")
        self._net_cfg = self._load_net_config()

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

    # ── UI helpers ──
    @staticmethod
    def _field(parent, label, default, show=None):
        f = tk.Frame(parent, bg=C["bg_elevated"])
        f.pack(fill=tk.X, pady=4)
        tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"], font=FONT, width=16, anchor="w").pack(side=tk.LEFT)
        e = ttk.Entry(f, width=40, font=FONT, show=show or "")
        e.insert(0, default)
        e.pack(side=tk.LEFT, padx=(8, 0))
        return e

    @staticmethod
    def _spin_field(parent, label, default, fr, to):
        f = tk.Frame(parent, bg=C["bg_elevated"])
        f.pack(fill=tk.X, pady=4)
        tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"], font=FONT, width=16, anchor="w").pack(side=tk.LEFT)
        sv = tk.StringVar(value=str(default))
        sp = ttk.Spinbox(f, from_=fr, to=to, textvariable=sv, width=10)
        sp.pack(side=tk.LEFT, padx=(8, 0))
        return sv

    def _section(self, parent, title, padding=(16, 16, 8)):
        f = tk.Frame(parent, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        f.pack(fill=tk.X, padx=padding[0], pady=padding[1:], ipadx=12, ipady=14)
        if title:
            tk.Label(f, text=title, bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 8, "bold")).pack(
                anchor="w"
            )
        return f

    @staticmethod
    def _clear_entry(entry, value):
        entry.delete(0, tk.END)
        entry.insert(0, value)

    # ═══════════════ UI 构建 ═══════════════════════════════
    def setup_ui(self):
        self.dlg.header("系统设置", "配置通知、监控、AI、代理、Cookie 等全部参数")

        nb = ttk.Notebook(self.dlg.container)
        nb.pack(fill=tk.BOTH, expand=True, padx=24, pady=(12, 0))

        self._build_notification_tab(nb)
        self._build_monitor_tab(nb)
        self._build_general_tab(nb)
        self._build_ai_tab(nb)
        self._build_weights_tab(nb)
        self._build_training_tab(nb)
        self._build_proxy_tab(nb)
        self._build_account_tab(nb)
        self._build_about_tab(nb)

        self.dlg.button_row(
            [
                ("取消", self._on_close, ""),
                ("保存设置", self._save_settings, "primary"),
            ]
        )
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

    # ──── 关闭 ────
    def _on_close(self):
        self._sync_proxy_text_to_cfg()
        self._save_net_config()
        self._verify_proxy_persisted()
        self.window.destroy()

    # ──── 保存系统设置 ────
    def _save_settings(self):  # noqa: C901
        try:
            interval = int(self.check_interval.get())
            if not (60 <= interval <= 3600):
                messagebox.showerror("验证失败", "检查间隔必须在 60 ~ 3600 秒之间", parent=self.window)
                return
        except ValueError:
            messagebox.showerror("验证失败", "检查间隔必须为整数", parent=self.window)
            return
        try:
            max_m = int(self.max_monitors.get())
            if not (10 <= max_m <= 500):
                messagebox.showerror("验证失败", "最大监控数必须在 10 ~ 500 之间", parent=self.window)
                return
        except ValueError:
            messagebox.showerror("验证失败", "最大监控数必须为整数", parent=self.window)
            return
        try:
            pred_hours = int(self.predict_hours.get())
            if not (24 <= pred_hours <= 720):
                messagebox.showerror("验证失败", "预测时长必须在 24 ~ 720 小时之间", parent=self.window)
                return
        except ValueError:
            messagebox.showerror("验证失败", "预测时长必须为整数", parent=self.window)
            return
        try:
            confidence = float(self.min_confidence.get())
            if not (0.1 <= confidence <= 1.0):
                messagebox.showerror("验证失败", "最小置信度必须在 0.1 ~ 1.0 之间", parent=self.window)
                return
        except ValueError:
            messagebox.showerror("验证失败", "最小置信度必须为数字", parent=self.window)
            return

        from config import save_config

        self._cfg["onebot"] = {
            "enabled": self.onebot_enabled.get(),
            "http_url": self.onebot_http.get().strip(),
            "ws_url": self.onebot_ws.get().strip(),
            "access_token": self.onebot_token.get().strip(),
            "private_qq": self.qq_private.get().strip(),
            "group_qq": self.qq_group.get().strip(),
        }
        self._cfg["monitor"]["check_interval"] = interval
        self._cfg["monitor"]["max_monitor_count"] = max_m
        self._cfg["prediction"]["prediction_hours"] = pred_hours
        self._cfg["prediction"]["min_confidence"] = confidence

        th_data = []
        for v_var, n_var, _ in getattr(self, "_thresh_rows", []):
            try:
                v = int(v_var.get())
                n = n_var.get().strip() or auto_threshold_name(v)
                if v > 0:
                    th_data.append([v, n])
            except (ValueError, TypeError):
                continue
        if th_data:
            self._cfg["prediction"]["thresholds"] = th_data

        self._cfg["ai"] = {
            "enabled": any(p.get("api_key") for p in self._profiles),
            "profiles": self._profiles,
            "selected_profile": self._ai_profile_var.get(),
        }
        save_config(self._cfg)

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

        messagebox.showinfo("成功", "设置已保存", parent=self.window)
        self.window.destroy()


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
SettingsWindow._discover_torch_algorithms = _discover_torch_algorithms
SettingsWindow._refresh_device_info = _refresh_device_info
SettingsWindow._on_force_cpu_changed = _on_force_cpu_changed
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
