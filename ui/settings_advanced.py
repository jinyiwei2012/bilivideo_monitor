"""
高级设置模块（AI 配置 + 权重设置 + 模型训练 + 关于作者）

Mixin 函数模块，为 SettingsWindow 提供高级功能标签页:
  - AI 配置: LLM 多配置文件管理（保存/切换/删除/测试连接），支持快速填入 DeepSeek/OpenAI/Claude/SiliconFlow
  - 权重设置: 算法权重可视化表格，支持勾选自定义权重、输入数值、批量重置/保存
  - 模型训练: PyTorch 算法训练配置（设备检测、数据规模估算、算法勾选、版本管理、导入导出）
  - 关于作者: 项目信息、版本号、相关链接（GitHub/B站主页）、项目介绍

所有函数以 self 为第一个参数（SettingsWindow 实例）。
"""

import os
import tkinter as tk
import logging
import webbrowser
from typing import Any, Dict, List, Optional
from tkinter import ttk, messagebox
from ui.theme import C
from ui.helpers import FONT, FONT_BOLD, FONT_SM, FONT_MONO, project_path
from algorithms.registry import AlgorithmRegistry
from algorithms.weight_manager import get_weight_manager
from utils.update_checker import _s, _hard, _train, _confirm_risky
from ui.scrollable_frame import ScrollableFrame

logger = logging.getLogger(__name__)


# ═══════════════ AI 配置 ═══════════════════════════════


def _build_ai_tab(self, nb):
    """构建 AI 配置标签页

    包含:
      - LLM 多配置文件管理（名称/API密钥/接口地址/模型名称）
      - 配置文件下拉选择器 + 切换/保存/删除/新增
      - 快速填入预设（DeepSeek/OpenAI/Claude/SiliconFlow）
      - API 连接测试按钮

    Args:
        self: SettingsWindow 实例
        nb: ttk.Notebook 对象
    """
    page = tk.Frame(nb, bg=C["bg_base"])
    nb.add(page, text="  AI配置  ")

    sec = self._section(page, "LLM 配置管理")
    ai_cfg = self._cfg.get("ai", {})

    # ── 配置文件选择行 ──
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

    # 兼容旧版 LLM 配置（单配置格式 → 多配置格式转换）
    profiles = ai_cfg.get("profiles", [])
    if not profiles:
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
    self._ai_profile_var.set(selected if selected in names else names[0])

    # ── 配置详情输入区 ──
    detail = tk.Frame(sec, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
    detail.pack(fill=tk.X, pady=4, ipadx=10, ipady=10)
    tk.Label(
        detail, text="配置详情", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 8, "bold")
    ).pack(anchor="w", pady=(0, 6))

    def _field_wrapper(parent, label):
        """创建标签+输入框的横向布局组件"""
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
    self._ai_key_entry.config(show="*")  # 密码掩码
    self._ai_endpoint_entry = _field_wrapper(detail, "接口地址")
    self._ai_model_entry = _field_wrapper(detail, "模型名称")

    # ── 操作按钮行 ──
    btn_row = tk.Frame(sec, bg=C["bg_elevated"])
    btn_row.pack(fill=tk.X, pady=(6, 0))
    ttk.Button(btn_row, text="💾 保存配置", command=lambda: self._save_ai_profile() if _confirm_risky("保存 AI 配置") else None).pack(side=tk.LEFT, padx=(0, 4))
    if _hard() == "normal":
        ttk.Button(btn_row, text="🗑 删除配置", command=self._delete_ai_profile).pack(side=tk.LEFT, padx=4)
    else:
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "settings.json")
        tk.Label(
            btn_row, text=f"📁 删除请编辑: data/settings.json", bg=C["bg_elevated"], fg=C["text_3"], font=FONT_SM
        ).pack(side=tk.LEFT, padx=4)
    ttk.Button(btn_row, text="+ 新增", command=self._new_ai_profile).pack(side=tk.LEFT, padx=4)

    # ── 快速填入预设 ──
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

    self._on_ai_profile_selected()


def _on_ai_profile_selected(self, event=None):
    """选中 AI 配置时，回填输入框

    Args:
        self: SettingsWindow 实例
        event: Tkinter 事件对象（可选）
    """
    name = self._ai_profile_var.get()
    for p in self._profiles:
        if p["name"] == name:
            self._clear_entry(self._ai_name_entry, p.get("name", ""))
            self._clear_entry(self._ai_key_entry, p.get("api_key", ""))
            self._clear_entry(self._ai_endpoint_entry, p.get("endpoint", ""))
            self._clear_entry(self._ai_model_entry, p.get("model", ""))
            break


def _save_ai_profile(self):
    """保存/更新 AI 配置

    如果配置名已存在则更新，否则作为新配置追加。
    """
    name = self._ai_name_entry.get().strip()
    if not name:
        messagebox.showwarning("提示", "配置名称不能为空", parent=self.window)
        return
    api_key = self._ai_key_entry.get().strip()
    endpoint = self._ai_endpoint_entry.get().strip() or "https://api.openai.com/v1/chat/completions"
    model = self._ai_model_entry.get().strip() or "gpt-4o-mini"

    # 查找并更新已有配置，或新增
    found = False
    for p in self._profiles:
        if p["name"] == name:
            p.update({"api_key": api_key, "endpoint": endpoint, "model": model})
            found = True
            break
    if not found:
        self._profiles.append({"name": name, "api_key": api_key, "endpoint": endpoint, "model": model})

    names = [p["name"] for p in self._profiles]
    self._ai_profile_cb["values"] = names
    self._ai_profile_var.set(name)
    self._ai_status_lbl.config(text=f"配置「{name}」已保存", fg=C["success"])


def _delete_ai_profile(self):
    """删除当前选中的 AI 配置（至少保留一个）"""
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
    """清空输入框以准备创建新配置"""
    self._clear_entry(self._ai_name_entry, "")
    self._clear_entry(self._ai_key_entry, "")
    self._clear_entry(self._ai_endpoint_entry, "https://api.openai.com/v1/chat/completions")
    self._clear_entry(self._ai_model_entry, "gpt-4o-mini")


def _test_ai_connection(self):
    """测试 AI API 连接（后台线程发送测试请求）

    自动识别 Claude API（通过 anthropic.com URL 判断）使用不同的认证头格式。
    """
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
                # Claude API 使用 x-api-key 头
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
                # OpenAI 兼容 API 使用 Bearer Token
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


# ═══════════════ 权重设置 ═══════════════════════════════


def _build_weights_tab(self, nb):
    """构建权重设置标签页

    展示所有算法的权重信息表格（算法名/自定义开关/权重值/ML权重/准确率/样本数），
    支持勾选自定义权重、输入数值、批量重置、保存。

    Args:
        self: SettingsWindow 实例
        nb: ttk.Notebook 对象
    """
    page = tk.Frame(nb, bg=C["bg_base"])
    nb.add(page, text="  权重设置  ")

    # ── 说明信息 ──
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

    # ── 表头 ──
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

    # ── 可滚动算法列表 ──
    canvas_frame = tk.Frame(page, bg=C["bg_base"])
    canvas_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))

    sf = ScrollableFrame(canvas_frame, bg=C["bg_elevated"])
    sf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    algo_frame = sf.inner

    self._weight_vars = {}       # {算法名: tk.DoubleVar} 权重值变量
    self._weight_check_vars = {} # {算法名: tk.BooleanVar} 是否启用自定义权重

    algo_info = AlgorithmRegistry.get_weights_info()
    for info in algo_info:
        row = tk.Frame(algo_frame, bg=C["bg_surface"], highlightthickness=1, highlightbackground=C["border_sub"])
        row.pack(fill=tk.X, pady=1)

        name = info["name"]
        # 算法名称
        tk.Label(row, text=name, bg=C["bg_surface"], fg=C["text_1"], font=FONT, width=24, anchor="w").grid(
            row=0, column=0, padx=4, pady=3, sticky="w"
        )

        # 自定义权重勾选框（取消勾选时恢复 ML 权重）
        var = tk.BooleanVar(value=info["is_customized"])
        self._weight_check_vars[name] = var
        ttk.Checkbutton(
            row,
            variable=var,
            command=lambda n=name: self._weight_vars[n].set(get_weight_manager().ml_weights.get(n, 1.0)),
        ).grid(row=0, column=1, padx=2)

        # 权重值输入框
        wv = tk.DoubleVar(value=info.get("user_weight") or info.get("final_weight", 1.0))
        self._weight_vars[name] = wv
        _entry = ttk.Entry(row, textvariable=wv, width=10)
        _entry.grid(row=0, column=2, padx=4)
        # 开发模式保护：非正常模式需要确认后才能编辑
        if _s() != "normal":
            _entry.configure(state="readonly")
            _entry.bind("<Button-1>", lambda e, ent=_entry, p=self.window: (
                None if not _confirm_risky("修改算法权重", p) else (ent.configure(state="normal") or ent.focus_set())
            ))

        # ML 权重（只读）
        ml_w = info.get("ml_weight", 1.0)
        tk.Label(
            row, text=f"{ml_w:.2f}", bg=C["bg_surface"], fg=C["text_3"], font=FONT_MONO, width=12, anchor="w"
        ).grid(row=0, column=3)

        # 准确率（百分比）
        acc = info.get("accuracy", 0)
        tk.Label(
            row, text=f"{acc * 100:.1f}%", bg=C["bg_surface"], fg=C["success"], font=FONT_MONO, width=10, anchor="w"
        ).grid(row=0, column=4)

        # 训练样本数
        samples = info.get("samples", 0)
        tk.Label(
            row, text=str(samples), bg=C["bg_surface"], fg=C["text_2"], font=FONT_MONO, width=8, anchor="w"
        ).grid(row=0, column=5)

    # ── 底部操作按钮 ──
    btn_row = tk.Frame(page, bg=C["bg_base"])
    btn_row.pack(fill=tk.X, padx=16, pady=(0, 12))
    ttk.Button(btn_row, text="重置所有权重", command=lambda: self._reset_all_weights() if _confirm_risky("重置算法权重") else None).pack(side=tk.LEFT, padx=(0, 4))
    ttk.Button(btn_row, text="刷新", command=self._refresh_weights).pack(side=tk.LEFT, padx=4)
    ttk.Button(btn_row, text="💾 保存权重", command=lambda: _confirm_risky("保存算法权重") and self._save_weights(), style="Primary.TButton").pack(side=tk.RIGHT)


def _reset_all_weights(self):
    """重置所有自定义权重为 ML 默认值"""
    if messagebox.askyesno("确认", "确定要重置所有自定义权重吗？", parent=self.window):
        get_weight_manager().reset_weights()
        self._refresh_weights()
        messagebox.showinfo("成功", "已重置所有权重", parent=self.window)


def _refresh_weights(self):
    """刷新权重表格中的所有值（从 WeightManager 重新加载）"""
    algo_info = AlgorithmRegistry.get_weights_info()
    for info in algo_info:
        name = info["name"]
        if name in self._weight_vars:
            self._weight_vars[name].set(info.get("user_weight") or info.get("final_weight", 1.0))
            self._weight_check_vars[name].set(info["is_customized"])


def _save_weights(self):
    """保存所有算法权重设置到 WeightManager"""
    for name, check_var in self._weight_check_vars.items():
        wv = self._weight_vars[name]
        try:
            weight = float(wv.get())
            weight = max(0.01, min(10.0, weight))  # 限制范围 [0.01, 10.0]
            if check_var.get():
                get_weight_manager().set_user_weight(name, weight)
            else:
                get_weight_manager().clear_user_weight(name)
        except ValueError:
            messagebox.showerror("错误", f"算法 {name} 的权重值无效", parent=self.window)
            return
    messagebox.showinfo("成功", "权重设置已保存", parent=self.window)


# ═══════════════ 模型训练 ═══════════════════════════════


def _build_training_tab(self, nb):
    """构建模型训练标签页

    包含:
      - 训练设备检测（GPU/CPU），强制使用 CPU 选项
      - 数据规模估算（视频数/有效视频/样本数/预计训练时间）
      - 可训练算法列表（勾选/版本管理/状态显示）
      - 训练参数设置（epoch/batch）
      - 训练控制（开始/取消/进度条）
      - 模型导入/导出

    Args:
        self: SettingsWindow 实例
        nb: ttk.Notebook 对象
    """
    page = tk.Frame(nb, bg=C["bg_base"])
    nb.add(page, text="  模型训练  ")

    # ── 训练设备 ──
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

    # ── 可训练算法列表 ──
    list_sec = self._section(page, "可训练算法（PyTorch）", padding=(16, 6, 6))

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

    # 选择工具条
    toolbar = tk.Frame(list_sec, bg=C["bg_elevated"])
    toolbar.pack(fill=tk.X, pady=(0, 4))
    ttk.Button(toolbar, text="全选", command=lambda: self._tr_select_all(True)).pack(side=tk.LEFT, padx=(0, 4))
    ttk.Button(toolbar, text="全不选", command=lambda: self._tr_select_all(False)).pack(side=tk.LEFT, padx=4)
    ttk.Button(toolbar, text="仅选未训练", command=self._tr_select_untrained).pack(side=tk.LEFT, padx=4)
    self._tr_count_lbl = tk.Label(toolbar, text="", bg=C["bg_elevated"], fg=C["text_3"], font=FONT_SM)
    self._tr_count_lbl.pack(side=tk.RIGHT)

    canvas_frame = tk.Frame(list_sec, bg=C["bg_base"])
    canvas_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
    sf = ScrollableFrame(canvas_frame, bg=C["bg_elevated"], height=200)
    sf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    self._tr_algo_frame = sf.inner

    self._tr_check_vars: Dict[str, tk.BooleanVar] = {}  # {算法ID: 勾选变量}
    self._tr_algo_meta: Dict[str, Dict[str, Any]] = {}  # {算法ID: 元数据字典}

    # ── 训练控制 ──
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
        btn_row, text="▶ 训练所有勾选", command=self._on_train_start, style="Primary.TButton", state=_train()
    )
    self._tr_train_btn.pack(side=tk.LEFT, padx=(0, 6))
    self._tr_cancel_btn = ttk.Button(btn_row, text="✕ 取消", command=self._on_train_cancel, state="disabled")
    self._tr_cancel_btn.pack(side=tk.LEFT)

    ttk.Button(btn_row, text="📤 导出模型", command=self._on_export_checkpoints).pack(side=tk.RIGHT, padx=(4, 0))
    ttk.Button(btn_row, text="📥 导入模型", command=self._on_import_checkpoints, state=_train()).pack(side=tk.RIGHT, padx=(4, 0))

    # 开发模式提示
    if _train() != "normal":
        tk.Label(
            btn_row, text="💡 创建 .enabletraining 文件开启训练 / 完整 devmode 见 README.md",
            bg=C["bg_elevated"], fg=C["warning"], font=("", 8),
        ).pack(side=tk.LEFT, padx=4)

    self._tr_progress = ttk.Progressbar(ctrl_sec, mode="determinate", maximum=100)
    self._tr_progress.pack(fill=tk.X, pady=(4, 2))
    self._tr_status_lbl = tk.Label(
        ctrl_sec, text="就绪", bg=C["bg_elevated"], fg=C["text_3"], font=FONT_SM, anchor="w"
    )
    self._tr_status_lbl.pack(fill=tk.X, padx=4, pady=(2, 2))

    # 训练状态变量
    self._tr_thread = None
    self._tr_queue = None
    self._tr_cancel_flag = [False]
    self._tr_t0 = None

    self._refresh_device_info()
    self._refresh_data_size()
    self._refresh_algo_list()


# —— Training tab helpers ——


def _discover_torch_algorithms(self) -> List[Dict[str, Any]]:
    """获取可训练算法列表（从 AlgorithmRegistry）

    Returns:
        list: 可训练算法信息列表
    """
    from algorithms.registry import AlgorithmRegistry
    return AlgorithmRegistry.get_trainable_info()


def _refresh_device_info(self):
    """检测并显示当前训练设备（GPU/CPU）"""
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
    """强制 CPU 开关变更时重新检测设备"""
    self._refresh_device_info()


def _refresh_data_size(self):
    """后台线程估算数据规模（视频数/有效视频/样本数/预计训练时间）"""
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
    """刷新可训练算法列表 UI"""
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

        # 默认勾选未训练的算法
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

        # 状态显示：已训练（含版本信息）或未训练
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
    """全选/取消全选所有可训练算法

    Args:
        flag: True=全选, False=全不选
    """
    for var in self._tr_check_vars.values():
        var.set(flag)


def _tr_select_untrained(self):
    """仅勾选尚未训练过的算法"""
    for aid, var in self._tr_check_vars.items():
        var.set(not self._tr_algo_meta.get(aid, {}).get("has_ckpt", False))


def _on_train_start(self):
    """开始训练：验证环境 + 确认参数 + 启动后台训练线程"""
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

    # 禁用开始按钮，启用取消按钮
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
        """训练进度回调：将进度信息放入队列，由主线程轮询处理"""
        payload = dict(payload)
        payload["_total_selected"] = len(selected)
        self._tr_queue.put(payload)

    def _worker():
        """后台训练线程"""
        try:
            from algorithms.training.trainer import ModelTrainer

            trainer = ModelTrainer()
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
    """取消训练：设置取消标记，当前正在训练的算法会继续完成"""
    self._tr_cancel_flag[0] = True
    self._tr_cancel_btn.config(state="disabled")
    self._tr_status_lbl.config(text="正在取消（等待当前算法完成）…", fg=C["warning"])


def _on_export_checkpoints(self):
    """导出所有 checkpoint 为 ZIP 文件"""
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
    """从 ZIP 文件导入 checkpoint"""
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
    """主线程轮询训练进度队列，更新进度条和状态文字

    每 200ms 轮询一次，处理队列中的消息:
      - start: 开始训练某个算法
      - epoch: epoch 进度更新（train_loss/val_loss）
      - done: 单个算法训练完成
      - error: 单个算法训练失败
      - cancelled: 用户取消了训练
      - all_done: 全部训练完成
      - fatal: 训练进程异常
    """
    import queue as _q
    import time as _t

    if self._tr_queue is None:
        return

    done_all = False
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


def _open_version_manager(self, algo_id: str):
    """打开版本管理窗口（激活/删除/导出 checkpoint 版本）

    Args:
        algo_id: 算法标识符
    """
    from algorithms.training.checkpoint_manager import CheckpointManager

    ckpt = CheckpointManager(algo_id)
    top, tree = _draw_version_ui(self, algo_id, ckpt)

    _bind_version_events(self, top, tree, ckpt, algo_id)


def _draw_version_ui(self, algo_id: str, ckpt):
    """构建版本管理窗口和版本列表 Treeview

    Args:
        algo_id: 算法 ID
        ckpt: CheckpointManager 实例

    Returns:
        tuple: (top_window, treeview)
    """
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

    _refresh_version_detail(tree, ckpt)
    return top, tree


def _refresh_version_detail(tree, ckpt) -> None:
    """清空并重新加载 Treeview 中的所有版本列表"""
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


def _bind_version_events(self, top, tree, ckpt, algo_id):
    """绑定版本管理窗口的按钮命令（激活/删除/导出/关闭）

    Args:
        top: 版本管理窗口
        tree: 版本列表 Treeview
        ckpt: CheckpointManager 实例
        algo_id: 算法 ID
    """

    def _reload():
        _refresh_version_detail(tree, ckpt)

    def _selected_version() -> Optional[str]:
        """获取当前选中的版本名称"""
        sel = tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一个版本", parent=top)
            return None
        return tree.item(sel[0], "values")[1]

    def _do_activate():
        """激活选中的版本"""
        v = _selected_version()
        if v and ckpt.activate(v):
            _reload()
            self._refresh_algo_list()

    def _do_delete():
        """删除选中的版本（带确认）"""
        v = _selected_version()
        if not v:
            return
        if not messagebox.askyesno("确认删除", f"确定删除版本 {v} 吗？", parent=top):
            return
        if ckpt.delete(v):
            _reload()
            self._refresh_algo_list()

    def _do_export():
        """导出选中的 checkpoint 为 .pt 文件"""
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
    if _hard() == "normal":
        ttk.Button(btn_f, text="删除", command=_do_delete).pack(side=tk.LEFT, padx=2)
    else:
        ckpt_dir = project_path("algorithms", "checkpoints", algo_id)
        tk.Label(
            btn_f, text=f"📁 删除请到: {os.path.relpath(ckpt_dir)}", bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM
        ).pack(side=tk.LEFT, padx=4)
    ttk.Button(btn_f, text="导出 .pt", command=_do_export).pack(side=tk.LEFT, padx=2)
    ttk.Button(btn_f, text="关闭", command=top.destroy).pack(side=tk.RIGHT, padx=2)


# ═══════════════ 关于作者 ═══════════════════════════════


def _build_about_tab(self, nb):
    """构建"关于作者"标签页

    展示:
      - 项目信息（名称/版本/作者）
      - 相关链接（GitHub / B站主页）
      - 项目介绍文字

    Args:
        self: SettingsWindow 实例
        nb: ttk.Notebook 对象
    """
    page = tk.Frame(nb, bg=C["bg_base"])
    nb.add(page, text="  关于作者  ")

    from __init__ import __version__, __author__

    # ── 项目信息 ──
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

    # ── 相关链接 ──
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
        # 可点击的链接标签（粉色，悬浮变色）
        link_lbl = tk.Label(
            f, text=url, bg=C["bg_elevated"], fg=C["bilibili"], font=FONT, cursor="hand2", anchor="w"
        )
        link_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        link_lbl.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
        link_lbl.bind("<Enter>", lambda e: e.widget.config(fg=C.get("accent", "#00a1d6")))
        link_lbl.bind("<Leave>", lambda e: e.widget.config(fg=C["bilibili"]))

    # ── 项目介绍 ──
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
