"""
OneBot / Notification 通知设置

Mixin functions for SettingsWindow.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from ui.theme import C


def _build_notification_tab(self, nb):
    page = tk.Frame(nb, bg=C["bg_base"])
    nb.add(page, text="  通知设置  ")
    sec = self._section(page, "OneBot 连接参数", (16, 16, 8))
    self.onebot_http = self._field(
        sec, "HTTP地址", self._cfg.get("onebot", {}).get("http_url", "http://127.0.0.1:5700")
    )
    self.onebot_ws = self._field(sec, "WebSocket地址", self._cfg.get("onebot", {}).get("ws_url", "ws://127.0.0.1:6700"))
    self.onebot_token = self._field(sec, "Access Token", self._cfg.get("onebot", {}).get("access_token", ""), show="*")
    self.qq_private = self._field(sec, "私聊QQ号", self._cfg.get("onebot", {}).get("private_qq", ""))
    self.qq_group = self._field(sec, "群号", self._cfg.get("onebot", {}).get("group_qq", ""))

    enabled = self._cfg.get("onebot", {}).get("enabled", False)
    self.onebot_enabled = tk.BooleanVar(value=enabled)
    cb_frame = tk.Frame(sec, bg=C["bg_elevated"])
    cb_frame.pack(fill=tk.X, pady=(8, 4))
    ttk.Checkbutton(cb_frame, text="启用 OneBot 通知", variable=self.onebot_enabled).pack(anchor="w")

    ttk.Button(sec, text="测试连接", command=self._test_connection).pack(anchor="w", padx=4, pady=(8, 0))


def _test_connection(self):
    http_url = self.onebot_http.get().strip()
    token = self.onebot_token.get().strip()

    if not http_url:
        messagebox.showwarning("提示", "请先填写 HTTP 地址", parent=self.window)
        return

    from core.notification import notification_manager
    from threading import Thread

    saved_http = notification_manager.onebot_http
    saved_ws = notification_manager.onebot_ws
    saved_token = notification_manager.token
    notification_manager.onebot_http = http_url
    notification_manager.onebot_ws = self.onebot_ws.get().strip() or saved_ws
    notification_manager.token = token

    def _do_test():
        try:
            result = notification_manager.test_connection()
            self.window.after(0, lambda: self._show_test_result(result))
        finally:
            notification_manager.onebot_http = saved_http
            notification_manager.onebot_ws = saved_ws
            notification_manager.token = saved_token

    Thread(target=_do_test, daemon=True).start()


def _show_test_result(self, result: dict):
    if result["ok"]:
        ver = result.get("version", "") or "未知版本"
        channel = result.get("channel", "HTTP")
        messagebox.showinfo(
            "连接成功",
            f"✅ OneBot 服务连接成功\n\n通道: {channel}\n版本: {ver}",
            parent=self.window,
        )
    else:
        messagebox.showerror(
            "连接失败",
            f"❌ OneBot 服务连接失败\n\n原因: {result.get('error', '未知错误')}",
            parent=self.window,
        )
