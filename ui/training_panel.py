"""
训练面板模块 — 主界面集成版
============================

提供 ``TrainingPanel`` 类，嵌入到主界面 Tab 中，支持深度学习模型的增量训练和重新训练。

功能：
  - 算法列表（左侧）：复选框选择、显示状态/置信度/版本、全选/仅未训练
  - Loss 图表 + 日志（右侧）：实时训练/验证 Loss 曲线，文字日志
  - 训练质量监控栏：自动检测 NaN/过拟合/震荡等问题
  - 底部控制栏：Epoch/Batch/LR/模式选择、开始/取消/跳过按钮
  - 版本管理对话框：查看/删除/激活 checkpoint，视频微调版本管理
  - 批量微调：选择多个视频 + 多个算法一键微调
  - 训练日志存盘：自动保存训练日志到 data/log/training/
  - 自动 LR 调整：根据数据规模和学习率自动控制机制动态推荐学习率

继承自 ``BaseTrainingPanel``（``ui.training_base``）。
"""

import tkinter as tk
from tkinter import ttk, messagebox
import io
import logging
import os
import threading
import time
from typing import Dict, List, Optional
from datetime import datetime
from ui.theme import C
from ui.helpers import (
    FONT,
    FONT_SM,
    FONT_MONO,
    FONT_BOLD,
    loss_to_confidence,
    format_confidence,
    load_algo_confidence,
    project_path,
)
from ui.scrollable_frame import ScrollableFrame
from ui.training_base import BaseTrainingPanel, TrainingMonitor
from utils.update_checker import _hard, _train, _confirm_risky

logger = logging.getLogger(__name__)

# 检测 PyTorch 是否可用
_torch_available = True
try:
    import torch  # noqa: F401
except ImportError:
    _torch_available = False


class TrainingPanel(BaseTrainingPanel):
    """
    训练面板 — 主界面选项卡，支持模型增量训练/重新训练。

    UI 布局：
      ┌─────────────────────────────────────────────────────┐
      │ 设备信息 / 数据规模 / 强制CPU                        │
      ├────────────────┬────────────────────────────────────┤
      │ 算法列表(左侧)  │  Loss 图表                         │
      │ [复选框+状态]   │  ──────────────────────────────── │
      │                │  训练质量监控栏                      │
      │                │  ──────────────────────────────── │
      │                │  训练日志                           │
      ├────────────────┴────────────────────────────────────┤
      │ Epoch/Batch/LR/模式  │  ▶开始 ✕取消 ⏭跳过 🎯批量微调 │
      └─────────────────────────────────────────────────────┘

    训练流程：
      1. 用户选择算法、设置参数
      2. 点击"开始训练" → 确认对话框
      3. 后台线程依次训练每个算法
      4. 训练进程通过 Queue 向前端发送进度消息
      5. _poll_progress 轮询队列 → 分发到对应 stage 处理器
      6. 完成后自动刷新算法列表 + 通知
    """

    def __init__(self, parent: tk.Widget, main_gui):
        """
        初始化训练面板。

        :param parent: 父容器 Widget
        :param main_gui: 主界面实例（用于访问 monitored_videos 等）
        """
        super().__init__(parent, main_gui)

        # ── 算法列表状态 ──
        self._check_vars: Dict[str, tk.BooleanVar] = {}    # aid → 复选框变量
        self._algo_meta: Dict[str, Dict] = {}              # aid → 算法元信息
        self._algo_confidence: Dict[str, float] = {}        # 训练完成时记录的置信度
        self._algo_row_refs: Dict[str, List[tk.Widget]] = {}  # aid → [状态标签, 置信度标签, 版本标签]

        # ── 日志存盘 ──
        self._log_dir = project_path("data", "log", "training")
        self._log_file: Optional[io.TextIOWrapper] = None
        self._log_file_path: str = ""

        self._build_ui()

    # ══════════════════════════════════════════════
    # UI 构建
    # ══════════════════════════════════════════════

    def _build_ui(self):
        """
        构建训练面板的完整 UI 布局：
          顶部信息栏 → 主体(算法列表|图表+日志) → 底部控制栏
        """
        outer = self.frame

        # ── 顶部信息栏：设备信息、数据规模、强制 CPU 开关 ──
        info_bar = tk.Frame(outer, bg=C["bg_elevated"])
        info_bar.pack(fill=tk.X, padx=8, pady=(8, 4))

        tk.Label(info_bar, text="训练设备:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(
            side=tk.LEFT, padx=(8, 2)
        )
        self._device_lbl = tk.Label(info_bar, text="检测中…", bg=C["bg_elevated"], fg=C["text_1"], font=FONT)
        self._device_lbl.pack(side=tk.LEFT, padx=(0, 16))
        tk.Label(info_bar, text="数据规模:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(
            side=tk.LEFT, padx=(8, 2)
        )
        self._data_lbl = tk.Label(info_bar, text="估算中…", bg=C["bg_elevated"], fg=C["text_3"], font=FONT_SM)
        self._data_lbl.pack(side=tk.LEFT, padx=(0, 16))
        self._force_cpu_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(info_bar, text="强制 CPU", variable=self._force_cpu_var, command=self._on_force_cpu).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(info_bar, text="刷新", command=self._refresh_all).pack(side=tk.RIGHT, padx=8)

        # ── 主体区域: 左(算法列表) | 右(图表+日志) ──
        body = tk.Frame(outer, bg=C["bg_base"])
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        body.grid_columnconfigure(0, weight=35, minsize=280)  # 左侧 35% 宽度
        body.grid_columnconfigure(1, weight=65, minsize=400)  # 右侧 65% 宽度
        body.grid_rowconfigure(0, weight=1)

        self._build_algo_section(body)
        self._build_chart_section(body)

        # ── 底部控制栏 ──
        self._build_controls(outer)

    # ── 算法列表 (左侧) ──

    def _build_algo_section(self, parent):
        """
        构建左侧算法列表区域：
          标题 + 计数 → 工具栏(全选/全不选/仅未训练/版本管理) → 算法行列表(表头+滚动)
        """
        left = tk.Frame(parent, bg=C["bg_surface"])
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_rowconfigure(1, weight=1)

        # 标题行
        hdr = tk.Frame(left, bg=C["bg_surface"])
        hdr.pack(fill=tk.X, padx=4, pady=(4, 0))
        tk.Label(hdr, text="可训练算法（PyTorch）", bg=C["bg_surface"], fg=C["text_1"], font=FONT_BOLD).pack(
            side=tk.LEFT
        )
        self._algo_count_lbl = tk.Label(hdr, text="", bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM)
        self._algo_count_lbl.pack(side=tk.RIGHT, padx=4)

        # 工具栏
        toolbar = tk.Frame(left, bg=C["bg_elevated"])
        toolbar.pack(fill=tk.X, padx=4, pady=(2, 2))
        ttk.Button(toolbar, text="全选", command=lambda: self._select_all(True), width=6).pack(side=tk.LEFT, padx=1)
        ttk.Button(toolbar, text="全不选", command=lambda: self._select_all(False), width=6).pack(side=tk.LEFT, padx=1)
        ttk.Button(toolbar, text="仅未训练", command=self._select_untrained, width=8).pack(side=tk.LEFT, padx=1)
        ttk.Button(toolbar, text="🗑️ 版本管理", command=self._on_manage_versions, width=10).pack(side=tk.LEFT, padx=1)

        # 滚动容器
        sf = ScrollableFrame(left, bg=C["bg_elevated"], height=300)
        sf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._algo_frame = sf.inner

        # 表头：复选框(空) | 算法 | ID | 状态 | 置信度 | 版本
        hdr_row = tk.Frame(self._algo_frame, bg=C["bg_surface"])
        hdr_row.pack(fill=tk.X, pady=(0, 1))
        for col, (txt, w) in enumerate([("", 4), ("算法", 16), ("ID", 14), ("状态", 12), ("置信度", 10), ("版本", 8)]):
            tk.Label(
                hdr_row,
                text=txt,
                bg=C["bg_surface"],
                fg=C["text_3"],
                font=("Microsoft YaHei UI", 8, "bold"),
                width=w,
                anchor="w",
            ).grid(row=0, column=col, padx=2, pady=2, sticky="w")

    # ── 图表+日志 (右侧) ──

    def _build_chart_section(self, parent):
        """
        构建右侧图表和日志区域（上下 1:1 分割）：
          上半：Loss 图表
          中部：训练质量监控栏
          下半：日志文本框
        """
        right = tk.Frame(parent, bg=C["bg_surface"])
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        right.grid_rowconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)

        # 上半: Loss 图表
        chart_frame = self._build_chart_widgets(right, title="训练 Loss 曲线")
        chart_frame.grid(row=0, column=0, sticky="nsew", padx=4, pady=(4, 2))

        # 中部: 训练质量监控状态栏
        monitor_bar = self._build_monitor_bar(right)
        monitor_bar.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 2))

        # 下半: 文字日志
        log_frame = self._build_log_widgets(right, title="训练日志")
        log_frame.grid(row=2, column=0, sticky="nsew", padx=4, pady=(2, 4))

    # ── 底部控制栏 ──

    def _build_controls(self, parent):
        """
        构建底部训练控制栏：
          - 训练参数：Epoch、Batch Size、Learning Rate（支持自动/手动）
          - 训练模式：增量训练 / 重新训练
          - 操作按钮：开始 / 取消 / 跳过 / 批量微调
          - 进度条 + 状态标签
        """
        ctrl = tk.Frame(parent, bg=C["bg_elevated"])
        ctrl.pack(fill=tk.X, padx=8, pady=(0, 6))

        # Epoch 设置
        tk.Label(ctrl, text="Epoch:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT, padx=(8, 2))
        self._epoch_var = tk.IntVar(value=20)
        ttk.Spinbox(ctrl, from_=1, to=500, textvariable=self._epoch_var, width=6).pack(side=tk.LEFT, padx=2)

        # Batch Size 设置
        tk.Label(ctrl, text="Batch:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT, padx=(8, 2))
        self._batch_var = tk.IntVar(value=32)
        ttk.Spinbox(ctrl, from_=1, to=512, textvariable=self._batch_var, width=6).pack(side=tk.LEFT, padx=2)

        # Learning Rate 设置（支持自动推荐）
        tk.Label(ctrl, text="LR:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT, padx=(8, 2))
        self._lr_var = tk.StringVar(value="0.001")
        self._lr_entry = ttk.Entry(ctrl, textvariable=self._lr_var, width=8, font=FONT_MONO)
        self._lr_entry.pack(side=tk.LEFT, padx=2)
        self._lr_auto_var = tk.BooleanVar(value=True)  # 默认启用自动学习率
        self._lr_auto_cb = ttk.Checkbutton(
            ctrl, text="自动", variable=self._lr_auto_var, command=self._on_lr_auto_toggle
        )
        self._lr_auto_cb.pack(side=tk.LEFT, padx=2)

        # 训练模式：增量训练 / 重新训练
        tk.Label(ctrl, text="模式:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT, padx=(8, 2))
        self._mode_var = tk.StringVar(value="incremental")
        ttk.Radiobutton(ctrl, text="增量训练", variable=self._mode_var, value="incremental").pack(side=tk.LEFT, padx=1)
        ttk.Radiobutton(ctrl, text="重新训练", variable=self._mode_var, value="retrain", state=_train()).pack(side=tk.LEFT, padx=1)

        # 操作按钮
        self._train_btn = ttk.Button(ctrl, text="▶ 开始训练", command=self._on_train_start, style="Primary.TButton", state=_train())
        self._train_btn.pack(side=tk.LEFT, padx=(12, 4))
        self._cancel_btn = ttk.Button(ctrl, text="✕ 取消", command=self._on_cancel, state="disabled")
        self._cancel_btn.pack(side=tk.LEFT, padx=4)
        self._skip_btn = ttk.Button(ctrl, text="⏭ 跳过当前", command=self._on_skip_algo, state="disabled")
        self._skip_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="🎯 批量微调", command=self._on_batch_finetune, width=10, state=_train()).pack(side=tk.LEFT, padx=4)

        # 开发模式提示（当训练功能受限时显示）
        if _train() != "normal":
            tk.Label(
                ctrl, text="💡 创建 .enabletraining 文件开启训练 / 完整 devmode 见 README.md",
                bg=C["bg_elevated"], fg=C["warning"], font=("", 8),
            ).pack(side=tk.LEFT, padx=8)

        # 进度条和状态标签
        self._progress = ttk.Progressbar(ctrl, mode="determinate", maximum=100)
        self._progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 4))

        self._status_lbl = tk.Label(
            ctrl, text="就绪", bg=C["bg_elevated"], fg=C["text_3"], font=FONT_SM, anchor="w", width=40
        )
        self._status_lbl.pack(side=tk.RIGHT, padx=(0, 8))

    # ══════════════════════════════════════════════
    # 数据刷新
    # ══════════════════════════════════════════════

    def on_show(self):
        """
        此面板被切换到前台时调用。
        刷新设备信息、数据规模和算法列表。
        """
        self._refresh_device()
        self._refresh_data_size()
        self._refresh_algo_list()

    def _refresh_all(self):
        """刷新所有数据：设备、数据规模、算法列表"""
        self._refresh_device()
        self._refresh_data_size()
        self._refresh_algo_list()

    def _refresh_device(self):
        """
        刷新训练设备信息显示。
        检测 CUDA/GPU 是否可用，显示显卡名称和显存。
        """
        try:
            from algorithms.training.device import get_device_info, is_torch_available, force_cpu

            force_cpu(self._force_cpu_var.get())
            info = get_device_info()
            if not is_torch_available():
                self._device_lbl.config(text="❌ torch 未安装", fg=C["danger"])
            elif info.get("is_gpu"):
                mem = info.get("total_memory_gb", 0)
                self._device_lbl.config(text=f"✅ {info['name']} ({mem:.1f} GB)", fg=C["success"])
            else:
                self._device_lbl.config(text=f"💻 {info['name']}", fg=C["warning"])
        except Exception as e:
            self._device_lbl.config(text=f"⚠ {e}", fg=C["danger"])

    def _on_force_cpu(self):
        """强制 CPU 切换时重新检测设备"""
        self._refresh_device()

    # ── 学习率控制 ────────────────────────────────

    def _on_lr_auto_toggle(self):
        """
        自动/手动学习率切换：
          自动时锁定输入框并填入根据数据规模推荐的 LR。
          手动时弹出安全确认，确认后解锁输入框。
        """
        if self._lr_auto_var.get():
            self._lr_entry.config(state="readonly")
            auto_lr = self._auto_compute_lr()
            self._lr_var.set(f"{auto_lr:.6f}")
        else:
            if _confirm_risky("切换到手动学习率模式", self.frame):
                self._lr_entry.config(state="normal")
            else:
                self._lr_auto_var.set(True)

    def _auto_compute_lr(self) -> float:
        """
        根据数据规模自动推荐学习率。
        估算训练样本数量，样本越多 → 学习率应越小（避免震荡）。

        :returns: 推荐的学习率值
        """
        try:
            from algorithms.training.trainer import ModelTrainer

            info = ModelTrainer().estimate_data_size()
            samples = info.get("total_samples", 1000)
        except Exception:
            samples = 1000

        if samples < 500:
            return 5e-3  # 小数据集：较大学习率快速收敛
        elif samples < 5000:
            return 2e-3  # 中等
        elif samples < 20000:
            return 1e-3  # 标准 Adam 默认值
        elif samples < 100000:
            return 5e-4  # 大数据集
        else:
            return 1e-4  # 超大数据集

    def _refresh_data_size(self):
        """
        刷新数据规模估算信息（异步线程）。
        显示视频数、有效数、样本数、单算法预估训练时间。
        """
        self._data_lbl.config(text="估算中…", fg=C["text_3"])

        def _worker():
            """后台线程：调用 ModelTrainer 估算"""
            try:
                from algorithms.training.trainer import ModelTrainer

                info = ModelTrainer().estimate_data_size()
                total = info.get("total_videos", 0)
                valid = info.get("valid_videos", 0)
                samples = info.get("total_samples", 0)
                eta = info.get("estimated_time_s", 0)
                txt = f"{total} 视频 · {valid} 有效 · {samples:,} 样本 · 约 {eta / 60:.1f} min/algo"
                self.frame.after(0, lambda: self._data_lbl.config(text=txt, fg=C["text_1"]))
            except Exception as e:
                self.frame.after(0, lambda e=e: self._data_lbl.config(text=f"⚠ {e}", fg=C["danger"]))

        threading.Thread(target=_worker, daemon=True).start()

    def _discover_algorithms(self) -> List[Dict]:
        """
        扫描所有实现了 build_model 的可训练算法。

        :returns: 算法信息列表 [{"algorithm_id": ..., "name": ..., "has_ckpt": ...}, ...]
        """
        from algorithms.registry import AlgorithmRegistry

        return AlgorithmRegistry.get_trainable_info()

    def _refresh_algo_list(self):
        """
        刷新算法列表 UI。
        清空旧行 → 读取可训练算法 → 每个算法一行（复选框、名称、ID、状态、置信度、版本）。
        未训练的算法默认勾选。
        """
        for w in self._algo_frame.winfo_children():
            w.destroy()
        self._check_vars.clear()
        self._algo_meta.clear()

        try:
            algos = self._discover_algorithms()
        except Exception as e:
            tk.Label(self._algo_frame, text=f"⚠ 加载失败: {e}", bg=C["bg_elevated"], fg=C["danger"], font=FONT).pack(
                padx=4, pady=8
            )
            return

        trained = sum(1 for a in algos if a["has_ckpt"])
        self._algo_count_lbl.config(text=f"{len(algos)} 算法 · 已训练 {trained}")

        self._algo_row_refs.clear()
        for a in algos:
            aid = a["algorithm_id"]
            self._algo_meta[aid] = a

            row = tk.Frame(
                self._algo_frame, bg=C["bg_surface"], highlightthickness=1, highlightbackground=C["border_sub"]
            )
            row.pack(fill=tk.X, pady=1)

            var = tk.BooleanVar(value=not a["has_ckpt"])  # 未训练的默认勾选
            self._check_vars[aid] = var
            ttk.Checkbutton(row, variable=var).grid(row=0, column=0, padx=4, pady=2)

            # 算法名称
            tk.Label(row, text=a["name"], bg=C["bg_surface"], fg=C["text_1"], font=FONT, width=16, anchor="w").grid(
                row=0, column=1, padx=2, sticky="w"
            )
            # 算法 ID
            tk.Label(row, text=aid, bg=C["bg_surface"], fg=C["text_3"], font=FONT_MONO, width=14, anchor="w").grid(
                row=0, column=2, padx=2, sticky="w"
            )

            # 状态：已训练显示版本号，未训练显示 □
            if a["has_ckpt"]:
                st = f"✅ {a['active_version'][:10]}"
                sf = C["success"]
            else:
                st = "□ 未训练"
                sf = C["text_3"]
            status_lbl = tk.Label(row, text=st, bg=C["bg_surface"], fg=sf, font=FONT_SM, width=12, anchor="w")
            status_lbl.grid(row=0, column=3, padx=2, sticky="w")

            # 置信度列
            conf = load_algo_confidence(aid)
            conf_text, conf_color = format_confidence(conf)
            conf_lbl = tk.Label(
                row, text=conf_text, bg=C["bg_surface"], fg=conf_color, font=FONT_SM, width=10, anchor="w"
            )
            conf_lbl.grid(row=0, column=4, padx=2, sticky="w")

            # 版本号
            ver_lbl = tk.Label(
                row,
                text=f"v{a['version_count']}",
                bg=C["bg_surface"],
                fg=C["text_3"],
                font=FONT_SM,
                width=6,
                anchor="w",
            )
            ver_lbl.grid(row=0, column=5, padx=2, sticky="w")

            self._algo_row_refs[aid] = [status_lbl, conf_lbl, ver_lbl]

    def _select_all(self, flag: bool):
        """全选或全不选所有算法"""
        for v in self._check_vars.values():
            v.set(flag)

    def _select_untrained(self):
        """仅选中尚未训练的算法（has_ckpt=False）"""
        for aid, var in self._check_vars.items():
            var.set(not self._algo_meta.get(aid, {}).get("has_ckpt", False))

    def _update_algo_row(
        self,
        aid: str,
        status: str = None,
        status_color: str = None,
        conf: str = None,
        conf_color: str = None,
        ver: str = None,
    ):
        """
        动态更新算法列表行的状态/置信度/版本列。

        :param aid: 算法 ID
        :param status: 状态文本（如 "▶ 训练中"）
        :param status_color: 状态文本颜色
        :param conf: 置信度文本
        :param conf_color: 置信度文本颜色
        :param ver: 版本号文本
        """
        refs = self._algo_row_refs.get(aid)
        if not refs:
            return
        status_lbl, conf_lbl, ver_lbl = refs
        if status is not None:
            status_lbl.config(text=status, fg=status_color or C["text_3"])
        if conf is not None:
            conf_lbl.config(text=conf, fg=conf_color or C["text_3"])
        if ver is not None:
            ver_lbl.config(text=ver)

    # ── 版本管理 ──────────────────────────────────

    def _on_manage_versions(self):
        """
        打开 checkpoint 版本管理对话框。
        左侧列出所有有 checkpoint 的算法，右侧显示该算法的版本列表。
        支持：查看详情、激活版本、删除版本、删除全部。
        """
        from algorithms.training.checkpoint_manager import (
            CheckpointManager,
            list_video_finetune_bvids,
        )
        from algorithms.registry import AlgorithmRegistry

        AlgorithmRegistry.initialize()
        algos = []
        # 收集所有有 checkpoint 的算法
        for aid, algo, _adapter in AlgorithmRegistry.get_trainable_algorithms():
            ckpt = CheckpointManager(aid)
            if ckpt.has_checkpoint() or os.path.exists(project_path("algorithms", "checkpoints", aid)):
                algos.append(
                    {
                        "algorithm_id": aid,
                        "name": getattr(algo, "name", aid),
                        "category": getattr(algo, "category", ""),
                    }
                )

        if not algos:
            messagebox.showinfo("提示", "没有任何已训练的模型", parent=self.frame)
            return

        dialog, info_lbl, detail_frame, algo_inner = self._draw_manage_dialog()

        def _refresh_detail(aid, name):
            """选中算法后的回调：刷新右侧版本详情"""
            self._draw_version_detail(detail_frame, info_lbl, aid, name, _refresh_detail)

        self._draw_version_list(algo_inner, algos, _refresh_detail)

    def _draw_manage_dialog(self):
        """
        构建版本管理对话框骨架（左列表 + 右详情）。

        :returns: (dialog, info_lbl, detail_frame, algo_inner)
        """
        dialog = tk.Toplevel(self.frame)
        dialog.title("Checkpoint 版本管理")
        dialog.geometry("700x500")
        dialog.transient(self.frame)
        dialog.grab_set()
        dialog.configure(bg=C["bg_base"])

        main = tk.Frame(dialog, bg=C["bg_base"])
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # 左侧面板：算法列表
        left_panel = tk.Frame(main, bg=C["bg_elevated"], width=220)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 6))
        left_panel.pack_propagate(False)
        tk.Label(left_panel, text="算法", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(
            fill=tk.X, padx=4, pady=4
        )

        algo_sf = ScrollableFrame(left_panel, bg=C["bg_elevated"])
        algo_sf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        algo_inner = algo_sf.inner

        # 右侧面板：版本详情
        right_panel = tk.Frame(main, bg=C["bg_surface"])
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        info_lbl = tk.Label(right_panel, text="← 选择一个算法", bg=C["bg_surface"], fg=C["text_3"], font=FONT)
        info_lbl.pack(pady=20)

        detail_frame = tk.Frame(right_panel, bg=C["bg_surface"])
        detail_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        return dialog, info_lbl, detail_frame, algo_inner

    def _draw_version_list(self, algo_inner, algos, refresh_cb):
        """
        填充左侧算法列表按钮（按名称排序）。

        :param algo_inner: 算法列表容器
        :param algos: 算法信息列表
        :param refresh_cb: 点击后的回调函数 (aid, name)
        """
        for a in sorted(algos, key=lambda x: x["name"]):
            btn = tk.Label(
                algo_inner,
                text=f"{a['name']}",
                bg=C["bg_elevated"],
                fg=C["text_1"],
                font=FONT_SM,
                anchor="w",
                cursor="hand2",
                padx=6,
                pady=3,
            )
            btn.pack(fill=tk.X)
            btn.bind("<Button-1>", lambda e, aid=a["algorithm_id"], n=a["name"]: refresh_cb(aid, n))
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=C["bg_surface"]))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=C["bg_elevated"]))

    def _draw_version_detail(self, detail_frame, info_lbl, aid, name, refresh_cb):
        """
        刷新指定算法的版本详情面板。
        显示：全局版本列表（支持激活/删除） + 视频微调版本列表。

        :param detail_frame: 右侧详情容器
        :param info_lbl: 占位提示 Label
        :param aid: 算法 ID
        :param name: 算法名称
        :param refresh_cb: 刷新回调
        """
        from algorithms.training.checkpoint_manager import CheckpointManager, list_video_finetune_bvids

        for w in detail_frame.winfo_children():
            w.destroy()

        info_lbl.pack_forget()

        tk.Label(detail_frame, text=f"{name}  ({aid})", bg=C["bg_surface"], fg=C["text_1"], font=FONT_BOLD).pack(
            anchor="w", pady=(0, 6)
        )

        ckpt = CheckpointManager(aid)

        # ── 全局版本 ──
        tk.Label(detail_frame, text="全局版本", bg=C["bg_surface"], fg=C["text_2"], font=FONT_SM).pack(anchor="w")

        versions = ckpt.list_versions()
        if not versions:
            tk.Label(
                detail_frame, text="  （无全局 checkpoint）", bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM
            ).pack(anchor="w", pady=2)
        else:
            for v in versions:
                row = tk.Frame(detail_frame, bg=C["bg_elevated"])
                row.pack(fill=tk.X, pady=1)
                active_tag = "★ " if v.get("active") else "  "
                tk.Label(
                    row,
                    text=f"{active_tag}{v['version']}",
                    bg=C["bg_elevated"],
                    fg=C["success"] if v.get("active") else C["text_1"],
                    font=FONT_MONO,
                    width=30,
                    anchor="w",
                ).pack(side=tk.LEFT, padx=4, pady=2)

                # 激活按钮（非活跃版本且有多版本时显示）
                if not v.get("active") and len(versions) > 1:
                    ttk.Button(
                        row,
                        text="激活",
                        width=4,
                        command=lambda ver=v["version"], c=ckpt, a=aid, n=name, cb=refresh_cb: (
                            self._activate_version(c, ver, a, n, cb)
                        ),
                    ).pack(side=tk.RIGHT, padx=2)

                # 删除按钮（多版本时显示）
                if len(versions) > 1:
                    ttk.Button(
                        row,
                        text="✕",
                        width=3,
                        command=lambda ver=v["version"], c=ckpt, a=aid, n=name, cb=refresh_cb: (
                            c.delete(ver),
                            cb(a, n),
                        ),
                    ).pack(side=tk.RIGHT, padx=2)

                # val_loss 显示
                vl = v.get("val_loss", -1)
                vl_txt = f"  val_loss={vl:.4f}" if vl >= 0 else ""
                tk.Label(row, text=vl_txt, bg=C["bg_elevated"], fg=C["text_3"], font=FONT_SM).pack(side=tk.LEFT)

        # ── 视频微调版本 ──
        bvids = list_video_finetune_bvids(aid)
        if bvids:
            tk.Label(detail_frame, text="\n视频微调版本", bg=C["bg_surface"], fg=C["text_2"], font=FONT_SM).pack(
                anchor="w"
            )
            for bvid in bvids:
                v_ckpt = CheckpointManager(aid, bvid=bvid)
                v_vers = v_ckpt.list_versions()
                for v in v_vers:
                    row = tk.Frame(detail_frame, bg=C["bg_elevated"])
                    row.pack(fill=tk.X, pady=1)
                    tk.Label(
                        row,
                        text=f"  📺 {bvid}  {v['version']}",
                        bg=C["bg_elevated"],
                        fg=C["text_1"],
                        font=FONT_MONO,
                        anchor="w",
                    ).pack(side=tk.LEFT, padx=4, pady=2)
                    # 删除视频微调版本
                    ttk.Button(
                        row,
                        text="✕",
                        width=3,
                        command=lambda b=bvid, ver=v["version"], a=aid, n=name, cb=refresh_cb: (
                            CheckpointManager(a, bvid=b).delete(ver),
                            cb(a, n),
                        ),
                    ).pack(side=tk.RIGHT, padx=2)

        # ── 底部批量操作按钮 ──
        if versions or bvids:
            tk.Label(detail_frame, text="", bg=C["bg_surface"]).pack()
            sep = tk.Frame(detail_frame, bg=C["border"], height=1)
            sep.pack(fill=tk.X, pady=4)
            btn_row = tk.Frame(detail_frame, bg=C["bg_surface"])
            btn_row.pack(fill=tk.X)
            if _hard() == "normal":
                ttk.Button(
                    btn_row,
                    text="删除所有全局版本",
                    command=lambda a=aid, n=name: self._delete_all_global(a, n, refresh_cb),
                ).pack(side=tk.LEFT, padx=2)
                if bvids:
                    ttk.Button(
                        btn_row,
                        text="删除所有微调版本",
                        command=lambda a=aid, n=name: self._delete_all_video(a, n, refresh_cb),
                    ).pack(side=tk.LEFT, padx=2)
            else:
                ckpt_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "algorithms", "checkpoints", aid,
                )
                tk.Label(
                    btn_row, text=f"📁 {os.path.relpath(ckpt_dir)}",
                    bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM,
                ).pack(side=tk.LEFT, padx=4)

    def _activate_version(self, ckpt, ver, aid, name, refresh_cb):
        """
        激活指定版本并刷新详情。

        :param ckpt: CheckpointManager 实例
        :param ver: 版本号字符串
        :param aid: 算法 ID
        :param name: 算法名称
        :param refresh_cb: 刷新回调
        """
        ckpt.activate(ver)
        refresh_cb(aid, name)

    def _delete_all_global(self, aid, name, refresh_cb):
        """
        删除算法的所有全局 checkpoint（需确认）。

        :param aid: 算法 ID
        :param name: 算法名称
        :param refresh_cb: 刷新回调
        """
        if not messagebox.askyesno(
            "确认删除", f"确定要删除 {name} ({aid}) 的所有全局版本？\n此操作不可撤销。", parent=self.frame
        ):
            return
        from algorithms.training.checkpoint_manager import CheckpointManager

        ckpt = CheckpointManager(aid)
        for v in ckpt.list_versions():
            ckpt.delete(v["version"])
        refresh_cb(aid, name)
        self._refresh_algo_list()

    def _delete_all_video(self, aid, name, refresh_cb):
        """
        删除算法的所有视频微调 checkpoint（需确认）。

        :param aid: 算法 ID
        :param name: 算法名称
        :param refresh_cb: 刷新回调
        """
        if not messagebox.askyesno(
            "确认删除", f"确定要删除 {name} ({aid}) 的所有视频微调版本？\n此操作不可撤销。", parent=self.frame
        ):
            return
        from algorithms.training.checkpoint_manager import CheckpointManager, list_video_finetune_bvids

        for bvid in list_video_finetune_bvids(aid):
            ckpt = CheckpointManager(aid, bvid=bvid)
            for v in ckpt.list_versions():
                ckpt.delete(v["version"])
        refresh_cb(aid, name)

    # ── 批量微调 ──────────────────────────────────

    def _on_batch_finetune(self):
        """
        打开批量微调对话框：选择视频 + 算法，一键微调。
        需要至少有一个已训练的深度学习算法和一个监控中的视频。
        """
        from algorithms.registry import AlgorithmRegistry
        from algorithms.training.checkpoint_manager import CheckpointManager

        AlgorithmRegistry.initialize()
        algo_list = []
        # 收集有 checkpoint 的可训练算法
        for aid, algo, _adapter in AlgorithmRegistry.get_trainable_algorithms():
            if CheckpointManager(aid).has_checkpoint():
                algo_list.append({"algorithm_id": aid, "name": getattr(algo, "name", aid)})

        if not algo_list:
            messagebox.showwarning("提示", "没有已训练的深度学习算法可供微调", parent=self.frame)
            return

        videos = []
        try:
            for v in self.main.monitored_videos:
                bvid = v.get("bvid", "")
                title = v.get("title", bvid)
                if bvid:
                    videos.append({"bvid": bvid, "title": title[:40]})
        except Exception as e:
            logger.debug("忽略异常: %s", e)

        if not videos:
            messagebox.showwarning("提示", "没有监控中的视频可微调", parent=self.frame)
            return

        dialog, ui = self._build_batch_dialog(algo_list, videos)

        def _ft_log(msg):
            """批量微调日志工具函数"""
            ui["log_text"].config(state="normal")
            ui["log_text"].insert(tk.END, msg + "\n")
            ui["log_text"].see(tk.END)
            ui["log_text"].config(state="disabled")

        def _start_ft():
            """开始批量微调按钮回调"""
            selected_videos = [b for b, v in ui["video_vars"].items() if v.get()]
            selected_algos = [a for a, v in ui["algo_vars"].items() if v.get()]
            if not selected_videos:
                messagebox.showwarning("提示", "请至少选择一个视频", parent=dialog)
                return
            if not selected_algos:
                messagebox.showwarning("提示", "请至少选择一个算法", parent=dialog)
                return

            epochs = max(1, ui["ft_epoch_var"].get())
            batch = max(1, ui["ft_batch_var"].get())
            total = len(selected_videos) * len(selected_algos)
            _ft_log(f"开始批量微调: {len(selected_videos)} 视频 × {len(selected_algos)} 算法 = {total} 任务")
            ui["start_btn"].config(state="disabled")

            # 后台线程执行批量微调
            threading.Thread(
                target=lambda: self._start_batch_worker(
                    selected_videos, selected_algos, epochs, batch, total, dialog, ui, _ft_log,
                ),
                daemon=True,
            ).start()

        ui["start_btn"].config(command=_start_ft)
        ui["cancel_btn"].config(command=dialog.destroy)

    def _build_batch_dialog(self, algo_list, videos):
        """
        构建批量微调对话框的 UI。

        :param algo_list: 可用算法列表
        :param videos: 监控视频列表
        :returns: (dialog, ui_dict)
        """
        dialog = tk.Toplevel(self.frame)
        dialog.title("批量微调")
        dialog.geometry("650x500")
        dialog.transient(self.frame)
        dialog.grab_set()
        dialog.configure(bg=C["bg_base"])

        main = tk.Frame(dialog, bg=C["bg_base"])
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 选择视频
        tk.Label(main, text="选择视频", bg=C["bg_base"], fg=C["text_1"], font=FONT_BOLD).pack(anchor="w", pady=(0, 2))
        video_frame = tk.Frame(main, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border"])
        video_frame.pack(fill=tk.X, pady=(0, 8))
        v_sf = ScrollableFrame(video_frame, bg=C["bg_elevated"], height=100)
        v_sf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        v_inner = v_sf.inner

        video_vars = {}
        for v in sorted(videos, key=lambda x: x["bvid"]):
            var = tk.BooleanVar(value=True)  # 默认勾选
            video_vars[v["bvid"]] = var
            row = tk.Frame(v_inner, bg=C["bg_elevated"])
            row.pack(fill=tk.X)
            ttk.Checkbutton(row, variable=var).pack(side=tk.LEFT, padx=2)
            tk.Label(
                row, text=f"{v['title']}  ({v['bvid']})", bg=C["bg_elevated"], fg=C["text_1"], font=FONT_SM, anchor="w"
            ).pack(side=tk.LEFT, padx=2, fill=tk.X)

        # 选择算法
        tk.Label(main, text="选择算法", bg=C["bg_base"], fg=C["text_1"], font=FONT_BOLD).pack(anchor="w", pady=(0, 2))
        algo_frame = tk.Frame(main, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border"])
        algo_frame.pack(fill=tk.X, pady=(0, 8))
        a_sf = ScrollableFrame(algo_frame, bg=C["bg_elevated"], height=100)
        a_sf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        a_inner = a_sf.inner

        algo_vars = {}
        for a in sorted(algo_list, key=lambda x: x["name"]):
            var = tk.BooleanVar(value=True)  # 默认勾选
            algo_vars[a["algorithm_id"]] = var
            row = tk.Frame(a_inner, bg=C["bg_elevated"])
            row.pack(fill=tk.X)
            ttk.Checkbutton(row, variable=var).pack(side=tk.LEFT, padx=2)
            tk.Label(
                row,
                text=f"{a['name']}  ({a['algorithm_id']})",
                bg=C["bg_elevated"],
                fg=C["text_1"],
                font=FONT_SM,
                anchor="w",
            ).pack(side=tk.LEFT, padx=2, fill=tk.X)

        # 参数行
        param_row = tk.Frame(main, bg=C["bg_base"])
        param_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(param_row, text="Epochs:", bg=C["bg_base"], fg=C["text_2"], font=FONT_SM).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ft_epoch_var = tk.IntVar(value=5)  # 微调默认 5 个 epoch
        ttk.Spinbox(param_row, from_=1, to=100, textvariable=ft_epoch_var, width=6).pack(side=tk.LEFT, padx=(0, 16))
        tk.Label(param_row, text="Batch:", bg=C["bg_base"], fg=C["text_2"], font=FONT_SM).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ft_batch_var = tk.IntVar(value=16)  # 微调默认 batch=16
        ttk.Spinbox(param_row, from_=1, to=512, textvariable=ft_batch_var, width=6).pack(side=tk.LEFT)

        # 状态 + 进度
        ft_status = tk.Label(main, text="就绪", bg=C["bg_base"], fg=C["text_3"], font=FONT_SM, anchor="w")
        ft_status.pack(fill=tk.X, pady=(0, 4))
        ft_progress = ttk.Progressbar(main, mode="determinate", maximum=100)
        ft_progress.pack(fill=tk.X, pady=(0, 8))

        # 日志区
        log_text = tk.Text(
            main, bg=C["bg_base"], fg=C["text_1"], font=("Consolas", 9), relief="flat", height=6, state="disabled"
        )
        log_text.pack(fill=tk.BOTH, expand=True)

        # 按钮行
        btn_row = tk.Frame(main, bg=C["bg_base"])
        btn_row.pack(fill=tk.X)
        start_btn = ttk.Button(btn_row, text="▶ 开始微调")
        start_btn.pack(side=tk.LEFT, padx=(0, 6))
        cancel_btn = ttk.Button(btn_row, text="取消")
        cancel_btn.pack(side=tk.LEFT)

        return dialog, {
            "video_vars": video_vars,
            "algo_vars": algo_vars,
            "ft_epoch_var": ft_epoch_var,
            "ft_batch_var": ft_batch_var,
            "ft_status": ft_status,
            "ft_progress": ft_progress,
            "log_text": log_text,
            "start_btn": start_btn,
            "cancel_btn": cancel_btn,
        }

    def _start_batch_worker(self, selected_videos, selected_algos, epochs, batch, total, dialog, ui, _ft_log):
        """
        后台工作线程：依次对每个视频的每个算法进行微调。

        :param selected_videos: 选中的视频 bvid 列表
        :param selected_algos: 选中的算法 ID 列表
        :param epochs: 微调 epoch 数
        :param batch: 微调 batch size
        :param total: 总任务数（视频数 × 算法数）
        :param dialog: 批量微调对话框
        :param ui: UI 元素字典
        :param _ft_log: 日志函数
        """
        from algorithms.training.trainer import ModelTrainer

        trainer = ModelTrainer()
        done = 0
        self.main.set_finetune_status(f"🎯 批量微调 0/{total}")
        for bvid in selected_videos:
            for aid in selected_algos:
                done += 1
                pct = int(done / total * 100)
                msg = f"[{done}/{total}] 微调 {aid} → {bvid}"
                dialog.after(0, lambda m=msg: ui["ft_status"].configure(text=m))
                dialog.after(0, lambda p=pct: ui["ft_progress"].config(value=p))
                dialog.after(0, lambda m=msg: _ft_log(m))
                dialog.after(0, lambda d=done, t=total: self.main.set_finetune_status(f"🎯 批量微调 {d}/{t}"))
                try:
                    ver = trainer.finetune_for_video(
                        algo_id=aid,
                        bvid=bvid,
                        epochs=epochs,
                        batch_size=batch,
                    )
                    dialog.after(0, lambda a=aid, b=bvid, v=ver: _ft_log(f"  ✓ {a}@{b} → {v[:12]}"))
                except Exception as e:
                    dialog.after(0, lambda a=aid, b=bvid, e=e: _ft_log(f"  ✗ {a}@{b}: {e}"))
        self._batch_done_callback(dialog, ui, _ft_log, done)

    def _batch_done_callback(self, dialog, ui, _ft_log, done):
        """
        批量微调完成后的 UI 更新回调。

        :param dialog: 批量微调对话框
        :param ui: UI 元素字典
        :param _ft_log: 日志函数
        :param done: 已完成任务数
        """
        dialog.after(0, lambda: ui["ft_status"].configure(text=f"✅ 微调完成 ({done} 任务)"))
        dialog.after(0, lambda: ui["ft_progress"].config(value=100))
        dialog.after(0, lambda: self.main.set_finetune_status(f"✅ 批量微调完成 ({done})"))
        dialog.after(0, lambda: ui["start_btn"].config(state="normal"))
        dialog.after(0, lambda: _ft_log("🏁 批量微调全部完成"))

    # ══════════════════════════════════════════════
    # 训练执行
    # ══════════════════════════════════════════════

    def _on_train_start(self):
        """
        开始训练按钮回调。

        流程：
          1. 验证参数（算法选择、epoch/batch/lr 合法性）
          2. 弹出确认对话框
          3. 准备训练状态（清理图表、日志、打开日志文件）
          4. 启动后台训练线程
        """
        config = self._validate_train_params()
        if config is None:
            return

        selected, epochs, batch, is_incremental, lr, mode_label, lr_label = config
        self._build_train_config(selected, epochs, batch, mode_label, lr)
        self._start_train_thread(selected, is_incremental, lr, epochs, batch)

    def _validate_train_params(self):
        """
        校验训练参数并弹出确认对话框。

        :returns: (selected, epochs, batch, is_incremental, lr, mode_label, lr_label) 或 None
        """
        if self._training:
            return None
        if not _torch_available:
            messagebox.showerror("torch 未安装", "请先 pip install torch", parent=self.frame)
            return None

        selected = [aid for aid, v in self._check_vars.items() if v.get()]
        if not selected:
            messagebox.showwarning("提示", "请至少勾选一个算法", parent=self.frame)
            return None

        epochs = max(1, int(self._epoch_var.get()))
        batch = max(1, int(self._batch_var.get()))
        is_incremental = self._mode_var.get() == "incremental"
        mode_label = "增量训练" if is_incremental else "重新训练"

        if self._lr_auto_var.get():
            lr = self._auto_compute_lr()
            self._lr_var.set(f"{lr:.6f}")
            lr_label = f"自动 ({lr:.6f})"
        else:
            try:
                lr = float(self._lr_var.get())
            except (ValueError, TypeError):
                messagebox.showerror("LR 无效", "请输入有效的学习率数值", parent=self.frame)
                return None
            lr = max(1e-8, min(1.0, lr))  # 限制 LR 在安全范围
            lr_label = f"手动 ({lr:.6f})"

        if not messagebox.askyesno(
            "确认训练",
            f"模式: {mode_label}\n算法: {len(selected)} 个\n"
            f"epoch={epochs}  batch={batch}  LR={lr_label}\n"
            f"训练过程不可中途暂停（只能取消未开始的算法）。",
            parent=self.frame,
        ):
            return None

        return (selected, epochs, batch, is_incremental, lr, mode_label, lr_label)

    def _build_train_config(self, selected, epochs, batch, mode_label, lr):
        """
        重置训练状态、打开日志文件、更新状态标签。

        :param selected: 选中的算法 ID 列表
        :param epochs: 训练 epoch
        :param batch: batch size
        :param mode_label: 模式描述
        :param lr: 学习率
        """
        self._prepare_training()
        self._open_log_file(len(selected), epochs, batch, mode_label, lr)
        self._append_log(
            f"🚀 开始训练: {mode_label}, {len(selected)} 个算法, epoch={epochs}, batch={batch}, lr={lr:.6f}"
        )
        self._status_lbl.config(text=f"准备训练 {len(selected)} 个算法 …", fg=C["text_2"])

    def _start_train_thread(self, selected, is_incremental, lr, epochs, batch):
        """
        定义训练回调和后台线程并启动。

        训练回调：
          - 处理每个 epoch 的 loss 数据
          - 通过 TrainingMonitor 实时监控训练质量
          - 自动调整学习率、判断提前停止
          - 通过 Queue 发送进度消息给前端

        :param selected: 选中的算法 ID 列表
        :param is_incremental: 是否增量训练
        :param lr: 初始学习率
        :param epochs: 训练 epoch
        :param batch: batch size
        """
        auto_control: Dict = {}  # 自动控制字典（传递给 trainer）
        auto_monitors: Dict[str, "TrainingMonitor"] = {}  # 每个算法独立的监控器
        algo_lr_factors: Dict[str, float] = {}  # 每个算法的累计 LR 缩放因子

        def _cb(payload: Dict):
            """
            训练回调（运行在工作线程中）。

            负责：
              1. 处理用户取消/跳过请求
              2. 监控每个 epoch 的 loss
              3. 检测到问题时自动调整 LR 或提前停止
              4. 将消息放入前端队列
            """
            payload["_total_selected"] = len(selected)
            payload["_incremental"] = is_incremental

            # 用户请求跳过当前算法
            if self._skip_algo_flag[0]:
                auto_control["early_stop"] = True
                auto_control["_force_early_stop"] = True
                payload["_adjustment"] = "⏭ 用户手动跳过"
                self._train_queue.put(payload)
                return

            if payload.get("stage") == "epoch":
                aid = payload.get("algo_id", "")
                ep = payload.get("epoch", 0)
                tloss = payload.get("train_loss", 0.0)
                vloss = payload.get("val_loss", -1.0)

                # 获取或创建该算法的独立监控器
                key = aid
                if key not in auto_monitors:
                    auto_monitors[key] = TrainingMonitor()
                mon = auto_monitors[key]
                mon.update(ep, tloss, vloss if vloss >= 0 else -1)

                # 根据监控结果自动调整训练参数
                if mon.level in ("warning", "danger") and auto_control is not None:
                    status = mon.status
                    factor = algo_lr_factors.get(aid, 1.0)
                    if "nan" in status.lower():
                        auto_control["early_stop"] = True
                        payload["_adjustment"] = "🔧 NaN 检测 — 提前停止"
                    elif "爆炸" in status:
                        scale = mon.compute_lr_scale("explosion")
                        auto_control["lr_scale"] = scale
                        algo_lr_factors[aid] = factor * scale
                        payload["_adjustment"] = (
                            f"🔧 Loss 爆炸 — {aid} LR×{scale:.2f} (累计 {algo_lr_factors[aid]:.2f})"
                        )
                    elif "严重过拟合" in status:
                        auto_control["early_stop"] = True
                        payload["_adjustment"] = "🔧 严重过拟合 — 提前停止"
                    elif "震荡" in status:
                        scale = mon.compute_lr_scale("oscillation")
                        auto_control["lr_scale"] = scale
                        algo_lr_factors[aid] = factor * scale
                        payload["_adjustment"] = (
                            f"🔧 Loss 震荡 — {aid} LR×{scale:.2f} (累计 {algo_lr_factors[aid]:.2f})"
                        )
                    elif "过拟合" in status:
                        scale = mon.compute_lr_scale("overfitting")
                        auto_control["lr_scale"] = scale
                        algo_lr_factors[aid] = factor * scale
                        payload["_adjustment"] = f"🔧 过拟合 — {aid} LR×{scale:.2f} (累计 {algo_lr_factors[aid]:.2f})"
                    elif "欠拟合" in status or "下降过慢" in status:
                        scale = mon.compute_lr_scale("underfitting")
                        auto_control["lr_scale"] = scale
                        algo_lr_factors[aid] = factor * scale
                        payload["_adjustment"] = f"🔧 欠拟合 — {aid} LR×{scale:.2f} (累计 {algo_lr_factors[aid]:.2f})"
                    elif "不再收敛" in status:
                        auto_control["early_stop"] = True
                        payload["_adjustment"] = "🔧 不再收敛 — 提前停止"

            self._train_queue.put(payload)

        def _worker():
            """
            后台工作线程：依次训练每个选中的算法。
            每次训练一个算法，完成后检查取消标志，继续下一个。
            """
            try:
                from algorithms.training.trainer import ModelTrainer

                trainer = ModelTrainer()
                remaining = list(selected)
                results = {}
                while remaining:
                    if self._cancel_flag[0]:
                        self._train_queue.put({"stage": "cancelled", "remaining": remaining})
                        break
                    aid = remaining.pop(0)

                    # 重新训练模式：先删除旧 checkpoint
                    if not is_incremental:
                        from algorithms.training.checkpoint_manager import CheckpointManager

                        _ckpt = CheckpointManager(aid)
                        _n = _ckpt.delete_all()
                        if _n:
                            self._train_queue.put(
                                {
                                    "stage": "log",
                                    "text": f"  🗑 已清除 {aid} 的 {_n} 个旧版本",
                                }
                            )

                    self._skip_algo_flag[0] = False  # 重置跳过标志
                    self.frame.after(0, lambda: self._skip_btn.config(state="normal"))

                    # 计算该算法的有效 LR（含之前的累计调整因子）
                    aid_factor = algo_lr_factors.get(aid, 1.0)
                    effective_lr = lr * aid_factor
                    auto_control.clear()
                    sub = trainer.train_global(
                        [aid],
                        epochs=epochs,
                        batch_size=batch,
                        progress_cb=_cb,
                        init_from_global=is_incremental,
                        lr=effective_lr,
                        control_dict=auto_control,
                    )
                    results.update(sub)
                self._train_queue.put({"stage": "all_done", "results": results})
            except Exception as e:
                self._train_queue.put({"stage": "fatal", "error": str(e)})

        self._launch_worker(_worker)

    def _on_cancel(self):
        """
        取消训练按钮回调。
        设置取消标志 → 禁用按钮 → 更新状态 → 关闭日志文件。
        """
        self._cancel_flag[0] = True
        if self._cancel_btn:
            self._cancel_btn.config(state="disabled")
        self._status_lbl.config(text="正在取消（等待当前算法完成）…", fg=C["warning"])
        self._append_log("⏹ 用户请求取消训练")
        self._close_log_file()

    def _on_skip_algo(self):
        """
        跳过当前正在训练的算法，继续下一个。
        设置跳过标志 → 禁用按钮 → 更新状态。
        """
        self._skip_algo_flag[0] = True
        if self._skip_btn:
            self._skip_btn.config(state="disabled")
        self._status_lbl.config(text="⏭ 跳过当前算法（等待本轮完成）…", fg=C["warning"])
        self._append_log("⏭ 用户请求跳过当前算法")

    # stage → handler 方法名映射
    STAGE_HANDLERS = {
        "start": "_on_stage_start",
        "epoch": "_on_stage_epoch",
        "done": "_on_stage_done",
        "error": "_on_stage_error",
        "auto_adjust": "_on_stage_auto_adjust",
        "cancelled": "_on_stage_cancelled",
        "all_done": "_on_stage_all_done",
        "fatal": "_on_stage_fatal",
    }

    def _handle_stage(self, msg) -> bool:
        """
        根据消息 stage 分发给对应的事件处理器。
        通过 STAGE_HANDLERS 映射表动态调用。

        :param msg: 训练回调发来的消息字典
        :returns: True 表示训练全部结束
        """
        stage = msg.get("stage")
        handler_name = self.STAGE_HANDLERS.get(stage)
        if handler_name:
            return getattr(self, handler_name)(msg)
        return False

    def _on_stage_start(self, msg):
        """
        处理训练开始事件。
        更新当前算法 ID、状态标签、日志、算法行状态。
        """
        aid = msg.get("algo_id", "?")
        cur = msg.get("current", 0)
        tot = msg.get("total", 1)
        self._current_aid = aid
        self._status_lbl.config(text=f"[{cur}/{tot}] 训练 {aid} …", fg=C["text_2"])
        self._append_log(f"── [{cur}/{tot}] 开始训练 {aid} ──")
        self._update_algo_row(aid, status="▶ 训练中", status_color=C["accent"])
        self._monitor.reset()

    def _on_stage_epoch(self, msg):
        """
        处理每个 epoch 完成事件。
        更新图表、进度条、状态标签、日志。
        每 5 个 epoch 或首尾 epoch 时更新置信度显示。
        """
        aid = msg.get("algo_id", "?")
        ep = msg.get("epoch", 0)
        eps = msg.get("epochs", 1)
        tloss = msg.get("train_loss", 0.0)
        vloss = msg.get("val_loss", -1.0)
        elapsed = msg.get("elapsed_s", 0.0)

        # 计算置信度（基于 val_loss）
        conf = loss_to_confidence(vloss) if vloss >= 0 else 0.0
        conf_str, conf_color = format_confidence(conf)

        # 每 5 epoch 或首尾时更新置信度
        if ep == 1 or ep % 5 == 0 or ep == eps:
            self._update_algo_row(aid, conf=conf_str, conf_color=conf_color)

        pct = min(100, int((ep / max(1, eps)) * 100))
        self._progress["value"] = pct
        vtxt = f"  val={vloss:.4f}" if vloss >= 0 else ""
        self._status_lbl.config(
            text=f"{aid}  ep{ep}/{eps}  train={tloss:.4f}{vtxt}  {conf_str}  {elapsed:.0f}s",
            fg=C["text_1"],
        )

        # 更新训练质量监控
        self._monitor.update(ep, tloss, vloss if vloss >= 0 else -1)
        self._refresh_monitor()

        # 记录自动调整信息
        adj = msg.get("_adjustment", "")
        if adj:
            self._append_log(f"  {adj}")

        # 记录 loss 历史
        self._loss_history.append(
            {
                "algo": aid,
                "epoch": ep,
                "train_loss": tloss,
                "val_loss": vloss,
            }
        )
        self._update_chart()
        self._append_log(
            f"  epoch {ep:>3}/{eps}  |  "
            f"train_loss={tloss:.6f}  |  "
            f"{f'val_loss={vloss:.6f}' if vloss >= 0 else 'val_loss=N/A'}  |  "
            f"confidence={conf_str}  |  "
            f"{elapsed:.1f}s"
        )

    def _on_stage_done(self, msg):
        """
        处理单个算法训练完成事件。
        从 checkpoint 读取最终 val_loss → 计算置信度 → 更新算法行。
        """
        total_sel = msg.get("_total_selected", 1)
        aid = msg.get("algo_id", "?")
        cur = msg.get("current", 0)
        ver = msg.get("version", "")
        self._status_lbl.config(text=f"✓ {aid} → {ver} ({cur}/{total_sel})", fg=C["success"])
        self._progress["value"] = int(cur / max(1, total_sel) * 100)

        # 从 checkpoint 读取 val_loss
        from algorithms.training.checkpoint_manager import CheckpointManager
        _val_loss = -1.0
        try:
            _ckpt = CheckpointManager(aid)
            _versions = _ckpt.list_versions()
            if _versions:
                _val_loss = _versions[0].get("val_loss", -1.0)
        except Exception as e:
            logger.debug("忽略异常: %s", e)
        conf = loss_to_confidence(_val_loss) if _val_loss >= 0 else load_algo_confidence(aid)
        conf_str, conf_color = format_confidence(conf)
        self._algo_confidence[aid] = conf
        if _val_loss >= 0:
            self._append_log(f"  ✓ {aid} → {ver}  置信度={conf_str}  val_loss={_val_loss:.4f}")
        else:
            self._append_log(f"  ✓ {aid} → {ver}")
        self._update_algo_row(
            aid,
            status=f"✓ {ver[:10]}",
            status_color=C["success"],
            conf=conf_str,
            conf_color=conf_color,
            ver=f"v{self._algo_meta.get(aid, {}).get('version_count', 0) + 1}",
        )

    def _on_stage_error(self, msg):
        """
        处理训练错误事件。
        更新状态标签、日志、算法行状态。
        """
        aid = msg.get("algo_id", "?")
        err = msg.get("error", "")
        self._status_lbl.config(text=f"✗ {aid} 失败: {err}", fg=C["danger"])
        self._append_log(f"✗ {aid} 训练失败: {err}")
        self._update_algo_row(aid, status="✗ 失败", status_color=C["danger"])

    def _on_stage_auto_adjust(self, msg):
        """
        处理自动调整事件（学习率调整等）。
        记录日志和状态。
        """
        message = msg.get("message", "")
        self._append_log(f"  🔧 自动调整: {message}")
        self._status_lbl.config(text=f"⚡ {message}", fg=C["warning"])

    def _on_stage_cancelled(self, msg):
        """
        处理取消训练事件。
        显示剩余算法数，返回 True 表示训练结束。
        """
        rem = msg.get("remaining", [])
        self._status_lbl.config(text=f"已取消，剩余 {len(rem)} 个", fg=C["warning"])
        self._append_log(f"⏹ 已取消, 剩余 {len(rem)} 个算法")
        return True

    def _on_stage_all_done(self, msg):
        """
        处理所有算法训练完成事件。
        统计成功/失败数，汇总各算法置信度，显示耗时。
        """
        results = msg.get("results", {})
        self._last_training_results = results
        ok = sum(1 for v in results.values() if v)
        bad = sum(1 for v in results.values() if not v)
        elapsed = time.time() - self._train_t0 if self._train_t0 else 0

        # 汇总各算法的最终置信度
        conf_summary = ""
        for aid, ver in results.items():
            if not ver:
                continue
            conf = load_algo_confidence(aid)
            self._algo_confidence[aid] = conf
            conf_str, _ = format_confidence(conf)
            conf_summary += f"  {aid}: {conf_str}"

        self._status_lbl.config(text=f"全部完成: ✓ {ok}  ✗ {bad}  · {elapsed:.0f}s", fg=C["success"])
        self._progress["value"] = 100
        self._append_log(f"🏁 训练全部完成: {ok} 成功, {bad} 失败, 耗时 {elapsed:.0f}s")
        self._append_log(f"📊 各算法最终置信度:{conf_summary}")
        return True

    def _on_stage_fatal(self, msg):
        """
        处理训练进程致命错误事件。
        """
        err = msg.get("error", "")
        self._status_lbl.config(text=f"训练异常: {err}", fg=C["danger"])
        self._append_log(f"💥 训练进程异常: {err}")
        return True

    def _cleanup_training(self):
        """
        训练清理：关闭日志文件 → 调用基类清理 → 刷新算法列表 → 通知完成
        """
        self._close_log_file()
        super()._cleanup_training()
        self._refresh_algo_list()
        try:
            self.main._refresh_model_status()
        except Exception as e:
            logger.debug("忽略异常: %s", e)

        # 训练完成回调：通知并触发重新预测
        trained = getattr(self, "_last_training_results", {})
        ok = [aid for aid, v in trained.items() if v]
        if ok:
            detail = ", ".join(ok[:6])
            if len(ok) > 6:
                detail += f" …等{len(ok)}个"
            try:
                self.main._on_training_completed("训练", len(ok), detail)
            except Exception as e:
                logger.debug("忽略异常: %s", e)

    # ══════════════════════════════════════════════
    # 训练质量监控
    # ══════════════════════════════════════════════

    def _on_monitor_changed(self):
        """
        监控状态变化时的日志记录。
        当检测到 warning/danger 级别时在日志中输出具体问题和建议，
        同时输出学习率调整建议。
        同一状态每 8 个 epoch 重复提醒一次。
        """
        if self._monitor.level in ("warning", "danger") and self._monitor.suggestions:
            cur_status = self._monitor.status
            last_status = getattr(self, "_last_monitor_status", "")
            last_epoch = getattr(self, "_last_monitor_log_epoch", 0)
            cur_epoch = len(self._monitor._points)

            # 状态变化 或 每 8 epoch 持续提醒
            if cur_status != last_status or cur_epoch - last_epoch >= 8:
                self._last_monitor_status = cur_status
                self._last_monitor_log_epoch = cur_epoch
                prefix = "🤖 训练质量检测" if cur_status != last_status else "🔄 持续监测"
                self._append_log(f"{prefix}: {cur_status}")
                for s in self._monitor.suggestions:
                    self._append_log(f"  💡 {s}")

                # 学习率建议：显示当前值和推荐值
                lr_suggestion = self._compute_lr_suggestion()
                if lr_suggestion:
                    self._append_log(f"  📐 {lr_suggestion}")

    def _compute_lr_suggestion(self) -> str:
        """
        根据 TrainingMonitor 的 loss 数据动态计算推荐学习率。

        :returns: 学习率建议文本（含当前值、推荐值、缩放系数）
        """
        suggestions_text = " ".join(self._monitor.suggestions).lower()
        if "增大学习率" in suggestions_text or "下降过慢" in self._monitor.status:
            scale = self._monitor.compute_lr_scale("underfitting")
            try:
                cur_lr = float(self._lr_var.get())
            except (ValueError, TypeError):
                cur_lr = 0.001
            new_lr = cur_lr * scale
            return f"学习率 {cur_lr:.6f} → {new_lr:.6f} (×{scale:.2f}) — 点击 LR 输入框可手动应用"
        elif "大幅降低" in suggestions_text:
            scale = self._monitor.compute_lr_scale("explosion")
            try:
                cur_lr = float(self._lr_var.get())
            except (ValueError, TypeError):
                cur_lr = 0.001
            new_lr = cur_lr * scale
            return f"学习率 {cur_lr:.6f} → {new_lr:.6f} (×{scale:.2f}) — 点击 LR 输入框可手动应用"
        elif "降低学习率" in suggestions_text:
            status = self._monitor.status
            issue = "oscillation" if "波动" in status else "overfitting"
            scale = self._monitor.compute_lr_scale(issue)
            try:
                cur_lr = float(self._lr_var.get())
            except (ValueError, TypeError):
                cur_lr = 0.001
            new_lr = cur_lr * scale
            return f"学习率 {cur_lr:.6f} → {new_lr:.6f} (×{scale:.2f}) — 点击 LR 输入框可手动应用"
        return ""

    # ══════════════════════════════════════════════
    # 日志（UI + 存盘）
    # ══════════════════════════════════════════════

    def _open_log_file(self, algo_count: int, epochs: int, batch: int, mode: str, lr: float = 0.001):
        """
        创建训练日志文件，写入文件头。

        :param algo_count: 算法数量
        :param epochs: 训练 epoch
        :param batch: batch size
        :param mode: 训练模式描述
        :param lr: 学习率
        """
        os.makedirs(self._log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_file_path = os.path.join(self._log_dir, f"train_{ts}.log")
        self._log_file = open(self._log_file_path, "w", encoding="utf-8")
        # 写文件头
        self._log_file.write(f"{'=' * 60}\n")
        self._log_file.write(f"  训练启动: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        self._log_file.write(
            f"  模式: {mode}  |  算法: {algo_count}  |  epoch: {epochs}  |  batch: {batch}  |  lr: {lr:.6f}\n"
        )
        self._log_file.write(f"{'=' * 60}\n")
        self._log_file.flush()

    def _close_log_file(self):
        """关闭训练日志文件，写入结束标记"""
        if self._log_file is None:
            return
        try:
            self._log_file.write(f"{'=' * 60}\n")
            self._log_file.write(f"  训练结束: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            self._log_file.write(f"{'=' * 60}\n")
            self._log_file.flush()
            self._log_file.close()
        except Exception as e:
            logger.debug("关闭训练日志文件失败: %s", e)
        self._log_file = None
        logger.info("训练日志已保存: %s", self._log_file_path)

    def _append_log(self, text: str):
        """
        追加日志到 UI 和文件。
        重写基类方法以同时写入磁盘日志文件。

        :param text: 日志内容
        """
        super()._append_log(text)
        if self._log_file is not None:
            try:
                line = f"[{time.strftime('%H:%M:%S')}] {text}\n"
                self._log_file.write(line)
                self._log_file.flush()
            except Exception as e:
                logger.debug("写入训练日志文件失败: %s", e)
