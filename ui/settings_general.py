"""
常规设置（预测参数 + 重试参数 + 运行状态）

Mixin functions for SettingsWindow.
"""

import tkinter as tk
import logging
from tkinter import ttk
from ui.theme import C
from ui.helpers import FONT
from core.bilibili_api import get_bilibili_api
from utils.update_checker import _confirm_risky

logger = logging.getLogger(__name__)


def _build_general_tab(self, nb):
    page = tk.Frame(nb, bg=C["bg_base"])
    nb.add(page, text="  常规设置  ")

    self._build_general_predict_section(page)
    self._build_general_retry_section(page)
    self._build_general_status_section(page)


def _build_general_predict_section(self, page):
    sec = self._section(page, "预测参数")
    self.predict_hours = self._spin_field(
        sec, "预测时长(小时)", self._cfg.get("prediction", {}).get("prediction_hours", 168), 24, 720
    )
    self.min_confidence = self._spin_field(
        sec, "最小置信度", self._cfg.get("prediction", {}).get("min_confidence", 0.5), 0.1, 1.0
    )


def _build_general_retry_section(self, page):
    sec = tk.Frame(page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
    sec.pack(fill=tk.X, padx=16, pady=(0, 8), ipadx=10, ipady=10)

    tk.Label(sec, text="重试参数", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 8, "bold")).pack(
        anchor="w"
    )

    def _spin_r(parent, label, default, fr, to):
        f = tk.Frame(parent, bg=C["bg_elevated"])
        f.pack(fill=tk.X, pady=4)
        tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"], font=FONT, width=20, anchor="w").pack(side=tk.LEFT)
        sv = tk.DoubleVar(value=default)
        sp = ttk.Spinbox(f, from_=fr, to=to, textvariable=sv, width=10)
        sp.pack(side=tk.LEFT, padx=(6, 0))
        return sv

    self.retry_count_var = _spin_r(sec, "最大重试次数", get_bilibili_api().max_retries, 1, 10)
    self.base_delay_var = _spin_r(sec, "基础重试延迟(秒)", get_bilibili_api().base_retry_delay, 1, 30)
    self.min_interval_var = _spin_r(sec, "最小请求间隔(秒)", get_bilibili_api()._min_request_interval, 0.1, 10)

    ttk.Button(sec, text="应用重试设置", command=self._apply_retry_settings).pack(anchor="w", pady=(8, 0))


def _build_general_status_section(self, page):
    sec = tk.Frame(page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
    sec.pack(fill=tk.X, padx=16, pady=(0, 12), ipadx=10, ipady=8)

    tk.Label(sec, text="运行状态", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 8, "bold")).pack(
        anchor="w"
    )

    self.status_labels = {}
    fields = [
        ("is_login", "登录状态"),
        ("login_name", "登录账号"),
        ("has_cookies", "Cookie已配置"),
        ("consecutive_412_errors", "连续412错误"),
        ("min_request_interval", "请求间隔(秒)"),
        ("proxy_count", "代理数量"),
    ]
    for key, label in fields:
        f = tk.Frame(sec, bg=C["bg_elevated"])
        f.pack(fill=tk.X, pady=2)
        tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"], font=FONT, width=16, anchor="w").pack(side=tk.LEFT)
        vl = tk.Label(f, text="-", bg=C["bg_elevated"], fg=C["success"], font=FONT)
        vl.pack(side=tk.LEFT)
        self.status_labels[key] = vl

    btn_s = tk.Frame(sec, bg=C["bg_elevated"])
    btn_s.pack(fill=tk.X, pady=(8, 0))
    ttk.Button(btn_s, text="刷新状态", command=self._refresh_status).pack(side=tk.LEFT, padx=(0, 4))
    ttk.Button(btn_s, text="重置状态", command=lambda: _confirm_risky("重置 API 状态") and self._reset_status()).pack(
        side=tk.LEFT, padx=4
    )

    self._refresh_status()


def _apply_retry_settings(self):
    get_bilibili_api().max_retries = int(self.retry_count_var.get())
    get_bilibili_api().base_retry_delay = self.base_delay_var.get()
    get_bilibili_api()._min_request_interval = self.min_interval_var.get()
    from tkinter import messagebox

    messagebox.showinfo("成功", "重试设置已更新", parent=self.window)


def _refresh_status(self):
    import threading

    def _worker():
        try:
            status = get_bilibili_api().get_status()
        except Exception as e:
            logger.debug("获取状态失败: %s", e)
            status = {}
        self.window.after(0, lambda s=status: self._apply_status(s))

    threading.Thread(target=_worker, daemon=True).start()


def _apply_status(self, status: dict):
    for key, label in self.status_labels.items():
        value = status.get(key, "N/A")
        if key == "is_login":
            v = "✅ 已登录" if value else "❌ 未登录"
            label.config(fg=C["success"] if value else C["danger"])
        elif key == "login_name":
            v = str(value) if value else "—"
            label.config(fg=C["text_1"] if value else C["text_3"])
        elif key == "has_cookies":
            v = "是" if value else "否"
            label.config(fg=C["success"] if value else C["danger"])
        elif key == "consecutive_412_errors":
            v = str(value)
            label.config(fg=C["danger"] if value > 0 else C["success"])
        else:
            v = str(value)
            label.config(fg=C["success"])
        label.config(text=v)


def _reset_status(self):
    from tkinter import messagebox

    if messagebox.askyesno("确认", "确定要重置所有状态吗？", parent=self.window):
        get_bilibili_api().reset_status()
        self._refresh_status()
