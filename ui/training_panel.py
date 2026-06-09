"""
训练面板 - 主界面集成版
支持模型增量训练/重新训练，实时 loss 图表 + 文字日志。
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

_torch_available = True
try:
    import torch  # noqa: F401
except ImportError:
    _torch_available = False


class TrainingPanel(BaseTrainingPanel):
    """训练面板 - 主界面选项卡，支持模型增量训练/重新训练"""

    def __init__(self, parent: tk.Widget, main_gui):
        """初始化训练面板"""
        super().__init__(parent, main_gui)

        # 算法列表状态
        self._check_vars: Dict[str, tk.BooleanVar] = {}
        self._algo_meta: Dict[str, Dict] = {}
        self._algo_confidence: Dict[str, float] = {}  # 训练完成时记录的置信度

        # 算法行标签引用（用于动态更新状态/置信度）
        self._algo_row_refs: Dict[str, List[tk.Widget]] = {}

        # 日志存盘
        self._log_dir = project_path("data", "log", "training")
        self._log_file: Optional[io.TextIOWrapper] = None
        self._log_file_path: str = ""
        self._saved_title: Optional[str] = None  # 训练时保存的窗口标题

        self._build_ui()

    # ══════════════════════════════════════════════
    # UI 构建
    # ══════════════════════════════════════════════

    def _build_ui(self):
        """构建训练面板的完整 UI 布局"""
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
        body.grid_columnconfigure(0, weight=35, minsize=280)
        body.grid_columnconfigure(1, weight=65, minsize=400)
        body.grid_rowconfigure(0, weight=1)

        self._build_algo_section(body)
        self._build_chart_section(body)

        # ── 底部控制栏 ──
        self._build_controls(outer)

    # ── 算法列表 (左侧) ──

    def _build_algo_section(self, parent):
        """构建左侧算法列表区域"""
        left = tk.Frame(parent, bg=C["bg_surface"])
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_rowconfigure(1, weight=1)

        hdr = tk.Frame(left, bg=C["bg_surface"])
        hdr.pack(fill=tk.X, padx=4, pady=(4, 0))
        tk.Label(hdr, text="可训练算法（PyTorch）", bg=C["bg_surface"], fg=C["text_1"], font=FONT_BOLD).pack(
            side=tk.LEFT
        )
        self._algo_count_lbl = tk.Label(hdr, text="", bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM)
        self._algo_count_lbl.pack(side=tk.RIGHT, padx=4)

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

        # 表头：复选框、算法名、ID、状态、置信度、版本
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
        """构建右侧图表和日志区域"""
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
        """构建底部训练控制栏"""
        ctrl = tk.Frame(parent, bg=C["bg_elevated"])
        ctrl.pack(fill=tk.X, padx=8, pady=(0, 6))

        # 训练参数
        tk.Label(ctrl, text="Epoch:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT, padx=(8, 2))
        self._epoch_var = tk.IntVar(value=20)
        ttk.Spinbox(ctrl, from_=1, to=500, textvariable=self._epoch_var, width=6).pack(side=tk.LEFT, padx=2)

        tk.Label(ctrl, text="Batch:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT, padx=(8, 2))
        self._batch_var = tk.IntVar(value=32)
        ttk.Spinbox(ctrl, from_=1, to=512, textvariable=self._batch_var, width=6).pack(side=tk.LEFT, padx=2)

        # 学习率
        tk.Label(ctrl, text="LR:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT, padx=(8, 2))
        self._lr_var = tk.StringVar(value="0.001")
        self._lr_entry = ttk.Entry(ctrl, textvariable=self._lr_var, width=8, font=FONT_MONO)
        self._lr_entry.pack(side=tk.LEFT, padx=2)
        self._lr_auto_var = tk.BooleanVar(value=True)
        self._lr_auto_cb = ttk.Checkbutton(
            ctrl, text="自动", variable=self._lr_auto_var, command=self._on_lr_auto_toggle
        )
        self._lr_auto_cb.pack(side=tk.LEFT, padx=2)

        # 训练模式：增量训练 / 重新训练
        tk.Label(ctrl, text="模式:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT, padx=(8, 2))
        self._mode_var = tk.StringVar(value="incremental")
        ttk.Radiobutton(ctrl, text="增量训练", variable=self._mode_var, value="incremental").pack(side=tk.LEFT, padx=1)
        ttk.Radiobutton(ctrl, text="重新训练", variable=self._mode_var, value="retrain", state=_train()).pack(
            side=tk.LEFT, padx=1
        )

        # 并行训练数
        tk.Label(ctrl, text="并行:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT, padx=(8, 2))
        self._parallel_var = tk.IntVar(value=2)
        ttk.Spinbox(ctrl, from_=1, to=4, textvariable=self._parallel_var, width=3).pack(side=tk.LEFT, padx=2)

        # 详细日志（batch 级进度 + 用户自定义间隔）
        self._batch_log_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(ctrl, text="详细日志", variable=self._batch_log_var).pack(side=tk.LEFT, padx=(4, 2))
        tk.Label(ctrl, text="每", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT)
        self._batch_interval_val = tk.StringVar(value="10")
        ttk.Entry(ctrl, textvariable=self._batch_interval_val, width=3, font=FONT_MONO).pack(side=tk.LEFT, padx=1)
        self._batch_interval_unit = tk.StringVar(value="%")
        ttk.Combobox(ctrl, textvariable=self._batch_interval_unit, values=["%", "个"], width=3, state="readonly").pack(side=tk.LEFT)

        # 按钮
        self._train_btn = ttk.Button(
            ctrl, text="▶ 开始训练", command=self._on_train_start, style="Primary.TButton", state=_train()
        )
        self._train_btn.pack(side=tk.LEFT, padx=(12, 4))
        self._cancel_btn = ttk.Button(ctrl, text="✕ 取消", command=self._on_cancel, state="disabled")
        self._cancel_btn.pack(side=tk.LEFT, padx=4)
        self._skip_btn = ttk.Button(ctrl, text="⏭ 跳过当前", command=self._on_skip_algo, state="disabled")
        self._skip_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="🎯 批量微调", command=self._on_batch_finetune, width=10, state=_train()).pack(
            side=tk.LEFT, padx=4
        )

        if _train() != "normal":
            tk.Label(
                ctrl,
                text="💡 创建 .enabletraining 文件开启训练 / 完整 devmode 见 README.md",
                bg=C["bg_elevated"],
                fg=C["warning"],
                font=("", 8),
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
        """此面板被切换到前台时调用"""
        self._refresh_device()
        self._refresh_data_size()
        self._refresh_algo_list()

    def _refresh_all(self):
        """刷新所有数据：设备、数据规模、算法列表"""
        self._refresh_device()
        self._refresh_data_size()
        self._refresh_algo_list()

    def _refresh_device(self):
        """刷新训练设备信息显示"""
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
        """自动/手动学习率切换：自动时锁定输入框，并填入推荐值。"""
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
        """根据数据规模和常用经验自动推荐学习率。"""
        try:
            from algorithms.training.trainer import ModelTrainer

            info = ModelTrainer().estimate_data_size()
            samples = info.get("total_samples", 1000)
        except Exception:
            samples = 1000

        # 样本越多 → 学习率应越小（避免在大数据集上震荡）
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
        """刷新数据规模估算信息（异步线程）"""
        self._data_lbl.config(text="估算中…", fg=C["text_3"])

        def _worker():
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
        """扫描有 build_model 的算法"""
        from algorithms.registry import AlgorithmRegistry

        return AlgorithmRegistry.get_trainable_info()

    def _refresh_algo_list(self):
        """刷新算法列表，显示每个算法的状态、置信度和版本"""
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

            var = tk.BooleanVar(value=not a["has_ckpt"])
            self._check_vars[aid] = var
            ttk.Checkbutton(row, variable=var).grid(row=0, column=0, padx=4, pady=2)

            tk.Label(row, text=a["name"], bg=C["bg_surface"], fg=C["text_1"], font=FONT, width=16, anchor="w").grid(
                row=0, column=1, padx=2, sticky="w"
            )
            tk.Label(row, text=aid, bg=C["bg_surface"], fg=C["text_3"], font=FONT_MONO, width=14, anchor="w").grid(
                row=0, column=2, padx=2, sticky="w"
            )

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
        """仅选中尚未训练的算法"""
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
        """动态更新算法列表行的状态/置信度/版本列。"""
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
        """打开 checkpoint 版本管理对话框 — 查看/删除/激活版本。"""
        from algorithms.training.checkpoint_manager import CheckpointManager
        from algorithms.registry import AlgorithmRegistry

        AlgorithmRegistry.initialize()
        algos = []
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
            self._draw_version_detail(detail_frame, info_lbl, aid, name, _refresh_detail)

        self._draw_version_list(algo_inner, algos, _refresh_detail)

    def _draw_manage_dialog(self):
        """构建版本管理对话框骨架，返回 (dialog, info_lbl, detail_frame, algo_inner)"""
        dialog = tk.Toplevel(self.frame)
        dialog.title("Checkpoint 版本管理")
        dialog.geometry("700x500")
        dialog.transient(self.frame)
        dialog.grab_set()
        dialog.configure(bg=C["bg_base"])

        main = tk.Frame(dialog, bg=C["bg_base"])
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left_panel = tk.Frame(main, bg=C["bg_elevated"], width=220)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 6))
        left_panel.pack_propagate(False)
        tk.Label(left_panel, text="算法", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(
            fill=tk.X, padx=4, pady=4
        )

        algo_sf = ScrollableFrame(left_panel, bg=C["bg_elevated"])
        algo_sf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        algo_inner = algo_sf.inner

        right_panel = tk.Frame(main, bg=C["bg_surface"])
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        info_lbl = tk.Label(right_panel, text="← 选择一个算法", bg=C["bg_surface"], fg=C["text_3"], font=FONT)
        info_lbl.pack(pady=20)

        detail_frame = tk.Frame(right_panel, bg=C["bg_surface"])
        detail_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        return dialog, info_lbl, detail_frame, algo_inner

    def _draw_version_list(self, algo_inner, algos, refresh_cb):
        """填充左侧算法列表按钮"""
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
        """刷新指定算法的版本详情面板"""
        from algorithms.training.checkpoint_manager import CheckpointManager, list_video_finetune_bvids

        for w in detail_frame.winfo_children():
            w.destroy()

        info_lbl.pack_forget()

        tk.Label(detail_frame, text=f"{name}  ({aid})", bg=C["bg_surface"], fg=C["text_1"], font=FONT_BOLD).pack(
            anchor="w", pady=(0, 6)
        )

        ckpt = CheckpointManager(aid)

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

                if not v.get("active") and len(versions) > 1:
                    ttk.Button(
                        row,
                        text="激活",
                        width=4,
                        command=lambda ver=v["version"], c=ckpt, a=aid, n=name, cb=refresh_cb: (
                            self._activate_version(c, ver, a, n, cb)
                        ),
                    ).pack(side=tk.RIGHT, padx=2)

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

                vl = v.get("val_loss", -1)
                vl_txt = f"  val_loss={vl:.4f}" if vl >= 0 else ""
                tk.Label(row, text=vl_txt, bg=C["bg_elevated"], fg=C["text_3"], font=FONT_SM).pack(side=tk.LEFT)

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
                    ttk.Button(
                        row,
                        text="✕",
                        width=3,
                        command=lambda b=bvid, ver=v["version"], a=aid, n=name, cb=refresh_cb: (
                            CheckpointManager(a, bvid=b).delete(ver),
                            cb(a, n),
                        ),
                    ).pack(side=tk.RIGHT, padx=2)

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
                    "algorithms",
                    "checkpoints",
                    aid,
                )
                tk.Label(
                    btn_row,
                    text=f"📁 {os.path.relpath(ckpt_dir)}",
                    bg=C["bg_surface"],
                    fg=C["text_3"],
                    font=FONT_SM,
                ).pack(side=tk.LEFT, padx=4)

    def _activate_version(self, ckpt, ver, aid, name, refresh_cb):
        """激活指定版本并刷新详情"""
        ckpt.activate(ver)
        refresh_cb(aid, name)

    def _delete_all_global(self, aid, name, refresh_cb):
        """删除算法的所有全局 checkpoint。"""
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
        """删除算法的所有视频微调 checkpoint。"""
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
        """打开批量微调对话框：选择视频 + 算法，一键微调。"""
        from algorithms.registry import AlgorithmRegistry
        from algorithms.training.checkpoint_manager import CheckpointManager

        AlgorithmRegistry.initialize()
        algo_list = []
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
            ui["log_text"].config(state="normal")
            ui["log_text"].insert(tk.END, msg + "\n")
            ui["log_text"].see(tk.END)
            ui["log_text"].config(state="disabled")

        def _start_ft():
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

            threading.Thread(
                target=lambda: self._start_batch_worker(
                    selected_videos,
                    selected_algos,
                    epochs,
                    batch,
                    total,
                    dialog,
                    ui,
                    _ft_log,
                ),
                daemon=True,
            ).start()

        ui["start_btn"].config(command=_start_ft)
        ui["cancel_btn"].config(command=dialog.destroy)

    def _build_batch_dialog(self, algo_list, videos):
        """构建批量微调对话框，返回 (dialog, ui_dict)"""
        dialog = tk.Toplevel(self.frame)
        dialog.title("批量微调")
        dialog.geometry("650x500")
        dialog.transient(self.frame)
        dialog.grab_set()
        dialog.configure(bg=C["bg_base"])

        main = tk.Frame(dialog, bg=C["bg_base"])
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        tk.Label(main, text="选择视频", bg=C["bg_base"], fg=C["text_1"], font=FONT_BOLD).pack(anchor="w", pady=(0, 2))
        video_frame = tk.Frame(main, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border"])
        video_frame.pack(fill=tk.X, pady=(0, 8))
        v_sf = ScrollableFrame(video_frame, bg=C["bg_elevated"], height=100)
        v_sf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        v_inner = v_sf.inner

        video_vars = {}
        for v in sorted(videos, key=lambda x: x["bvid"]):
            var = tk.BooleanVar(value=True)
            video_vars[v["bvid"]] = var
            row = tk.Frame(v_inner, bg=C["bg_elevated"])
            row.pack(fill=tk.X)
            ttk.Checkbutton(row, variable=var).pack(side=tk.LEFT, padx=2)
            tk.Label(
                row, text=f"{v['title']}  ({v['bvid']})", bg=C["bg_elevated"], fg=C["text_1"], font=FONT_SM, anchor="w"
            ).pack(side=tk.LEFT, padx=2, fill=tk.X)

        tk.Label(main, text="选择算法", bg=C["bg_base"], fg=C["text_1"], font=FONT_BOLD).pack(anchor="w", pady=(0, 2))
        algo_frame = tk.Frame(main, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border"])
        algo_frame.pack(fill=tk.X, pady=(0, 8))
        a_sf = ScrollableFrame(algo_frame, bg=C["bg_elevated"], height=100)
        a_sf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        a_inner = a_sf.inner

        algo_vars = {}
        for a in sorted(algo_list, key=lambda x: x["name"]):
            var = tk.BooleanVar(value=True)
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

        param_row = tk.Frame(main, bg=C["bg_base"])
        param_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(param_row, text="Epochs:", bg=C["bg_base"], fg=C["text_2"], font=FONT_SM).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ft_epoch_var = tk.IntVar(value=5)
        ttk.Spinbox(param_row, from_=1, to=100, textvariable=ft_epoch_var, width=6).pack(side=tk.LEFT, padx=(0, 16))
        tk.Label(param_row, text="Batch:", bg=C["bg_base"], fg=C["text_2"], font=FONT_SM).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ft_batch_var = tk.IntVar(value=16)
        ttk.Spinbox(param_row, from_=1, to=512, textvariable=ft_batch_var, width=6).pack(side=tk.LEFT)

        ft_status = tk.Label(main, text="就绪", bg=C["bg_base"], fg=C["text_3"], font=FONT_SM, anchor="w")
        ft_status.pack(fill=tk.X, pady=(0, 4))
        ft_progress = ttk.Progressbar(main, mode="determinate", maximum=100)
        ft_progress.pack(fill=tk.X, pady=(0, 8))

        log_text = tk.Text(
            main, bg=C["bg_base"], fg=C["text_1"], font=("Consolas", 9), relief="flat", height=6, state="disabled"
        )
        log_text.pack(fill=tk.BOTH, expand=True)

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
        """后台工作线程：依次对每个视频的每个算法进行微调"""
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
        """批量微调完成后的 UI 更新回调"""
        dialog.after(0, lambda: ui["ft_status"].configure(text=f"✅ 微调完成 ({done} 任务)"))
        dialog.after(0, lambda: ui["ft_progress"].config(value=100))
        dialog.after(0, lambda: self.main.set_finetune_status(f"✅ 批量微调完成 ({done})"))
        dialog.after(0, lambda: ui["start_btn"].config(state="normal"))
        dialog.after(0, lambda: _ft_log("🏁 批量微调全部完成"))

    # ══════════════════════════════════════════════
    # 训练执行
    # ══════════════════════════════════════════════

    def _on_train_start(self):
        """开始训练按钮回调 — 验证参数、确认、启动训练线程"""
        config = self._validate_train_params()
        if config is None:
            return

        selected, epochs, batch, is_incremental, lr, mode_label, lr_label, parallel, batch_log, interval_val, interval_unit = config
        self._build_train_config(selected, epochs, batch, mode_label, lr)
        self._start_train_thread(selected, is_incremental, lr, epochs, batch, parallel, batch_log, interval_val, interval_unit)

    def _validate_train_params(self):
        """校验训练参数并弹出确认对话框，返回训练配置或 None"""
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

        # 并行数 + VRAM 安全检查
        parallel = max(1, min(4, int(self._parallel_var.get())))
        if parallel > len(selected):
            parallel = len(selected)
        parallel_warning = ""
        try:
            from algorithms.training.device import get_device_info
            dev_info = get_device_info()
            if dev_info.get("is_gpu") and dev_info.get("total_memory_gb", 0) > 0:
                vram_gb = dev_info["total_memory_gb"]
                # 保守估计每个模型 ~0.4GB（实际模型多数 < 50MB，0.4GB 已含余量）
                est_per_model_gb = 0.4
                max_safe = max(1, int(vram_gb / est_per_model_gb))
                if parallel > max_safe:
                    parallel = max_safe
                    parallel_warning = (
                        f"\n⚠️ 显存安全限制：{vram_gb:.1f}GB 显存，"
                        f"自动降为并行 {parallel}（避免炸显存）"
                    )
        except Exception:
            pass

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
            lr = max(1e-8, min(1.0, lr))
            lr_label = f"手动 ({lr:.6f})"

        if not messagebox.askyesno(
            "确认训练",
            f"模式: {mode_label}  并行: {parallel}\n"
            f"算法: {len(selected)} 个\n"
            f"epoch={epochs}  batch={batch}  LR={lr_label}"
            f"{parallel_warning}\n"
            f"训练过程不可中途暂停（只能取消未开始的算法）。",
            parent=self.frame,
        ):
            return None

        return (selected, epochs, batch, is_incremental, lr, mode_label, lr_label, parallel, self._batch_log_var.get(), self._batch_interval_val.get(), self._batch_interval_unit.get())

    def _build_train_config(self, selected, epochs, batch, mode_label, lr):
        """重置训练状态、打开日志文件、更新状态标签"""
        self._prepare_training()
        self._open_log_file(len(selected), epochs, batch, mode_label, lr)
        self._append_log(
            f"🚀 开始训练: {mode_label}, {len(selected)} 个算法, epoch={epochs}, batch={batch}, lr={lr:.6f}"
        )
        if self._batch_log_var.get():
            val = self._batch_interval_val.get()
            unit = self._batch_interval_unit.get()
            self._append_log(f"📋 详细日志：每 {val}{unit} batch 输出进度")
        self._status_lbl.config(text=f"准备训练 {len(selected)} 个算法 …", fg=C["text_2"])

        # ── 全局反馈：窗口标题 + 主界面状态栏 ──
        try:
            top = self.frame.winfo_toplevel()
            self._saved_title = top.title()
            top.title(f"🔴 训练中 — {self._saved_title}")
        except Exception:
            self._saved_title = None
        try:
            self.main._sb("algo", f"🤖 训练: 0/{len(selected)} 算法", color=C["accent"])
            self.main._sb("status", "训练中…", color=C["accent"])
        except Exception:
            pass
        self._algo_durations: List[float] = []  # 各算法耗时（用于跨算法 ETA）

    def _start_train_thread(self, selected, is_incremental, lr, epochs, batch, parallel, batch_log, interval_val, interval_unit):
        """启动训练线程（支持并行模式 + 可配置 batch 级日志间隔）"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        total = len(selected)
        algo_lr_factors: Dict[str, float] = {}
        completed_count = [0]

        # 解析 batch 日志间隔
        batch_interval = None
        batch_interval_mode = "%"  # % 或 count
        try:
            val = float(interval_val)
            if interval_unit == "%":
                val = max(1, min(100, val))  # 限制 1%~100%
                batch_interval = val / 100.0  # 转为比例
                batch_interval_mode = "%"
            else:
                val = max(1, int(val))
                batch_interval = val
                batch_interval_mode = "count"
        except (ValueError, TypeError):
            batch_interval = 0.1  # 默认 10%
            batch_interval_mode = "%"

        def _cb(payload: Dict):
            """训练回调 — 线程安全。batch_log 关闭时过滤 batch 消息。"""
            payload["_total_selected"] = total
            payload["_incremental"] = is_incremental

            if not batch_log and payload.get("stage") == "batch":
                return

            if self._skip_algo_flag[0]:
                payload["_adjustment"] = "⏭ 用户手动跳过"
                payload["early_stop"] = True
                self._train_queue.put(payload)
                return

            self._train_queue.put(payload)

        def _train_one_algo(aid):
            """在独立线程中训练单个算法。每个算法有自己的 trainer/control/monitor。"""
            if self._cancel_flag[0]:
                return aid, False

            try:
                from algorithms.training.trainer import ModelTrainer

                # 非增量模式：清除旧 checkpoint
                if not is_incremental:
                    from algorithms.training.checkpoint_manager import CheckpointManager
                    _ckpt = CheckpointManager(aid)
                    _n = _ckpt.delete_all()
                    if _n:
                        self._train_queue.put({"stage": "log", "text": f"  🗑 已清除 {aid} 的 {_n} 个旧版本"})

                self._skip_algo_flag[0] = False
                self.frame.after(0, lambda: self._skip_btn.config(state="normal"))

                aid_factor = algo_lr_factors.get(aid, 1.0)
                effective_lr = lr * aid_factor
                control = {}
                # 注入 batch 日志间隔配置
                if batch_log and batch_interval is not None:
                    control["_batch_interval"] = batch_interval
                    control["_batch_interval_mode"] = batch_interval_mode
                trainer = ModelTrainer()
                sub = trainer.train_global(
                    [aid],
                    epochs=epochs,
                    batch_size=batch,
                    progress_cb=_cb,
                    init_from_global=is_incremental,
                    lr=effective_lr,
                    control_dict=control,
                )
                completed_count[0] += 1
                return aid, bool(sub.get(aid))
            except Exception as e:
                self._train_queue.put({"stage": "error", "algo_id": aid, "current": completed_count[0], "total": total, "error": str(e)})
                return aid, False

        def _worker():
            """并行训练调度线程"""
            try:
                results = {}
                if parallel <= 1:
                    # 串行模式（保持原有行为）
                    for aid in selected:
                        if self._cancel_flag[0]:
                            self._train_queue.put({"stage": "cancelled", "remaining": selected[completed_count[0]:]})
                            break
                        ok, success = _train_one_algo(aid)
                        results[ok] = ok if success else ""
                else:
                    # 并行模式
                    self._append_log(f"⚡ 并行训练 ({parallel} 线程)")
                    with ThreadPoolExecutor(max_workers=parallel) as pool:
                        futures = {pool.submit(_train_one_algo, aid): aid for aid in selected}
                        for f in as_completed(futures):
                            if self._cancel_flag[0]:
                                # 取消剩余任务
                                for remaining_f in futures:
                                    if not remaining_f.done():
                                        remaining_f.cancel()
                                remaining_aids = [futures[rf] for rf in futures if not rf.done()]
                                self._train_queue.put({"stage": "cancelled", "remaining": remaining_aids})
                                break
                            aid, success = f.result()
                            results[aid] = aid if success else ""

                self._train_queue.put({"stage": "all_done", "results": results})
            except Exception as e:
                self._train_queue.put({"stage": "fatal", "error": str(e)})

        self._launch_worker(_worker)

    def _on_cancel(self):
        """取消训练按钮回调"""
        self._cancel_flag[0] = True
        if self._cancel_btn:
            self._cancel_btn.config(state="disabled")
        self._status_lbl.config(text="正在取消（等待当前算法完成）…", fg=C["warning"])
        self._append_log("⏹ 用户请求取消训练")
        self._close_log_file()

    def _on_skip_algo(self):
        """跳过当前正在训练的算法，继续下一个。"""
        self._skip_algo_flag[0] = True
        if self._skip_btn:
            self._skip_btn.config(state="disabled")
        self._status_lbl.config(text="⏭ 跳过当前算法（等待本轮完成）…", fg=C["warning"])
        self._append_log("⏭ 用户请求跳过当前算法")

    STAGE_HANDLERS = {
        "start": "_on_stage_start",
        "batch": "_on_stage_batch",
        "epoch": "_on_stage_epoch",
        "done": "_on_stage_done",
        "error": "_on_stage_error",
        "auto_adjust": "_on_stage_auto_adjust",
        "cancelled": "_on_stage_cancelled",
        "all_done": "_on_stage_all_done",
        "fatal": "_on_stage_fatal",
    }

    def _handle_stage(self, msg) -> bool:
        """根据消息 stage 分发给对应的事件处理器"""
        stage = msg.get("stage")
        handler_name = self.STAGE_HANDLERS.get(stage)
        if handler_name:
            return getattr(self, handler_name)(msg)
        return False

    def _on_stage_start(self, msg):
        """处理训练开始事件"""
        aid = msg.get("algo_id", "?")
        cur = msg.get("current", 0)
        tot = msg.get("total", 1)
        self._current_aid = aid
        self._total_algos = tot
        self._algo_start_time = time.time()
        self._epoch_times: List[float] = []  # 当前算法各 epoch 耗时（秒）
        self._last_epoch_elapsed = 0.0
        self._status_lbl.config(text=f"[{cur}/{tot}] 训练 {aid} …", fg=C["text_2"])
        self._append_log(f"── [{cur}/{tot}] 开始训练 {aid} ──")
        self._update_algo_row(aid, status="▶ 训练中", status_color=C["accent"])
        self._monitor.reset()
        # 状态栏 + 进度条动画
        try:
            self.main._sb("algo", f"🤖 [{cur}/{tot}] {aid}", color=C["accent"])
        except Exception:
            pass
        if self._progress:
            self._progress["value"] = 0
            self._progress.configure(mode="determinate")

    def _on_stage_batch(self, msg):
        """处理每 10% batch 完成事件 — 更新主窗口状态栏（轻量，不写日志）"""
        aid = msg.get("algo_id", "?")
        b = msg.get("batch", 0)
        tot_b = msg.get("total_batches", 1)
        avg_loss = msg.get("avg_loss", 0)
        try:
            self.main._sb("status", f"🔄 {aid} batch {b}/{tot_b} loss={avg_loss:.4f}", color=C["text_2"])
        except Exception:
            pass
        return False

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        """格式化时长为可读字符串"""
        if seconds < 0:
            return "--"
        if seconds < 60:
            return f"{seconds:.0f}s"
        if seconds < 3600:
            m, s = divmod(int(seconds), 60)
            return f"{m}m{s}s" if s > 0 else f"{m}m"
        h, r = divmod(int(seconds), 3600)
        m = r // 60
        return f"{h}h{m}m" if m > 0 else f"{h}h"

    def _on_stage_epoch(self, msg):
        """处理每个 epoch 完成事件 — 更新图表、进度、日志、EMA 加权 ETA"""
        aid = msg.get("algo_id", "?")
        ep = msg.get("epoch", 0)
        eps = msg.get("epochs", 1)
        tloss = msg.get("train_loss", 0.0)
        vloss = msg.get("val_loss", -1.0)
        elapsed = msg.get("elapsed_s", 0.0)

        conf = loss_to_confidence(vloss) if vloss >= 0 else 0.0
        conf_str, conf_color = format_confidence(conf)

        if ep == 1 or ep % 5 == 0 or ep == eps:
            self._update_algo_row(aid, conf=conf_str, conf_color=conf_color)

        pct = min(100, int((ep / max(1, eps)) * 100))
        self._progress["value"] = pct
        vtxt = f"  val={vloss:.4f}" if vloss >= 0 else ""

        # ── EMA 加权 ETA：最近 epoch 权重更高 ──
        epoch_duration = max(0, elapsed - self._last_epoch_elapsed)
        self._last_epoch_elapsed = elapsed
        if epoch_duration > 0 and epoch_duration < 3600:  # 排除异常值
            self._epoch_times.append(epoch_duration)
            if len(self._epoch_times) > 10:
                self._epoch_times = self._epoch_times[-10:]

        total_eta_str = ""
        if self._epoch_times:
            # EMA：衰减因子 0.7，最近 epoch 权重指数级更高
            alpha = 0.7
            recent_weights = [alpha ** (len(self._epoch_times) - 1 - i) for i in range(len(self._epoch_times))]
            weight_sum = sum(recent_weights)
            ema_epoch = sum(t * w for t, w in zip(self._epoch_times, recent_weights)) / max(weight_sum, 1e-10)

            # 本算法剩余时间
            algo_remaining = ema_epoch * (eps - ep)
            algo_eta = self._fmt_duration(algo_remaining)

            # 总训练剩余时间 = 本算法剩余 + 未开始算法预估
            cur = msg.get("current", 0)
            tot = msg.get("total", 1)
            remaining_algos = tot - cur
            if remaining_algos > 0 and hasattr(self, "_algo_durations") and self._algo_durations:
                avg_algo_time = sum(self._algo_durations) / len(self._algo_durations)
                # 已完成算法数较少时，用本算法当前速率补充
                if len(self._algo_durations) < 2:
                    avg_algo_time = max(avg_algo_time, ema_epoch * eps * 0.8)
                other_remaining = avg_algo_time * (remaining_algos - 1)  # -1 因为当前算法已在算
            else:
                # 无历史数据：用本算法速率外推
                other_remaining = ema_epoch * eps * max(0, remaining_algos - 1)

            total_remaining = algo_remaining + other_remaining
            total_eta_str = f"  ⏱本{algo_eta} 总{self._fmt_duration(total_remaining)}"

        self._status_lbl.config(
            text=f"{aid}  ep{ep}/{eps}  train={tloss:.4f}{vtxt}  {conf_str}  {elapsed:.0f}s{total_eta_str}",
            fg=C["text_1"],
        )

        # 主窗口状态栏（含 ETA）
        try:
            cur = msg.get("current", 0)
            tot = msg.get("total", 1)
            status_text = f"🤖 [{cur}/{tot}] {aid} ep{ep}/{eps}  {elapsed:.0f}s"
            if total_eta_str:
                # 提取总 ETA 部分
                parts = total_eta_str.split("总")
                if len(parts) > 1:
                    status_text += f"  ⇨{parts[1]}"
            self.main._sb("algo", status_text, color=C["accent"])
            self.main._sb("status", f"训练中  loss={tloss:.4f}", color=C["text_2"])
        except Exception:
            pass

        self._monitor.update(ep, tloss, vloss if vloss >= 0 else -1)
        self._refresh_monitor()

        adj = msg.get("_adjustment", "")
        if adj:
            self._append_log(f"  {adj}")

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
        """处理单个算法训练完成事件"""
        total_sel = msg.get("_total_selected", 1)
        aid = msg.get("algo_id", "?")
        cur = msg.get("current", 0)
        ver = msg.get("version", "")
        algo_elapsed = time.time() - getattr(self, "_algo_start_time", time.time())

        # 记录算法耗时用于跨算法 ETA
        if not hasattr(self, "_algo_durations"):
            self._algo_durations = []
        self._algo_durations.append(algo_elapsed)

        self._status_lbl.config(text=f"✓ {aid} → {ver} ({cur}/{total_sel})  {algo_elapsed:.0f}s", fg=C["success"])
        self._progress["value"] = int(cur / max(1, total_sel) * 100)

        # 计算总体 ETA
        remaining = total_sel - cur
        total_eta = ""
        if remaining > 0 and self._algo_durations:
            avg_dur = sum(self._algo_durations) / len(self._algo_durations)
            total_eta = f"  ⇨剩余≈{self._fmt_duration(avg_dur * remaining)}"

        # 主窗口状态栏
        try:
            self.main._sb("algo", f"🤖 ✓ [{cur}/{total_sel}] {aid}  {algo_elapsed:.0f}s{total_eta}", color=C["success"])
        except Exception:
            pass

        # 从 checkpoint 读取 val_loss 和置信度
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
        """处理训练错误事件"""
        aid = msg.get("algo_id", "?")
        err = msg.get("error", "")
        self._status_lbl.config(text=f"✗ {aid} 失败: {err}", fg=C["danger"])
        self._append_log(f"✗ {aid} 训练失败: {err}")
        self._update_algo_row(aid, status="✗ 失败", status_color=C["danger"])
        try:
            self.main._sb("algo", f"🤖 ✗ {aid} 失败", color=C["danger"])
        except Exception:
            pass

    def _on_stage_auto_adjust(self, msg):
        """处理自动调整事件"""
        message = msg.get("message", "")
        self._append_log(f"  🔧 自动调整: {message}")
        self._status_lbl.config(text=f"⚡ {message}", fg=C["warning"])

    def _on_stage_cancelled(self, msg):
        """处理取消训练事件"""
        rem = msg.get("remaining", [])
        self._status_lbl.config(text=f"已取消，剩余 {len(rem)} 个", fg=C["warning"])
        self._append_log(f"⏹ 已取消, 剩余 {len(rem)} 个算法")
        try:
            self.main._sb("algo", f"⏹ 训练已取消 (剩余{len(rem)}个)", color=C["warning"])
        except Exception:
            pass
        return True

    def _on_stage_all_done(self, msg):
        """处理所有算法训练完成事件"""
        results = msg.get("results", {})
        self._last_training_results = results
        ok = sum(1 for v in results.values() if v)
        bad = sum(1 for v in results.values() if not v)
        elapsed = time.time() - self._train_t0 if self._train_t0 else 0

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
        # 主窗口状态栏
        try:
            self.main._sb("algo", f"🤖 ✓ 训练完成 ({ok}成功 {bad}失败)  {elapsed:.0f}s", color=C["success"])
        except Exception:
            pass
        return True

    def _on_stage_fatal(self, msg):
        """处理训练进程致命错误事件"""
        err = msg.get("error", "")
        self._status_lbl.config(text=f"训练异常: {err}", fg=C["danger"])
        self._append_log(f"💥 训练进程异常: {err}")
        return True

    def _cleanup_training(self):
        """训练清理：关闭日志、刷新列表、通知完成"""
        self._close_log_file()
        super()._cleanup_training()
        self._refresh_algo_list()
        try:
            self.main._refresh_model_status()
        except Exception as e:
            logger.debug("忽略异常: %s", e)

        # 恢复窗口标题和状态栏
        try:
            if self._saved_title:
                self.frame.winfo_toplevel().title(self._saved_title)
        except Exception:
            pass
        try:
            self.main._sb("status", "就绪", color=C["text_3"])
        except Exception:
            pass

        # 训练自动回调：通知 + 重新预测
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
        """日志记录：状态变化时记录，同状态每 8 epoch 持续监测提醒。"""
        if self._monitor.level in ("warning", "danger") and self._monitor.suggestions:
            cur_status = self._monitor.status
            last_status = getattr(self, "_last_monitor_status", "")
            last_epoch = getattr(self, "_last_monitor_log_epoch", 0)
            cur_epoch = len(self._monitor._points)

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
        """根据 TrainingMonitor 的 loss 数据动态计算推荐学习率。"""
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
        """创建训练日志文件。"""
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
        """关闭训练日志文件。"""
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

    def __del__(self):
        """析构时兜底关闭日志文件，防止异常路径下文件句柄泄漏。"""
        if getattr(self, "_log_file", None) is not None:
            try:
                self._log_file.flush()
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None

    def _append_log(self, text: str):
        """追加日志到 UI 和文件"""
        super()._append_log(text)
        if self._log_file is not None:
            try:
                line = f"[{time.strftime('%H:%M:%S')}] {text}\n"
                self._log_file.write(line)
                self._log_file.flush()
            except Exception as e:
                logger.debug("写入训练日志文件失败: %s", e)
