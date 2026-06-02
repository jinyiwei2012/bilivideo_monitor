"""
OneBot 通知设置模块
===================

本模块为 ``SettingsWindow`` 提供 mixin 函数，构建「通知设置」标签页。
支持 OneBot (QQ Bot) 协议的连接配置与测试：

  - HTTP 地址：OneBot HTTP API 入口（默认 http://127.0.0.1:5700）
  - WebSocket 地址：OneBot 反向 WebSocket 连接（默认 ws://127.0.0.1:6700）
  - Access Token：鉴权密钥（可选，输入时用 * 遮蔽）
  - 私聊/群聊 QQ 号：推送目标
  - 启用开关：控制是否启用 OneBot 通知

提供「测试连接」功能，通过后台线程尝试连接 OneBot 服务，
测试完成后自动恢复原始配置，不影响其他模块运行。
"""

import tkinter as tk
from tkinter import ttk, messagebox
from ui.theme import C
from ui.helpers import FONT, FONT_SM


def _build_notification_tab(self, nb):
    """
    构建「通知设置」标签页并注册到 Notebook。
    包含 OneBot 连接参数表单、启用开关和测试连接按钮。

    :param self: SettingsWindow 实例（隐式）
    :param nb: ttk.Notebook 控件，标签页容器
    """
    page = tk.Frame(nb, bg=C["bg_base"])
    nb.add(page, text="  通知设置  ")
    sec = self._section(page, "OneBot 连接参数", (16, 16, 8))
    self.onebot_http = self._field(
        sec, "HTTP地址", self._cfg.get("onebot", {}).get("http_url", "http://127.0.0.1:5700")
    )
    self.onebot_ws = self._field(
        sec, "WebSocket地址", self._cfg.get("onebot", {}).get("ws_url", "ws://127.0.0.1:6700")
    )
    # Access Token 输入框使用 show="*" 遮蔽敏感内容
    self.onebot_token = self._field(
        sec, "Access Token", self._cfg.get("onebot", {}).get("access_token", ""), show="*"
    )
    self.qq_private = self._field(sec, "私聊QQ号", self._cfg.get("onebot", {}).get("private_qq", ""))
    self.qq_group = self._field(sec, "群号", self._cfg.get("onebot", {}).get("group_qq", ""))

    # 启用开关（BooleanVar）
    enabled = self._cfg.get("onebot", {}).get("enabled", False)
    self.onebot_enabled = tk.BooleanVar(value=enabled)
    cb_frame = tk.Frame(sec, bg=C["bg_elevated"])
    cb_frame.pack(fill=tk.X, pady=(8, 4))
    ttk.Checkbutton(cb_frame, text="启用 OneBot 通知", variable=self.onebot_enabled).pack(anchor="w")

    ttk.Button(sec, text="测试连接", command=self._test_connection).pack(anchor="w", padx=4, pady=(8, 0))


def _test_connection(self):
    """
    测试 OneBot 连接是否可用。

    流程：
      1. 保存当前 notification_manager 的原始配置
      2. 将 UI 输入值临时写入 notification_manager
      3. 在后台线程调用 test_connection()
      4. 测试结束后通过 finally 恢复原始配置
      5. 通过 after() 回到主线程显示结果

    这样即使测试失败，也不会影响正在运行的监控通知功能。

    :param self: SettingsWindow 实例（隐式）
    """
    http_url = self.onebot_http.get().strip()
    token = self.onebot_token.get().strip()

    if not http_url:
        messagebox.showwarning("提示", "请先填写 HTTP 地址", parent=self.window)
        return

    from core.notification import notification_manager
    from threading import Thread

    # 保存原始配置，测试后恢复
    saved_http = notification_manager.onebot_http
    saved_ws = notification_manager.onebot_ws
    saved_token = notification_manager.token
    notification_manager.onebot_http = http_url
    notification_manager.onebot_ws = self.onebot_ws.get().strip() or saved_ws
    notification_manager.token = token

    def _do_test():
        """后台线程：执行连接测试"""
        try:
            result = notification_manager.test_connection()
            self.window.after(0, lambda: self._show_test_result(result))
        finally:
            # 无论成功失败都恢复原始配置
            notification_manager.onebot_http = saved_http
            notification_manager.onebot_ws = saved_ws
            notification_manager.token = saved_token

    Thread(target=_do_test, daemon=True).start()


def _show_test_result(self, result: dict):
    """
    显示 OneBot 连接测试的结果弹窗。

    :param self: SettingsWindow 实例（隐式）
    :param result: notification_manager.test_connection() 的返回值
                   {'ok': bool, 'version': str, 'channel': str, 'error': str}
    """
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
