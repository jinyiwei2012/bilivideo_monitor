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
        self.dlg = DialogBase(parent, "系统设置", "720x580", resizable=(True, True))
        self.window = self.dlg.window

        # 加载现有配置
        from config import load_config
        self._cfg = load_config()

        self.setup_ui()

    # ── helper: 文本字段 ──
    @staticmethod
    def _field(parent, label, default, show=None):
        f = tk.Frame(parent, bg=C["bg_elevated"])
        f.pack(fill=tk.X, pady=4)
        tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"],
                 font=FONT, width=16, anchor="w").pack(side=tk.LEFT)
        e = ttk.Entry(f, width=40, font=FONT, show=show or "")
        e.insert(0, default)
        e.pack(side=tk.LEFT, padx=(8, 0))
        return e

    # ── helper: 数字调节 ──
    @staticmethod
    def _spin_field(parent, label, default, fr, to):
        f = tk.Frame(parent, bg=C["bg_elevated"])
        f.pack(fill=tk.X, pady=4)
        tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"],
                 font=FONT, width=16, anchor="w").pack(side=tk.LEFT)
        sv = tk.StringVar(value=str(default))
        sp = ttk.Spinbox(f, from_=fr, to=to, textvariable=sv, width=10)
        sp.pack(side=tk.LEFT, padx=(8, 0))
        return sv

    def _section(self, parent, title, padding=(16, 16, 8)):
        f = tk.Frame(parent, bg=C["bg_elevated"],
                      highlightthickness=1, highlightbackground=C["border_sub"])
        f.pack(fill=tk.X, padx=padding[0], pady=padding[1:], ipadx=12, ipady=14)
        tk.Label(f, text=title, bg=C["bg_elevated"], fg=C["text_2"],
                 font=("Microsoft YaHei UI", 8, "bold")).pack(anchor="w")
        return f

    def setup_ui(self):
        self.dlg.header("系统设置", "配置 OneBot 通知、监控参数、AI 与预测选项")

        nb = ttk.Notebook(self.dlg.container)
        nb.pack(fill=tk.BOTH, expand=True, padx=24, pady=(12, 0))

        # ═══════════════ OneBot设置页 ═══════════════
        onebot = tk.Frame(nb, bg=C["bg_base"])
        nb.add(onebot, text="  OneBot通知  ")

        sec1 = self._section(onebot, "连接参数", (16, 16, 8))
        self.onebot_http = self._field(sec1, "HTTP地址",
                                       self._cfg.get("onebot", {}).get("http_url", "http://127.0.0.1:5700"))
        self.onebot_ws = self._field(sec1, "WebSocket地址",
                                     self._cfg.get("onebot", {}).get("ws_url", "ws://127.0.0.1:6700"))
        self.qq_private = self._field(sec1, "私聊QQ号",
                                      self._cfg.get("onebot", {}).get("private_qq", ""))
        self.qq_group = self._field(sec1, "群号",
                                    self._cfg.get("onebot", {}).get("group_qq", ""))

        ttk.Button(sec1, text="测试连接",
                   command=self._test_connection).pack(anchor="w", padx=4, pady=(8, 0))

        # ═══════════════ 监控设置页 ═══════════════
        monitor = tk.Frame(nb, bg=C["bg_base"])
        nb.add(monitor, text="  监控参数  ")

        sec2 = self._section(monitor, "基础参数")
        self.check_interval = self._spin_field(sec2, "检查间隔(秒)",
                                               self._cfg.get("monitor", {}).get("check_interval", 300), 60, 3600)
        self.max_monitors = self._spin_field(sec2, "最大监控数",
                                             self._cfg.get("monitor", {}).get("max_monitor_count", 100), 10, 500)

        # ═══════════════ 预测设置页 ═══════════════
        predict = tk.Frame(nb, bg=C["bg_base"])
        nb.add(predict, text="  预测参数  ")

        sec3 = self._section(predict, "预测参数")
        self.predict_hours = self._spin_field(sec3, "预测时长(小时)",
                                              self._cfg.get("prediction", {}).get("prediction_hours", 168), 24, 720)
        self.min_confidence = self._spin_field(sec3, "最小置信度",
                                               self._cfg.get("prediction", {}).get("min_confidence", 0.5), 0.1, 1.0)

        # ═══════════════ AI配置页 ═════════════════
        ai_page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(ai_page, text="  AI配置  ")

        sec4 = self._section(ai_page, "LLM 接口参数")
        ai_cfg = self._cfg.get("ai", {})

        self.ai_api_key = self._field(sec4, "API密钥", ai_cfg.get("api_key", ""), show="*")
        self.ai_endpoint = self._field(sec4, "接口地址",
                                       ai_cfg.get("endpoint", "") or "https://api.openai.com/v1/chat/completions")
        self.ai_model = self._field(sec4, "模型名称", ai_cfg.get("model", "gpt-4o-mini"))

        tk.Label(sec4, text="支持任何 OpenAI 兼容接口（如 API2D、DeepSeek、Claude 等）",
                 bg=C["bg_elevated"], fg=C["text_3"],
                 font=("Microsoft YaHei UI", 8)).pack(anchor="w", padx=4, pady=(8, 0))

        # 快捷填充按钮
        preset_f = tk.Frame(ai_page, bg=C["bg_base"])
        preset_f.pack(fill=tk.X, padx=16, pady=(4, 0))
        tk.Label(preset_f, text="快速填入:", bg=C["bg_base"], fg=C["text_2"],
                 font=FONT).pack(side=tk.LEFT)

        presets = {
            "DeepSeek": ("https://api.deepseek.com/v1/chat/completions", "deepseek-chat"),
            "OpenAI": ("https://api.openai.com/v1/chat/completions", "gpt-4o-mini"),
            "Claude": ("https://api.anthropic.com/v1/messages", "claude-sonnet-4-6"),
        }
        for name, (ep, mdl) in presets.items():
            ttk.Button(preset_f, text=name, command=lambda ep=ep, mdl=mdl: (
                self._clear_entry(self.ai_endpoint, ep),
                self._clear_entry(self.ai_model, mdl),
            )).pack(side=tk.LEFT, padx=2)

        # ── 按钮行 ──
        self.dlg.button_row([
            ("取消", self.window.destroy, ""),
            ("保存设置", self._save_settings, "primary"),
        ])

    @staticmethod
    def _clear_entry(entry, value):
        entry.delete(0, tk.END)
        entry.insert(0, value)

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

        from config import save_config

        # 构建配置字典
        self._cfg["onebot"] = {
            "enabled": bool(self.onebot_http.get().strip()),
            "http_url": self.onebot_http.get().strip(),
            "ws_url": self.onebot_ws.get().strip(),
            "private_qq": self.qq_private.get().strip(),
            "group_qq": self.qq_group.get().strip(),
        }
        self._cfg["monitor"]["check_interval"] = interval
        self._cfg["monitor"]["max_monitor_count"] = max_m
        self._cfg["prediction"]["prediction_hours"] = pred_hours
        self._cfg["prediction"]["min_confidence"] = confidence
        self._cfg["ai"] = {
            "enabled": bool(self.ai_api_key.get().strip()),
            "api_key": self.ai_api_key.get().strip(),
            "endpoint": self.ai_endpoint.get().strip(),
            "model": self.ai_model.get().strip(),
        }

        save_config(self._cfg)

        messagebox.showinfo("成功", "设置已保存", parent=self.window)
        self.window.destroy()
