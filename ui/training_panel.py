"""
训练面板 - 主界面集成版
支持模型增量训练/重新训练，实时 loss 图表 + 文字日志。
"""

import tkinter as tk
from tkinter import ttk, messagebox
import io
import logging
import math
import os
import threading
import queue
import time
from typing import Any, Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)

_torch_available = True
try:
    import torch  # noqa: F401
except ImportError:
    _torch_available = False

# Matplotlib 内嵌
try:
    import matplotlib
    matplotlib.use("TkAgg", force=True)
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    _mpl_available = True
except Exception:
    _mpl_available = False

from ui.theme import C
from ui.helpers import FONT, FONT_SM, FONT_MONO, FONT_BOLD


class TrainingMonitor:
    """实时训练质量监控器 — 自动判断模型好坏并给出建议。"""

    def __init__(self):
        self.reset()

    def reset(self):
        self._points: List[tuple] = []  # [(epoch, train_loss, val_loss)]
        self.status = "等待数据…"
        self.level = "info"  # "good" | "warning" | "danger" | "info"
        self.suggestions: List[str] = []
        self._overfit_streak = 0
        self._no_improve_streak = 0

    STATUS_LABELS = {
        "good":   ("🟢 训练良好", C["success"]),
        "warning": ("🟡 注意", C["warning"]),
        "danger":  ("🔴 异常", C["danger"]),
        "info":    ("🔵 收集中", C["text_3"]),
    }

    def update(self, epoch: int, train_loss: float, val_loss: float):
        self._points.append((epoch, train_loss, val_loss))
        self._evaluate()

    def _evaluate(self):
        pts = self._points
        n = len(pts)
        self.suggestions.clear()

        # 1. NaN 检测（优先于所有检查，即使数据不足）
        for _, tl, vl in pts:
            if math.isnan(tl) or (vl >= 0 and math.isnan(vl)):
                self.status = "Loss = NaN — 训练失败"
                self.level = "danger"
                self.suggestions = ["降低学习率", "检查数据中是否有 NaN", "添加 gradient clipping"]
                return

        if n < 3:
            self.status = f"收集数据 ({n}/3 epoch)…"
            self.level = "info"
            return

        # 2. Loss 爆炸
        if n >= 3:
            recent = [tl for _, tl, _ in pts[-3:]]
            if max(recent) > 10 * (pts[0][1] or 1e-8):
                self.status = "Loss 爆炸 — 梯度可能溢出"
                self.level = "danger"
                self.suggestions = ["大幅降低学习率 (÷10)", "检查数据归一化"]
                return

        # 3. 过拟合 — val_loss 连续上升而 train_loss 下降
        if n >= 5 and all(vl >= 0 for _, _, vl in pts[-5:]):
            tl_trend = pts[-1][1] < pts[-5][1]   # train 在下降
            vl_trend = [pts[i][2] for i in range(-5, 0)]
            vl_up = sum(1 for i in range(1, len(vl_trend)) if vl_trend[i] > vl_trend[i-1])
            if tl_trend and vl_up >= 4:
                self._overfit_streak += 1
            else:
                self._overfit_streak = max(0, self._overfit_streak - 1)

            if self._overfit_streak >= 2:
                self.status = "⚠️ 过拟合 — val_loss 持续上升"
                self.level = "warning"
                self.suggestions = ["建议停止训练 (early stopping)", "增加 Dropout", "减小模型容量"]
                return

            if self._overfit_streak >= 4:
                self.status = "🚫 严重过拟合 — 必须停止"
                self.level = "danger"
                self.suggestions = ["立即停止训练", "val_loss 已连续多 epoch 上升",
                                    "减小模型或增加正则化后重新训练"]
                return

        # 4. 不再收敛 — val_loss 连续 N epoch 没有下降
        if n >= 8 and all(vl >= 0 for _, _, vl in pts[-8:]):
            best_vl = min(vl for _, _, vl in pts)
            recent_vl = [vl for _, _, vl in pts[-4:]]
            if all(vl >= best_vl for vl in recent_vl):
                self._no_improve_streak += 1
            else:
                self._no_improve_streak = max(0, self._no_improve_streak - 1)

            if self._no_improve_streak >= 2:
                self.status = "📉 不再收敛 — val_loss 已停止下降"
                self.level = "warning"
                self.suggestions = ["可以提前停止 (early stopping)", "尝试降低学习率后继续",
                                    "若已训练充足 epoch 则可接受当前结果"]
                # 不要 return，允许继续判断其他情况

        # 5. 震荡 — loss 波动剧烈（非单调下降的抖动）
        if n >= 8:
            recent_tl = [tl for _, tl, _ in pts[-8:]]
            # 排除单调下降的正常情况
            is_monotonic_down = all(recent_tl[i] >= recent_tl[i+1] for i in range(len(recent_tl)-1))
            if not is_monotonic_down:
                mean_tl = sum(recent_tl) / len(recent_tl)
                cv = math.sqrt(sum((x - mean_tl)**2 for x in recent_tl) / len(recent_tl)) / max(1e-8, mean_tl)
                # 同时检查残差（去趋势后的波动是否仍然很大）
                residual_var = sum(abs(recent_tl[i] - recent_tl[i-1]) for i in range(1, len(recent_tl))) / (len(recent_tl) - 1)
                avg_tl = abs(mean_tl)
                if cv > 0.3 and residual_var > 0.02 * max(1, avg_tl):
                    self.status = "📊 Loss 波动较大 — 训练不稳定"
                    self.level = "warning"
                    self.suggestions = ["降低学习率", "增大 batch size"]
                    return

        # 6. 欠拟合 — 前几个 epoch loss 下降太慢
        if n == max(5, n) and n >= 5:
            initial_loss = pts[0][1]
            current_loss = pts[-1][1]
            if initial_loss > 0.1 and (initial_loss - current_loss) / initial_loss < 0.05:
                self.status = "🐢 欠拟合 — Loss 下降过慢"
                self.level = "warning"
                self.suggestions = ["增大学习率", "增加模型容量 (更多层 / 更多神经元)",
                                    "检查数据是否包含有效信号"]
                return

        # 7. 正常训练
        if self._no_improve_streak >= 2:
            status = "已收敛" if self.level == "warning" else "训练中"
            self.status = f"✅ 训练正常 — {status}"
        elif n >= 3:
            tl_trend = pts[-1][1] < pts[-3][1]
            has_val = pts[-1][2] >= 0
            if tl_trend:
                self.status = "✅ 训练正常 — Loss 稳步下降"
                self.level = "good"
            else:
                self.status = "✅ 训练正常 — Loss 趋于平稳"
                self.level = "good"

    def get_status_display(self):
        """返回 (status_text, color)"""
        label, color = self.STATUS_LABELS.get(self.level, ("", C["text_3"]))
        return f"{label}  {self.status}", color

    def get_tip(self) -> str:
        """返回一条当前最关键的简短建议，没有则返回空字符串。"""
        if self.suggestions:
            return "💡 " + self.suggestions[0]
        return ""
    """训练面板 - 主界面选项卡"""

    def __init__(self, parent: tk.Widget, main_gui):
        self.parent = parent
        self.main = main_gui  # BilibiliMonitorGUI 实例
        self.frame = tk.Frame(parent, bg=C["bg_base"])

        # 状态变量
        self._check_vars: Dict[str, tk.BooleanVar] = {}
        self._algo_meta: Dict[str, Dict] = {}
        self._algo_confidence: Dict[str, float] = {}  # 训练完成时记录的置信度
        self._training = False
        self._cancel_flag = [False]
        self._train_thread: Optional[threading.Thread] = None
        self._train_queue: Optional[queue.Queue] = None
        self._train_t0: Optional[float] = None
        self._loss_history: List[Dict] = []  # [{epoch, train_loss, val_loss, algo_id}]
        self._current_algo = ""

        # 训练质量监控器
        self._monitor = TrainingMonitor()
        self._last_monitor_level = ""

        # 图表数据
        self._fig: Optional[Figure] = None
        self._canvas: Optional[FigureCanvasTkAgg] = None
        self._ax = None

        # 日志存盘
        self._log_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "log", "training"
        )
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

        tk.Label(info_bar, text="训练设备:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT, padx=(8, 2))
        self._device_lbl = tk.Label(info_bar, text="检测中…", bg=C["bg_elevated"], fg=C["text_1"], font=FONT)
        self._device_lbl.pack(side=tk.LEFT, padx=(0, 16))
        tk.Label(info_bar, text="数据规模:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT, padx=(8, 2))
        self._data_lbl = tk.Label(info_bar, text="估算中…", bg=C["bg_elevated"], fg=C["text_3"], font=FONT_SM)
        self._data_lbl.pack(side=tk.LEFT, padx=(0, 16))
        self._force_cpu_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(info_bar, text="强制 CPU", variable=self._force_cpu_var,
                        command=self._on_force_cpu).pack(side=tk.LEFT, padx=4)
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
        tk.Label(hdr, text="可训练算法（PyTorch）", bg=C["bg_surface"], fg=C["text_1"],
                 font=FONT_BOLD).pack(side=tk.LEFT)
        self._algo_count_lbl = tk.Label(hdr, text="", bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM)
        self._algo_count_lbl.pack(side=tk.RIGHT, padx=4)

        toolbar = tk.Frame(left, bg=C["bg_elevated"])
        toolbar.pack(fill=tk.X, padx=4, pady=(2, 2))
        ttk.Button(toolbar, text="全选", command=lambda: self._select_all(True), width=6).pack(side=tk.LEFT, padx=1)
        ttk.Button(toolbar, text="反选", command=lambda: self._select_all(False), width=6).pack(side=tk.LEFT, padx=1)
        ttk.Button(toolbar, text="仅未训练", command=self._select_untrained, width=8).pack(side=tk.LEFT, padx=1)

        # 滚动容器
        canvas = tk.Canvas(left, bg=C["bg_elevated"], highlightthickness=0, height=300)
        vsb = ttk.Scrollbar(left, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        algo_frame = tk.Frame(canvas, bg=C["bg_elevated"])
        canvas.create_window((0, 0), window=algo_frame, anchor="nw", tags="algo_frame")
        algo_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>",
                    lambda ev: canvas.yview_scroll(int(-1 * (ev.delta / 120)), "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        self._algo_frame = algo_frame
        self._algo_canvas = canvas

        # 表头
        hdr_row = tk.Frame(algo_frame, bg=C["bg_surface"])
        hdr_row.pack(fill=tk.X, pady=(0, 1))
        for col, (txt, w) in enumerate([("", 4), ("算法", 16), ("ID", 14), ("状态", 12), ("置信度", 10), ("版本", 8)]):
            tk.Label(hdr_row, text=txt, bg=C["bg_surface"], fg=C["text_3"],
                     font=("Microsoft YaHei UI", 8, "bold"), width=w, anchor="w"
                     ).grid(row=0, column=col, padx=2, pady=2, sticky="w")

    # ── 图表+日志 (右侧) ──

    def _build_chart_section(self, parent):
        right = tk.Frame(parent, bg=C["bg_surface"])
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        right.grid_rowconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)

        # 上半: Loss 图表
        chart_frame = tk.Frame(right, bg=C["bg_elevated"])
        chart_frame.grid(row=0, column=0, sticky="nsew", padx=4, pady=(4, 2))
        tk.Label(chart_frame, text="训练 Loss 曲线", bg=C["bg_elevated"], fg=C["text_2"],
                 font=FONT_SM).pack(anchor="nw", padx=4, pady=(2, 0))

        if _mpl_available:
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

        # 中部: 训练质量监控状态栏
        monitor_bar = tk.Frame(right, bg=C["bg_surface"], highlightthickness=1,
                               highlightbackground=C["border_sub"])
        monitor_bar.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 2))

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

        # 下半: 文字日志
        log_frame = tk.Frame(right, bg=C["bg_elevated"])
        log_frame.grid(row=2, column=0, sticky="nsew", padx=4, pady=(2, 4))

        log_hdr = tk.Frame(log_frame, bg=C["bg_elevated"])
        log_hdr.pack(fill=tk.X)
        tk.Label(log_hdr, text="训练日志", bg=C["bg_elevated"], fg=C["text_2"],
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

        # 训练参数
        tk.Label(ctrl, text="Epoch:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT, padx=(8, 2))
        self._epoch_var = tk.IntVar(value=20)
        ttk.Spinbox(ctrl, from_=1, to=500, textvariable=self._epoch_var, width=6).pack(side=tk.LEFT, padx=2)

        tk.Label(ctrl, text="Batch:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT, padx=(8, 2))
        self._batch_var = tk.IntVar(value=32)
        ttk.Spinbox(ctrl, from_=1, to=512, textvariable=self._batch_var, width=6).pack(side=tk.LEFT, padx=2)

        # 训练模式
        tk.Label(ctrl, text="模式:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT, padx=(8, 2))
        self._mode_var = tk.StringVar(value="incremental")
        ttk.Radiobutton(ctrl, text="增量训练", variable=self._mode_var, value="incremental").pack(side=tk.LEFT, padx=1)
        ttk.Radiobutton(ctrl, text="重新训练", variable=self._mode_var, value="retrain").pack(side=tk.LEFT, padx=1)

        # 按钮
        self._train_btn = ttk.Button(ctrl, text="▶ 开始训练", command=self._on_train_start,
                                     style="Primary.TButton")
        self._train_btn.pack(side=tk.LEFT, padx=(12, 4))
        self._cancel_btn = ttk.Button(ctrl, text="✕ 取消", command=self._on_train_cancel, state="disabled")
        self._cancel_btn.pack(side=tk.LEFT, padx=4)

        # 进度
        self._progress = ttk.Progressbar(ctrl, mode="determinate", maximum=100)
        self._progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 4))

        self._status_lbl = tk.Label(ctrl, text="就绪", bg=C["bg_elevated"], fg=C["text_3"],
                                    font=FONT_SM, anchor="w", width=40)
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
                self.frame.after(0, lambda: self._data_lbl.config(text=f"⚠ {e}", fg=C["danger"]))

        threading.Thread(target=_worker, daemon=True).start()

    def _discover_algorithms(self) -> List[Dict]:
        """扫描有 build_model 的算法"""
        from algorithms.registry import AlgorithmRegistry
        from algorithms.training.checkpoint_manager import CheckpointManager

        AlgorithmRegistry.initialize()
        result = []
        for adapter in AlgorithmRegistry.get_all_algorithms():
            algo = getattr(adapter, "algo", adapter)
            if not hasattr(algo, "build_model"):
                continue
            aid = getattr(algo, "algorithm_id", None) or getattr(algo, "name", None)
            if not aid:
                continue
            ckpt = CheckpointManager(aid)
            versions = ckpt.list_versions()
            result.append({
                "algorithm_id": aid,
                "name": getattr(algo, "name", aid),
                "category": getattr(algo, "category", ""),
                "has_ckpt": ckpt.has_checkpoint(),
                "active_version": ckpt.active_version() or "",
                "version_count": len(versions),
            })
        result.sort(key=lambda r: (not r["has_ckpt"], r["algorithm_id"]))
        return result

    def _refresh_algo_list(self):
        for w in self._algo_frame.winfo_children():
            w.destroy()
        self._check_vars.clear()
        self._algo_meta.clear()

        try:
            algos = self._discover_algorithms()
        except Exception as e:
            tk.Label(self._algo_frame, text=f"⚠ 加载失败: {e}",
                     bg=C["bg_elevated"], fg=C["danger"], font=FONT).pack(padx=4, pady=8)
            return

        trained = sum(1 for a in algos if a["has_ckpt"])
        self._algo_count_lbl.config(text=f"{len(algos)} 算法 · 已训练 {trained}")

        for a in algos:
            aid = a["algorithm_id"]
            self._algo_meta[aid] = a

            row = tk.Frame(self._algo_frame, bg=C["bg_surface"],
                           highlightthickness=1, highlightbackground=C["border_sub"])
            row.pack(fill=tk.X, pady=1)

            var = tk.BooleanVar(value=not a["has_ckpt"])
            self._check_vars[aid] = var
            ttk.Checkbutton(row, variable=var).grid(row=0, column=0, padx=4, pady=2)

            tk.Label(row, text=a["name"], bg=C["bg_surface"], fg=C["text_1"],
                     font=FONT, width=16, anchor="w").grid(row=0, column=1, padx=2, sticky="w")
            tk.Label(row, text=aid, bg=C["bg_surface"], fg=C["text_3"],
                     font=FONT_MONO, width=14, anchor="w").grid(row=0, column=2, padx=2, sticky="w")

            if a["has_ckpt"]:
                st = f"✅ {a['active_version'][:10]}"
                sf = C["success"]
            else:
                st = "□ 未训练"
                sf = C["text_3"]
            tk.Label(row, text=st, bg=C["bg_surface"], fg=sf,
                     font=FONT_SM, width=12, anchor="w").grid(row=0, column=3, padx=2, sticky="w")

            # 置信度列
            conf = self._load_confidence(aid)
            conf_text, conf_color = self._format_confidence(conf)
            tk.Label(row, text=conf_text, bg=C["bg_surface"], fg=conf_color,
                     font=FONT_SM, width=10, anchor="w").grid(row=0, column=4, padx=2, sticky="w")

            tk.Label(row, text=f"v{a['version_count']}", bg=C["bg_surface"], fg=C["text_3"],
                     font=FONT_SM, width=6, anchor="w").grid(row=0, column=5, padx=2, sticky="w")

    def _select_all(self, flag: bool):
        for v in self._check_vars.values():
            v.set(flag)

    def _select_untrained(self):
        for aid, var in self._check_vars.items():
            var.set(not self._algo_meta.get(aid, {}).get("has_ckpt", False))

    # ── 置信度辅助 ────────────────────────────────

    @staticmethod
    def _loss_to_confidence(val_loss: float) -> float:
        """将 val_loss 映射到 [0, 1] 置信度。"""
        if val_loss is None or val_loss < 0:
            return 0.0
        # exp(-loss): loss=0 → conf=1.0, loss=0.5 → conf≈0.61, loss=1.0 → conf≈0.37
        return max(0.0, min(1.0, math.exp(-val_loss)))

    @staticmethod
    def _format_confidence(conf: float):
        """返回 (显示文本, 颜色) 对。"""
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
        """读取算法 active checkpoint 的 val_loss 并计算置信度。"""
        try:
            from algorithms.training.checkpoint_manager import CheckpointManager
            ckpt = CheckpointManager(algo_id)
            versions = ckpt.list_versions()
            active_v = ckpt.active_version()
            if not versions or not active_v:
                return 0.0
            for v in versions:
                if v["version"] == active_v:
                    val_loss = v.get("val_loss", -1.0)
                    return self._loss_to_confidence(val_loss)
            # fallback: latest version
            return self._loss_to_confidence(versions[0].get("val_loss", -1.0))
        except Exception:
            return 0.0

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

        if not messagebox.askyesno(
            "确认训练",
            f"模式: {mode_label}\n算法: {len(selected)} 个\nepoch={epochs}  batch={batch}\n"
            f"训练过程不可中途暂停（只能取消未开始的算法）。",
            parent=self.frame,
        ):
            return

        # 重置监控器
        self._monitor.reset()

        # 锁定 UI
        self._training = True
        self._train_btn.config(state="disabled")
        self._cancel_btn.config(state="normal")
        self._cancel_flag[0] = False
        self._progress["value"] = 0
        self._loss_history.clear()
        self._clear_chart()
        self._clear_log()

        self._open_log_file(len(selected), epochs, batch, mode_label)
        self._append_log(f"🚀 开始训练: {mode_label}, {len(selected)} 个算法, epoch={epochs}, batch={batch}")
        self._status_lbl.config(text=f"准备训练 {len(selected)} 个算法 …", fg=C["text_2"])

        import queue as _q
        self._train_t0 = time.time()
        self._train_queue = _q.Queue()

        def _cb(payload: Dict):
            payload["_total_selected"] = len(selected)
            payload["_incremental"] = is_incremental
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
                    sub = trainer.train_global(
                        [aid], epochs=epochs, batch_size=batch, progress_cb=_cb,
                        init_from_global=is_incremental,
                    )
                    results.update(sub)
                self._train_queue.put({"stage": "all_done", "results": results})
            except Exception as e:
                self._train_queue.put({"stage": "fatal", "error": str(e)})

        self._train_thread = threading.Thread(target=_worker, daemon=True)
        self._train_thread.start()
        self.frame.after(150, self._poll_progress)

    def _on_train_cancel(self):
        self._cancel_flag[0] = True
        self._cancel_btn.config(state="disabled")
        self._status_lbl.config(text="正在取消（等待当前算法完成）…", fg=C["warning"])
        self._append_log("⏹ 用户请求取消训练")

    def _poll_progress(self):
        import queue as _q

        if self._train_queue is None:
            return

        done_all = False
        try:
            while True:
                msg = self._train_queue.get_nowait()
                stage = msg.get("stage")
                total_sel = msg.get("_total_selected", 1)

                if stage == "start":
                    aid = msg.get("algo_id", "?")
                    cur = msg.get("current", 0)
                    tot = msg.get("total", 1)
                    self._current_algo = aid
                    self._status_lbl.config(text=f"[{cur}/{tot}] 训练 {aid} …", fg=C["text_2"])
                    self._append_log(f"── [{cur}/{tot}] 开始训练 {aid} ──")

                elif stage == "epoch":
                    aid = msg.get("algo_id", "?")
                    ep = msg.get("epoch", 0)
                    eps = msg.get("epochs", 1)
                    tloss = msg.get("train_loss", 0.0)
                    vloss = msg.get("val_loss", -1.0)
                    elapsed = msg.get("elapsed_s", 0.0)

                    # 实时置信度（基于 val_loss）
                    conf = self._loss_to_confidence(vloss) if vloss >= 0 else 0.0
                    conf_str, _ = self._format_confidence(conf)

                    pct = min(100, int((ep / max(1, eps)) * 100))
                    self._progress["value"] = pct
                    total_elapsed = time.time() - self._train_t0 if self._train_t0 else 0
                    vtxt = f"  val={vloss:.4f}" if vloss >= 0 else ""
                    self._status_lbl.config(
                        text=f"{aid}  ep{ep}/{eps}  train={tloss:.4f}{vtxt}  {conf_str}  {elapsed:.0f}s",
                        fg=C["text_1"],
                    )

                    # 训练质量监控
                    self._monitor.update(ep, tloss, vloss if vloss >= 0 else -1)
                    self._refresh_monitor()

                    # 记录 loss 历史 + 更新图表
                    self._loss_history.append({
                        "algo": aid, "epoch": ep,
                        "train_loss": tloss, "val_loss": vloss,
                    })
                    self._update_chart()
                    self._append_log(
                        f"  epoch {ep:>3}/{eps}  |  "
                        f"train_loss={tloss:.6f}  |  "
                        f"{f'val_loss={vloss:.6f}' if vloss>=0 else 'val_loss=N/A'}  |  "
                        f"confidence={conf_str}  |  "
                        f"{elapsed:.1f}s"
                    )

                elif stage == "done":
                    aid = msg.get("algo_id", "?")
                    cur = msg.get("current", 0)
                    ver = msg.get("version", "")
                    self._status_lbl.config(text=f"✓ {aid} → {ver} ({cur}/{total_sel})", fg=C["success"])
                    self._progress["value"] = int(cur / max(1, total_sel) * 100)
                    self._append_log(f"✓ {aid} 完成, 保存为 {ver}")

                elif stage == "error":
                    aid = msg.get("algo_id", "?")
                    err = msg.get("error", "")
                    self._status_lbl.config(text=f"✗ {aid} 失败: {err}", fg=C["danger"])
                    self._append_log(f"✗ {aid} 训练失败: {err}")

                elif stage == "cancelled":
                    rem = msg.get("remaining", [])
                    self._status_lbl.config(text=f"已取消，剩余 {len(rem)} 个", fg=C["warning"])
                    self._append_log(f"⏹ 已取消, 剩余 {len(rem)} 个算法")
                    done_all = True

                elif stage == "all_done":
                    results = msg.get("results", {})
                    ok = sum(1 for v in results.values() if v)
                    bad = sum(1 for v in results.values() if not v)
                    elapsed = time.time() - self._train_t0 if self._train_t0 else 0

                    # 读取每个成功算法的最终置信度
                    conf_summary = ""
                    for aid, ver in results.items():
                        if not ver:
                            continue
                        conf = self._load_confidence(aid)
                        self._algo_confidence[aid] = conf
                        conf_str, _ = self._format_confidence(conf)
                        conf_summary += f"  {aid}: {conf_str}"

                    self._status_lbl.config(text=f"全部完成: ✓ {ok}  ✗ {bad}  · {elapsed:.0f}s", fg=C["success"])
                    self._progress["value"] = 100
                    self._append_log(f"🏁 训练全部完成: {ok} 成功, {bad} 失败, 耗时 {elapsed:.0f}s")
                    self._append_log(f"📊 各算法最终置信度:{conf_summary}")
                    done_all = True

                elif stage == "fatal":
                    err = msg.get("error", "")
                    self._status_lbl.config(text=f"训练异常: {err}", fg=C["danger"])
                    self._append_log(f"💥 训练进程异常: {err}")
                    done_all = True

        except _q.Empty:
            pass

        if done_all:
            self._training = False
            self._train_btn.config(state="normal")
            self._cancel_btn.config(state="disabled")
            self._train_queue = None
            self._train_thread = None
            # 关闭日志文件
            self._close_log_file()
            # 刷新列表
            self._refresh_algo_list()
            # 刷新主界面模型状态
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
        """更新监控状态栏显示。"""
        text, color = self._monitor.get_status_display()
        self._monitor_status.config(text=text, fg=color)
        tip = self._monitor.get_tip()
        self._monitor_tip.config(text=tip)

        # 图标映射
        icon_map = {"good": "🟢", "warning": "🟡", "danger": "🔴", "info": "🔵"}
        self._monitor_icon.config(text=icon_map.get(self._monitor.level, "🔵"))

        # 关键事件记录到日志
        if self._monitor.level in ("warning", "danger") and self._monitor.suggestions:
            # 只在首次触发时记录，避免刷屏：用 _last_monitor_level 跟踪
            last = getattr(self, "_last_monitor_level", "")
            if last != self._monitor.level:
                self._last_monitor_level = self._monitor.level
                self._append_log(f"🤖 训练质量检测: {self._monitor.status}")
                for s in self._monitor.suggestions:
                    self._append_log(f"  💡 {s}")

    # ══════════════════════════════════════════════
    # 图表
    # ══════════════════════════════════════════════

    def _update_chart(self):
        if not _mpl_available or self._ax is None:
            return
        self._ax.clear()
        self._ax.set_facecolor(C["bg_elevated"])
        self._ax.tick_params(colors=C["text_3"], labelsize=7)
        self._ax.set_xlabel("Epoch", color=C["text_3"], fontsize=7)
        self._ax.set_ylabel("Loss", color=C["text_3"], fontsize=7)
        self._ax.grid(True, alpha=0.3, color=C["border"])
        for spine in self._ax.spines.values():
            spine.set_color(C["border"])

        # 按 algo 分组画线
        algos_in_chart = set(d["algo"] for d in self._loss_history)
        for algo_name in algos_in_chart:
            pts = [d for d in self._loss_history if d["algo"] == algo_name]
            epochs = [d["epoch"] for d in pts]
            train = [d["train_loss"] for d in pts]
            val = [d["val_loss"] for d in pts]
            self._ax.plot(epochs, train, "-o", label=f"{algo_name} train", markersize=2, linewidth=1)
            valid_val = [(e, v) for e, v in zip(epochs, val) if v >= 0]
            if valid_val:
                self._ax.plot([e for e, v in valid_val], [v for e, v in valid_val],
                              "--s", label=f"{algo_name} val", markersize=2, linewidth=1)

        self._ax.legend(fontsize=6, loc="upper right", facecolor=C["bg_elevated"],
                        edgecolor=C["border"], labelcolor=C["text_1"])
        self._fig.tight_layout(pad=1.5)
        self._canvas.draw_idle()

    def _clear_chart(self):
        if not _mpl_available or self._ax is None:
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
    # 日志（UI + 存盘）
    # ══════════════════════════════════════════════

    def _open_log_file(self, algo_count: int, epochs: int, batch: int, mode: str):
        """创建训练日志文件。"""
        os.makedirs(self._log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_file_path = os.path.join(self._log_dir, f"train_{ts}.log")
        self._log_file = open(self._log_file_path, "w", encoding="utf-8")
        # 写文件头
        self._log_file.write(f"{'=' * 60}\n")
        self._log_file.write(f"  训练启动: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        self._log_file.write(f"  模式: {mode}  |  算法: {algo_count}  |  epoch: {epochs}  |  batch: {batch}\n")
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
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {text}\n"
        self._log_text.config(state="normal")
        self._log_text.insert(tk.END, line)
        self._log_text.see(tk.END)
        self._log_text.config(state="disabled")
        # 同时写入文件
        if self._log_file is not None:
            try:
                self._log_file.write(line)
                self._log_file.flush()
            except Exception as e:
                logger.debug("写入训练日志文件失败: %s", e)

    def _clear_log(self):
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", tk.END)
        self._log_text.config(state="disabled")
        # 不清除文件日志，下次训练会创建新文件
