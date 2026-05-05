"""
现代化系统设置界面
包含OneBot配置、监控设置、预测设置等
"""
import tkinter as tk
from tkinter import ttk, messagebox

from ui.theme import C
from ui.helpers import FONT
from ui.dialog_base import DialogBase


class SettingsWindow:
    """设置窗口（现代化风格）"""

    def __init__(self, parent=None):
        self.dlg = DialogBase(parent, "系统设置", "720x520", resizable=(True, True))
        self.window = self.dlg.window
        self.setup_ui()

    def setup_ui(self):
        self.dlg.header("系统设置", "配置 OneBot 通知、监控参数与预测选项")

        nb = ttk.Notebook(self.dlg.container)
        nb.pack(fill=tk.BOTH, expand=True, padx=24, pady=(12, 0))

        # ── OneBot设置页 ──
        onebot = tk.Frame(nb, bg=C["bg_base"])
        nb.add(onebot, text="  OneBot通知  ")

        sec1 = tk.Frame(onebot, bg=C["bg_elevated"],
                        highlightthickness=1, highlightbackground=C["border_sub"])
        sec1.pack(fill=tk.X, padx=16, pady=(16, 8), ipadx=12, ipady=14)

        tk.Label(sec1, text="连接参数", bg=C["bg_elevated"], fg=C["text_2"],
                 font=("Microsoft YaHei UI", 8, "bold")).pack(anchor="w")

        def _field(parent, label, default, row):
            f = tk.Frame(parent, bg=C["bg_elevated"])
            f.pack(fill=tk.X, pady=4)
            tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"],
                     font=FONT, width=16, anchor="w").pack(side=tk.LEFT)
            e = ttk.Entry(f, width=40, font=FONT)
            e.insert(0, default)
            e.pack(side=tk.LEFT, padx=(8, 0))
            return e

        self.onebot_http = _field(sec1, "HTTP地址", "http://127.0.0.1:5700", 0)
        self.onebot_ws = _field(sec1, "WebSocket地址", "ws://127.0.0.1:6700", 1)
        self.qq_private = _field(sec1, "私聊QQ号", "", 2)
        self.qq_group = _field(sec1, "群号", "", 3)

        ttk.Button(sec1, text="测试连接",
                   command=self._test_connection).pack(anchor="w", padx=4, pady=(8, 0))

        # ── 监控设置页 ──
        monitor = tk.Frame(nb, bg=C["bg_base"])
        nb.add(monitor, text="  监控参数  ")

        sec2 = tk.Frame(monitor, bg=C["bg_elevated"],
                        highlightthickness=1, highlightbackground=C["border_sub"])
        sec2.pack(fill=tk.X, padx=16, pady=(16, 8), ipadx=12, ipady=14)

        def _spin_field(parent, label, default, fr, to):
            f = tk.Frame(parent, bg=C["bg_elevated"])
            f.pack(fill=tk.X, pady=4)
            tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"],
                     font=FONT, width=16, anchor="w").pack(side=tk.LEFT)
            sv = tk.StringVar(value=str(default))
            sp = ttk.Spinbox(f, from_=fr, to=to, textvariable=sv, width=10)
            sp.pack(side=tk.LEFT, padx=(8, 0))
            return sv

        self.check_interval = _spin_field(sec2, "检查间隔(秒)", 300, 60, 3600)
        self.max_monitors = _spin_field(sec2, "最大监控数", 100, 10, 500)

        # ── 预测设置页 ──
        predict = tk.Frame(nb, bg=C["bg_base"])
        nb.add(predict, text="  预测参数  ")

        sec3 = tk.Frame(predict, bg=C["bg_elevated"],
                        highlightthickness=1, highlightbackground=C["border_sub"])
        sec3.pack(fill=tk.X, padx=16, pady=(16, 8), ipadx=12, ipady=14)

        self.predict_hours = _spin_field(sec3, "预测时长(小时)", 168, 24, 720)
        self.min_confidence = _spin_field(sec3, "最小置信度", 0.5, 0.1, 1.0)

        self.dlg.button_row([
            ("取消", self.window.destroy, ""),
            ("保存设置", self._save_settings, "primary"),
        ])

    def _test_connection(self):
        messagebox.showinfo("测试", "连接测试功能", parent=self.window)

    def _save_settings(self):
        try:
            interval = int(self.check_interval.get())
            if not (60 <= interval <= 3600):
                messagebox.showerror("验证失败", "检查间隔必须在 60 ~ 3600 秒之间",
                                     parent=self.window)
                return
        except ValueError:
            messagebox.showerror("验证失败", "检查间隔必须为整数", parent=self.window)
            return

        try:
            max_m = int(self.max_monitors.get())
            if not (10 <= max_m <= 500):
                messagebox.showerror("验证失败", "最大监控数必须在 10 ~ 500 之间",
                                     parent=self.window)
                return
        except ValueError:
            messagebox.showerror("验证失败", "最大监控数必须为整数", parent=self.window)
            return

        try:
            pred_hours = int(self.predict_hours.get())
            if not (24 <= pred_hours <= 720):
                messagebox.showerror("验证失败", "预测时长必须在 24 ~ 720 小时之间",
                                     parent=self.window)
                return
        except ValueError:
            messagebox.showerror("验证失败", "预测时长必须为整数", parent=self.window)
            return

        try:
            confidence = float(self.min_confidence.get())
            if not (0.1 <= confidence <= 1.0):
                messagebox.showerror("验证失败", "最小置信度必须在 0.1 ~ 1.0 之间",
                                     parent=self.window)
                return
        except ValueError:
            messagebox.showerror("验证失败", "最小置信度必须为数字", parent=self.window)
            return

        messagebox.showinfo("成功", "设置已保存", parent=self.window)
        self.window.destroy()
