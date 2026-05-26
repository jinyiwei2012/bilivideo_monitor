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
from typing import Any, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

_torch_available = True
try:
    import torch  # noqa: F401
except ImportError:
    _torch_available = False

from ui.mpl_imports import mpl_available, Figure, FigureCanvasTkAgg

from ui.theme import C
from ui.helpers import (
    FONT,
    FONT_SM,
    FONT_MONO,
    FONT_BOLD,
    loss_to_confidence,
    format_confidence,
    load_algo_confidence,
    clear_loss_chart,
    project_path,
)
from ui.scrollable_frame import ScrollableFrame
from ui.training_base import BaseTrainingPanel, TrainingMonitor


class TrainingPanel(BaseTrainingPanel):
    """训练面板 - 主界面选项卡"""

    def __init__(self, parent: tk.Widget, main_gui):
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

        self._build_ui()

    # ══════════════════════════════════════════════
    # UI 构建
    # ══════════════════════════════════════════════

    def _build_ui(self):
        outer = self.frame

        # ── 顶部信息栏 ──
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
        ttk.Button(toolbar, text="反选", command=lambda: self._select_all(False), width=6).pack(side=tk.LEFT, padx=1)
        ttk.Button(toolbar, text="仅未训练", command=self._select_untrained, width=8).pack(side=tk.LEFT, padx=1)
        ttk.Button(toolbar, text="🗑️ 版本管理", command=self._on_manage_versions, width=10).pack(side=tk.LEFT, padx=1)

        # 滚动容器
        sf = ScrollableFrame(left, bg=C["bg_elevated"], height=300)
        sf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._algo_frame = sf.inner

        # 表头
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

        # 训练模式
        tk.Label(ctrl, text="模式:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT, padx=(8, 2))
        self._mode_var = tk.StringVar(value="incremental")
        ttk.Radiobutton(ctrl, text="增量训练", variable=self._mode_var, value="incremental").pack(side=tk.LEFT, padx=1)
        ttk.Radiobutton(ctrl, text="重新训练", variable=self._mode_var, value="retrain").pack(side=tk.LEFT, padx=1)

        # 按钮
        self._train_btn = ttk.Button(ctrl, text="▶ 开始训练", command=self._on_train_start, style="Primary.TButton")
        self._train_btn.pack(side=tk.LEFT, padx=(12, 4))
        self._cancel_btn = ttk.Button(ctrl, text="✕ 取消", command=self._on_cancel, state="disabled")
        self._cancel_btn.pack(side=tk.LEFT, padx=4)
        self._skip_btn = ttk.Button(ctrl, text="⏭ 跳过当前", command=self._on_skip_algo, state="disabled")
        self._skip_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="🎯 批量微调", command=self._on_batch_finetune, width=10).pack(side=tk.LEFT, padx=4)

        # 进度
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
        self._refresh_device()
        self._refresh_data_size()
        self._refresh_algo_list()

    def _refresh_device(self):
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
        self._refresh_device()

    # ── 学习率控制 ────────────────────────────────

    def _on_lr_auto_toggle(self):
        """自动/手动学习率切换：自动时锁定输入框，并填入推荐值。"""
        if self._lr_auto_var.get():
            self._lr_entry.config(state="readonly")
            auto_lr = self._auto_compute_lr()
            self._lr_var.set(f"{auto_lr:.6f}")
        else:
            self._lr_entry.config(state="normal")

    def _auto_compute_lr(self) -> float:
        """根据数据规模和常用经验自动推荐学习率。"""
        try:
            from algorithms.training.trainer import ModelTrainer

            info = ModelTrainer().estimate_data_size()
            samples = info.get("total_samples", 1000)
        except Exception:
            samples = 1000

        # 启发式规则：
        # 样本越多 → 学习率应越小（避免在大数据集上震荡）
        # 基础值 1e-3 (Adam 常用默认值)
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
        self._data_lbl.config(text="估算中…", fg=C["text_3"])

        def _worker():
            try:
                from algorithms.training.trainer import ModelTrainer

                info = ModelTrainer().estimate_data_size()
                total = info.get("total_videos", 0)
                valid = info.get("valid_videos", 0)
                samples = info.get("total_samples", 0)
                eta = info.get("estimated_time_s", 0)
                txt = f"{total} 视频 · {valid} 有效 · {samples:,} 样本 · 约 {eta/60:.1f} min/algo"
                self.frame.after(0, lambda: self._data_lbl.config(text=txt, fg=C["text_1"]))
            except Exception as e:
                self.frame.after(0, lambda e=e: self._data_lbl.config(text=f"⚠ {e}", fg=C["danger"]))

        threading.Thread(target=_worker, daemon=True).start()

    def _discover_algorithms(self) -> List[Dict]:
        """扫描有 build_model 的算法"""
        from algorithms.registry import AlgorithmRegistry

        return AlgorithmRegistry.get_trainable_info()

    def _refresh_algo_list(self):
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
        for v in self._check_vars.values():
            v.set(flag)

    def _select_untrained(self):
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
        from algorithms.training.checkpoint_manager import (
            CheckpointManager,
            list_video_finetune_bvids,
        )
        from algorithms.registry import AlgorithmRegistry

        AlgorithmRegistry.initialize()
        # 收集所有有 checkpoint 的算法
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

        dialog = tk.Toplevel(self.frame)
        dialog.title("Checkpoint 版本管理")
        dialog.geometry("700x500")
        dialog.transient(self.frame)
        dialog.grab_set()
        dialog.configure(bg=C["bg_base"])

        main = tk.Frame(dialog, bg=C["bg_base"])
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # 左侧：算法列表 | 右侧：版本详情
        left_panel = tk.Frame(main, bg=C["bg_elevated"], width=220)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 6))
        left_panel.pack_propagate(False)
        tk.Label(left_panel, text="算法", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(
            fill=tk.X, padx=4, pady=4
        )

        algo_sf = ScrollableFrame(left_panel, bg=C["bg_elevated"])
        algo_sf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        algo_inner = algo_sf.inner

        # 右侧：版本列表
        right_panel = tk.Frame(main, bg=C["bg_surface"])
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        info_lbl = tk.Label(right_panel, text="← 选择一个算法", bg=C["bg_surface"], fg=C["text_3"], font=FONT)
        info_lbl.pack(pady=20)

        detail_frame = tk.Frame(right_panel, bg=C["bg_surface"])
        detail_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        def _refresh_detail(aid, name):
            for w in detail_frame.winfo_children():
                w.destroy()

            info_lbl.pack_forget()

            # 算法标题
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

                    # 激活按钮（如果不是当前激活版本）
                    if not v.get("active") and len(versions) > 1:
                        ttk.Button(
                            row,
                            text="激活",
                            width=4,
                            command=lambda ver=v["version"], c=ckpt, a=aid, n=name: (
                                c.activate(ver),
                                _refresh_detail(a, n),
                            ),
                        ).pack(side=tk.RIGHT, padx=2)

                    # 删除按钮（只有一个版本时不显示）
                    if len(versions) > 1:
                        ttk.Button(
                            row,
                            text="✕",
                            width=3,
                            command=lambda ver=v["version"], c=ckpt, a=aid, n=name: (
                                c.delete(ver),
                                _refresh_detail(a, n),
                            ),
                        ).pack(side=tk.RIGHT, padx=2)

                    # val_loss 元信息
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
                        ttk.Button(
                            row,
                            text="✕",
                            width=3,
                            command=lambda b=bvid, ver=v["version"], a=aid, n=name: (
                                CheckpointManager(a, bvid=b).delete(ver),
                                _refresh_detail(a, n),
                            ),
                        ).pack(side=tk.RIGHT, padx=2)

            # ── 危险操作 ──
            if versions or bvids:
                tk.Label(detail_frame, text="", bg=C["bg_surface"]).pack()
                sep = tk.Frame(detail_frame, bg=C["border"], height=1)
                sep.pack(fill=tk.X, pady=4)
                btn_row = tk.Frame(detail_frame, bg=C["bg_surface"])
                btn_row.pack(fill=tk.X)
                ttk.Button(
                    btn_row,
                    text="删除所有全局版本",
                    command=lambda a=aid, n=name: self._delete_all_global(a, n, _refresh_detail),
                ).pack(side=tk.LEFT, padx=2)
                if bvids:
                    ttk.Button(
                        btn_row,
                        text="删除所有微调版本",
                        command=lambda a=aid, n=name: self._delete_all_video(a, n, _refresh_detail),
                    ).pack(side=tk.LEFT, padx=2)

        # 填充算法列表
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
            btn.bind("<Button-1>", lambda e, aid=a["algorithm_id"], n=a["name"]: _refresh_detail(aid, n))
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=C["bg_surface"]))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=C["bg_elevated"]))

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

        # 可微调的算法（有全局 checkpoint 的 DL 算法）
        AlgorithmRegistry.initialize()
        algo_list = []
        for aid, algo, _adapter in AlgorithmRegistry.get_trainable_algorithms():
            if CheckpointManager(aid).has_checkpoint():
                algo_list.append({"algorithm_id": aid, "name": getattr(algo, "name", aid)})

        if not algo_list:
            messagebox.showwarning("提示", "没有已训练的深度学习算法可供微调", parent=self.frame)
            return

        # 可微调的视频（当前监控中的视频）
        videos = []
        try:
            for v in self.main.monitored_videos:
                bvid = v.get("bvid", "")
                title = v.get("title", bvid)
                if bvid:
                    videos.append({"bvid": bvid, "title": title[:40]})
        except Exception:
            pass

        if not videos:
            messagebox.showwarning("提示", "没有监控中的视频可微调", parent=self.frame)
            return

        # ── 构建对话框 ──
        dialog = tk.Toplevel(self.frame)
        dialog.title("批量微调")
        dialog.geometry("650x500")
        dialog.transient(self.frame)
        dialog.grab_set()
        dialog.configure(bg=C["bg_base"])

        main = tk.Frame(dialog, bg=C["bg_base"])
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 视频选择
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

        # 算法选择
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

        # 参数行
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

        # 状态 & 进度
        ft_status = tk.Label(main, text="就绪", bg=C["bg_base"], fg=C["text_3"], font=FONT_SM, anchor="w")
        ft_status.pack(fill=tk.X, pady=(0, 4))
        ft_progress = ttk.Progressbar(main, mode="determinate", maximum=100)
        ft_progress.pack(fill=tk.X, pady=(0, 8))

        # 日志区域
        log_text = tk.Text(
            main, bg=C["bg_base"], fg=C["text_1"], font=("Consolas", 9), relief="flat", height=6, state="disabled"
        )
        log_text.pack(fill=tk.BOTH, expand=True)

        def _ft_log(msg):
            log_text.config(state="normal")
            log_text.insert(tk.END, msg + "\n")
            log_text.see(tk.END)
            log_text.config(state="disabled")

        def _start_ft():
            selected_videos = [b for b, v in video_vars.items() if v.get()]
            selected_algos = [a for a, v in algo_vars.items() if v.get()]
            if not selected_videos:
                messagebox.showwarning("提示", "请至少选择一个视频", parent=dialog)
                return
            if not selected_algos:
                messagebox.showwarning("提示", "请至少选择一个算法", parent=dialog)
                return

            epochs = max(1, ft_epoch_var.get())
            batch = max(1, ft_batch_var.get())
            total = len(selected_videos) * len(selected_algos)
            _ft_log(f"开始批量微调: {len(selected_videos)} 视频 × {len(selected_algos)} 算法 = {total} 任务")
            start_btn.config(state="disabled")

            def _worker():
                from algorithms.training.trainer import ModelTrainer

                trainer = ModelTrainer()
                done = 0
                self.main.set_finetune_status(f"🎯 批量微调 0/{total}")
                for bvid in selected_videos:
                    for aid in selected_algos:
                        done += 1
                        pct = int(done / total * 100)
                        msg = f"[{done}/{total}] 微调 {aid} → {bvid}"
                        dialog.after(0, lambda m=msg: ft_status.configure(text=m))
                        dialog.after(0, lambda p=pct: ft_progress.config(value=p))
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
                dialog.after(0, lambda: ft_status.configure(text=f"✅ 微调完成 ({done} 任务)"))
                dialog.after(0, lambda: ft_progress.config(value=100))
                dialog.after(0, lambda: self.main.set_finetune_status(f"✅ 批量微调完成 ({done})"))
                dialog.after(0, lambda: start_btn.config(state="normal"))
                dialog.after(0, lambda: _ft_log("🏁 批量微调全部完成"))

            threading.Thread(target=_worker, daemon=True).start()

        btn_row = tk.Frame(main, bg=C["bg_base"])
        btn_row.pack(fill=tk.X)
        start_btn = ttk.Button(btn_row, text="▶ 开始微调", command=_start_ft)
        start_btn.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="取消", command=dialog.destroy).pack(side=tk.LEFT)

    # ══════════════════════════════════════════════
    # 训练执行
    # ══════════════════════════════════════════════

    def _on_train_start(self):
        if self._training:
            return
        if not _torch_available:
            messagebox.showerror("torch 未安装", "请先 pip install torch", parent=self.frame)
            return

        selected = [aid for aid, v in self._check_vars.items() if v.get()]
        if not selected:
            messagebox.showwarning("提示", "请至少勾选一个算法", parent=self.frame)
            return

        epochs = max(1, int(self._epoch_var.get()))
        batch = max(1, int(self._batch_var.get()))
        is_incremental = self._mode_var.get() == "incremental"
        mode_label = "增量训练" if is_incremental else "重新训练"

        # 学习率：自动模式计算推荐值，手动模式读取用户输入
        if self._lr_auto_var.get():
            lr = self._auto_compute_lr()
            self._lr_var.set(f"{lr:.6f}")
            lr_label = f"自动 ({lr:.6f})"
        else:
            try:
                lr = float(self._lr_var.get())
            except (ValueError, TypeError):
                messagebox.showerror("LR 无效", f"请输入有效的学习率数值", parent=self.frame)
                return
            lr = max(1e-8, min(1.0, lr))
            lr_label = f"手动 ({lr:.6f})"

        if not messagebox.askyesno(
            "确认训练",
            f"模式: {mode_label}\n算法: {len(selected)} 个\n"
            f"epoch={epochs}  batch={batch}  LR={lr_label}\n"
            f"训练过程不可中途暂停（只能取消未开始的算法）。",
            parent=self.frame,
        ):
            return

        # 重置状态并锁定 UI
        self._prepare_training()

        # 打开日志文件
        self._open_log_file(len(selected), epochs, batch, mode_label, lr)
        self._append_log(
            f"🚀 开始训练: {mode_label}, {len(selected)} 个算法, epoch={epochs}, batch={batch}, lr={lr:.6f}"
        )
        self._status_lbl.config(text=f"准备训练 {len(selected)} 个算法 …", fg=C["text_2"])

        # 自动调整状态（每个算法独立 LR 系数）
        auto_control: Dict = {}
        auto_monitors: Dict[str, "TrainingMonitor"] = {}
        algo_lr_factors: Dict[str, float] = {}

        def _cb(payload: Dict):
            """训练回调 — 运行在工作线程中，负责通信 + 自动调整。"""
            payload["_total_selected"] = len(selected)
            payload["_incremental"] = is_incremental

            # 用户手动跳过当前算法
            if self._skip_algo_flag[0]:
                auto_control["early_stop"] = True
                auto_control["_force_early_stop"] = True
                payload["_adjustment"] = "⏭ 用户手动跳过"
                self._train_queue.put(payload)
                return

            # 自动质量检测与参数调整
            if payload.get("stage") == "epoch":
                aid = payload.get("algo_id", "")
                ep = payload.get("epoch", 0)
                tloss = payload.get("train_loss", 0.0)
                vloss = payload.get("val_loss", -1.0)

                key = aid
                if key not in auto_monitors:
                    auto_monitors[key] = TrainingMonitor()
                mon = auto_monitors[key]
                mon.update(ep, tloss, vloss if vloss >= 0 else -1)

                if mon.level in ("warning", "danger") and auto_control is not None:
                    status = mon.status
                    # 每个算法独立 LR 系数
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
                    elif "波动" in status and "不稳定" in status:
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

                    # 重新训练模式：删除已有 checkpoint
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

                    # 重置跳过标记，启用跳过按钮
                    self._skip_algo_flag[0] = False
                    self.frame.after(0, lambda: self._skip_btn.config(state="normal"))

                    # 每个算法独立 LR = 基础 LR × 该算法的累积系数
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
        self._cancel_flag[0] = True
        if self._cancel_btn:
            self._cancel_btn.config(state="disabled")
        self._status_lbl.config(text="正在取消（等待当前算法完成）…", fg=C["warning"])
        self._append_log("⏹ 用户请求取消训练")

    def _on_skip_algo(self):
        """跳过当前正在训练的算法，继续下一个。"""
        self._skip_algo_flag[0] = True
        if self._skip_btn:
            self._skip_btn.config(state="disabled")
        self._status_lbl.config(text="⏭ 跳过当前算法（等待本轮完成）…", fg=C["warning"])
        self._append_log("⏭ 用户请求跳过当前算法")

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
        stage = msg.get("stage")
        handler_name = self.STAGE_HANDLERS.get(stage)
        if handler_name:
            return getattr(self, handler_name)(msg)
        return False

    def _on_stage_start(self, msg):
        aid = msg.get("algo_id", "?")
        cur = msg.get("current", 0)
        tot = msg.get("total", 1)
        self._current_aid = aid
        self._status_lbl.config(text=f"[{cur}/{tot}] 训练 {aid} …", fg=C["text_2"])
        self._append_log(f"── [{cur}/{tot}] 开始训练 {aid} ──")
        self._update_algo_row(aid, status="▶ 训练中", status_color=C["accent"])

    def _on_stage_epoch(self, msg):
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
        total_elapsed = time.time() - self._train_t0 if self._train_t0 else 0
        vtxt = f"  val={vloss:.4f}" if vloss >= 0 else ""
        self._status_lbl.config(
            text=f"{aid}  ep{ep}/{eps}  train={tloss:.4f}{vtxt}  {conf_str}  {elapsed:.0f}s",
            fg=C["text_1"],
        )

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
            f"{f'val_loss={vloss:.6f}' if vloss>=0 else 'val_loss=N/A'}  |  "
            f"confidence={conf_str}  |  "
            f"{elapsed:.1f}s"
        )

    def _on_stage_done(self, msg):
        total_sel = msg.get("_total_selected", 1)
        aid = msg.get("algo_id", "?")
        cur = msg.get("current", 0)
        ver = msg.get("version", "")
        self._status_lbl.config(text=f"✓ {aid} → {ver} ({cur}/{total_sel})", fg=C["success"])
        self._progress["value"] = int(cur / max(1, total_sel) * 100)
        self._append_log(f"✓ {aid} 完成, 保存为 {ver}")
        conf = load_algo_confidence(aid)
        conf_str, conf_color = format_confidence(conf)
        self._algo_confidence[aid] = conf
        self._update_algo_row(
            aid,
            status=f"✓ {ver[:10]}",
            status_color=C["success"],
            conf=conf_str,
            conf_color=conf_color,
            ver=f"v{self._algo_meta.get(aid, {}).get('version_count', 0) + 1}",
        )

    def _on_stage_error(self, msg):
        aid = msg.get("algo_id", "?")
        err = msg.get("error", "")
        self._status_lbl.config(text=f"✗ {aid} 失败: {err}", fg=C["danger"])
        self._append_log(f"✗ {aid} 训练失败: {err}")
        self._update_algo_row(aid, status="✗ 失败", status_color=C["danger"])

    def _on_stage_auto_adjust(self, msg):
        message = msg.get("message", "")
        self._append_log(f"  🔧 自动调整: {message}")
        self._status_lbl.config(text=f"⚡ {message}", fg=C["warning"])

    def _on_stage_cancelled(self, msg):
        rem = msg.get("remaining", [])
        self._status_lbl.config(text=f"已取消，剩余 {len(rem)} 个", fg=C["warning"])
        self._append_log(f"⏹ 已取消, 剩余 {len(rem)} 个算法")
        return True

    def _on_stage_all_done(self, msg):
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
        return True

    def _on_stage_fatal(self, msg):
        err = msg.get("error", "")
        self._status_lbl.config(text=f"训练异常: {err}", fg=C["danger"])
        self._append_log(f"💥 训练进程异常: {err}")
        return True

    def _cleanup_training(self):
        self._close_log_file()
        super()._cleanup_training()
        self._refresh_algo_list()
        try:
            self.main._refresh_model_status()
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
            except Exception:
                pass

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

    def _append_log(self, text: str):
        super()._append_log(text)
        if self._log_file is not None:
            try:
                line = f"[{time.strftime('%H:%M:%S')}] {text}\n"
                self._log_file.write(line)
                self._log_file.flush()
            except Exception as e:
                logger.debug("写入训练日志文件失败: %s", e)
