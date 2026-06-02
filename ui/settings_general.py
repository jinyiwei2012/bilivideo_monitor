"""
常规设置模块（预测参数 + 重试参数 + 运行状态）
=================================================

本模块为 ``SettingsWindow`` 提供 mixin 函数，构建「常规设置」标签页。
包含三个子区域：
  - 预测参数：预测时长、最小置信度
  - 重试参数：最大重试次数、基础延迟、请求间隔、应用按钮
  - 运行状态：实时显示 BilibiliAPI 的登录/代理/412 错误等运行态信息

所有函数以 ``_build_*`` / ``_apply_*`` / ``_refresh_*`` / ``_reset_*`` 命名，
由 ``settings_window.py`` 中 SettingsWindow 通过 monkey-patch 方式附加为实例方法。

.. note::
   本文件的所有函数依赖 ``self`` 引用 SettingsWindow 实例，因此不能独立调用。
"""

import tkinter as tk
import logging
from tkinter import ttk
from ui.theme import C
from ui.helpers import FONT, FONT_SM
from core.bilibili_api import get_bilibili_api
from utils.update_checker import _confirm_risky

logger = logging.getLogger(__name__)


def _build_general_tab(self, nb):
    """
    构建「常规设置」标签页并注册到 Notebook。

    :param self: SettingsWindow 实例（隐式）
    :param nb: ttk.Notebook 控件，标签页容器
    """
    page = tk.Frame(nb, bg=C["bg_base"])
    nb.add(page, text="  常规设置  ")

    self._build_general_predict_section(page)
    self._build_general_retry_section(page)
    self._build_general_status_section(page)


def _build_general_predict_section(self, page):
    """
    构建「预测参数」卡片区域，包含：
      - 预测时长（小时）：控制算法向前预测的天/周数
      - 最小置信度：低于此值的预测结果将被忽略

    :param self: SettingsWindow 实例（隐式）
    :param page: 父容器 Frame
    """
    sec = self._section(page, "预测参数")
    # Spinbox 数字输入 — 预测时长，范围 24~720 小时
    self.predict_hours = self._spin_field(
        sec, "预测时长(小时)", self._cfg.get("prediction", {}).get("prediction_hours", 168), 24, 720
    )
    # Spinbox 浮点输入 — 最小置信度，范围 0.1~1.0
    self.min_confidence = self._spin_field(
        sec, "最小置信度", self._cfg.get("prediction", {}).get("min_confidence", 0.5), 0.1, 1.0
    )


def _build_general_retry_section(self, page):
    """
    构建「重试参数」卡片区域，用于配置 Bilibili API 的请求重试策略。
    包含：最大重试次数、基础重试延迟（秒）、最小请求间隔（秒）。
    底部提供「应用重试设置」按钮，即时生效。

    :param self: SettingsWindow 实例（隐式）
    :param page: 父容器 Frame
    """
    sec = tk.Frame(page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
    sec.pack(fill=tk.X, padx=16, pady=(0, 8), ipadx=10, ipady=10)

    tk.Label(
        sec, text="重试参数", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 8, "bold")
    ).pack(anchor="w")

    def _spin_r(parent, label, default, fr, to):
        """内部辅助：在 retry section 中创建一个带标签的 Spinbox 行"""
        f = tk.Frame(parent, bg=C["bg_elevated"])
        f.pack(fill=tk.X, pady=4)
        tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"], font=FONT, width=20, anchor="w").pack(
            side=tk.LEFT
        )
        sv = tk.DoubleVar(value=default)
        sp = ttk.Spinbox(f, from_=fr, to=to, textvariable=sv, width=10)
        sp.pack(side=tk.LEFT, padx=(6, 0))
        return sv

    # 最大重试次数（整数）：遇到 412 错误时的重试上限
    self.retry_count_var = _spin_r(sec, "最大重试次数", get_bilibili_api().max_retries, 1, 10)
    # 基础重试延迟（秒）：指数退避的基准等待时间
    self.base_delay_var = _spin_r(sec, "基础重试延迟(秒)", get_bilibili_api().base_retry_delay, 1, 30)
    # 最小请求间隔（秒）：两次 API 请求之间的冷却时间
    self.min_interval_var = _spin_r(sec, "最小请求间隔(秒)", get_bilibili_api()._min_request_interval, 0.1, 10)

    ttk.Button(sec, text="应用重试设置", command=self._apply_retry_settings).pack(anchor="w", pady=(8, 0))


def _build_general_status_section(self, page):
    """
    构建「运行状态」卡片区域，实时展示 Bilibili API 的关键运行指标：
      - 登录状态 / 登录账号 / Cookie 配置状态
      - 连续 412 错误计数（频率限制）
      - 请求间隔 / 代理数量

    底部提供「刷新状态」和「重置状态」按钮。初始化时自动刷新一次。

    :param self: SettingsWindow 实例（隐式）
    :param page: 父容器 Frame
    """
    sec = tk.Frame(page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
    sec.pack(fill=tk.X, padx=16, pady=(0, 12), ipadx=10, ipady=8)

    tk.Label(
        sec, text="运行状态", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 8, "bold")
    ).pack(anchor="w")

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
        tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"], font=FONT, width=16, anchor="w").pack(
            side=tk.LEFT
        )
        vl = tk.Label(f, text="-", bg=C["bg_elevated"], fg=C["success"], font=FONT)
        vl.pack(side=tk.LEFT)
        self.status_labels[key] = vl  # 保存引用，后续 _apply_status 中更新

    btn_s = tk.Frame(sec, bg=C["bg_elevated"])
    btn_s.pack(fill=tk.X, pady=(8, 0))
    ttk.Button(btn_s, text="刷新状态", command=self._refresh_status).pack(side=tk.LEFT, padx=(0, 4))
    ttk.Button(
        btn_s, text="重置状态", command=lambda: _confirm_risky("重置 API 状态") and self._reset_status()
    ).pack(side=tk.LEFT, padx=4)

    # 初始化时自动加载一次状态
    self._refresh_status()


def _apply_retry_settings(self):
    """
    将用户在 UI 中设置的重试参数同步到 BilibiliAPI 单例。
    同步后弹出成功提示。

    :param self: SettingsWindow 实例（隐式）
    """
    get_bilibili_api().max_retries = int(self.retry_count_var.get())
    get_bilibili_api().base_retry_delay = self.base_delay_var.get()
    get_bilibili_api()._min_request_interval = self.min_interval_var.get()
    from tkinter import messagebox
    messagebox.showinfo("成功", "重试设置已更新", parent=self.window)


def _refresh_status(self):
    """
    异步刷新 API 运行状态（后台线程调用 get_bilibili_api().get_status()）。
    获取到数据后通过 after() 回到主线程更新 UI。

    :param self: SettingsWindow 实例（隐式）
    """
    import threading

    def _worker():
        """后台线程：调用 API 获取运行状态"""
        try:
            status = get_bilibili_api().get_status()
        except Exception as e:
            logger.debug("获取状态失败: %s", e)
            status = {}
        # 回到主线程更新 UI
        self.window.after(0, lambda s=status: self._apply_status(s))

    threading.Thread(target=_worker, daemon=True).start()


def _apply_status(self, status: dict):
    """
    将 API 状态字典写入 UI 标签，并用颜色区分正常/异常。

    - 登录状态 → ✅/❌ 图标
    - 连续 412 错误 → 大于 0 时红色
    - Cookie/代理 → 有无判断

    :param self: SettingsWindow 实例（隐式）
    :param status: BilibiliAPI.get_status() 返回的状态字典
    """
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
    """
    重置 Bilibili API 的内部状态（连续 412 计数、代理索引等）。
    操作前弹出确认对话框，确认后清除状态并刷新 UI。

    :param self: SettingsWindow 实例（隐式）
    """
    from tkinter import messagebox
    if messagebox.askyesno("确认", "确定要重置所有状态吗？", parent=self.window):
        get_bilibili_api().reset_status()
        self._refresh_status()
