"""
现代化系统设置界面
包含OneBot配置、监控设置、预测设置、AI配置、网络设置（代理/Cookie/扫码登录）
"""

import json
import os
import tkinter as tk
import logging
from tkinter import ttk, messagebox

from ui.theme import C
from ui.helpers import FONT, FONT_SM, FONT_MONO
from ui.dialog_base import DialogBase
from core.bilibili_api import bilibili_api
from core.proxy_manager import ProxyManager
from algorithms.registry import AlgorithmRegistry
from algorithms.weight_manager import weight_manager

logger = logging.getLogger(__name__)


class SettingsWindow:
    """统一设置窗口"""

    def __init__(self, parent=None):
        self.dlg = DialogBase(parent, "系统设置", "860x680", resizable=(True, True), modal=False)
        self.window = self.dlg.window

        from config import load_config

        self._cfg = load_config()

        # 网络配置（代理/Cookie）
        self._net_cfg_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "network_config.json")
        self._net_cfg = self._load_net_config()

        self.setup_ui()

    # ── 网络配置持久化 ──
    def _load_net_config(self) -> dict:
        if os.path.exists(self._net_cfg_file):
            try:
                with open(self._net_cfg_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.debug("加载网络配置失败: %s", e)
        return {"proxies": [], "cookies": {}}

    def _save_net_config(self):
        os.makedirs(os.path.dirname(self._net_cfg_file), exist_ok=True)
        with open(self._net_cfg_file, "w", encoding="utf-8") as f:
            json.dump(self._net_cfg, f, ensure_ascii=False, indent=2)

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

    # ═══════════════ UI 构建 ═══════════════════════════

    def setup_ui(self):
        self.dlg.header("系统设置", "配置通知、监控、AI、代理、Cookie 等全部参数")

        nb = ttk.Notebook(self.dlg.container)
        nb.pack(fill=tk.BOTH, expand=True, padx=24, pady=(12, 0))

        self._build_onebot_tab(nb)
        self._build_monitor_tab(nb)
        self._build_predict_tab(nb)
        self._build_ai_tab(nb)
        self._build_weights_tab(nb)
        self._build_proxy_tab(nb)
        self._build_cookie_tab(nb)
        self._build_retry_tab(nb)
        self._build_status_tab(nb)

        self.dlg.button_row(
            [
                ("取消", self._on_close, ""),
                ("保存设置", self._save_settings, "primary"),
            ]
        )

        # 窗口 X 按钮也触发自动保存
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

    # ──── OneBot ────
    def _build_onebot_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  OneBot通知  ")
        sec = self._section(page, "连接参数", (16, 16, 8))
        self.onebot_http = self._field(
            sec, "HTTP地址", self._cfg.get("onebot", {}).get("http_url", "http://127.0.0.1:5700")
        )
        self.onebot_ws = self._field(
            sec, "WebSocket地址", self._cfg.get("onebot", {}).get("ws_url", "ws://127.0.0.1:6700")
        )
        self.qq_private = self._field(sec, "私聊QQ号", self._cfg.get("onebot", {}).get("private_qq", ""))
        self.qq_group = self._field(sec, "群号", self._cfg.get("onebot", {}).get("group_qq", ""))
        ttk.Button(sec, text="测试连接", command=self._test_connection).pack(anchor="w", padx=4, pady=(8, 0))

    # ──── 监控 ────
    def _build_monitor_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  监控参数  ")
        sec = self._section(page, "基础参数")
        self.check_interval = self._spin_field(
            sec, "检查间隔(秒)", self._cfg.get("monitor", {}).get("check_interval", 300), 60, 3600
        )
        self.max_monitors = self._spin_field(
            sec, "最大监控数", self._cfg.get("monitor", {}).get("max_monitor_count", 100), 10, 500
        )

    # ──── 预测 ────
    def _build_predict_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  预测参数  ")
        sec = self._section(page, "预测参数")
        self.predict_hours = self._spin_field(
            sec, "预测时长(小时)", self._cfg.get("prediction", {}).get("prediction_hours", 168), 24, 720
        )
        self.min_confidence = self._spin_field(
            sec, "最小置信度", self._cfg.get("prediction", {}).get("min_confidence", 0.5), 0.1, 1.0
        )

    # ──── AI配置 ────
    def _build_ai_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  AI配置  ")

        sec = self._section(page, "LLM 配置管理")
        ai_cfg = self._cfg.get("ai", {})

        # 当前配置选择
        sel_row = tk.Frame(sec, bg=C["bg_elevated"])
        sel_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(sel_row, text="当前配置:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT, width=16, anchor="w").pack(
            side=tk.LEFT
        )
        self._ai_profile_var = tk.StringVar()
        self._ai_profile_cb = ttk.Combobox(
            sel_row, textvariable=self._ai_profile_var, width=38, font=FONT, state="readonly"
        )
        self._ai_profile_cb.pack(side=tk.LEFT, padx=(8, 0))
        self._ai_profile_cb.bind("<<ComboboxSelected>>", self._on_ai_profile_selected)

        # 初始化 profiles
        profiles = ai_cfg.get("profiles", [])
        if not profiles:
            # 从旧字段迁移
            old_key = ai_cfg.get("api_key", "")
            old_ep = ai_cfg.get("endpoint", "") or "https://api.openai.com/v1/chat/completions"
            old_mdl = ai_cfg.get("model", "gpt-4o-mini")
            if old_key:
                profiles.append({"name": "默认配置", "api_key": old_key, "endpoint": old_ep, "model": old_mdl})
        if not profiles:
            profiles.append(
                {
                    "name": "默认配置",
                    "api_key": "",
                    "endpoint": "https://api.openai.com/v1/chat/completions",
                    "model": "gpt-4o-mini",
                }
            )
        self._profiles = profiles
        selected = ai_cfg.get("selected_profile", profiles[0]["name"])
        names = [p["name"] for p in profiles]
        self._ai_profile_cb["values"] = names
        if selected in names:
            self._ai_profile_var.set(selected)
        else:
            self._ai_profile_var.set(names[0])

        # ── 配置详情 ──
        detail = tk.Frame(sec, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        detail.pack(fill=tk.X, pady=4, ipadx=10, ipady=10)
        tk.Label(
            detail, text="配置详情", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 8, "bold")
        ).pack(anchor="w", pady=(0, 6))

        def _field_wrapper(parent, label):
            f = tk.Frame(parent, bg=C["bg_elevated"])
            f.pack(fill=tk.X, pady=3)
            tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"], font=FONT, width=16, anchor="w").pack(
                side=tk.LEFT
            )
            e = ttk.Entry(f, width=40, font=FONT)
            e.pack(side=tk.LEFT, padx=(8, 0))
            return e

        self._ai_name_entry = _field_wrapper(detail, "配置名称")
        self._ai_key_entry = _field_wrapper(detail, "API密钥")
        self._ai_key_entry.config(show="*")
        self._ai_endpoint_entry = _field_wrapper(detail, "接口地址")
        self._ai_model_entry = _field_wrapper(detail, "模型名称")

        # ── 操作按钮 ──
        btn_row = tk.Frame(sec, bg=C["bg_elevated"])
        btn_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_row, text="💾 保存配置", command=self._save_ai_profile).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="🗑 删除配置", command=self._delete_ai_profile).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="+ 新增", command=self._new_ai_profile).pack(side=tk.LEFT, padx=4)

        # ── 快速填入 ──
        preset_f = tk.Frame(page, bg=C["bg_base"])
        preset_f.pack(fill=tk.X, padx=16, pady=(8, 0))
        tk.Label(preset_f, text="快速填入:", bg=C["bg_base"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)
        presets = {
            "DeepSeek": ("https://api.deepseek.com/v1/chat/completions", "deepseek-chat"),
            "OpenAI": ("https://api.openai.com/v1/chat/completions", "gpt-4o-mini"),
            "Claude": ("https://api.anthropic.com/v1/messages", "claude-sonnet-4-6"),
            "SiliconFlow": ("https://api.siliconflow.cn/v1/chat/completions", "deepseek-ai/DeepSeek-V3"),
        }
        for name, (ep, mdl) in presets.items():
            ttk.Button(
                preset_f,
                text=name,
                command=lambda ep=ep, mdl=mdl: (
                    self._clear_entry(self._ai_endpoint_entry, ep),
                    self._clear_entry(self._ai_model_entry, mdl),
                ),
            ).pack(side=tk.LEFT, padx=2)

        ttk.Button(preset_f, text="测试连接", command=self._test_ai_connection).pack(side=tk.LEFT, padx=(10, 0))

        self._ai_status_lbl = tk.Label(sec, text="", bg=C["bg_elevated"], fg=C["text_3"], font=FONT_SM)
        self._ai_status_lbl.pack(anchor="w", padx=4, pady=(6, 0))

        # 首次加载选中配置
        self._on_ai_profile_selected()

    def _on_ai_profile_selected(self, event=None):
        """当 Combobox 选中项改变时，填充配置详情"""
        name = self._ai_profile_var.get()
        for p in self._profiles:
            if p["name"] == name:
                self._clear_entry(self._ai_name_entry, p.get("name", ""))
                self._clear_entry(self._ai_key_entry, p.get("api_key", ""))
                self._clear_entry(self._ai_endpoint_entry, p.get("endpoint", ""))
                self._clear_entry(self._ai_model_entry, p.get("model", ""))
                break

    def _save_ai_profile(self):
        """保存当前编辑的配置到 profiles 列表"""
        name = self._ai_name_entry.get().strip()
        if not name:
            messagebox.showwarning("提示", "配置名称不能为空", parent=self.window)
            return
        api_key = self._ai_key_entry.get().strip()
        endpoint = self._ai_endpoint_entry.get().strip() or "https://api.openai.com/v1/chat/completions"
        model = self._ai_model_entry.get().strip() or "gpt-4o-mini"

        # 更新或新增
        found = False
        for p in self._profiles:
            if p["name"] == name:
                p.update({"api_key": api_key, "endpoint": endpoint, "model": model})
                found = True
                break
        if not found:
            self._profiles.append({"name": name, "api_key": api_key, "endpoint": endpoint, "model": model})

        # 刷新 combobox
        names = [p["name"] for p in self._profiles]
        self._ai_profile_cb["values"] = names
        self._ai_profile_var.set(name)
        self._ai_status_lbl.config(text=f"配置「{name}」已保存", fg=C["success"])

    def _delete_ai_profile(self):
        """删除当前选中的配置"""
        name = self._ai_profile_var.get()
        if not name:
            return
        if len(self._profiles) <= 1:
            messagebox.showwarning("提示", "至少保留一个配置", parent=self.window)
            return
        if not messagebox.askyesno("确认删除", f"确定删除配置「{name}」？", parent=self.window):
            return
        self._profiles = [p for p in self._profiles if p["name"] != name]
        names = [p["name"] for p in self._profiles]
        self._ai_profile_cb["values"] = names
        self._ai_profile_var.set(names[0])
        self._on_ai_profile_selected()

    def _new_ai_profile(self):
        """清空编辑字段以新增配置"""
        self._clear_entry(self._ai_name_entry, "")
        self._clear_entry(self._ai_key_entry, "")
        self._clear_entry(self._ai_endpoint_entry, "https://api.openai.com/v1/chat/completions")
        self._clear_entry(self._ai_model_entry, "gpt-4o-mini")

    # ──── 权重设置 ────
    def _build_weights_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  权重设置  ")

        # 说明
        info_sec = tk.Frame(page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        info_sec.pack(fill=tk.X, padx=16, pady=12, ipadx=10, ipady=8)
        for line in [
            "• 用户自定义权重优先级最高，机器学习不会修改已自定义的权重",
            "• 权重范围：0.01 ~ 10.0",
            "• 权重越高，该算法在综合预测中占比越大",
        ]:
            tk.Label(info_sec, text=line, bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM, anchor="w").pack(
                fill=tk.X, padx=4
            )

        # 表头
        hdr = tk.Frame(page, bg=C["bg_surface"], highlightthickness=1, highlightbackground=C["border_sub"])
        hdr.pack(fill=tk.X, padx=16)
        for col_i, (text, w) in enumerate(
            [
                ("算法", 24),
                ("自定义", 8),
                ("权重值", 10),
                ("ML权重", 10),
                ("准确率", 10),
                ("样本数", 8),
            ]
        ):
            tk.Label(
                hdr,
                text=text,
                bg=C["bg_surface"],
                fg=C["text_2"],
                font=("Microsoft YaHei UI", 8, "bold"),
                width=w,
                anchor="w",
            ).grid(row=0, column=col_i, padx=6, pady=4, sticky="w")

        # 滚动的算法列表
        canvas_frame = tk.Frame(page, bg=C["bg_base"])
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))

        vsb = ttk.Scrollbar(canvas_frame, orient="vertical")
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        canvas = tk.Canvas(canvas_frame, bg=C["bg_elevated"], highlightthickness=0, yscrollcommand=vsb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.config(command=canvas.yview)

        algo_frame = tk.Frame(canvas, bg=C["bg_elevated"])
        canvas.create_window((0, 0), window=algo_frame, anchor="nw")
        algo_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        self._weight_vars = {}
        self._weight_check_vars = {}

        algo_info = AlgorithmRegistry.get_weights_info()
        for info in algo_info:
            row = tk.Frame(algo_frame, bg=C["bg_surface"], highlightthickness=1, highlightbackground=C["border_sub"])
            row.pack(fill=tk.X, pady=1)

            name = info["name"]
            tk.Label(row, text=name, bg=C["bg_surface"], fg=C["text_1"], font=FONT, width=24, anchor="w").grid(
                row=0, column=0, padx=4, pady=3, sticky="w"
            )

            var = tk.BooleanVar(value=info["is_customized"])
            self._weight_check_vars[name] = var
            ttk.Checkbutton(
                row,
                variable=var,
                command=lambda n=name: self._weight_vars[n].set(weight_manager.ml_weights.get(n, 1.0)),
            ).grid(row=0, column=1, padx=2)

            wv = tk.DoubleVar(value=info.get("user_weight") or info.get("final_weight", 1.0))
            self._weight_vars[name] = wv
            ttk.Entry(row, textvariable=wv, width=10).grid(row=0, column=2, padx=4)

            ml_w = info.get("ml_weight", 1.0)
            tk.Label(
                row, text=f"{ml_w:.2f}", bg=C["bg_surface"], fg=C["text_3"], font=FONT_MONO, width=12, anchor="w"
            ).grid(row=0, column=3)

            acc = info.get("accuracy", 0)
            tk.Label(
                row, text=f"{acc * 100:.1f}%", bg=C["bg_surface"], fg=C["success"], font=FONT_MONO, width=10, anchor="w"
            ).grid(row=0, column=4)

            samples = info.get("samples", 0)
            tk.Label(
                row, text=str(samples), bg=C["bg_surface"], fg=C["text_2"], font=FONT_MONO, width=8, anchor="w"
            ).grid(row=0, column=5)

        # 按钮
        btn_row = tk.Frame(page, bg=C["bg_base"])
        btn_row.pack(fill=tk.X, padx=16, pady=(0, 12))
        ttk.Button(btn_row, text="重置所有权重", command=self._reset_all_weights).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="刷新", command=self._refresh_weights).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="💾 保存权重", command=self._save_weights, style="Primary.TButton").pack(side=tk.RIGHT)

    def _reset_all_weights(self):
        if messagebox.askyesno("确认", "确定要重置所有自定义权重吗？", parent=self.window):
            weight_manager.reset_weights()
            self._refresh_weights()
            messagebox.showinfo("成功", "已重置所有权重", parent=self.window)

    def _refresh_weights(self):
        """刷新权重列表中的值"""
        algo_info = AlgorithmRegistry.get_weights_info()
        for info in algo_info:
            name = info["name"]
            if name in self._weight_vars:
                self._weight_vars[name].set(info.get("user_weight") or info.get("final_weight", 1.0))
                self._weight_check_vars[name].set(info["is_customized"])

    def _save_weights(self):
        for name, check_var in self._weight_check_vars.items():
            wv = self._weight_vars[name]
            try:
                weight = float(wv.get())
                weight = max(0.01, min(10.0, weight))
                if check_var.get():
                    weight_manager.set_user_weight(name, weight)
                else:
                    weight_manager.clear_user_weight(name)
            except ValueError:
                messagebox.showerror("错误", f"算法 {name} 的权重值无效", parent=self.window)
                return
        messagebox.showinfo("成功", "权重设置已保存", parent=self.window)

    # ──── 代理 ────
    def _build_proxy_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  代理设置  ")

        sec = tk.Frame(page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        sec.pack(fill=tk.BOTH, expand=True, padx=16, pady=12, ipadx=10, ipady=8)
        tk.Label(sec, text="HTTP代理列表（每行一个）", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(
            anchor="w", pady=(0, 4)
        )
        tk.Label(
            sec,
            text="格式: http://host:port 或 http://user:pass@host:port\n支持 HTTP/HTTPS/SOCKS4/SOCKS5 协议，自动识别协议类型",
            bg=C["bg_elevated"],
            fg=C["text_3"],
            font=FONT_SM,
        ).pack(anchor="w")

        self.proxy_text = tk.Text(
            sec,
            height=8,
            bg=C["bg_base"],
            fg=C["text_1"],
            insertbackground=C["text_1"],
            font=("Consolas", 10),
            relief="flat",
            highlightthickness=1,
            highlightbackground=C["border"],
        )
        self.proxy_text.pack(fill=tk.X, pady=6)
        if self._net_cfg.get("proxies"):
            self.proxy_text.insert("1.0", "\n".join(self._net_cfg["proxies"]))

        btn_row = tk.Frame(sec, bg=C["bg_elevated"])
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text="应用代理", command=self._apply_proxies).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="检查可用性", command=self._check_proxies).pack(side=tk.LEFT, padx=4)
        self._proxy_test_status = tk.Label(btn_row, text="", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM)
        self._proxy_test_status.pack(side=tk.LEFT, padx=8)

        url_row = tk.Frame(sec, bg=C["bg_elevated"])
        url_row.pack(fill=tk.X, pady=(6, 0))
        tk.Label(
            url_row, text="测试地址:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM, width=8, anchor="w"
        ).pack(side=tk.LEFT)
        self._test_url_var = tk.StringVar(value="https://api.bilibili.com/x/web-interface/view?bvid=BV1GJ411x7hQ")
        url_entry = ttk.Entry(url_row, textvariable=self._test_url_var, font=FONT_SM)
        url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        # 内联检测结果区（Treeview 表格）
        result_container = tk.Frame(sec, bg=C["bg_base"], highlightthickness=1, highlightbackground=C["border"])
        result_container.pack(fill=tk.BOTH, expand=True, pady=(6, 4))

        columns = ("addr", "status", "latency", "country", "ip", "asn", "isp")
        self._proxy_tree = ttk.Treeview(result_container, columns=columns, show="headings", height=6)
        self._proxy_tree.heading("addr", text="代理地址")
        self._proxy_tree.heading("status", text="状态")
        self._proxy_tree.heading("latency", text="延迟/原因")
        self._proxy_tree.heading("country", text="地区")
        self._proxy_tree.heading("ip", text="IP")
        self._proxy_tree.heading("asn", text="ASN")
        self._proxy_tree.heading("isp", text="ISP")
        self._proxy_tree.column("addr", anchor="w", width=200, minwidth=120, stretch=True)
        self._proxy_tree.column("status", anchor="center", width=40, minwidth=40, stretch=False)
        self._proxy_tree.column("latency", anchor="w", width=200, minwidth=120, stretch=True)
        self._proxy_tree.column("country", anchor="w", width=80, minwidth=60, stretch=False)
        self._proxy_tree.column("ip", anchor="w", width=140, minwidth=100, stretch=False)
        self._proxy_tree.column("asn", anchor="w", width=150, minwidth=100, stretch=False)
        self._proxy_tree.column("isp", anchor="w", width=150, minwidth=100, stretch=False)

        tree_sb = ttk.Scrollbar(result_container, orient="vertical", command=self._proxy_tree.yview)
        self._proxy_tree.configure(yscrollcommand=tree_sb.set)
        self._proxy_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_sb.pack(side=tk.RIGHT, fill=tk.Y)
        # Treeview 行样式
        style = ttk.Style()
        style.configure("Treeview", rowheight=24, font=("Consolas", 9))
        self._proxy_tree.tag_configure("ok", foreground=C["success"])
        self._proxy_tree.tag_configure("fail", foreground=C["danger"])

        tk.Label(
            sec,
            text="使用代理可有效绕过IP级别的频率限制",
            bg=C["bg_elevated"],
            fg=C["warning"],
            font=FONT_SM,
            anchor="w",
        ).pack(fill=tk.X, pady=(4, 0))

    # ──── Cookie ────
    def _build_cookie_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  Cookie设置  ")

        sec = tk.Frame(page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        sec.pack(fill=tk.BOTH, expand=True, padx=16, pady=(12, 6), ipadx=10, ipady=6)

        import_row = tk.Frame(sec, bg=C["bg_elevated"])
        import_row.pack(fill=tk.X, pady=(0, 6))
        tk.Label(import_row, text="导入方式:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)
        ttk.Button(import_row, text="📋 Cookie-Editor JSON", command=self._import_cookie_editor).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(import_row, text="📱 扫码登录", command=self._qrcode_login).pack(side=tk.LEFT, padx=4)

        self.cookie_text = tk.Text(
            sec,
            height=5,
            bg=C["bg_base"],
            fg=C["text_1"],
            insertbackground=C["text_1"],
            font=("Consolas", 10),
            relief="flat",
            highlightthickness=1,
            highlightbackground=C["border"],
        )
        self.cookie_text.pack(fill=tk.BOTH, expand=True, pady=4)
        self._refresh_cookie_display()

        btn_row = tk.Frame(sec, bg=C["bg_elevated"])
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text="应用Cookie", command=self._apply_cookies).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="清空Cookie", command=self._clear_cookies).pack(side=tk.LEFT)

        tk.Label(
            sec,
            text="支持直接粘贴 Cookie 字符串 (key=value; key2=value2) 或 Cookie-Editor JSON 格式，自动识别解析。",
            bg=C["bg_elevated"],
            fg=C["text_3"],
            font=FONT_SM,
            anchor="w",
        ).pack(fill=tk.X, pady=(4, 0))

    # ──── 重试参数 ────
    def _build_retry_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  重试参数  ")

        sec = tk.Frame(page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        sec.pack(fill=tk.X, padx=16, pady=12, ipadx=10, ipady=10)

        def _spin_r(parent, label, default, fr, to):
            f = tk.Frame(parent, bg=C["bg_elevated"])
            f.pack(fill=tk.X, pady=4)
            tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"], font=FONT, width=20, anchor="w").pack(
                side=tk.LEFT
            )
            sv = tk.DoubleVar(value=default)
            sp = ttk.Spinbox(f, from_=fr, to=to, textvariable=sv, width=10)
            sp.pack(side=tk.LEFT, padx=(6, 0))
            return sv

        self.retry_count_var = _spin_r(sec, "最大重试次数", bilibili_api.max_retries, 1, 10)
        self.base_delay_var = _spin_r(sec, "基础重试延迟(秒)", bilibili_api.base_retry_delay, 1, 30)
        self.min_interval_var = _spin_r(sec, "最小请求间隔(秒)", bilibili_api._min_request_interval, 0.1, 10)

        ttk.Button(sec, text="应用重试设置", command=self._apply_retry_settings).pack(anchor="w", pady=(8, 0))

    # ──── 运行状态 ────
    def _build_status_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  运行状态  ")

        sec = tk.Frame(page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        sec.pack(fill=tk.X, padx=16, pady=12, ipadx=10, ipady=8)

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
            self.status_labels[key] = vl

        btn_s = tk.Frame(sec, bg=C["bg_elevated"])
        btn_s.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_s, text="刷新状态", command=self._refresh_status).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_s, text="重置状态", command=self._reset_status).pack(side=tk.LEFT, padx=4)

        self._refresh_status()

    # ═══════════════════════════════════════════════════

    @staticmethod
    def _clear_entry(entry, value):
        entry.delete(0, tk.END)
        entry.insert(0, value)

    def _test_connection(self):
        messagebox.showinfo("测试", "连接测试功能", parent=self.window)

    def _test_ai_connection(self):
        """测试 AI API 密钥可用性（后台线程，不阻塞 UI）"""
        api_key = self._ai_key_entry.get().strip()
        endpoint = self._ai_endpoint_entry.get().strip()
        model = self._ai_model_entry.get().strip()

        if not api_key:
            messagebox.showwarning("提示", "请先填写 API 密钥", parent=self.window)
            return
        if not endpoint:
            endpoint = "https://api.openai.com/v1/chat/completions"
        if not model:
            model = "gpt-4o-mini"

        import threading

        result = []

        def _worker():
            try:
                is_claude = "anthropic.com" in endpoint
                import requests as req

                if is_claude:
                    resp = req.post(
                        endpoint,
                        headers={
                            "x-api-key": api_key,
                            "Content-Type": "application/json",
                            "anthropic-version": "2023-06-01",
                        },
                        json={
                            "model": model,
                            "max_tokens": 10,
                            "messages": [{"role": "user", "content": "回复OK即可"}],
                        },
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        result.append(f"✅ 连接成功（Claude {model}）")
                    else:
                        result.append(f"❌ HTTP {resp.status_code}: {resp.text[:200]}")
                else:
                    resp = req.post(
                        endpoint,
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": "回复OK即可"}],
                            "max_tokens": 10,
                        },
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        result.append(f"✅ 连接成功（{model}）")
                    else:
                        err = resp.json().get("error", {})
                        result.append(f"❌ HTTP {resp.status_code}: {err.get('message', resp.text[:200])}")
            except Exception as e:
                result.append(f"❌ 请求失败: {e}")

            self.window.after(
                0, lambda: messagebox.showinfo("API 连接测试", result[0] if result else "❌ 无响应", parent=self.window)
            )

        _th = threading.Thread(target=_worker, daemon=True)
        _th.start()
        messagebox.showinfo("测试中", f"正在测试 {model} 连接...\n请稍候", parent=self.window)

    # ──── 代理操作 ────
    def _apply_proxies(self):
        text = self.proxy_text.get("1.0", "end").strip()
        proxy_list = [line.strip() for line in text.split("\n") if line.strip()]
        bilibili_api.clear_proxies()
        for ps in proxy_list:
            bilibili_api.add_proxy({"http": ps, "https": ps})
        self._net_cfg["proxies"] = proxy_list
        self._save_net_config()
        self._check_proxies()

    def _check_proxies(self):
        """测试每个代理的可用性、延迟、地区、ASN、ISP（Treeview 表格显示）"""
        text = self.proxy_text.get("1.0", "end").strip()
        proxy_list = [line.strip() for line in text.split("\n") if line.strip()]
        if not proxy_list:
            messagebox.showwarning("提示", "请先输入要测试的代理", parent=self.window)
            return

        test_url = self._test_url_var.get().strip()

        # 清空旧结果
        for item in self._proxy_tree.get_children():
            self._proxy_tree.delete(item)

        # 插入占位行
        row_items = []
        for proxy in proxy_list:
            item = self._proxy_tree.insert("", "end", values=(proxy, "⏳", "—", "", "", "", ""))
            row_items.append(item)

        import threading

        # ── 并行测试 + 取消支持 ──
        total = len(proxy_list)
        ok_count = [0]
        fail_count = [0]
        cancel_flag = [False]
        threads = []
        lock = threading.Lock()
        self._proxy_test_status.configure(text=f"测试中 0/{total} …", fg=C["warning"])

        cancel_btn = ttk.Button(
            self._proxy_test_status.master, text="✕ 取消", command=lambda: cancel_flag.__setitem__(0, True)
        )
        cancel_btn.pack(side=tk.LEFT, padx=2)

        def test_one(proxy, item):
            if cancel_flag[0]:
                return
            result = ProxyManager.test_proxy(proxy, test_url=test_url)
            ok = result.get("ok", False)
            latency = f"{result.get('latency_ms', '—')}ms" if ok else (result.get("error") or "—")
            country = result.get("country") or "—"
            ip = result.get("ip") or "—"
            asn = result.get("asn") or "—"
            isp = result.get("isp") or "—"
            status = "✅" if ok else "❌"
            tag = "ok" if ok else "fail"
            self.window.after(
                0,
                lambda item=item, status=status, latency=latency, country=country, ip=ip, asn=asn, isp=isp, tag=tag: (
                    self._proxy_tree.set(item, "status", status),
                    self._proxy_tree.set(item, "latency", latency),
                    self._proxy_tree.set(item, "country", country),
                    self._proxy_tree.set(item, "ip", ip),
                    self._proxy_tree.set(item, "asn", asn),
                    self._proxy_tree.set(item, "isp", isp),
                    self._proxy_tree.item(item, tags=(tag,)),
                ),
            )
            with lock:
                if ok:
                    ok_count[0] += 1
                else:
                    fail_count[0] += 1
                done = ok_count[0] + fail_count[0]
                self.window.after(
                    0, lambda d=done: self._proxy_test_status.configure(text=f"测试中 {d}/{total} …", fg=C["warning"])
                )

        for proxy, item in zip(proxy_list, row_items):
            t = threading.Thread(target=test_one, args=(proxy, item), daemon=True)
            t.start()
            threads.append(t)

        def _wait_all():
            for t in threads:
                t.join()
            self.window.after(0, cancel_btn.destroy)
            ok_n, fail_n = ok_count[0], fail_count[0]
            status_text = f"完成: {ok_n} 可用" + (f", {fail_n} 失败" if fail_n else "")
            self.window.after(
                0, lambda: self._proxy_test_status.configure(text=status_text, fg=C["success"] if ok_n else C["danger"])
            )

            if fail_n:
                failed = []
                for proxy, item in zip(proxy_list, row_items):
                    tags = self._proxy_tree.item(item, "tags")
                    if "fail" in tags:
                        failed.append(proxy)
                if failed:
                    self.window.after(0, lambda: self._auto_remove_failed_proxies(failed))

        threading.Thread(target=_wait_all, daemon=True).start()

    def _auto_remove_failed_proxies(self, failed_urls):
        """测试完成后自动移除连接失败的代理"""
        text = self.proxy_text.get("1.0", "end").strip()
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        remaining = [ln for ln in lines if ln not in failed_urls]
        self.proxy_text.delete("1.0", "end")
        self.proxy_text.insert("1.0", "\n".join(remaining))

        bilibili_api.clear_proxies()
        for ps in remaining:
            bilibili_api.add_proxy({"http": ps, "https": ps})

        self._net_cfg["proxies"] = remaining
        self._save_net_config()

        masked = ", ".join(ProxyManager.mask_url(u) for u in failed_urls)
        msg = f"已自动移除 {len(failed_urls)} 个失效代理:\n{masked}"
        logger.info(msg)
        messagebox.showinfo("代理清理", msg, parent=self.window)

    # ──── Cookie: 刷新显示 ────
    def _refresh_cookie_display(self):
        self.cookie_text.delete("1.0", tk.END)
        cookies = {}
        for cookie in bilibili_api.session.cookies:
            if "bilibili.com" in (cookie.domain or ""):
                cookies[cookie.name] = cookie.value
        if cookies:
            self.cookie_text.insert("1.0", "; ".join(f"{k}={v}" for k, v in cookies.items()))
        elif self._net_cfg.get("cookies"):
            self.cookie_text.insert("1.0", "; ".join(f"{k}={v}" for k, v in self._net_cfg["cookies"].items()))

    # ──── Cookie: 手动应用 ────
    def _apply_cookies(self):
        text = self.cookie_text.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("警告", "Cookie不能为空", parent=self.window)
            return
        cookies = self._parse_cookie_input(text)
        if not cookies:
            messagebox.showerror("错误", "无法解析输入内容，请检查格式", parent=self.window)
            return
        bilibili_api.set_cookies(cookies)
        self._net_cfg["cookies"] = cookies
        self._save_net_config()
        self._refresh_status()
        # 验证登录状态
        self.window.after(500, self._verify_login)
        messagebox.showinfo("成功", "已应用 Cookie，正在验证登录状态...", parent=self.window)

    @staticmethod
    def _parse_cookie_input(text: str) -> dict:
        """自动识别并解析 Cookie 输入（JSON 数组 / JSON 对象 / key=value 字符串）"""
        import json as _json

        # 尝试 JSON 解析
        stripped = text.strip()
        if stripped.startswith("["):
            try:
                entries = _json.loads(stripped)
                if isinstance(entries, list) and entries:
                    cookies = {}
                    for entry in entries:
                        if isinstance(entry, dict):
                            name = entry.get("name", "")
                            value = entry.get("value", "")
                            if name and value:
                                cookies[name] = value
                    if cookies:
                        return cookies
            except _json.JSONDecodeError:
                pass
        elif stripped.startswith("{"):
            try:
                obj = _json.loads(stripped)
                if isinstance(obj, dict):
                    # 过滤出合法 cookie 名
                    valid_keys = {"SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid", "buvid3", "buvid4"}
                    return {k: v for k, v in obj.items() if k in valid_keys or not k.startswith("_")}
            except _json.JSONDecodeError:
                pass
        # key=value; key2=value2 格式
        cookies = {}
        for item in stripped.split(";"):
            item = item.strip()
            if "=" in item:
                key, value = item.split("=", 1)
                cookies[key.strip()] = value.strip()
        return cookies

    def _verify_login(self):
        """验证登录状态并更新 UI"""
        try:
            status = bilibili_api.get_status()
            is_login = status.get("is_login", False)
            login_name = status.get("login_name", "")
            if self.gui and hasattr(self.gui, "log_panel"):
                if is_login:
                    self.gui.log_panel.add_log("INFO", f"Cookie 登录验证成功: {login_name}")
                else:
                    self.gui.log_panel.add_log("WARNING", "Cookie 登录验证失败，请检查 Cookie 是否有效")
        except Exception as e:
            logger.debug("检查Cookie登录状态失败: %s", e)
        self._refresh_status()

    # ──── Cookie: 清空 ────
    def _clear_cookies(self):
        if messagebox.askyesno("确认", "确定要清空所有Cookie吗？", parent=self.window):
            for name in (
                "SESSDATA",
                "bili_jct",
                "DedeUserID",
                "DedeUserID__ckMd",
                "sid",
                "buvid3",
                "buvid4",
                "buvid_fp",
            ):
                bilibili_api.session.cookies.set(name, "", domain=".bilibili.com")
            bilibili_api._cookies = {}
            self._net_cfg["cookies"] = {}
            self._save_net_config()
            self._refresh_cookie_display()
            self._refresh_status()
            messagebox.showinfo("成功", "Cookie 已清空", parent=self.window)

    # ──── Cookie: Cookie-Editor 导入 ────
    def _import_cookie_editor(self):
        top = tk.Toplevel(self.window)
        top.title("导入 Cookie-Editor JSON")
        top.geometry("520x360")
        top.configure(bg=C["bg_surface"])
        top.transient(self.window)
        top.grab_set()

        tk.Label(top, text="粘贴 Cookie-Editor 导出的 JSON 内容：", bg=C["bg_surface"], fg=C["text_1"], font=FONT).pack(
            pady=(12, 4)
        )
        tk.Label(
            top,
            text='格式: [{"domain": ".bilibili.com", "name": "SESSDATA", ...}]',
            bg=C["bg_surface"],
            fg=C["text_3"],
            font=FONT_SM,
        ).pack()

        text_w = tk.Text(
            top,
            height=10,
            bg=C["bg_base"],
            fg=C["text_1"],
            font=("Consolas", 10),
            relief="flat",
            highlightthickness=1,
            highlightbackground=C["border"],
            insertbackground=C["text_1"],
        )
        text_w.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)

        def _do_import():
            raw = text_w.get("1.0", tk.END).strip()
            if not raw:
                messagebox.showwarning("提示", "请粘贴 JSON 内容", parent=top)
                return
            try:
                entries = json.loads(raw)
            except json.JSONDecodeError as e:
                messagebox.showerror("解析失败", f"JSON 格式错误:\n{e}", parent=top)
                return
            if not isinstance(entries, list):
                messagebox.showerror("格式错误", "JSON 应为数组格式", parent=top)
                return
            cookies = {}
            for entry in entries:
                name = entry.get("name", "")
                value = entry.get("value", "")
                domain = entry.get("domain", "")
                if name and value and ("bilibili.com" in domain or not domain):
                    cookies[name] = value
            if not cookies:
                messagebox.showwarning("未找到", "JSON 中未找到 B站 相关 Cookie", parent=top)
                return
            bilibili_api.set_cookies(cookies)
            self._net_cfg["cookies"] = cookies
            self._save_net_config()
            self._refresh_cookie_display()
            self._refresh_status()
            top.destroy()
            self.window.after(500, self._verify_login)
            messagebox.showinfo("成功", f"已导入 {len(cookies)} 个 Cookie，正在验证登录状态...", parent=self.window)

        btn_f = tk.Frame(top, bg=C["bg_surface"])
        btn_f.pack(pady=(0, 12))
        ttk.Button(btn_f, text="导入并应用", command=_do_import, style="Primary.TButton").pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_f, text="取消", command=top.destroy).pack(side=tk.LEFT, padx=4)

    # ──── Cookie: 扫码登录 ────
    def _qrcode_login(self):
        qr_data = bilibili_api.get_qrcode_login_url()
        if not qr_data:
            messagebox.showerror("错误", "获取二维码失败", parent=self.window)
            return
        qrcode_key = qr_data.get("qrcode_key", "")
        qr_url = qr_data.get("url", "")

        # 生成二维码图片
        self._qr_img = None
        try:
            import qrcode
            from PIL import ImageTk

            img = qrcode.make(qr_url).resize((200, 200))
            self._qr_img = ImageTk.PhotoImage(img)
        except ImportError:
            pass

        qr_top = tk.Toplevel(self.window)
        qr_top.title("扫码登录 B站")
        qr_top.geometry("320x380")
        qr_top.configure(bg=C["bg_surface"])
        qr_top.transient(self.window)
        qr_top.grab_set()
        qr_top.resizable(False, False)

        tk.Label(
            qr_top,
            text="请使用 B站 手机客户端扫码",
            bg=C["bg_surface"],
            fg=C["text_1"],
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(pady=(14, 6))

        if self._qr_img:
            tk.Label(qr_top, image=self._qr_img, bg=C["bg_surface"]).pack(pady=6)
        else:
            tk.Label(
                qr_top,
                text=f"扫码链接:\n{qr_url}",
                bg=C["bg_surface"],
                fg=C["text_1"],
                font=("Consolas", 9),
                wraplength=280,
                justify="left",
            ).pack(pady=6, padx=10)

        status_var = tk.StringVar(value="等待扫码...")
        status_lbl = tk.Label(qr_top, textvariable=status_var, bg=C["bg_surface"], fg=C["text_2"], font=FONT)
        status_lbl.pack(pady=(6, 4))

        def _poll():
            if not qr_top.winfo_exists():
                return
            result = bilibili_api.poll_qrcode_login(qrcode_key)
            status_var.set(result.get("message", ""))
            if result.get("status") == 2:
                cookies = result.get("cookies", {})
                if cookies:
                    self._net_cfg["cookies"] = cookies
                    self._save_net_config()
                    self._refresh_cookie_display()
                    self._refresh_status()
                    status_lbl.config(fg=C["success"])
                    qr_top.after(800, qr_top.destroy)
                    self.window.after(1000, self._verify_login)
                    messagebox.showinfo("登录成功", f"已获取 Cookie: {', '.join(cookies.keys())}", parent=self.window)
                else:
                    self._refresh_status()
                    status_lbl.config(fg=C["success"])
                    qr_top.after(800, qr_top.destroy)
                    self.window.after(1000, self._verify_login)
                    messagebox.showinfo("登录成功", "扫码成功！Cookie 已通过浏览器同步。", parent=self.window)
                return
            elif result.get("status") == -1:
                status_lbl.config(fg=C["danger"])
                ttk.Button(
                    qr_top, text="重新生成二维码", command=lambda: [qr_top.destroy(), self._qrcode_login()]
                ).pack(pady=4)
                return
            qr_top.after(1500, _poll)

        qr_top.after(500, _poll)

    # ──── 重试设置 ────
    def _apply_retry_settings(self):
        bilibili_api.max_retries = int(self.retry_count_var.get())
        bilibili_api.base_retry_delay = self.base_delay_var.get()
        bilibili_api._min_request_interval = self.min_interval_var.get()
        messagebox.showinfo("成功", "重试设置已更新", parent=self.window)

    # ──── 状态 ────
    def _refresh_status(self):
        status = bilibili_api.get_status()
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
        if messagebox.askyesno("确认", "确定要重置所有状态吗？", parent=self.window):
            bilibili_api.reset_status()
            self._refresh_status()

    # ──── 自动保存 on close ────
    def _on_close(self):
        """关闭时自动保存代理文本到 network_config.json"""
        text = self.proxy_text.get("1.0", "end").strip()
        self._net_cfg["proxies"] = [line.strip() for line in text.split("\n") if line.strip()]
        self._save_net_config()
        self.window.destroy()

    # ──── 保存系统设置 ────
    def _save_settings(self):
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
            "enabled": any(p.get("api_key") for p in self._profiles),
            "profiles": self._profiles,
            "selected_profile": self._ai_profile_var.get(),
        }
        save_config(self._cfg)
        self._save_net_config()

        messagebox.showinfo("成功", "设置已保存", parent=self.window)
        self.window.destroy()
