"""
微调面板 — 与训练面板同级同显示
支持选择多个视频 + 多个算法，一键启动微调
右侧实时 loss 图表 + 训练质量监控 + 文字日志
自动切换当前训练视频的模型信息与置信度
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import queue
import time
import math
import logging
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
from ui.helpers import FONT, FONT_SM, FONT_MONO, FONT_BOLD
from ui.training_panel import TrainingMonitor


class FinetunePanel:
    """微调面板 — 与训练面板同级同显示"""

    def __init__(self, parent: tk.Widget, main_gui):
        self.parent = parent
        self.main = main_gui
        self.frame = tk.Frame(parent, bg=C["bg_base"])

        # 状态
        self._video_vars: Dict[str, tk.BooleanVar] = {}
        self._algo_vars: Dict[str, tk.BooleanVar] = {}
        self._algo_meta: Dict[str, Dict] = {}
        self._mode_var = tk.StringVar(value="incremental")
        self._training = False
        self._cancel_flag = [False]
        self._skip_algo_flag = [False]
        self._train_thread: Optional[threading.Thread] = None
        self._train_queue: Optional[queue.Queue] = None
        self._train_t0: Optional[float] = None

        # 训练质量监控器
        self._monitor = TrainingMonitor()
        self._last_monitor_level = ""

        # Loss 历史（用于图表）
        self._loss_history: List[Dict] = []
        self._current_bvid = ""
        self._current_aid = ""

        # 自动调整状态
        self._auto_control: Dict = {}
        self._auto_monitors: Dict[str, TrainingMonitor] = {}
        self._algo_lr_factors: Dict[str, float] = {}  # 跨任务 LR 累积系数

        # 当前视频的所有算法结果缓存（用于自动切换显示）
        self._video_results: Dict[str, List[Dict]] = {}  # bvid -> [{aid, version, confidence}]

        # 图表
        self._fig: Optional[Figure] = None
        self._canvas: Optional[FigureCanvasTkAgg] = None
        self._ax = None

        self._build_ui()

    # ══════════════════════════════════════════════
    # UI 构建
    # ══════════════════════════════════════════════

    def _build_ui(self):
        outer = self.frame

        # ── 顶部信息栏 ──
        info_bar = tk.Frame(outer, bg=C["bg_elevated"])
        info_bar.pack(fill=tk.X, padx=8, pady=(8, 4))
        tk.Label(info_bar, text="批量微调 — 选择视频和算法，一键微调已有全局 checkpoint 的模型",
                 bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT, padx=8)
        ttk.Button(info_bar, text="刷新列表", command=self._refresh_all).pack(side=tk.RIGHT, padx=8)

        # ── 主体区域: 左(视频+算法) | 右(图表+监控+日志) ──
        body = tk.Frame(outer, bg=C["bg_base"])
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        body.grid_columnconfigure(0, weight=35, minsize=280)
        body.grid_columnconfigure(1, weight=65, minsize=400)
        body.grid_rowconfigure(0, weight=1)

        self._build_left(body)
        self._build_right(body)

        # ── 底部控制栏 ──
        self._build_controls(outer)

    # ── 左侧: 视频 + 算法 ──

    def _build_left(self, parent):
        left = tk.Frame(parent, bg=C["bg_surface"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        left.grid_rowconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)

        # ── 视频列表 ──
        v_frame = tk.Frame(left, bg=C["bg_elevated"])
        v_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 4))
        v_frame.grid_rowconfigure(1, weight=1)
        v_hdr = tk.Frame(v_frame, bg=C["bg_elevated"])
        v_hdr.pack(fill=tk.X, padx=4, pady=(4, 0))
        tk.Label(v_hdr, text="🎬 选择视频", bg=C["bg_elevated"], fg=C["text_1"],
                 font=FONT_BOLD).pack(side=tk.LEFT)
        self._video_count_lbl = tk.Label(v_hdr, text="", bg=C["bg_elevated"],
                                          fg=C["text_3"], font=FONT_SM)
        self._video_count_lbl.pack(side=tk.RIGHT, padx=4)

        self._video_canvas = tk.Canvas(v_frame, bg=C["bg_elevated"], highlightthickness=0)
        v_sb = ttk.Scrollbar(v_frame, orient="vertical", command=self._video_canvas.yview)
        self._video_canvas.configure(yscrollcommand=v_sb.set)
        v_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._video_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._video_inner = tk.Frame(self._video_canvas, bg=C["bg_elevated"])
        self._video_canvas.create_window((0, 0), window=self._video_inner, anchor="nw")
        self._video_inner.bind("<Configure>", lambda e: self._video_canvas.configure(
            scrollregion=self._video_canvas.bbox("all")))

        # ── 算法列表（带状态/置信度/版本列）──
        a_frame = tk.Frame(left, bg=C["bg_elevated"])
        a_frame.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        a_frame.grid_rowconfigure(2, weight=1)
        a_hdr = tk.Frame(a_frame, bg=C["bg_elevated"])
        a_hdr.pack(fill=tk.X, padx=4, pady=(4, 0))
        tk.Label(a_hdr, text="🧠 选择算法（已训练）", bg=C["bg_elevated"], fg=C["text_1"],
                 font=FONT_BOLD).pack(side=tk.LEFT)
        self._algo_count_lbl = tk.Label(a_hdr, text="", bg=C["bg_elevated"],
                                         fg=C["text_3"], font=FONT_SM)
        self._algo_count_lbl.pack(side=tk.RIGHT, padx=4)

        a_toolbar = tk.Frame(a_frame, bg=C["bg_elevated"])
        a_toolbar.pack(fill=tk.X, padx=4, pady=(2, 2))
        ttk.Button(a_toolbar, text="全选", command=lambda: self._toggle_algos(True), width=6).pack(side=tk.LEFT, padx=1)
        ttk.Button(a_toolbar, text="反选", command=lambda: self._toggle_algos(False), width=6).pack(side=tk.LEFT, padx=1)
        ttk.Button(a_toolbar, text="🗑️ 版本管理", command=self._on_manage_versions, width=10).pack(side=tk.LEFT, padx=1)

        # 表头
        hdr_row = tk.Frame(a_frame, bg=C["bg_surface"])
        hdr_row.pack(fill=tk.X, padx=4, pady=(0, 1))
        for col, (txt, w) in enumerate([("", 4), ("算法", 14), ("ID", 12), ("状态", 10), ("置信度", 8), ("版本", 8)]):
            tk.Label(hdr_row, text=txt, bg=C["bg_surface"], fg=C["text_3"],
                     font=("Microsoft YaHei UI", 8, "bold"), width=w, anchor="w"
                     ).grid(row=0, column=col, padx=2, pady=2, sticky="w")

        # 滚动容器
        self._algo_canvas = tk.Canvas(a_frame, bg=C["bg_elevated"], highlightthickness=0, height=200)
        a_sb = ttk.Scrollbar(a_frame, orient="vertical", command=self._algo_canvas.yview)
        self._algo_canvas.configure(yscrollcommand=a_sb.set)
        a_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._algo_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._algo_inner = tk.Frame(self._algo_canvas, bg=C["bg_elevated"])
        self._algo_canvas.create_window((0, 0), window=self._algo_inner, anchor="nw")
        self._algo_inner.bind("<Configure>", lambda e: self._algo_canvas.configure(
            scrollregion=self._algo_canvas.bbox("all")))

    # ── 右侧: 图表 + 监控 + 日志 ──

    def _build_right(self, parent):
        right = tk.Frame(parent, bg=C["bg_surface"])
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)  # 图表
        right.grid_rowconfigure(3, weight=1)  # 日志
        right.grid_columnconfigure(0, weight=1)

        # ── 当前任务信息栏 ──
        task_bar = tk.Frame(right, bg=C["bg_elevated"])
        task_bar.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 2))
        self._task_lbl = tk.Label(task_bar, text="就绪 — 选择视频和算法后开始微调",
                                  bg=C["bg_elevated"], fg=C["text_3"], font=FONT)
        self._task_lbl.pack(side=tk.LEFT, padx=8, pady=6)
        self._task_detail = tk.Label(task_bar, text="", bg=C["bg_elevated"],
                                     fg=C["text_3"], font=FONT_SM)
        self._task_detail.pack(side=tk.RIGHT, padx=8, pady=6)

        # ── 上半: Loss 图表 ──
        chart_frame = tk.Frame(right, bg=C["bg_elevated"])
        chart_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 2))
        chart_frame.grid_rowconfigure(1, weight=1)
        tk.Label(chart_frame, text="微调 Loss 曲线", bg=C["bg_elevated"], fg=C["text_2"],
                 font=FONT_SM).pack(anchor="nw", padx=4, pady=(2, 0))

        if mpl_available:
            self._fig = Figure(figsize=(5, 2.5), dpi=80, facecolor=C["bg_elevated"])
            self._ax = self._fig.add_subplot(111)
            self._ax.set_facecolor(C["bg_elevated"])
            self._ax.tick_params(colors=C["text_3"], labelsize=7)
            self._ax.set_xlabel("Epoch", color=C["text_3"], fontsize=7)
            self._ax.set_ylabel("Loss", color=C["text_3"], fontsize=7)
            self._ax.grid(True, alpha=0.3, color=C["border"])
            for spine in self._ax.spines.values():
                spine.set_color(C["border"])
            self._fig.tight_layout(pad=1.5)

            self._canvas = FigureCanvasTkAgg(self._fig, master=chart_frame)
            self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
            self._canvas.draw()
        else:
            tk.Label(chart_frame, text="matplotlib 未安装，无法显示图表",
                     bg=C["bg_elevated"], fg=C["text_3"], font=FONT).pack(expand=True)

        # ── 中部: 训练质量监控 ──
        monitor_bar = tk.Frame(right, bg=C["bg_surface"], highlightthickness=1,
                               highlightbackground=C["border_sub"])
        monitor_bar.grid(row=2, column=0, sticky="ew", padx=4, pady=(0, 2))

        self._monitor_icon = tk.Label(monitor_bar, text="🔵", bg=C["bg_surface"],
                                      font=("Segoe UI", 14))
        self._monitor_icon.pack(side=tk.LEFT, padx=(6, 2), pady=2)
        self._monitor_status = tk.Label(monitor_bar, text="等待训练开始…",
                                        bg=C["bg_surface"], fg=C["text_3"],
                                        font=FONT_SM, anchor="w")
        self._monitor_status.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2, pady=2)
        self._monitor_tip = tk.Label(monitor_bar, text="", bg=C["bg_surface"],
                                     fg=C["text_3"], font=("Microsoft YaHei UI", 8),
                                     anchor="e")
        self._monitor_tip.pack(side=tk.RIGHT, padx=(4, 8), pady=2)

        # ── 下半: 文字日志 ──
        log_frame = tk.Frame(right, bg=C["bg_elevated"])
        log_frame.grid(row=3, column=0, sticky="nsew", padx=4, pady=(2, 4))

        log_hdr = tk.Frame(log_frame, bg=C["bg_elevated"])
        log_hdr.pack(fill=tk.X)
        tk.Label(log_hdr, text="微调日志", bg=C["bg_elevated"], fg=C["text_2"],
                 font=FONT_SM).pack(side=tk.LEFT, padx=4, pady=(2, 0))
        ttk.Button(log_hdr, text="清空", command=self._clear_log, width=4).pack(side=tk.RIGHT, padx=4)

        self._log_text = tk.Text(
            log_frame, bg=C["bg_base"], fg=C["text_1"], font=("Consolas", 9),
            relief="flat", bd=0, wrap=tk.WORD, state="disabled",
            highlightthickness=1, highlightbackground=C["border_sub"],
        )
        self._log_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=(2, 4))
        log_sb = ttk.Scrollbar(log_frame, orient="vertical", command=self._log_text.yview)
        log_sb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4), pady=(2, 4))
        self._log_text.configure(yscrollcommand=log_sb.set)

    # ── 底部控制栏 ──

    def _build_controls(self, parent):
        ctrl = tk.Frame(parent, bg=C["bg_elevated"])
        ctrl.pack(fill=tk.X, padx=8, pady=(0, 6))

        tk.Label(ctrl, text="Epochs:", bg=C["bg_elevated"], fg=C["text_2"],
                 font=FONT_SM).pack(side=tk.LEFT, padx=(8, 2))
        self._epoch_var = tk.IntVar(value=5)
        ttk.Spinbox(ctrl, from_=1, to=100, textvariable=self._epoch_var, width=6).pack(side=tk.LEFT, padx=2)

        tk.Label(ctrl, text="Batch:", bg=C["bg_elevated"], fg=C["text_2"],
                 font=FONT_SM).pack(side=tk.LEFT, padx=(8, 2))
        self._batch_var = tk.IntVar(value=16)
        ttk.Spinbox(ctrl, from_=1, to=512, textvariable=self._batch_var, width=6).pack(side=tk.LEFT, padx=2)

        tk.Label(ctrl, text="模式:", bg=C["bg_elevated"], fg=C["text_2"],
                 font=FONT_SM).pack(side=tk.LEFT, padx=(8, 2))
        ttk.Radiobutton(ctrl, text="增量微调", variable=self._mode_var, value="incremental").pack(side=tk.LEFT, padx=1)
        ttk.Radiobutton(ctrl, text="重新训练", variable=self._mode_var, value="retrain").pack(side=tk.LEFT, padx=1)

        self._train_btn = ttk.Button(ctrl, text="▶ 开始微调", command=self._on_start,
                                     style="Primary.TButton")
        self._train_btn.pack(side=tk.LEFT, padx=(12, 4))
        self._cancel_btn = ttk.Button(ctrl, text="✕ 取消", command=self._on_cancel, state="disabled")
        self._cancel_btn.pack(side=tk.LEFT, padx=4)
        self._skip_btn = ttk.Button(ctrl, text="⏭ 跳过当前", command=self._on_skip_algo, state="disabled")
        self._skip_btn.pack(side=tk.LEFT, padx=4)

        self._progress = ttk.Progressbar(ctrl, mode="determinate", maximum=100)
        self._progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 4))

        self._status_lbl = tk.Label(ctrl, text="就绪", bg=C["bg_elevated"], fg=C["text_3"],
                                    font=FONT_SM, anchor="w", width=40)
        self._status_lbl.pack(side=tk.RIGHT, padx=(0, 8))

    # ══════════════════════════════════════════════
    # 数据刷新
    # ══════════════════════════════════════════════

    def on_show(self):
        self._refresh_all()

    def _refresh_all(self):
        self._refresh_videos()
        self._refresh_algos()

    def _refresh_videos(self):
        for w in self._video_inner.winfo_children():
            w.destroy()
        self._video_vars.clear()

        videos = []
        try:
            for v in self.main.monitored_videos:
                bvid = v.get("bvid", "")
                title = v.get("title", bvid)
                if bvid:
                    videos.append({"bvid": bvid, "title": title[:50]})
        except Exception:
            pass

        self._video_count_lbl.config(text=f"{len(videos)} 个视频")
        for v in sorted(videos, key=lambda x: x["bvid"]):
            var = tk.BooleanVar(value=True)
            self._video_vars[v["bvid"]] = var
            row = tk.Frame(self._video_inner, bg=C["bg_elevated"])
            row.pack(fill=tk.X)
            ttk.Checkbutton(row, variable=var).pack(side=tk.LEFT, padx=2)
            tk.Label(row, text=f"{v['title']}  ({v['bvid']})", bg=C["bg_elevated"],
                     fg=C["text_1"], font=FONT_SM, anchor="w").pack(
                side=tk.LEFT, padx=2, fill=tk.X)

    def _refresh_algos(self):
        for w in self._algo_inner.winfo_children():
            w.destroy()
        self._algo_vars.clear()
        self._algo_meta.clear()

        from algorithms.registry import AlgorithmRegistry
        from algorithms.training.checkpoint_manager import CheckpointManager
        AlgorithmRegistry.initialize()

        algos = []
        for aid, algo, _adapter in AlgorithmRegistry.get_trainable_algorithms():
            ckpt = CheckpointManager(aid)
            versions = ckpt.list_versions()
            has_ckpt = ckpt.has_checkpoint()
            algos.append({
                "algorithm_id": aid,
                "name": getattr(algo, "name", aid),
                "has_ckpt": has_ckpt,
                "active_version": ckpt.active_version() or "",
                "version_count": len(versions),
                "category": getattr(algo, "category", ""),
            })

        trained = sum(1 for a in algos if a["has_ckpt"])
        self._algo_count_lbl.config(text=f"{len(algos)} 算法 · 已训练 {trained}")

        for a in sorted(algos, key=lambda x: (not x["has_ckpt"], x["name"])):
            aid = a["algorithm_id"]
            self._algo_meta[aid] = a

            row = tk.Frame(self._algo_inner, bg=C["bg_surface"],
                           highlightthickness=1, highlightbackground=C["border_sub"])
            row.pack(fill=tk.X, pady=1)

            var = tk.BooleanVar(value=True)
            self._algo_vars[aid] = var
            ttk.Checkbutton(row, variable=var).grid(row=0, column=0, padx=4, pady=2)

            tk.Label(row, text=a["name"], bg=C["bg_surface"], fg=C["text_1"],
                     font=FONT, width=14, anchor="w").grid(row=0, column=1, padx=2, sticky="w")
            tk.Label(row, text=aid, bg=C["bg_surface"], fg=C["text_3"],
                     font=FONT_MONO, width=12, anchor="w").grid(row=0, column=2, padx=2, sticky="w")

            if a["has_ckpt"]:
                st = f"✅ {a['active_version'][:10]}"
                sf = C["success"]
            else:
                st = "□ 未训练"
                sf = C["text_3"]
            tk.Label(row, text=st, bg=C["bg_surface"], fg=sf,
                     font=FONT_SM, width=10, anchor="w").grid(row=0, column=3, padx=2, sticky="w")

            # 置信度（全局）
            conf = self._load_confidence(aid)
            conf_text, conf_color = self._format_confidence(conf)
            tk.Label(row, text=conf_text, bg=C["bg_surface"], fg=conf_color,
                     font=FONT_SM, width=8, anchor="w").grid(row=0, column=4, padx=2, sticky="w")

            tk.Label(row, text=f"v{a['version_count']}", bg=C["bg_surface"], fg=C["text_3"],
                     font=FONT_SM, width=6, anchor="w").grid(row=0, column=5, padx=2, sticky="w")

    def _refresh_algo_row(self, row_idx: int, aid: str, status_text: str, status_color: str,
                          conf_text: str = "", conf_color: str = "", ver_text: str = ""):
        """更新算法行指定列（不会重建整个列表）。"""
        for w in self._algo_inner.winfo_children():
            info = getattr(w, "_algo_row_info", None)
            if info and info == aid:
                children = w.winfo_children()
                if len(children) >= 6:
                    if status_text:
                        children[3].config(text=status_text, fg=status_color)
                    if conf_text:
                        children[4].config(text=conf_text, fg=conf_color)
                    if ver_text:
                        children[5].config(text=ver_text)
                break

    def _toggle_algos(self, flag: bool):
        for v in self._algo_vars.values():
            v.set(flag)

    # ── 置信度辅助 ──

    @staticmethod
    def _loss_to_confidence(val_loss: float) -> float:
        if val_loss is None or val_loss < 0:
            return 0.0
        return max(0.0, min(1.0, math.exp(-val_loss)))

    @staticmethod
    def _format_confidence(conf: float):
        if conf <= 0:
            return "—", C["text_3"]
        pct = conf * 100
        if conf >= 0.8:
            return f"↑ {pct:.0f}%", C["success"]
        elif conf >= 0.5:
            return f"→ {pct:.0f}%", C["warning"]
        else:
            return f"↓ {pct:.0f}%", C["danger"]

    def _load_confidence(self, algo_id: str) -> float:
        try:
            from algorithms.training.checkpoint_manager import CheckpointManager
            ckpt = CheckpointManager(algo_id)
            versions = ckpt.list_versions()
            active_v = ckpt.active_version()
            if not versions or not active_v:
                return 0.0
            for v in versions:
                if v["version"] == active_v:
                    return self._loss_to_confidence(v.get("val_loss", -1.0))
            return self._loss_to_confidence(versions[0].get("val_loss", -1.0))
        except Exception:
            return 0.0

    def _load_video_confidence(self, algo_id: str, bvid: str) -> float:
        """读取视频微调 checkpoint 的置信度。"""
        try:
            from algorithms.training.checkpoint_manager import CheckpointManager
            ckpt = CheckpointManager(algo_id, bvid=bvid)
            versions = ckpt.list_versions()
            active_v = ckpt.active_version()
            if not versions or not active_v:
                return 0.0
            for v in versions:
                if v["version"] == active_v:
                    return self._loss_to_confidence(v.get("val_loss", -1.0))
            return self._loss_to_confidence(versions[0].get("val_loss", -1.0))
        except Exception:
            return 0.0

    def _on_manage_versions(self):
        """打开版本管理对话框（复用训练面板的完整实现）。"""
        if hasattr(self.main, "training_panel") and self.main.training_panel is not None:
            self.main.training_panel._on_manage_versions()

    # ══════════════════════════════════════════════
    # 微调执行
    # ══════════════════════════════════════════════

    def _on_start(self):
        if self._training:
            return

        selected_videos = [b for b, v in self._video_vars.items() if v.get()]
        selected_algos = [a for a, v in self._algo_vars.items() if v.get()]
        if not selected_videos:
            messagebox.showwarning("提示", "请至少选择一个视频", parent=self.frame)
            return
        if not selected_algos:
            messagebox.showwarning("提示", "请至少选择一个算法", parent=self.frame)
            return

        epochs = max(1, self._epoch_var.get())
        batch = max(1, self._batch_var.get())
        total = len(selected_videos) * len(selected_algos)
        mode = self._mode_var.get()

        if mode == "retrain":
            if not messagebox.askyesno(
                "重新训练",
                "将删除所选算法在当前所有选定视频上的已有微调版本并重置版本号，\n"
                "同时删除 data/<bvid>/model/ 中的对应文件。\n确定要继续？",
                parent=self.frame,
            ):
                return

        if not messagebox.askyesno(
            "确认微调",
            f"模式: {'重新训练' if mode == 'retrain' else '增量微调'}\n"
            f"视频: {len(selected_videos)} 个\n算法: {len(selected_algos)} 个\n"
            f"总任务: {total}\nepoch={epochs}  batch={batch}",
            parent=self.frame,
        ):
            return

        self._training = True
        self._train_btn.config(state="disabled")
        self._cancel_btn.config(state="normal")
        self._skip_btn.config(state="normal")
        self._cancel_flag[0] = False

        # 重置训练状态
        self._skip_algo_flag[0] = False
        self._monitor.reset()
        self._loss_history.clear()
        self._video_results.clear()
        self._auto_monitors.clear()
        self._auto_control = {}
        self._last_monitor_status = ""
        self._last_monitor_log_epoch = 0
        self._clear_chart()
        self._clear_log()
        self._progress["value"] = 0

        mode_label = "重新训练" if mode == "retrain" else "增量微调"
        self._append_log(f"🚀 开始{mode_label}: {len(selected_videos)} 视频 × {len(selected_algos)} 算法, "
                         f"epoch={epochs}, batch={batch}")
        self._task_lbl.config(text=f"{mode_label}进行中…")
        self._task_detail.config(text=f"0/{total}")
        self._status_lbl.config(text="准备任务…", fg=C["text_2"])

        import queue as _q
        self._train_t0 = time.time()
        self._train_queue = _q.Queue()

        def _cb(payload: Dict):
            """训练回调 — 运行在工作线程中，负责通信 + 自动调整。"""
            payload["_mode"] = mode
            payload["_control"] = dict(self._auto_control) if self._auto_control else {}

            # 用户手动跳过当前任务
            if self._skip_algo_flag[0]:
                self._auto_control["early_stop"] = True
                self._auto_control["_force_early_stop"] = True
                payload["_adjustment"] = "⏭ 用户手动跳过"
                self._train_queue.put(payload)
                return

            # 自动质量检测与参数调整
            if payload.get("stage") == "epoch":
                aid = payload.get("algo_id", "")
                bvid_ = payload.get("bvid", "") or self._current_bvid
                ep = payload.get("epoch", 0)
                tloss = payload.get("train_loss", 0.0)
                vloss = payload.get("val_loss", -1.0)

                key = f"{aid}@{bvid_}"
                if key not in self._auto_monitors:
                    self._auto_monitors[key] = TrainingMonitor()
                mon = self._auto_monitors[key]
                mon.update(ep, tloss, vloss if vloss >= 0 else -1)

                # 根据检测结果自动调整
                if mon.level in ("warning", "danger") and self._auto_control is not None:
                    status = mon.status
                    suggestions_text = " ".join(mon.suggestions).lower()
                    if "nan" in status.lower():
                        self._auto_control["early_stop"] = True
                        payload["_adjustment"] = "🔧 NaN 检测 — 提前停止"
                    elif "爆炸" in status:
                        scale = mon.compute_lr_scale("explosion")
                        self._auto_control["lr_scale"] = scale
                        self._algo_lr_factors[aid] = self._algo_lr_factors.get(aid, 1.0) * scale
                        payload["_adjustment"] = f"🔧 Loss 爆炸 — LR×{scale:.2f} (累计×{self._algo_lr_factors[aid]:.2f})"
                    elif "严重过拟合" in status:
                        self._auto_control["early_stop"] = True
                        payload["_adjustment"] = "🔧 严重过拟合 — 提前停止"
                    elif "波动" in status and "不稳定" in status:
                        scale = mon.compute_lr_scale("oscillation")
                        self._auto_control["lr_scale"] = scale
                        self._algo_lr_factors[aid] = self._algo_lr_factors.get(aid, 1.0) * scale
                        payload["_adjustment"] = f"🔧 Loss 震荡 — LR×{scale:.2f} (累计×{self._algo_lr_factors[aid]:.2f})"
                    elif "过拟合" in status:
                        scale = mon.compute_lr_scale("overfitting")
                        self._auto_control["lr_scale"] = scale
                        self._algo_lr_factors[aid] = self._algo_lr_factors.get(aid, 1.0) * scale
                        payload["_adjustment"] = f"🔧 过拟合 — LR×{scale:.2f} (累计×{self._algo_lr_factors[aid]:.2f})"
                    elif "欠拟合" in status or "下降过慢" in status:
                        scale = mon.compute_lr_scale("underfitting")
                        self._auto_control["lr_scale"] = scale
                        self._algo_lr_factors[aid] = self._algo_lr_factors.get(aid, 1.0) * scale
                        payload["_adjustment"] = f"🔧 欠拟合 — LR×{scale:.2f} (累计×{self._algo_lr_factors[aid]:.2f})"
                    elif "不再收敛" in status:
                        self._auto_control["early_stop"] = True
                        payload["_adjustment"] = "🔧 不再收敛 — 提前停止"

            self._train_queue.put(payload)

        def _worker():
            from algorithms.training.trainer import ModelTrainer
            from algorithms.training.checkpoint_manager import CheckpointManager
            import os as _os
            trainer = ModelTrainer()
            _data_root = _os.path.join(
                _os.path.dirname(_os.path.dirname(__file__)), "data")
            done = 0
            for bvid in selected_videos:
                if self._cancel_flag[0]:
                    self._train_queue.put({"stage": "cancelled", "done": done, "total": total})
                    return
                for aid in selected_algos:
                    if self._cancel_flag[0]:
                        self._train_queue.put({"stage": "cancelled", "done": done, "total": total})
                        return
                    done += 1

                    # 重新训练模式：清除已有 checkpoint 和模型文件
                    if mode == "retrain":
                        vid_ckpt = CheckpointManager(aid, bvid=bvid)
                        deleted = vid_ckpt.delete_all()
                        model_path = _os.path.join(_data_root, bvid, "model", f"{aid}.pt")
                        try:
                            if _os.path.exists(model_path):
                                _os.remove(model_path)
                        except Exception:
                            pass
                        if deleted:
                            self._train_queue.put({
                                "stage": "log", "text": f"  🗑 已清除 {aid}@{bvid} 的 {deleted} 个旧版本",
                            })

                    # 重置跳过标记，启用跳过按钮
                    self._skip_algo_flag[0] = False
                    self._skip_btn.config(state="normal")

                    # 通知开始
                    self._train_queue.put({
                        "stage": "start", "done": done, "total": total,
                        "aid": aid, "bvid": bvid,
                    })
                    # 初始化自动调整控制字典（每个任务独立）
                    self._auto_control = {}
                    default_epochs = epochs
                    # 应用累积 LR 调整
                    algo_factor = self._algo_lr_factors.get(aid, 1.0)
                    effective_lr = 0.001 * algo_factor  # 基于 Adam 默认 1e-3
                    try:
                        ver = trainer.finetune_for_video(
                            algo_id=aid, bvid=bvid, epochs=default_epochs, batch_size=batch,
                            progress_cb=_cb, control_dict=self._auto_control,
                            lr=effective_lr,
                        )
                        # 读取完成后的置信度
                        ckpt = CheckpointManager(aid, bvid=bvid)
                        versions = ckpt.list_versions()
                        val_loss = -1.0
                        if versions:
                            val_loss = versions[0].get("val_loss", -1.0)
                        conf = self._loss_to_confidence(val_loss)
                        self._train_queue.put({
                            "stage": "done", "done": done, "total": total,
                            "aid": aid, "bvid": bvid, "version": ver[:12],
                            "confidence": conf, "val_loss": val_loss,
                        })
                    except Exception as e:
                        self._train_queue.put({
                            "stage": "error", "done": done, "total": total,
                            "aid": aid, "bvid": bvid, "error": str(e),
                        })
            self._train_queue.put({"stage": "all_done", "done": done, "total": total})

        self._train_thread = threading.Thread(target=_worker, daemon=True)
        self._train_thread.start()
        self.frame.after(150, self._poll_progress)

    def _on_cancel(self):
        self._cancel_flag[0] = True
        self._cancel_btn.config(state="disabled")
        self._append_log("⏹ 用户请求取消")
        self.main.set_finetune_status("⏹ 微调已取消", color=C["warning"])

    def _on_skip_algo(self):
        """跳过当前正在微调的（视频,算法）对，继续下一个。"""
        self._skip_algo_flag[0] = True
        self._skip_btn.config(state="disabled")
        self._append_log("⏭ 用户请求跳过当前任务")

    def _poll_progress(self):
        import queue as _q
        if self._train_queue is None:
            return

        done_all = False
        try:
            while True:
                msg = self._train_queue.get_nowait()
                stage = msg.get("stage")

                if stage == "start":
                    done = msg.get("done", 0)
                    total = msg.get("total", 1)
                    aid = msg.get("aid", "?")
                    bvid = msg.get("bvid", "?")
                    self._current_bvid = bvid
                    self._current_aid = aid

                    # 切换到新视频时重置图表
                    if bvid not in self._video_results:
                        self._loss_history.clear()
                        self._clear_chart()
                        self._monitor.reset()
                        self._task_lbl.config(
                            text=f"🎯 视频 {bvid}: 开始微调 {aid}", fg=C["accent"])
                    else:
                        self._task_lbl.config(
                            text=f"🎯 视频 {bvid}: 微调 {aid}", fg=C["accent"])
                    self._task_detail.config(text=f"{done}/{total}")
                    pct = min(100, int(done / max(1, total) * 100))
                    self._progress["value"] = pct
                    self._status_lbl.config(
                        text=f"[{done}/{total}] 微调 {aid} → {bvid}", fg=C["text_2"])
                    self._append_log(f"── [{done}/{total}] 开始微调 {aid}@{bvid} ──")
                    self.main.set_finetune_status(f"🎯 微调 {bvid}: [{done}/{total}] {aid}")

                    # 更新算法行状态
                    conf_v = self._load_video_confidence(aid, bvid)
                    self._refresh_algo_row(0, aid, "▶ 训练中", C["accent"], "", "", "")

                elif stage == "epoch":
                    aid = msg.get("algo_id", aid)
                    bvid = msg.get("bvid", self._current_bvid)
                    ep = msg.get("epoch", 0)
                    eps = msg.get("epochs", 1)
                    tloss = msg.get("train_loss", 0.0)
                    vloss = msg.get("val_loss", -1.0)
                    elapsed = msg.get("elapsed_s", 0.0)

                    # 实时置信度
                    conf = self._loss_to_confidence(vloss) if vloss >= 0 else 0.0
                    conf_str, _ = self._format_confidence(conf)

                    pct = min(100, int((ep / max(1, eps)) * 100))
                    self._progress["value"] = pct
                    total_elapsed = time.time() - self._train_t0 if self._train_t0 else 0
                    vtxt = f"  val={vloss:.4f}" if vloss >= 0 else ""
                    ctrl_data = msg.get("_control", {})
                    if ctrl_data.get("early_stop"):
                        self._status_lbl.config(
                            text=f"{aid}@{bvid}  ep{ep}/{eps}  ⏹ 即将停止",
                            fg=C["warning"],
                        )
                    elif ctrl_data.get("lr_scale"):
                        self._status_lbl.config(
                            text=f"{aid}@{bvid}  ep{ep}/{eps}  ⚡ 调整LR",
                            fg=C["warning"],
                        )
                    else:
                        self._status_lbl.config(
                            text=f"{aid}@{bvid}  ep{ep}/{eps}  train={tloss:.4f}{vtxt}  {conf_str}  {elapsed:.0f}s",
                            fg=C["text_1"],
                        )

                    # 训练质量监控
                    self._monitor.update(ep, tloss, vloss if vloss >= 0 else -1)
                    self._refresh_monitor()

                    # 记录 loss 历史 + 更新图表
                    self._loss_history.append({
                        "algo": aid, "bvid": bvid, "epoch": ep,
                        "train_loss": tloss, "val_loss": vloss,
                    })
                    self._update_chart()
                    adj = msg.get("_adjustment", "")
                    adj_suffix = f"  |  {adj}" if adj else ""
                    self._append_log(
                        f"  epoch {ep:>3}/{eps}  |  "
                        f"train_loss={tloss:.6f}  |  "
                        f"{f'val_loss={vloss:.6f}' if vloss>=0 else 'val_loss=N/A'}  |  "
                        f"confidence={conf_str}  |  "
                        f"{elapsed:.1f}s{adj_suffix}"
                    )

                elif stage == "done":
                    done = msg.get("done", 0)
                    total = msg.get("total", 1)
                    aid = msg.get("aid", "?")
                    bvid = msg.get("bvid", "?")
                    ver = msg.get("version", "")
                    conf = msg.get("confidence", 0.0)
                    val_loss = msg.get("val_loss", -1.0)

                    pct = min(100, int(done / max(1, total) * 100))
                    self._progress["value"] = pct
                    self._task_detail.config(text=f"{done}/{total}")
                    conf_str, conf_color = self._format_confidence(conf)

                    # 缓存视频结果
                    if bvid not in self._video_results:
                        self._video_results[bvid] = []
                    self._video_results[bvid].append({
                        "aid": aid, "version": ver, "confidence": conf, "val_loss": val_loss,
                    })

                    # 更新算法行状态
                    self._refresh_algo_row(0, aid, f"✓ {ver}", C["success"],
                                           conf_str, conf_color, f"v{msg.get('done', 0)}")

                    self._status_lbl.config(
                        text=f"✓ {aid}@{bvid}  → {ver}  conf={conf_str}  ({done}/{total})",
                        fg=C["success"])
                    self._append_log(f"  ✓ {aid}@{bvid} → {ver}  置信度={conf_str}  val_loss={val_loss:.4f}")

                elif stage == "error":
                    done = msg.get("done", 0)
                    total = msg.get("total", 1)
                    aid = msg.get("aid", "?")
                    bvid = msg.get("bvid", "?")
                    err = msg.get("error", "")
                    pct = min(100, int(done / max(1, total) * 100))
                    self._progress["value"] = pct
                    self._task_detail.config(text=f"{done}/{total}")
                    self._status_lbl.config(text=f"✗ {aid}@{bvid}: {err}", fg=C["danger"])
                    self._append_log(f"  ✗ {aid}@{bvid}: {err}")
                    self._refresh_algo_row(0, aid, "✗ 失败", C["danger"], "", "", "")

                elif stage == "auto_adjust":
                    action = msg.get("action", "")
                    message = msg.get("message", "")
                    self._append_log(f"  🔧 自动调整: {message}")
                    self._status_lbl.config(text=f"⚡ {message}", fg=C["warning"])
                    if action == "early_stop":
                        self._monitor_status.config(text="⏹ 自动提前停止", fg=C["warning"])

                elif stage == "log":
                    self._append_log(msg.get("text", ""))

                elif stage == "cancelled":
                    done = msg.get("done", 0)
                    total = msg.get("total", 1)
                    self._status_lbl.config(text=f"已取消 ({done}/{total})", fg=C["warning"])
                    self._append_log(f"⏹ 已取消, {done}/{total} 已完成")
                    done_all = True

                elif stage == "all_done":
                    done = msg.get("done", 0)
                    elapsed = time.time() - self._train_t0 if self._train_t0 else 0

                    # 汇总所有置信度
                    conf_summary = ""
                    for bvid, results in self._video_results.items():
                        for r in results:
                            cs, _ = self._format_confidence(r["confidence"])
                            conf_summary += f"\n  {bvid} → {r['aid']}: {cs}"

                    self._task_lbl.config(text="✅ 微调全部完成", fg=C["success"])
                    self._task_detail.config(text=f"{done}/{done}")
                    self._status_lbl.config(text=f"全部完成: {done} 任务 · {elapsed:.0f}s", fg=C["success"])
                    self._progress["value"] = 100
                    self._append_log(f"🏁 批量微调全部完成: {done} 任务, 耗时 {elapsed:.0f}s")
                    self._append_log(f"📊 各算法最终置信度:{conf_summary}")
                    self.main.set_finetune_status(f"✅ 批量微调完成 ({done})")
                    done_all = True

        except _q.Empty:
            pass

        if done_all:
            self._training = False
            self._train_btn.config(state="normal")
            self._cancel_btn.config(state="disabled")
            self._skip_btn.config(state="disabled")
            self._train_queue = None
            self._train_thread = None
            try:
                self.main._refresh_model_status()
            except Exception:
                pass
        else:
            self.frame.after(200, self._poll_progress)

    # ══════════════════════════════════════════════
    # 训练质量监控
    # ══════════════════════════════════════════════

    def _refresh_monitor(self):
        text, color = self._monitor.get_status_display()
        self._monitor_status.config(text=text, fg=color)
        tip = self._monitor.get_tip()
        self._monitor_tip.config(text=tip)

        icon_map = {"good": "🟢", "warning": "🟡", "danger": "🔴", "info": "🔵"}
        self._monitor_icon.config(text=icon_map.get(self._monitor.level, "🔵"))

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

                # 显示累积 LR 调整信息
                factor = self._algo_lr_factors.get(self._current_aid, 1.0)
                if factor != 1.0:
                    base_lr = 0.001
                    cur_lr = base_lr * factor
                    self._append_log(f"  📐 当前有效学习率: {cur_lr:.6f} (基础 {base_lr} × {factor:.2f}) — 自动调整已应用于后续训练")

    # ══════════════════════════════════════════════
    # 图表
    # ══════════════════════════════════════════════

    def _update_chart(self):
        if not mpl_available or self._ax is None:
            return
        self._ax.clear()
        self._ax.set_facecolor(C["bg_elevated"])
        self._ax.tick_params(colors=C["text_3"], labelsize=7)
        self._ax.set_xlabel("Epoch", color=C["text_3"], fontsize=7)
        self._ax.set_ylabel("Loss", color=C["text_3"], fontsize=7)
        self._ax.grid(True, alpha=0.3, color=C["border"])
        for spine in self._ax.spines.values():
            spine.set_color(C["border"])

        # 按 algo 分组画线（仅当前视频）
        current_algos = set(d["algo"] for d in self._loss_history
                            if d.get("bvid") == self._current_bvid)
        if not current_algos:
            current_algos = set(d["algo"] for d in self._loss_history)

        for algo_name in current_algos:
            pts = [d for d in self._loss_history if d["algo"] == algo_name]
            epochs = [d["epoch"] for d in pts]
            train = [d["train_loss"] for d in pts]
            val = [d["val_loss"] for d in pts]
            self._ax.plot(epochs, train, "-o", label=f"{algo_name} train",
                          markersize=2, linewidth=1)
            valid_val = [(e, v) for e, v in zip(epochs, val) if v >= 0]
            if valid_val:
                self._ax.plot([e for e, v in valid_val], [v for e, v in valid_val],
                              "--s", label=f"{algo_name} val", markersize=2, linewidth=1)

        self._ax.legend(fontsize=6, loc="upper right", facecolor=C["bg_elevated"],
                        edgecolor=C["border"], labelcolor=C["text_1"])
        self._fig.tight_layout(pad=1.5)
        self._canvas.draw_idle()

    def _clear_chart(self):
        if not mpl_available or self._ax is None:
            return
        self._ax.clear()
        self._ax.set_facecolor(C["bg_elevated"])
        self._ax.tick_params(colors=C["text_3"], labelsize=7)
        self._ax.set_xlabel("Epoch", color=C["text_3"], fontsize=7)
        self._ax.set_ylabel("Loss", color=C["text_3"], fontsize=7)
        self._ax.grid(True, alpha=0.3, color=C["border"])
        for spine in self._ax.spines.values():
            spine.set_color(C["border"])
        self._fig.tight_layout(pad=1.5)
        self._canvas.draw_idle()

    # ══════════════════════════════════════════════
    # 日志
    # ══════════════════════════════════════════════

    def _append_log(self, text: str):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {text}\n"
        self._log_text.config(state="normal")
        self._log_text.insert(tk.END, line)
        self._log_text.see(tk.END)
        self._log_text.config(state="disabled")

    def _clear_log(self):
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", tk.END)
        self._log_text.config(state="disabled")
