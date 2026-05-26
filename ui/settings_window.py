"""
现代化系统设置界面
包含OneBot配置、监控设置、预测设置、AI配置、网络设置（代理/Cookie/扫码登录）
"""

import json
import os
import re
import tkinter as tk
import webbrowser
import logging
from typing import Any, Dict, List, Optional
from tkinter import ttk, messagebox

from ui.theme import C
from ui.helpers import FONT, FONT_BOLD, FONT_SM, FONT_MONO, project_path, auto_threshold_name
from ui.dialog_base import DialogBase
from ui.scrollable_frame import ScrollableFrame
from core.bilibili_api import get_bilibili_api
from core.proxy_manager import ProxyManager
from algorithms.registry import AlgorithmRegistry
from algorithms.weight_manager import get_weight_manager
from utils.update_checker import _s

logger = logging.getLogger(__name__)


class SettingsWindow:
    """统一设置窗口"""

    def __init__(self, parent=None, gui=None):
        # 自适应对话框尺寸
        self.dlg = DialogBase(
            parent, "系统设置", DialogBase.calc_geometry(parent, 0.48, 0.68), resizable=(True, True), modal=False
        )
        self.window = self.dlg.window
        self.gui = gui

        from config import load_config

        self._cfg = load_config()

        # 网络配置（代理/Cookie）
        self._net_cfg_file = project_path("data", "network_config.json")
        self._net_cfg = self._load_net_config()

        self.setup_ui()

    # ── 网络配置持久化 ──
    def _load_net_config(self) -> dict:
        if os.path.exists(self._net_cfg_file):
            try:
                with open(self._net_cfg_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                # 解密 Cookie
                cookies = cfg.get("cookies", {})
                if cookies:
                    from utils.crypto import decrypt_dict

                    decrypt_dict(cookies, "SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")
                return cfg
            except Exception as e:
                logger.debug("加载网络配置失败: %s", e)
        return {"proxies": [], "cookies": {}}

    def _save_net_config(self):
        os.makedirs(os.path.dirname(self._net_cfg_file), exist_ok=True)
        # 加密 Cookie 后再持久化
        cookies = self._net_cfg.get("cookies", {})
        if cookies:
            from utils.crypto import encrypt_dict

            encrypt_dict(cookies, "SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")
        with open(self._net_cfg_file, "w", encoding="utf-8") as f:
            json.dump(self._net_cfg, f, ensure_ascii=False, indent=2)
        # 保存后恢复明文（UI 继续使用明文）
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
        self._build_training_tab(nb)
        self._build_proxy_tab(nb)
        self._build_cookie_tab(nb)
        self._build_retry_tab(nb)
        self._build_status_tab(nb)
        self._build_about_tab(nb)

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
        self.onebot_token = self._field(
            sec, "Access Token", self._cfg.get("onebot", {}).get("access_token", ""), show="*"
        )
        self.qq_private = self._field(sec, "私聊QQ号", self._cfg.get("onebot", {}).get("private_qq", ""))
        self.qq_group = self._field(sec, "群号", self._cfg.get("onebot", {}).get("group_qq", ""))

        # 启用开关
        enabled = self._cfg.get("onebot", {}).get("enabled", False)
        self.onebot_enabled = tk.BooleanVar(value=enabled)
        cb_frame = tk.Frame(sec, bg=C["bg_elevated"])
        cb_frame.pack(fill=tk.X, pady=(8, 4))
        ttk.Checkbutton(cb_frame, text="启用 OneBot 通知", variable=self.onebot_enabled).pack(anchor="w")

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

        # ── 基础参数 ──
        sec = self._section(page, "基础参数")
        self.predict_hours = self._spin_field(
            sec, "预测时长(小时)", self._cfg.get("prediction", {}).get("prediction_hours", 168), 24, 720
        )
        self.min_confidence = self._spin_field(
            sec, "最小置信度", self._cfg.get("prediction", {}).get("min_confidence", 0.5), 0.1, 1.0
        )

        # ── 自定义阈值 ──
        th_sec = self._section(page, "播放量阈值", padding=(16, 8, 12))
        tk.Label(
            th_sec,
            text="每个阈值代表一个里程碑，达到时触发推送提醒",
            bg=C["bg_elevated"],
            fg=C["text_3"],
            font=FONT_SM,
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 6))

        # 阈值列表容器
        th_list_frame = tk.Frame(th_sec, bg=C["bg_elevated"])
        th_list_frame.pack(fill=tk.X, pady=(0, 6))

        self._thresh_rows: list = []  # [(value_var, name_var, frame)]

        # 从当前配置加载阈值
        raw = self._cfg.get("prediction", {}).get("thresholds", [])
        if raw and isinstance(raw[0], (list, tuple)):
            th_data = [(int(v), str(n)) for v, n in raw]
        else:
            th_data = (
                [(int(v), auto_threshold_name(v)) for v in raw]
                if raw
                else [(100000, "10万"), (1000000, "100万"), (10000000, "1000万")]
            )

        for v, n in sorted(th_data, key=lambda x: x[0]):
            self._add_threshold_row(th_list_frame, v, n)

        add_btn = ttk.Button(th_sec, text="+ 添加阈值", command=lambda: self._add_threshold_row(th_list_frame))
        add_btn.pack(anchor="w", padx=0)

    # ── 阈值行管理 ──

    def _add_threshold_row(self, parent, value=100000, name=""):
        """添加一行阈值编辑控件"""
        row = tk.Frame(parent, bg=C["bg_elevated"])
        row.pack(fill=tk.X, pady=2)

        v_var = tk.StringVar(value=str(int(value)))
        n_var = tk.StringVar(value=name or auto_threshold_name(value))

        tk.Label(row, text="播放量:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT)
        v_spin = ttk.Spinbox(row, from_=1000, to=999_999_999, textvariable=v_var, width=14, font=FONT_SM)
        v_spin.pack(side=tk.LEFT, padx=(2, 8))

        tk.Label(row, text="名称:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT)
        n_entry = ttk.Entry(row, textvariable=n_var, width=12, font=FONT_SM)
        n_entry.pack(side=tk.LEFT, padx=(2, 8))

        del_btn = tk.Label(
            row, text="✕", bg=C["bg_elevated"], fg=C["danger"], font=("Segoe UI", 10, "bold"), cursor="hand2"
        )
        del_btn.pack(side=tk.LEFT, padx=2)
        del_btn.bind("<Button-1>", lambda e: (row.destroy(), self._thresh_rows.remove((v_var, n_var, row))))

        self._thresh_rows.append((v_var, n_var, row))

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
        ttk.Button(btn_row, text="🗑 删除配置", command=self._delete_ai_profile, state=_s()).pack(side=tk.LEFT, padx=4)
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

        sf = ScrollableFrame(canvas_frame, bg=C["bg_elevated"])
        sf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        algo_frame = sf.inner

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
                command=lambda n=name: self._weight_vars[n].set(get_weight_manager().ml_weights.get(n, 1.0)),
            ).grid(row=0, column=1, padx=2)

            wv = tk.DoubleVar(value=info.get("user_weight") or info.get("final_weight", 1.0))
            self._weight_vars[name] = wv
            ttk.Entry(row, textvariable=wv, width=10, state=_s()).grid(row=0, column=2, padx=4)

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
        ttk.Button(btn_row, text="重置所有权重", command=self._reset_all_weights, state=_s()).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="刷新", command=self._refresh_weights).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="💾 保存权重", command=self._save_weights, style="Primary.TButton", state=_s()).pack(side=tk.RIGHT)

    def _reset_all_weights(self):
        if messagebox.askyesno("确认", "确定要重置所有自定义权重吗？", parent=self.window):
            get_weight_manager().reset_weights()
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
                    get_weight_manager().set_user_weight(name, weight)
                else:
                    get_weight_manager().clear_user_weight(name)
            except ValueError:
                messagebox.showerror("错误", f"算法 {name} 的权重值无效", parent=self.window)
                return
        messagebox.showinfo("成功", "权重设置已保存", parent=self.window)

    # ──── 模型训练 ────
    def _build_training_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  模型训练  ")

        # ── 设备信息 ──
        dev_sec = self._section(page, "训练设备", padding=(16, 12, 6))
        dev_row = tk.Frame(dev_sec, bg=C["bg_elevated"])
        dev_row.pack(fill=tk.X, pady=(4, 4))
        tk.Label(dev_row, text="当前设备:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT, width=12, anchor="w").pack(
            side=tk.LEFT
        )
        self._tr_device_lbl = tk.Label(
            dev_row, text="检测中…", bg=C["bg_elevated"], fg=C["text_1"], font=FONT_BOLD, anchor="w"
        )
        self._tr_device_lbl.pack(side=tk.LEFT, padx=(4, 12))
        self._tr_force_cpu_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            dev_row, text="强制使用 CPU", variable=self._tr_force_cpu_var, command=self._on_force_cpu_changed
        ).pack(side=tk.LEFT)
        ttk.Button(dev_row, text="刷新", command=self._refresh_device_info).pack(side=tk.RIGHT)

        # ── 数据规模 ──
        data_sec = self._section(page, "数据规模", padding=(16, 6, 6))
        self._tr_data_lbl = tk.Label(
            data_sec, text="估算中…", bg=C["bg_elevated"], fg=C["text_1"], font=FONT, anchor="w", justify="left"
        )
        self._tr_data_lbl.pack(fill=tk.X, padx=4, pady=(4, 4))
        ttk.Button(data_sec, text="重新估算", command=self._refresh_data_size).pack(anchor="w", padx=4)

        # ── 算法列表 ──
        list_sec = self._section(page, "可训练算法（PyTorch）", padding=(16, 6, 6))

        # 算法列表头
        hdr = tk.Frame(list_sec, bg=C["bg_surface"], highlightthickness=1, highlightbackground=C["border_sub"])
        hdr.pack(fill=tk.X, pady=(2, 2))
        for col_i, (text, w) in enumerate([("选择", 6), ("算法", 22), ("ID", 22), ("状态", 16), ("操作", 12)]):
            tk.Label(
                hdr,
                text=text,
                bg=C["bg_surface"],
                fg=C["text_2"],
                font=("Microsoft YaHei UI", 8, "bold"),
                width=w,
                anchor="w",
            ).grid(row=0, column=col_i, padx=4, pady=3, sticky="w")

        # 全选 / 反选
        toolbar = tk.Frame(list_sec, bg=C["bg_elevated"])
        toolbar.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(toolbar, text="全选", command=lambda: self._tr_select_all(True)).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="全不选", command=lambda: self._tr_select_all(False)).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="仅选未训练", command=self._tr_select_untrained).pack(side=tk.LEFT, padx=4)
        self._tr_count_lbl = tk.Label(toolbar, text="", bg=C["bg_elevated"], fg=C["text_3"], font=FONT_SM)
        self._tr_count_lbl.pack(side=tk.RIGHT)

        # 滚动容器
        canvas_frame = tk.Frame(list_sec, bg=C["bg_base"])
        canvas_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        sf = ScrollableFrame(canvas_frame, bg=C["bg_elevated"], height=200)
        sf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._tr_algo_frame = sf.inner

        self._tr_check_vars: Dict[str, tk.BooleanVar] = {}  # algo_id -> BooleanVar
        self._tr_algo_meta: Dict[str, Dict[str, Any]] = {}  # algo_id -> {name, has_ckpt, active, ...}

        # ── 训练参数 + 控制 ──
        ctrl_sec = self._section(page, "训练控制", padding=(16, 6, 12))

        param_row = tk.Frame(ctrl_sec, bg=C["bg_elevated"])
        param_row.pack(fill=tk.X, pady=(4, 4))
        tk.Label(param_row, text="Epoch:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT)
        self._tr_epoch_var = tk.IntVar(value=20)
        ttk.Spinbox(param_row, from_=1, to=500, textvariable=self._tr_epoch_var, width=6).pack(
            side=tk.LEFT, padx=(4, 12)
        )
        tk.Label(param_row, text="Batch:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT)
        self._tr_batch_var = tk.IntVar(value=32)
        ttk.Spinbox(param_row, from_=1, to=512, textvariable=self._tr_batch_var, width=6).pack(
            side=tk.LEFT, padx=(4, 12)
        )

        btn_row = tk.Frame(ctrl_sec, bg=C["bg_elevated"])
        btn_row.pack(fill=tk.X, pady=(2, 4))
        self._tr_train_btn = ttk.Button(
            btn_row, text="▶ 训练所有勾选", command=self._on_train_start, style="Primary.TButton", state=_s()
        )
        self._tr_train_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._tr_cancel_btn = ttk.Button(btn_row, text="✕ 取消", command=self._on_train_cancel, state="disabled")
        self._tr_cancel_btn.pack(side=tk.LEFT)

        # 模型导入/导出
        ttk.Button(btn_row, text="📤 导出模型", command=self._on_export_checkpoints).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_row, text="📥 导入模型", command=self._on_import_checkpoints, state=_s()).pack(side=tk.RIGHT, padx=(4, 0))

        self._tr_progress = ttk.Progressbar(ctrl_sec, mode="determinate", maximum=100)
        self._tr_progress.pack(fill=tk.X, pady=(4, 2))
        self._tr_status_lbl = tk.Label(
            ctrl_sec, text="就绪", bg=C["bg_elevated"], fg=C["text_3"], font=FONT_SM, anchor="w"
        )
        self._tr_status_lbl.pack(fill=tk.X, padx=4, pady=(2, 2))

        # 训练状态
        self._tr_thread = None
        self._tr_queue = None
        self._tr_cancel_flag = [False]
        self._tr_t0 = None

        # 首次渲染
        self._refresh_device_info()
        self._refresh_data_size()
        self._refresh_algo_list()

    # —— Training tab helpers ——

    def _discover_torch_algorithms(self) -> List[Dict[str, Any]]:
        """扫描注册器，返回可训练算法清单。"""
        from algorithms.registry import AlgorithmRegistry

        return AlgorithmRegistry.get_trainable_info()

    def _refresh_device_info(self):
        try:
            from algorithms.training.device import get_device_info, is_torch_available, force_cpu

            force_cpu(self._tr_force_cpu_var.get())
            info = get_device_info()
            if not is_torch_available():
                self._tr_device_lbl.config(text="❌ torch 未安装（请 pip install torch）", fg=C["danger"])
            elif info.get("is_gpu"):
                mem = info.get("total_memory_gb", 0)
                self._tr_device_lbl.config(text=f"✅ {info['name']} ({mem:.1f} GB) [{info['device']}]", fg=C["success"])
            else:
                self._tr_device_lbl.config(text=f"💻 {info['name']} ({info.get('device', 'cpu')})", fg=C["warning"])
        except Exception as e:
            self._tr_device_lbl.config(text=f"⚠ 检测失败: {e}", fg=C["danger"])

    def _on_force_cpu_changed(self):
        self._refresh_device_info()

    def _refresh_data_size(self):
        self._tr_data_lbl.config(text="估算中…", fg=C["text_3"])

        def _worker():
            try:
                from algorithms.training.trainer import ModelTrainer

                tr = ModelTrainer()
                info = tr.estimate_data_size()
                total_videos = info.get("total_videos", 0)
                valid_videos = info.get("valid_videos", 0)
                total_samples = info.get("total_samples", 0)
                est_s = info.get("estimated_time_s", 0)
                eta_min = est_s / 60
                txt = (
                    f"视频总数: {total_videos}  ·  有效视频: {valid_videos}  ·  "
                    f"训练样本: {total_samples:,}\n"
                    f"预计单算法训练时间: {eta_min:.1f} 分钟"
                )
                self.window.after(0, lambda: self._tr_data_lbl.config(text=txt, fg=C["text_1"]))
            except Exception as e:
                self.window.after(0, lambda e=e: self._tr_data_lbl.config(text=f"⚠ 估算失败: {e}", fg=C["danger"]))

        import threading

        threading.Thread(target=_worker, daemon=True).start()

    def _refresh_algo_list(self):
        # 清空旧行
        for w in self._tr_algo_frame.winfo_children():
            w.destroy()
        self._tr_check_vars.clear()
        self._tr_algo_meta.clear()

        try:
            algos = self._discover_torch_algorithms()
        except Exception as e:
            tk.Label(
                self._tr_algo_frame,
                text=f"⚠ 加载算法列表失败: {e}",
                bg=C["bg_elevated"],
                fg=C["danger"],
                font=FONT,
            ).pack(fill=tk.X, padx=4, pady=8)
            return

        trained_n = sum(1 for a in algos if a["has_ckpt"])
        self._tr_count_lbl.config(text=f"{len(algos)} 个算法 · 已训练 {trained_n}")

        for a in algos:
            aid = a["algorithm_id"]
            self._tr_algo_meta[aid] = a

            row = tk.Frame(
                self._tr_algo_frame,
                bg=C["bg_surface"],
                highlightthickness=1,
                highlightbackground=C["border_sub"],
            )
            row.pack(fill=tk.X, pady=1)

            var = tk.BooleanVar(value=not a["has_ckpt"])
            self._tr_check_vars[aid] = var
            ttk.Checkbutton(row, variable=var).grid(row=0, column=0, padx=6, pady=3)

            tk.Label(
                row,
                text=a["name"],
                bg=C["bg_surface"],
                fg=C["text_1"],
                font=FONT,
                width=22,
                anchor="w",
            ).grid(row=0, column=1, padx=4, sticky="w")

            tk.Label(
                row,
                text=aid,
                bg=C["bg_surface"],
                fg=C["text_3"],
                font=FONT_MONO,
                width=22,
                anchor="w",
            ).grid(row=0, column=2, padx=4, sticky="w")

            if a["has_ckpt"]:
                status_txt = f"✅ {a['active_version'][:18]}" + (
                    f" (+{a['version_count'] - 1})" if a["version_count"] > 1 else ""
                )
                status_fg = C["success"]
            else:
                status_txt = "□ 未训练"
                status_fg = C["text_3"]
            tk.Label(
                row,
                text=status_txt,
                bg=C["bg_surface"],
                fg=status_fg,
                font=FONT_SM,
                width=22,
                anchor="w",
            ).grid(row=0, column=3, padx=4, sticky="w")

            ttk.Button(
                row,
                text="版本管理",
                width=10,
                command=lambda aid=aid: self._open_version_manager(aid),
            ).grid(row=0, column=4, padx=4, pady=2)

    def _tr_select_all(self, flag: bool):
        for var in self._tr_check_vars.values():
            var.set(flag)

    def _tr_select_untrained(self):
        for aid, var in self._tr_check_vars.items():
            var.set(not self._tr_algo_meta.get(aid, {}).get("has_ckpt", False))

    # —— 训练执行 ——

    def _on_train_start(self):
        from algorithms.training.device import is_torch_available

        if not is_torch_available():
            messagebox.showerror("torch 未安装", "请先安装 PyTorch:\npip install torch", parent=self.window)
            return

        selected = [aid for aid, v in self._tr_check_vars.items() if v.get()]
        if not selected:
            messagebox.showwarning("提示", "请至少勾选一个算法", parent=self.window)
            return

        epochs = max(1, int(self._tr_epoch_var.get()))
        batch = max(1, int(self._tr_batch_var.get()))

        if not messagebox.askyesno(
            "确认训练",
            f"将训练 {len(selected)} 个算法，epoch={epochs}，batch={batch}。\n"
            "训练过程不可中途暂停（只能取消未开始的算法）。",
            parent=self.window,
        ):
            return

        # 锁住 UI
        self._tr_train_btn.config(state="disabled")
        self._tr_cancel_btn.config(state="normal")
        self._tr_cancel_flag[0] = False
        self._tr_progress["value"] = 0
        self._tr_status_lbl.config(text=f"准备训练 {len(selected)} 个算法 …", fg=C["text_2"])

        import threading
        import queue as _q
        import time as _t

        self._tr_t0 = _t.time()
        self._tr_queue = _q.Queue()

        def _cb(payload: Dict):
            payload = dict(payload)
            payload["_total_selected"] = len(selected)
            self._tr_queue.put(payload)

        def _worker():
            try:
                from algorithms.training.trainer import ModelTrainer

                trainer = ModelTrainer()
                # 在每个算法开始前检查 cancel
                remaining = list(selected)
                results = {}
                while remaining:
                    if self._tr_cancel_flag[0]:
                        self._tr_queue.put({"stage": "cancelled", "remaining": remaining})
                        break
                    aid = remaining.pop(0)
                    sub = trainer.train_global([aid], epochs=epochs, batch_size=batch, progress_cb=_cb)
                    results.update(sub)
                self._tr_queue.put({"stage": "all_done", "results": results})
            except Exception as e:
                self._tr_queue.put({"stage": "fatal", "error": str(e)})

        self._tr_thread = threading.Thread(target=_worker, daemon=True)
        self._tr_thread.start()
        self.window.after(150, self._poll_training_progress)

    def _on_train_cancel(self):
        self._tr_cancel_flag[0] = True
        self._tr_cancel_btn.config(state="disabled")
        self._tr_status_lbl.config(text="正在取消（等待当前算法完成）…", fg=C["warning"])

    def _on_export_checkpoints(self):
        """导出所有 checkpoint 为 zip 文件"""
        try:
            from utils.checkpoint_io import export_checkpoints

            path = export_checkpoints()
            self._tr_status_lbl.config(text=f"导出完成: {os.path.basename(path)}", fg=C["success"])
            if messagebox.askyesno("导出完成", f"模型已导出到:\n{path}\n\n是否打开所在文件夹？", parent=self.window):
                os.startfile(os.path.dirname(path))
        except Exception as e:
            messagebox.showerror("导出失败", str(e), parent=self.window)
            self._tr_status_lbl.config(text=f"导出失败: {e}", fg=C["danger"])

    def _on_import_checkpoints(self):
        """从 zip 文件导入 checkpoint"""
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title="选择要导入的 checkpoint 文件",
            filetypes=[("Zip 文件", "*.zip"), ("所有文件", "*.*")],
            parent=self.window,
        )
        if not path:
            return
        try:
            from utils.checkpoint_io import import_checkpoints

            count = import_checkpoints(path)
            messagebox.showinfo(
                "导入完成", f"已导入 {count} 个算法的模型\n\n请刷新算法列表查看更新。", parent=self.window
            )
            self._refresh_algo_list()
        except Exception as e:
            messagebox.showerror("导入失败", str(e), parent=self.window)

    def _poll_training_progress(self):
        import queue as _q
        import time as _t

        if self._tr_queue is None:
            return

        done_all = False
        # 排空队列以避免堆积
        while True:
            try:
                msg = self._tr_queue.get_nowait()
            except _q.Empty:
                break
            stage = msg.get("stage")
            total_sel = msg.get("_total_selected", 1)

            if stage == "start":
                aid = msg.get("algo_id", "?")
                cur = msg.get("current", 0)
                tot = msg.get("total", 1)
                self._tr_status_lbl.config(text=f"[{cur}/{tot}] 开始训练 {aid} …", fg=C["text_2"])
            elif stage == "epoch":
                aid = msg.get("algo_id", "?")
                ep = msg.get("epoch", 0)
                eps = msg.get("epochs", 1)
                tloss = msg.get("train_loss", 0.0)
                vloss = msg.get("val_loss", -1.0)
                elapsed = msg.get("elapsed_s", 0.0)
                # 进度百分比：当前算法 epoch / total_epochs
                pct = min(100, int((ep / max(1, eps)) * 100))
                self._tr_progress["value"] = pct
                vtxt = f" val={vloss:.4f}" if vloss >= 0 else ""
                eta_total = (_t.time() - self._tr_t0) if self._tr_t0 else 0
                self._tr_status_lbl.config(
                    text=(
                        f"{aid}  ·  epoch {ep}/{eps}  ·  "
                        f"train={tloss:.4f}{vtxt}  ·  本算法 {elapsed:.1f}s  ·  累计 {eta_total:.1f}s"
                    ),
                    fg=C["text_1"],
                )
            elif stage == "done":
                aid = msg.get("algo_id", "?")
                cur = msg.get("current", 0)
                ver = msg.get("version", "")
                self._tr_status_lbl.config(text=f"✓ {aid} 完成 → {ver}  ({cur}/{total_sel})", fg=C["success"])
                self._tr_progress["value"] = int(cur / max(1, total_sel) * 100)
            elif stage == "error":
                aid = msg.get("algo_id", "?")
                err = msg.get("error", "")
                self._tr_status_lbl.config(text=f"✗ {aid} 失败: {err}", fg=C["danger"])
            elif stage == "cancelled":
                rem = msg.get("remaining", [])
                self._tr_status_lbl.config(text=f"已取消，剩余 {len(rem)} 个算法未训练", fg=C["warning"])
                done_all = True
            elif stage == "all_done":
                results = msg.get("results", {})
                ok = sum(1 for v in results.values() if v)
                bad = sum(1 for v in results.values() if not v)
                elapsed = (_t.time() - self._tr_t0) if self._tr_t0 else 0
                self._tr_status_lbl.config(text=f"全部完成: ✓ {ok}  ✗ {bad}  ·  耗时 {elapsed:.1f}s", fg=C["success"])
                self._tr_progress["value"] = 100
                done_all = True
            elif stage == "fatal":
                err = msg.get("error", "")
                self._tr_status_lbl.config(text=f"训练进程异常: {err}", fg=C["danger"])
                done_all = True

        if done_all:
            self._tr_train_btn.config(state="normal")
            self._tr_cancel_btn.config(state="disabled")
            self._refresh_algo_list()
            self._tr_queue = None
            self._tr_thread = None
        else:
            self.window.after(200, self._poll_training_progress)

    # —— 版本管理弹窗 ——

    def _open_version_manager(self, algo_id: str):  # noqa: C901
        from algorithms.training.checkpoint_manager import CheckpointManager

        ckpt = CheckpointManager(algo_id)

        top = tk.Toplevel(self.window)
        top.title(f"版本管理 — {algo_id}")
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        top.geometry(f"{int(sw * 0.40)}x{int(sh * 0.45)}")
        top.configure(bg=C["bg_surface"])
        top.transient(self.window)
        top.grab_set()

        tk.Label(
            top,
            text=f"算法: {algo_id}",
            bg=C["bg_surface"],
            fg=C["text_1"],
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(pady=(14, 4))

        cols = ("active", "version", "created", "samples", "val_loss")
        tree = ttk.Treeview(top, columns=cols, show="headings", height=10)
        tree.heading("active", text="●")
        tree.heading("version", text="版本")
        tree.heading("created", text="创建时间")
        tree.heading("samples", text="样本数")
        tree.heading("val_loss", text="val_loss")
        tree.column("active", width=36, anchor="center", stretch=False)
        tree.column("version", width=200, anchor="w")
        tree.column("created", width=150, anchor="w")
        tree.column("samples", width=80, anchor="e", stretch=False)
        tree.column("val_loss", width=90, anchor="e", stretch=False)
        tree.pack(fill=tk.BOTH, expand=True, padx=14, pady=6)

        def _reload():
            for item in tree.get_children():
                tree.delete(item)
            for v in ckpt.list_versions():
                marker = "✅" if v["active"] else ""
                val_loss = f"{v['val_loss']:.4f}" if v["val_loss"] >= 0 else "—"
                tree.insert(
                    "",
                    "end",
                    values=(marker, v["version"], v["created_at"], v["data_count"], val_loss),
                )

        _reload()

        def _selected_version() -> Optional[str]:
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("提示", "请先选择一个版本", parent=top)
                return None
            return tree.item(sel[0], "values")[1]

        def _do_activate():
            v = _selected_version()
            if v and ckpt.activate(v):
                _reload()
                self._refresh_algo_list()

        def _do_delete():
            v = _selected_version()
            if not v:
                return
            if not messagebox.askyesno("确认删除", f"确定删除版本 {v} 吗？", parent=top):
                return
            if ckpt.delete(v):
                _reload()
                self._refresh_algo_list()

        def _do_export():
            v = _selected_version()
            if not v:
                return
            from tkinter import filedialog

            path = filedialog.asksaveasfilename(
                parent=top,
                defaultextension=".pt",
                initialfile=f"{algo_id}_{v}.pt",
                filetypes=[("PyTorch checkpoint", "*.pt"), ("所有文件", "*.*")],
            )
            if not path:
                return
            try:
                import shutil

                src = project_path("algorithms", "checkpoints", algo_id, f"{v}.pt")
                shutil.copyfile(src, path)
                messagebox.showinfo("成功", f"已导出到:\n{path}", parent=top)
            except Exception as e:
                messagebox.showerror("失败", f"导出失败: {e}", parent=top)

        btn_f = tk.Frame(top, bg=C["bg_surface"])
        btn_f.pack(fill=tk.X, padx=14, pady=(4, 14))
        ttk.Button(btn_f, text="激活", command=_do_activate, style="Primary.TButton").pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_f, text="删除", command=_do_delete, state=_s()).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_f, text="导出 .pt", command=_do_export).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_f, text="关闭", command=top.destroy).pack(side=tk.RIGHT, padx=2)

    # ──── 代理 ────
    def _build_proxy_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  代理设置  ")

        sec = tk.Frame(page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        sec.pack(fill=tk.BOTH, expand=True, padx=16, pady=12, ipadx=10, ipady=8)
        tk.Label(sec, text="代理列表（每行一个）", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(
            anchor="w", pady=(0, 4)
        )

        # 协议选择 + 快速添加行
        add_row = tk.Frame(sec, bg=C["bg_elevated"])
        add_row.pack(fill=tk.X, pady=(0, 4))
        tk.Label(add_row, text="协议:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT)
        self._proxy_proto_var = tk.StringVar(value="http://")
        proto_cb = ttk.Combobox(
            add_row,
            textvariable=self._proxy_proto_var,
            values=["http://", "https://", "socks4://", "socks5://"],
            width=10,
            state="readonly",
            font=FONT_SM,
        )
        proto_cb.pack(side=tk.LEFT, padx=(4, 8))
        tk.Label(add_row, text="地址:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT)
        self._proxy_addr_entry = ttk.Entry(add_row, width=35, font=FONT_SM)
        self._proxy_addr_entry.pack(side=tk.LEFT, padx=(4, 8))
        self._proxy_addr_entry.bind("<Return>", lambda e: self._add_proxy_entry())
        ttk.Button(add_row, text="添加", command=self._add_proxy_entry, style="Primary.TButton").pack(side=tk.LEFT)

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
        ttk.Button(btn_row, text="批量导入", command=self._batch_import_proxies).pack(side=tk.LEFT, padx=4)
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
        ttk.Button(import_row, text="🔑 密码登录", command=self._password_login, state=_s()).pack(side=tk.LEFT, padx=4)

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
        self._cookie_unlock_btn = ttk.Button(
            btn_row, text="🔒 解锁查看", command=self._toggle_cookie_unlock, width=10,
        )
        self._cookie_unlock_btn.pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(btn_row, text="清空Cookie", command=self._clear_cookies, state=_s()).pack(side=tk.LEFT)

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

        self.retry_count_var = _spin_r(sec, "最大重试次数", get_bilibili_api().max_retries, 1, 10)
        self.base_delay_var = _spin_r(sec, "基础重试延迟(秒)", get_bilibili_api().base_retry_delay, 1, 30)
        self.min_interval_var = _spin_r(sec, "最小请求间隔(秒)", get_bilibili_api()._min_request_interval, 0.1, 10)

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

    # ──── 关于作者 ────
    def _build_about_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  关于作者  ")

        from __init__ import __version__, __author__

        # 项目信息
        sec1 = tk.Frame(page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        sec1.pack(fill=tk.X, padx=16, pady=(16, 6), ipadx=10, ipady=10)
        tk.Label(
            sec1, text="项目信息", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 9, "bold")
        ).pack(anchor="w")

        rows = [
            ("项目名称", "B站视频监控与播放量预测系统"),
            ("版本号", f"v{__version__}"),
            ("作者", __author__),
        ]
        for label, value in rows:
            f = tk.Frame(sec1, bg=C["bg_elevated"])
            f.pack(fill=tk.X, pady=2)
            tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_3"], font=FONT, width=12, anchor="w").pack(
                side=tk.LEFT
            )
            tk.Label(f, text=value, bg=C["bg_elevated"], fg=C["text_1"], font=FONT, anchor="w").pack(side=tk.LEFT)

        # 链接
        sec2 = tk.Frame(page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        sec2.pack(fill=tk.X, padx=16, pady=6, ipadx=10, ipady=10)
        tk.Label(
            sec2, text="相关链接", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 9, "bold")
        ).pack(anchor="w")

        links = [
            ("GitHub", "https://github.com/jinyiwei2012/bilivideo_monitor", "项目源代码，欢迎 Star ⭐"),
            ("B站主页", "https://space.bilibili.com/1610751976", "作者的 Bilibili 个人空间"),
        ]
        for title, url, desc in links:
            f = tk.Frame(sec2, bg=C["bg_elevated"])
            f.pack(fill=tk.X, pady=2)
            tk.Label(f, text=title, bg=C["bg_elevated"], fg=C["text_3"], font=FONT, width=12, anchor="w").pack(
                side=tk.LEFT
            )
            link_lbl = tk.Label(
                f, text=url, bg=C["bg_elevated"], fg=C["bilibili"], font=FONT, cursor="hand2", anchor="w"
            )
            link_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
            link_lbl.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
            link_lbl.bind("<Enter>", lambda e: e.widget.config(fg=C.get("accent", "#00a1d6")))
            link_lbl.bind("<Leave>", lambda e: e.widget.config(fg=C["bilibili"]))

        # 描述
        sec3 = tk.Frame(page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        sec3.pack(fill=tk.X, padx=16, pady=(6, 16), ipadx=10, ipady=10)
        tk.Label(sec3, text="说明", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 9, "bold")).pack(
            anchor="w"
        )
        desc_text = (
            "本系统用于监控 Bilibili 视频播放量增长趋势，"
            "支持 55 种预测算法、多阈值告警、QQ 机器人通知等功能。\n\n"
            "如果您觉得本项目对您有帮助，欢迎在 GitHub 上给项目点一个 Star！"
        )
        tk.Label(
            sec3,
            text=desc_text,
            bg=C["bg_elevated"],
            fg=C["text_2"],
            font=FONT,
            anchor="w",
            justify="left",
            wraplength=500,
        ).pack(anchor="w", fill=tk.X)

    # ═══════════════════════════════════════════════════

    @staticmethod
    def _clear_entry(entry, value):
        entry.delete(0, tk.END)
        entry.insert(0, value)

    def _test_connection(self):
        """测试 OneBot 服务连通性（后台线程，不阻塞 UI）"""
        http_url = self.onebot_http.get().strip()
        token = self.onebot_token.get().strip()

        if not http_url:
            messagebox.showwarning("提示", "请先填写 HTTP 地址", parent=self.window)
            return

        from core.notification import notification_manager
        from threading import Thread

        # 用当前 UI 的配置暂存到 notification_manager 做测试
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
        """显示连接测试结果弹窗"""
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
    def _add_proxy_entry(self):
        """从协议选择 + 地址输入框添加代理到列表"""
        proto = self._proxy_proto_var.get()
        addr = self._proxy_addr_entry.get().strip()
        if not addr:
            return
        # 如果用户已经输入了协议头，不再重复添加
        if re.match(r"^(https?|socks[45])://", addr, re.IGNORECASE):
            line = addr
        else:
            line = f"{proto}{addr}"
        self._proxy_addr_entry.delete(0, tk.END)
        text = self.proxy_text.get("1.0", "end").strip()
        lines = [ln for ln in text.split("\n") if ln.strip()] if text else []
        lines.append(line)
        self.proxy_text.delete("1.0", "end")
        self.proxy_text.insert("1.0", "\n".join(lines))

    def _batch_import_proxies(self):
        """批量导入代理窗口：粘贴地址列表，自动补全已选择的协议头"""
        top = tk.Toplevel(self.window)
        top.title("批量导入代理")
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        top.geometry(f"{int(sw * 0.35)}x{int(sh * 0.45)}")
        top.configure(bg=C["bg_surface"])
        top.transient(self.window)
        top.grab_set()
        top.resizable(True, True)

        tk.Label(
            top,
            text="批量导入代理地址",
            bg=C["bg_surface"],
            fg=C["text_1"],
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(pady=(14, 2))

        # 协议选择（使用父窗口已选择的协议）
        proto_row = tk.Frame(top, bg=C["bg_surface"])
        proto_row.pack(fill=tk.X, padx=20, pady=(4, 2))
        tk.Label(proto_row, text="协议:", bg=C["bg_surface"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)
        batch_proto_var = tk.StringVar(value=self._proxy_proto_var.get())
        ttk.Combobox(
            proto_row,
            textvariable=batch_proto_var,
            values=["http://", "https://", "socks4://", "socks5://"],
            width=12,
            state="readonly",
            font=FONT,
        ).pack(side=tk.LEFT, padx=(6, 0))

        tk.Label(
            top,
            text="每行一个地址（host:port 或完整URL），导入时自动补全协议头",
            bg=C["bg_surface"],
            fg=C["text_3"],
            font=FONT_SM,
        ).pack(pady=(4, 2))

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
        text_w.pack(fill=tk.BOTH, expand=True, padx=20, pady=4)

        # 导入按钮行
        btn_f = tk.Frame(top, bg=C["bg_surface"])
        btn_f.pack(fill=tk.X, padx=20, pady=(4, 14))

        status_var = tk.StringVar(value="")
        status_lbl = tk.Label(
            btn_f, textvariable=status_var, bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM, anchor="w"
        )
        status_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def _do_import():
            raw = text_w.get("1.0", tk.END).strip()
            if not raw:
                status_var.set("请输入代理地址")
                status_lbl.config(fg=C["danger"])
                return

            lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
            proto = batch_proto_var.get()
            imported = []
            for ln in lines:
                if re.match(r"^(https?|socks[45])://", ln, re.IGNORECASE):
                    imported.append(ln)
                else:
                    imported.append(f"{proto}{ln}")

            # 追加到主窗口代理文本框
            current = self.proxy_text.get("1.0", "end").strip()
            all_lines = [ln for ln in current.split("\n") if ln.strip()] if current else []
            all_lines.extend(imported)
            self.proxy_text.delete("1.0", "end")
            self.proxy_text.insert("1.0", "\n".join(all_lines))

            # 检查重复
            unique = set(all_lines)
            dup_count = len(all_lines) - len(unique)

            total_count = len(imported)
            status_lbl.config(fg=C["success"])
            msg = f"✅ 已导入 {total_count} 条代理"
            if dup_count:
                msg += f"（含 {dup_count} 条重复）"
            status_var.set(msg)

            # 同时显示 messagebox 确保用户注意到
            top.after(
                200,
                lambda: messagebox.showinfo(
                    "导入完成",
                    f"成功导入 {total_count} 条代理\n"
                    f"当前代理列表共 {len(all_lines)} 条"
                    + (f"\n（其中 {dup_count} 条重复已去重）" if dup_count else ""),
                    parent=top,
                ),
            )

        ttk.Button(btn_f, text="导入并追加", command=_do_import, style="Primary.TButton").pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        ttk.Button(btn_f, text="取消", command=top.destroy).pack(side=tk.RIGHT, padx=4)

    def _apply_proxies(self):
        text = self.proxy_text.get("1.0", "end").strip()
        proxy_list = [line.strip() for line in text.split("\n") if line.strip()]
        get_bilibili_api().clear_proxies()
        for ps in proxy_list:
            get_bilibili_api().add_proxy({"http": ps, "https": ps})
        self._net_cfg["proxies"] = proxy_list
        self._save_net_config()
        # 验证文件已持久化
        self._verify_proxy_persisted()
        self._check_proxies()

    @staticmethod
    def _verify_proxy_persisted():
        """验证代理配置已正确写入文件"""
        try:
            import json

            cfg_path = project_path("data", "network_config.json")
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                count = len(saved.get("proxies", []))
                logger.info("代理配置持久化验证: %s — %d 条代理已保存", cfg_path, count)
        except Exception as e:
            logger.warning("代理配置持久化验证失败: %s", e)

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

        get_bilibili_api().clear_proxies()
        for ps in remaining:
            get_bilibili_api().add_proxy({"http": ps, "https": ps})

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
        for cookie in get_bilibili_api().session.cookies:
            if "bilibili.com" in (cookie.domain or ""):
                cookies[cookie.name] = cookie.value
        if not cookies:
            cookies = self._net_cfg.get("cookies", {})
        if cookies:
            show_raw = getattr(self, "_cookie_unlocked", False)
            self._cookie_unlock_btn.config(text="🔓 已解锁" if show_raw else "🔒 解锁查看")
            parts = []
            for k, v in cookies.items():
                if show_raw:
                    parts.append(f"{k}={v}")
                else:
                    masked = v[:4] + "****" + v[-4:] if len(v) > 8 else "********"
                    parts.append(f"{k}={masked}")
            self.cookie_text.insert("1.0", "; ".join(parts))

    def _toggle_cookie_unlock(self):
        self._cookie_unlocked = not getattr(self, "_cookie_unlocked", False)
        self._refresh_cookie_display()

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
        get_bilibili_api().set_cookies(cookies)
        self._net_cfg["cookies"] = cookies
        self._net_cfg["refresh_token"] = get_bilibili_api().get_refresh_token()
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
            status = get_bilibili_api().get_status()
            is_login = status.get("is_login", False)
            login_name = status.get("login_name", "")
            if hasattr(self, "gui") and self.gui and hasattr(self.gui, "log_panel"):
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
                get_bilibili_api().session.cookies.set(name, "", domain=".bilibili.com")
            get_bilibili_api()._cookies = {}
            get_bilibili_api()._refresh_token = ""
            self._net_cfg["cookies"] = {}
            self._net_cfg["refresh_token"] = ""
            self._save_net_config()
            self._refresh_cookie_display()
            self._refresh_status()
            messagebox.showinfo("成功", "Cookie 已清空", parent=self.window)

    # ──── Cookie: Cookie-Editor 导入 ────
    def _import_cookie_editor(self):
        top = tk.Toplevel(self.window)
        top.title("导入 Cookie-Editor JSON")
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        top.geometry(f"{int(sw * 0.36)}x{int(sh * 0.42)}")
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
            get_bilibili_api().set_cookies(cookies)
            self._net_cfg["cookies"] = cookies
            self._net_cfg["refresh_token"] = get_bilibili_api().get_refresh_token()
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
        qr_data = get_bilibili_api().get_qrcode_login_url()
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
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        qr_top.geometry(f"{int(sw * 0.28)}x{int(sh * 0.45)}")
        qr_top.configure(bg=C["bg_surface"])
        qr_top.transient(self.window)
        qr_top.grab_set()
        qr_top.resizable(True, True)

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
            result = get_bilibili_api().poll_qrcode_login(qrcode_key)
            status_var.set(result.get("message", ""))
            if result.get("status") == 2:
                cookies = result.get("cookies", {})
                if cookies:
                    self._net_cfg["cookies"] = cookies
                    self._net_cfg["refresh_token"] = get_bilibili_api().get_refresh_token()
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
        get_bilibili_api().max_retries = int(self.retry_count_var.get())
        get_bilibili_api().base_retry_delay = self.base_delay_var.get()
        get_bilibili_api()._min_request_interval = self.min_interval_var.get()
        messagebox.showinfo("成功", "重试设置已更新", parent=self.window)

    # ──── 状态 ────
    def _refresh_status(self):
        status = get_bilibili_api().get_status()
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
            get_bilibili_api().reset_status()
            self._refresh_status()

    # ──── Cookie: 密码登录 ────
    def _password_login(self):  # noqa: C901
        pwd_top = tk.Toplevel(self.window)
        pwd_top.title("密码登录 B站")
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        pwd_top.geometry(f"{int(sw * 0.28)}x{int(sh * 0.36)}")
        pwd_top.configure(bg=C["bg_surface"])
        pwd_top.transient(self.window)
        pwd_top.grab_set()
        pwd_top.resizable(False, False)

        tk.Label(
            pwd_top,
            text="B站 账号密码登录",
            bg=C["bg_surface"],
            fg=C["text_1"],
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(pady=(18, 4))
        tk.Label(
            pwd_top,
            text="部分账号需要手机验证码，建议使用扫码登录",
            bg=C["bg_surface"],
            fg=C["text_3"],
            font=FONT_SM,
        ).pack()

        form = tk.Frame(pwd_top, bg=C["bg_surface"])
        form.pack(pady=(12, 0))

        tk.Label(form, text="账号:", bg=C["bg_surface"], fg=C["text_2"], font=FONT).grid(row=0, column=0, sticky="w")
        username_entry = ttk.Entry(form, width=28, font=FONT)
        username_entry.grid(row=0, column=1, padx=(8, 0), pady=4)

        tk.Label(form, text="密码:", bg=C["bg_surface"], fg=C["text_2"], font=FONT).grid(row=1, column=0, sticky="w")
        password_entry = ttk.Entry(form, width=28, font=FONT, show="*")
        password_entry.grid(row=1, column=1, padx=(8, 0), pady=4)

        # 验证码区域（初始隐藏）
        captcha_frame = tk.Frame(pwd_top, bg=C["bg_surface"])
        captcha_row = tk.Frame(captcha_frame, bg=C["bg_surface"])
        captcha_row.pack()
        tk.Label(captcha_row, text="验证码:", bg=C["bg_surface"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)
        captcha_entry = ttk.Entry(captcha_row, width=14, font=FONT)
        captcha_entry.pack(side=tk.LEFT, padx=(8, 0))
        captcha_type_var = tk.IntVar(value=0)

        status_var = tk.StringVar(value="")
        status_lbl = tk.Label(
            pwd_top, textvariable=status_var, bg=C["bg_surface"], fg=C["text_2"], font=FONT_SM, wraplength=300
        )
        status_lbl.pack(pady=(8, 0))

        # 按钮区域
        btn_f = tk.Frame(pwd_top, bg=C["bg_surface"])
        btn_f.pack(pady=(6, 0))
        login_btn = ttk.Button(btn_f, text="登录", style="Primary.TButton")
        login_btn.pack(side=tk.LEFT, padx=4)

        captcha_btn_f = tk.Frame(pwd_top, bg=C["bg_surface"])
        submit_captcha_btn = ttk.Button(captcha_btn_f, text="提交验证码", style="Primary.TButton")

        cancel_btn = ttk.Button(btn_f, text="取消", command=pwd_top.destroy)
        cancel_btn.pack(side=tk.LEFT, padx=4)

        def _do_login(captcha_code: str = "", ct: int = 0):
            uname = username_entry.get().strip()
            pwd = password_entry.get()
            if not uname or not pwd:
                messagebox.showwarning("提示", "请输入账号和密码", parent=pwd_top)
                return
            for w in (username_entry, password_entry, captcha_entry):
                w.config(state="disabled")
            login_btn.config(state="disabled")
            status_var.set("登录中..." if not captcha_code else "验证中...")
            status_lbl.config(fg=C["text_2"])
            pwd_top.update()

            def _worker():
                try:
                    result = get_bilibili_api().login_with_password(uname, pwd, captcha=captcha_code, captcha_type=ct)
                    pwd_top.after(0, lambda: _handle_result(result))
                except Exception as e:
                    pwd_top.after(0, lambda e=e: status_var.set(f"异常: {e}"))

            import threading

            threading.Thread(target=_worker, daemon=True).start()

        def _handle_result(result):
            code = result.get("code", -1)
            if code == 0:
                cookies = result.get("cookies", {})
                self._net_cfg["cookies"] = cookies
                self._net_cfg["refresh_token"] = result.get("refresh_token", "")
                self._save_net_config()
                self._refresh_cookie_display()
                self._refresh_status()
                status_var.set("登录成功！")
                status_lbl.config(fg=C["success"])
                pwd_top.after(800, pwd_top.destroy)
                self.window.after(1000, self._verify_login)
                messagebox.showinfo(
                    "登录成功",
                    f"已获取 Cookie: {', '.join(cookies.keys())}",
                    parent=self.window,
                )
            elif result.get("need_captcha") and not captcha_entry.get().strip():
                ct = result.get("captcha_type", 0)
                captcha_type_var.set(ct)
                if ct == 6:
                    phone = result.get("captcha_phone", "")
                    hint = f"验证码已发送至 {phone}" if phone else "请输入手机收到的验证码"
                    status_var.set(hint)
                    status_lbl.config(fg=C["warning"])
                    captcha_frame.pack(pady=(6, 0))
                    captcha_entry.config(state="normal")
                    captcha_entry.focus_set()
                    captcha_btn_f.pack(pady=(2, 0))
                    submit_captcha_btn.pack(side=tk.LEFT, padx=4)
                    login_btn.pack_forget()
                    cancel_btn.pack_forget()
                    ttk.Button(captcha_btn_f, text="取消", command=pwd_top.destroy).pack(side=tk.LEFT, padx=4)
                else:
                    status_var.set("需要滑块验证，请使用扫码登录")
                    status_lbl.config(fg=C["danger"])
                for w in (username_entry, password_entry):
                    w.config(state="normal")
                login_btn.config(state="normal")
            else:
                msg = result.get("message", "未知错误")
                if code == -1057:
                    msg += "，请检查账号密码"
                status_var.set(msg)
                status_lbl.config(fg=C["danger"])
                for w in (username_entry, password_entry, captcha_entry):
                    w.config(state="normal")
                login_btn.config(state="normal")

        def _submit_captcha():
            code = captcha_entry.get().strip()
            if not code:
                messagebox.showwarning("提示", "请输入验证码", parent=pwd_top)
                return
            _do_login(captcha_code=code, ct=captcha_type_var.get())

        login_btn.config(command=lambda: _do_login())
        submit_captcha_btn.config(command=_submit_captcha)

        # 回车触发
        for w in (username_entry, password_entry):
            w.bind("<Return>", lambda e: _do_login())
        captcha_entry.bind("<Return>", lambda e: _submit_captcha())
        ttk.Button(btn_f, text="取消", command=pwd_top.destroy).pack(side=tk.LEFT, padx=4)

        # 验证码提交按钮（初始隐藏，随 captcha_frame 一起显示）
        captcha_btn_f = tk.Frame(pwd_top, bg=C["bg_surface"])
        captcha_submit_btn = ttk.Button(
            captcha_btn_f, text="提交验证码", command=_submit_captcha, style="Primary.TButton"
        )
        captcha_submit_btn.pack()

        # 挂钩 captcha 回车
        captcha_entry.bind("<Return>", lambda e: _submit_captcha())

        # 主登录回车
        for w in (username_entry, password_entry):
            w.bind("<Return>", lambda e: _do_login())

        # 在 _handle_result 的 need_captcha 分支中也 pack captcha_btn_f
        # 将 captcha_btn_f 放在 status_lbl 下方
        captcha_btn_f.pack(pady=(4, 0))
        captcha_btn_f.pack_forget()  # 初始隐藏

    # ──── 代理文本同步 ────
    def _sync_proxy_text_to_cfg(self):
        """将代理文本框的内容同步到 _net_cfg"""
        text = self.proxy_text.get("1.0", "end").strip()
        self._net_cfg["proxies"] = [line.strip() for line in text.split("\n") if line.strip()]

    # ──── 自动保存 on close ────
    def _on_close(self):
        """关闭时自动保存代理文本到 network_config.json"""
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

        # 收集自定义阈值
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

        # 立即生效通知配置（无需重启）
        from core.notification import notification_manager

        notification_manager.configure(self._cfg)

        # 立即生效阈值变更（无需重启）
        try:
            from ui.helpers import reload_thresholds

            reload_thresholds()
        except Exception:
            pass

        # 同步代理文本到 net_cfg 后再保存（防止跳过"应用代理"直接点保存导致空覆盖）
        self._sync_proxy_text_to_cfg()
        self._save_net_config()
        self._verify_proxy_persisted()

        messagebox.showinfo("成功", "设置已保存", parent=self.window)
        self.window.destroy()
