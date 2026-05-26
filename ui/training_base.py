"""训练面板基类 — 提取 TrainingPanel 与 FinetunePanel 的共享逻辑。

包含：
- TrainingMonitor: 实时训练质量监控器（自动检测 NaN/过拟合/欠拟合/震荡/爆炸）
- BaseTrainingPanel: 训练/微调面板的共享基类
"""

import tkinter as tk
from tkinter import ttk
import threading
import queue as _q
import time
import math
import logging
from typing import Any, Dict, List, Optional
from ui.mpl_imports import mpl_available, Figure, FigureCanvasTkAgg
from ui.theme import C
from ui.helpers import (
    FONT,
    FONT_SM,
    clear_loss_chart,
)

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# 训练质量监控器
# ══════════════════════════════════════════════════════════════════════════════


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
        "good": ("🟢 训练良好", C["success"]),
        "warning": ("🟡 注意", C["warning"]),
        "danger": ("🔴 异常", C["danger"]),
        "info": ("🔵 收集中", C["text_3"]),
    }

    def update(self, epoch: int, train_loss: float, val_loss: float):
        self._points.append((epoch, train_loss, val_loss))
        self._evaluate()

    def _set_finding(self, level, status, suggestions):
        priority = {"danger": 3, "warning": 2, "good": 1, "info": 0}
        if priority.get(level, 0) > priority.get(self._finding_level, 0):
            self._finding_level = level
            self._finding_status = status
            self._finding_suggestions = suggestions

    def _check_nan(self, pts):
        for _, tl, vl in pts:
            if math.isnan(tl) or (vl >= 0 and math.isnan(vl)):
                self.status = "Loss = NaN — 训练失败"
                self.level = "danger"
                self.suggestions = ["降低学习率", "检查数据中是否有 NaN", "添加 gradient clipping"]
                return True
        return False

    def _check_loss_explosion(self, pts):
        if len(pts) < 2:
            return
        prev = pts[-2][1]
        curr = pts[-1][1]
        if prev > 1e-8 and curr > prev * 2.0:
            jump_ratio = curr / prev
            if jump_ratio > 5:
                self._set_finding("danger", f"Loss 爆炸 (×{jump_ratio:.1f})", ["大幅降低学习率", "检查数据归一化"])
            else:
                self._set_finding("warning", f"Loss 跳升 (×{jump_ratio:.1f})", ["适当降低学习率"])

    def _check_overfitting(self, pts, n):
        if n < 5 or not all(vl >= 0 for _, _, vl in pts[-5:]):
            return
        tl_trend = pts[-1][1] < pts[-5][1]
        vl_trend = [pts[i][2] for i in range(-5, 0)]
        vl_up = sum(1 for i in range(1, len(vl_trend)) if vl_trend[i] > vl_trend[i - 1])
        if tl_trend and vl_up >= 4:
            self._overfit_streak += 1
        else:
            self._overfit_streak = max(0, self._overfit_streak - 1)

        if self._overfit_streak >= 4:
            self._set_finding(
                "danger",
                "严重过拟合 — 必须停止",
                ["立即停止训练", "val_loss 已连续多 epoch 上升", "减小模型或增加正则化后重新训练"],
            )
        elif self._overfit_streak >= 2:
            self._set_finding(
                "warning",
                "过拟合 — val_loss 持续上升",
                ["降低学习率或提前停止", "增加 Dropout", "减小模型容量"],
            )

    def _check_no_improvement(self, pts, n):
        if n < 8 or not all(vl >= 0 for _, _, vl in pts[-8:]):
            return
        best_vl = min(vl for _, _, vl in pts)
        recent_vl = [vl for _, _, vl in pts[-4:]]
        if all(vl >= best_vl for vl in recent_vl):
            self._no_improve_streak += 1
        else:
            self._no_improve_streak = max(0, self._no_improve_streak - 1)

        if self._no_improve_streak >= 2:
            self._set_finding(
                "warning",
                "不再收敛 — val_loss 已停止下降",
                ["可提前停止", "尝试降低学习率后继续", "若已训练充足 epoch 则可接受当前结果"],
            )

    def _check_oscillation(self, pts, n):
        if n < 5:
            return
        recent = [tl for _, tl, _ in pts[-5:]]
        mean_tl = sum(recent) / len(recent)
        if mean_tl < 1e-8:
            return
        max_dev = max(abs(v - mean_tl) for v in recent)
        cv = max_dev / mean_tl
        # 连续方向变化次数
        dir_changes = sum(1 for i in range(2, len(recent)) if (recent[i] - recent[i-1]) * (recent[i-1] - recent[i-2]) < 0)
        if cv > 0.2 and dir_changes >= 2:
            self._set_finding("warning", "Loss 震荡 — 训练不稳定", ["降低学习率", "增大 batch size"])

    def _check_underfitting(self, pts, n):
        if n < 5:
            return
        early_avg = sum(p[1] for p in pts[:3]) / 3
        late_avg = sum(p[1] for p in pts[-3:]) / 3
        if early_avg > 0.01 and (early_avg - late_avg) / early_avg < 0.03:
            self._set_finding(
                "warning",
                "Loss 下降过慢 — 可能欠拟合",
                ["适当增大学习率", "增加模型容量", "检查数据是否包含有效信号"],
            )

    def _apply_finding(self, pts, n):
        if self._finding_level != "good":
            self.level = self._finding_level
            self.status = self._finding_status
            self.suggestions = self._finding_suggestions
        elif self._no_improve_streak >= 2:
            self.status = "✅ 训练正常 — 已收敛"
            self.level = "good"
        elif n >= 3:
            tl_trend = pts[-1][1] < pts[-3][1]
            if tl_trend:
                self.status = "✅ 训练正常 — Loss 稳步下降"
            else:
                self.status = "✅ 训练正常 — Loss 趋于平稳"
            self.level = "good"

    def _evaluate(self):
        pts = self._points
        n = len(pts)
        self.suggestions.clear()
        self._finding_level = "good"
        self._finding_status = "训练正常"
        self._finding_suggestions = []

        if self._check_nan(pts):
            return

        if n < 3:
            self.status = f"收集数据 ({n}/3 epoch)…"
            self.level = "info"
            return

        self._check_loss_explosion(pts)
        self._check_overfitting(pts, n)
        self._check_no_improvement(pts, n)
        self._check_oscillation(pts, n)
        self._check_underfitting(pts, n)
        self._apply_finding(pts, n)

    def get_status_display(self):
        """返回 (status_text, color)"""
        label, color = self.STATUS_LABELS.get(self.level, ("", C["text_3"]))
        return f"{label}  {self.status}", color

    def get_tip(self) -> str:
        """返回一条当前最关键的简短建议，没有则返回空字符串。"""
        if self.suggestions:
            return "💡 " + self.suggestions[0]
        return ""

    # ── 动态 LR 系数计算 ─────────────────────────

    def compute_lr_scale(self, issue_type: str) -> float:
        """根据实际 loss 数据动态计算 LR 乘除系数。

        Args:
            issue_type: "explosion" | "oscillation" | "overfitting" | "underfitting"

        Returns:
            大于 1 表示增大 LR，小于 1 表示减小 LR。
        """
        pts = self._points
        n = len(pts)
        if n < 2:
            return 1.0

        if issue_type == "explosion":
            prev = pts[-2][1]
            curr = pts[-1][1]
            if prev > 1e-8 and curr > prev:
                jump_ratio = curr / prev
                scale = 1.0 / max(jump_ratio, 1.5)
                return max(0.1, min(0.6, scale))
            return 0.5

        if issue_type == "oscillation":
            recent = [p[1] for p in pts[-min(6, n) :]]
            mean = sum(recent) / len(recent)
            if mean > 1e-8:
                max_dev = max(abs(v - mean) for v in recent)
                cv = max_dev / mean
                scale = 1.0 / (1.0 + cv * 3.0)
                return max(0.3, min(0.9, scale))
            return 0.7

        if issue_type == "overfitting":
            recent_vl = [p[2] for p in pts[-4:] if p[2] >= 0]
            if len(recent_vl) >= 3:
                vl_increasing = sum(1 for i in range(1, len(recent_vl)) if recent_vl[i] > recent_vl[i-1])
                ratio = vl_increasing / (len(recent_vl) - 1)
                scale = 1.0 - ratio * 0.5
                return max(0.3, min(0.85, scale))
            return 0.7

        if issue_type == "underfitting":
            early_avg = sum(p[1] for p in pts[:3]) / 3
            late_avg = sum(p[1] for p in pts[-3:]) / 3
            if early_avg > 1e-8 and late_avg > 0:
                drop_ratio = (early_avg - late_avg) / early_avg
                per_epoch = drop_ratio / max(1, n - 1)
                target_per_epoch = 0.015
                scale = target_per_epoch / max(1e-4, per_epoch)
                return max(1.05, min(2.5, scale))
            return 1.5

        return 1.0

    # ── 动态梯度裁剪系数 ──────────────────────

    def compute_grad_clip(self, issue_type: str) -> float:
        """根据 loss 动态计算梯度裁剪阈值。

        Args:
            issue_type: "explosion" | "oscillation"

        Returns:
            裁剪阈值（>0 启用），数值越小裁剪越强。
        """
        pts = self._points
        n = len(pts)
        if n < 2:
            return 0.0

        if issue_type == "explosion":
            prev = pts[-2][1]
            curr = pts[-1][1]
            if prev > 1e-8 and curr > prev:
                jump_ratio = curr / prev
                return max(0.1, min(10.0, 2.0 / max(1.5, jump_ratio - 0.5)))
            return 1.0

        if issue_type == "oscillation":
            recent = [p[1] for p in pts[-min(6, n):]]
            mean = sum(recent) / len(recent)
            if mean > 1e-8:
                max_dev = max(abs(v - mean) for v in recent)
                cv = max_dev / mean
                return max(0.5, min(20.0, 5.0 / max(1.0, cv * 2)))
            return 5.0

        return 0.0

    # ── 动态权重衰减系数 ──────────────────────

    def compute_weight_decay(self) -> float:
        """根据过拟合程度动态计算 weight_decay。

        Returns:
            适用的 weight_decay 值（0 表示不启用）。
        """
        pts = self._points
        n = len(pts)
        if n < 5:
            return 0.0

        valids = [(tl, vl) for _, tl, vl in pts[-8:] if vl >= 0]
        if len(valids) < 5:
            train_only = [tl for _, tl, _ in pts[-8:]]
            if len(train_only) >= 5:
                early = sum(train_only[:3]) / 3
                late = sum(train_only[-3:]) / 3
                if early > 1e-8 and late / early > 0.95:
                    return 0.005
            return 0.0

        tl_trend = valids[-1][0] < valids[-5][0]
        vl_rising = sum(1 for i in range(1, len(valids)) if valids[i][1] > valids[i-1][1])
        ratio = vl_rising / (len(valids) - 1)

        if tl_trend and ratio > 0.7:
            return 0.02
        if ratio > 0.5:
            return 0.01
        if ratio > 0.3:
            return 0.005
        return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 训练/微调面板共享基类
# ══════════════════════════════════════════════════════════════════════════════


class BaseTrainingPanel:
    """训练/微调面板的共享基类。

    提供：
    - 共享状态变量（_training / _cancel_flag / _skip_algo_flag / _train_thread / …）
    - Loss 图表构建 (_build_chart_widgets) / 更新 (_update_chart) / 清空 (_clear_chart)
    - 日志构建 (_build_log_widgets) / 追加 (_append_log) / 清空 (_clear_log)
    - 训练质量监控栏 (_build_monitor_bar / _refresh_monitor)
    - 取消/跳过按钮逻辑 (_on_cancel / _on_skip_algo)
    - 训练生命周期：准备 (_prepare_training) → 启动线程 (_launch_worker)
      → 轮询 (_poll_progress / _handle_stage) → 清理 (_cleanup_training)
    """

    def __init__(self, parent: tk.Widget, main_gui):
        self.parent = parent
        self.main = main_gui
        self.frame = tk.Frame(parent, bg=C["bg_base"])

        # 训练线程状态
        self._training = False
        self._cancel_flag = [False]
        self._skip_algo_flag = [False]
        self._train_thread: Optional[threading.Thread] = None
        self._train_queue: Optional[_q.Queue] = None
        self._train_t0: Optional[float] = None

        # Loss 历史
        self._loss_history: List[Dict[str, Any]] = []
        self._current_aid = ""

        # 训练质量监控器
        self._monitor = TrainingMonitor()
        self._last_monitor_level = ""
        self._last_monitor_status = ""
        self._last_monitor_log_epoch = 0

        # 图表（由 _build_chart_widgets 设置）
        self._fig: Optional[Figure] = None
        self._canvas: Optional[FigureCanvasTkAgg] = None
        self._ax = None

        # 日志（由 _build_log_widgets 设置）
        self._log_text: Optional[tk.Text] = None

        # UI 控件引用（由子类 _build_controls 设置）
        self._train_btn: Optional[ttk.Button] = None
        self._cancel_btn: Optional[ttk.Button] = None
        self._skip_btn: Optional[ttk.Button] = None
        self._progress: Optional[ttk.Progressbar] = None
        self._status_lbl: Optional[tk.Label] = None

        # 训练质量监控控件（由 _build_monitor_bar 设置）
        self._monitor_icon: Optional[tk.Label] = None
        self._monitor_status: Optional[tk.Label] = None
        self._monitor_tip: Optional[tk.Label] = None

    # ══════════════════════════════════════════════════════════════════════════
    # Chart
    # ══════════════════════════════════════════════════════════════════════════

    def _build_chart_widgets(self, parent, title="") -> tk.Frame:
        """创建 matplotlib 图表控件。返回 chart_frame。"""
        chart_frame = tk.Frame(parent, bg=C["bg_elevated"])
        if title:
            tk.Label(chart_frame, text=title, bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(
                anchor="nw", padx=4, pady=(2, 0)
            )
        if not mpl_available:
            tk.Label(
                chart_frame, text="matplotlib 未安装，无法显示图表", bg=C["bg_elevated"], fg=C["text_3"], font=FONT
            ).pack(expand=True)
            return chart_frame

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
        return chart_frame

    def _update_chart(self):
        """刷新 Loss 折线图。子类可重写 _get_chart_series 自定义分组。"""
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

        for algo_name, pts in self._get_chart_series():
            epochs = [d["epoch"] for d in pts]
            train = [d["train_loss"] for d in pts]
            val = [d["val_loss"] for d in pts]
            self._ax.plot(epochs, train, "-o", label=f"{algo_name} train", markersize=2, linewidth=1)
            valid_val = [(e, v) for e, v in zip(epochs, val) if v >= 0]
            if valid_val:
                self._ax.plot(
                    [e for e, v in valid_val],
                    [v for e, v in valid_val],
                    "--s",
                    label=f"{algo_name} val",
                    markersize=2,
                    linewidth=1,
                )

        self._ax.legend(
            fontsize=6, loc="upper right", facecolor=C["bg_elevated"], edgecolor=C["border"], labelcolor=C["text_1"]
        )
        self._fig.tight_layout(pad=1.5)
        self._canvas.draw_idle()

    def _get_chart_series(self):
        """返回 [(系列名, 条目列表)]。默认按 algo 分组。子类可重写以过滤。"""
        algos = set(d["algo"] for d in self._loss_history)
        return [(a, [d for d in self._loss_history if d["algo"] == a]) for a in sorted(algos)]

    def _clear_chart(self):
        clear_loss_chart(self._ax, self._fig, self._canvas)

    # ══════════════════════════════════════════════════════════════════════════
    # Log
    # ══════════════════════════════════════════════════════════════════════════

    def _build_log_widgets(self, parent, title="日志") -> tk.Frame:
        """创建日志文本框区域。返回 log_frame。"""
        log_frame = tk.Frame(parent, bg=C["bg_elevated"])

        log_hdr = tk.Frame(log_frame, bg=C["bg_elevated"])
        log_hdr.pack(fill=tk.X)
        tk.Label(log_hdr, text=title, bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(
            side=tk.LEFT, padx=4, pady=(2, 0)
        )
        ttk.Button(log_hdr, text="清空", command=self._clear_log, width=4).pack(side=tk.RIGHT, padx=4)

        self._log_text = tk.Text(
            log_frame,
            bg=C["bg_base"],
            fg=C["text_1"],
            font=("Consolas", 9),
            relief="flat",
            bd=0,
            wrap=tk.WORD,
            state="disabled",
            highlightthickness=1,
            highlightbackground=C["border_sub"],
        )
        self._log_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=(2, 4))

        log_sb = ttk.Scrollbar(log_frame, orient="vertical", command=self._log_text.yview)
        log_sb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4), pady=(2, 4))
        self._log_text.configure(yscrollcommand=log_sb.set)

        return log_frame

    def _append_log(self, text: str):
        if self._log_text is None:
            return
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {text}\n"
        self._log_text.config(state="normal")
        self._log_text.insert(tk.END, line)
        self._log_text.see(tk.END)
        self._log_text.config(state="disabled")

    def _clear_log(self):
        if self._log_text is None:
            return
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", tk.END)
        self._log_text.config(state="disabled")

    # ══════════════════════════════════════════════════════════════════════════
    # Monitor
    # ══════════════════════════════════════════════════════════════════════════

    def _build_monitor_bar(self, parent) -> tk.Frame:
        """创建训练质量监控状态栏。返回 monitor_bar。"""
        monitor_bar = tk.Frame(parent, bg=C["bg_surface"], highlightthickness=1, highlightbackground=C["border_sub"])

        self._monitor_icon = tk.Label(monitor_bar, text="🔵", bg=C["bg_surface"], font=("Segoe UI", 14))
        self._monitor_icon.pack(side=tk.LEFT, padx=(6, 2), pady=2)
        self._monitor_status = tk.Label(
            monitor_bar, text="等待训练开始…", bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM, anchor="w"
        )
        self._monitor_status.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2, pady=2)
        self._monitor_tip = tk.Label(
            monitor_bar, text="", bg=C["bg_surface"], fg=C["text_3"], font=("Microsoft YaHei UI", 8), anchor="e"
        )
        self._monitor_tip.pack(side=tk.RIGHT, padx=(4, 8), pady=2)

        return monitor_bar

    def _refresh_monitor(self):
        text, color = self._monitor.get_status_display()
        if self._monitor_status:
            self._monitor_status.config(text=text, fg=color)
        tip = self._monitor.get_tip()
        if self._monitor_tip:
            self._monitor_tip.config(text=tip)
        icon_map = {"good": "🟢", "warning": "🟡", "danger": "🔴", "info": "🔵"}
        if self._monitor_icon:
            self._monitor_icon.config(text=icon_map.get(self._monitor.level, "🔵"))

        self._on_monitor_changed()

    def _on_monitor_changed(self):
        """子类可重写以在监控状态变化时添加额外日志。"""
        pass

    # ══════════════════════════════════════════════════════════════════════════
    # Cancel / Skip
    # ══════════════════════════════════════════════════════════════════════════

    def _on_cancel(self):
        self._cancel_flag[0] = True
        if self._cancel_btn:
            self._cancel_btn.config(state="disabled")
        self._append_log("⏹ 用户请求取消训练")

    def _on_skip_algo(self):
        self._skip_algo_flag[0] = True
        if self._skip_btn:
            self._skip_btn.config(state="disabled")
        self._append_log("⏭ 用户请求跳过当前算法")

    # ══════════════════════════════════════════════════════════════════════════
    # Training lifecycle
    # ══════════════════════════════════════════════════════════════════════════

    def _prepare_training(self):
        """训练前重置状态、锁定 UI。"""
        self._training = True
        self._cancel_flag[0] = False
        self._skip_algo_flag[0] = False
        self._monitor.reset()
        self._loss_history.clear()
        self._clear_chart()
        self._clear_log()
        if self._train_btn:
            self._train_btn.config(state="disabled")
        if self._cancel_btn:
            self._cancel_btn.config(state="normal")
        if self._skip_btn:
            self._skip_btn.config(state="normal")
        if self._progress:
            self._progress["value"] = 0

    def _launch_worker(self, worker_func):
        """创建队列并启动工作线程 + 轮询循环。"""
        self._train_t0 = time.time()
        self._train_queue = _q.Queue()
        self._train_thread = threading.Thread(target=worker_func, daemon=True)
        self._train_thread.start()
        self.frame.after(150, self._poll_progress)

    def _poll_progress(self):
        """主轮询循环：不断从队列取消息 → _handle_stage → 完成时 _cleanup_training。"""
        if self._train_queue is None:
            return
        done_all = False
        try:
            while True:
                msg = self._train_queue.get_nowait()
                if self._handle_stage(msg):
                    done_all = True
        except _q.Empty:
            pass
        if done_all:
            self._cleanup_training()
        else:
            self.frame.after(200, self._poll_progress)

    def _handle_stage(self, msg) -> bool:
        """处理单条进度消息。返回 True 表示训练全部结束。子类必须实现。"""
        raise NotImplementedError

    def _cleanup_training(self):
        """训练结束后恢复 UI。子类可通过 super() 扩展。"""
        self._training = False
        if self._train_btn:
            self._train_btn.config(state="normal")
        if self._cancel_btn:
            self._cancel_btn.config(state="disabled")
        if self._skip_btn:
            self._skip_btn.config(state="disabled")
        self._train_queue = None
        self._train_thread = None
