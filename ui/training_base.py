"""
训练面板基类 — 提取 TrainingPanel 与 FinetunePanel 的共享逻辑。

包含：
- TrainingMonitor: 实时训练质量监控器（自动检测 NaN/过拟合/欠拟合/震荡/爆炸）
- BaseTrainingPanel: 训练/微调面板的共享基类（PyQt6 版）
"""

import threading
import queue as _q
import time
import math
import logging
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QProgressBar, QFrame,
)
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont

from ui.mpl_imports import mpl_available, Figure, FigureCanvasQTAgg
from ui.theme import C
from ui.async_queue_runner import AsyncQueueRunner
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
        """初始化监控器"""
        self.reset()

    def reset(self):
        """重置所有监控状态"""
        self._points: List[tuple] = []  # [(epoch, train_loss, val_loss)]
        self.status = "等待数据…"
        self.level = "info"  # "good" | "warning" | "danger" | "info"
        self.suggestions: List[str] = []
        self._overfit_streak = 0  # 过拟合连续计数
        self._no_improve_streak = 0  # 不收敛连续计数

    STATUS_LABELS = {
        "good": ("● 训练良好", C["success"]),
        "warning": ("● 注意", C["warning"]),
        "danger": ("● 异常", C["danger"]),
        "info": ("● 收集中", C["text_3"]),
    }

    def update(self, epoch: int, train_loss: float, val_loss: float):
        """添加一个新的 epoch 数据点并重新评估"""
        self._points.append((epoch, train_loss, val_loss))
        self._evaluate()

    def _set_finding(self, level, status, suggestions):
        """按优先级记录监控发现（高风险优先覆盖低风险）"""
        priority = {"danger": 3, "warning": 2, "good": 1, "info": 0}
        if priority.get(level, 0) > priority.get(self._finding_level, 0):
            self._finding_level = level
            self._finding_status = status
            self._finding_suggestions = suggestions

    def _check_nan(self, pts):
        """检查 loss 是否为 NaN"""
        for _, tl, vl in pts:
            if math.isnan(tl) or (vl >= 0 and math.isnan(vl)):
                self.status = "Loss = NaN — 训练失败"
                self.level = "danger"
                self.suggestions = ["降低学习率", "检查数据中是否有 NaN", "添加 gradient clipping"]
                return True
        return False

    def _check_loss_explosion(self, pts):
        """检查 loss 是否发生爆炸性增长"""
        if len(pts) < 2:
            return
        prev = pts[-2][1]
        curr = pts[-1][1]
        # 如果 loss 翻倍以上则判定为爆炸
        if prev > 1e-8 and curr > prev * 2.0:
            jump_ratio = curr / prev
            if jump_ratio > 5:
                self._set_finding("danger", f"Loss 爆炸 (×{jump_ratio:.1f})", ["大幅降低学习率", "检查数据归一化"])
            else:
                self._set_finding("warning", f"Loss 跳升 (×{jump_ratio:.1f})", ["适当降低学习率"])

    def _check_overfitting(self, pts, n):
        """检查是否过拟合：训练 loss 下降但验证 loss 持续上升"""
        if n < 5 or not all(vl >= 0 for _, _, vl in pts[-5:]):
            return
        tl_trend = pts[-1][1] < pts[-5][1]  # 训练 loss 下降趋势
        vl_trend = [pts[i][2] for i in range(-5, 0)]
        vl_up = sum(1 for i in range(1, len(vl_trend)) if vl_trend[i] > vl_trend[i - 1])  # 验证 loss 上升次数
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
        """检查是否不再收敛：验证 loss 已停止下降"""
        if n < 8 or not all(vl >= 0 for _, _, vl in pts[-8:]):
            return
        best_before = min(vl for _, _, vl in pts[:-4])  # 最近 4 epoch 之前的最佳
        best_recent = min(vl for _, _, vl in pts[-4:])  # 最近 4 epoch 的最佳
        if best_before > 0 and best_recent >= best_before * 0.995:
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
        """检查 loss 是否震荡：变异系数大且方向频繁变化"""
        if n < 5:
            return
        recent = [tl for _, tl, _ in pts[-5:]]
        mean_tl = sum(recent) / len(recent)
        if mean_tl < 1e-8:
            return
        max_dev = max(abs(v - mean_tl) for v in recent)
        cv = max_dev / mean_tl  # 变异系数
        dir_changes = sum(
            1 for i in range(2, len(recent)) if (recent[i] - recent[i - 1]) * (recent[i - 1] - recent[i - 2]) < 0
        )
        if cv > 0.2 and dir_changes >= 2:
            self._set_finding("warning", "Loss 震荡 — 训练不稳定", ["降低学习率", "增大 batch size"])

    def _check_underfitting(self, pts, n):
        """检查是否欠拟合：训练初期到后期 loss 下降不足 3%"""
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
        """根据发现的最高优先级问题，更新最终状态"""
        if self._finding_level != "good":
            self.level = self._finding_level
            self.status = self._finding_status
            self.suggestions = self._finding_suggestions
        elif self._no_improve_streak >= 2:
            self.status = "✓ 训练正常 — 已收敛"
            self.level = "good"
        elif n >= 3:
            tl_trend = pts[-1][1] < pts[-3][1]
            if tl_trend:
                self.status = "✓ 训练正常 — Loss 稳步下降"
            else:
                self.status = "✓ 训练正常 — Loss 趋于平稳"
            self.level = "good"

    def _evaluate(self):
        """执行完整的训练质量评估流水线"""
        pts = self._points
        n = len(pts)
        self.suggestions.clear()
        self._finding_level = "good"
        self._finding_status = "训练正常"
        self._finding_suggestions = []

        # 按优先级依次检查：NaN > 爆炸 > 过拟合 > 不收敛 > 震荡 > 欠拟合
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
            return "✦ " + self.suggestions[0]
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

        # 爆炸：按跳升比例大幅降低 LR
        if issue_type == "explosion":
            prev = pts[-2][1]
            curr = pts[-1][1]
            if prev > 1e-8 and curr > prev:
                jump_ratio = curr / prev
                scale = 1.0 / max(jump_ratio, 1.5)
                return max(0.1, min(0.6, scale))
            return 0.5

        # 震荡：按变异系数降低 LR
        if issue_type == "oscillation":
            recent = [p[1] for p in pts[-min(6, n):]]
            mean = sum(recent) / len(recent)
            if mean > 1e-8:
                max_dev = max(abs(v - mean) for v in recent)
                cv = max_dev / mean
                scale = 1.0 / (1.0 + cv * 3.0)
                return max(0.3, min(0.9, scale))
            return 0.7

        # 过拟合：按验证 loss 上升比例降低 LR
        if issue_type == "overfitting":
            recent_vl = [p[2] for p in pts[-4:] if p[2] >= 0]
            if len(recent_vl) >= 3:
                vl_increasing = sum(1 for i in range(1, len(recent_vl)) if recent_vl[i] > recent_vl[i - 1])
                ratio = vl_increasing / (len(recent_vl) - 1)
                scale = 1.0 - ratio * 0.5
                return max(0.3, min(0.85, scale))
            return 0.7

        # 欠拟合：按实际下降速度与目标速度的比值提高 LR
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

        # 爆炸：按跳升比例计算裁剪阈值
        if issue_type == "explosion":
            prev = pts[-2][1]
            curr = pts[-1][1]
            if prev > 1e-8 and curr > prev:
                jump_ratio = curr / prev
                return max(0.1, min(10.0, 2.0 / max(1.5, jump_ratio - 0.5)))
            return 1.0

        # 震荡：按变异系数计算裁剪阈值
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
            # 只有训练 loss 时，如果后期下降很少则启用小幅度 weight_decay
            train_only = [tl for _, tl, _ in pts[-8:]]
            if len(train_only) >= 5:
                early = sum(train_only[:3]) / 3
                late = sum(train_only[-3:]) / 3
                if early > 1e-8 and late / early > 0.95:
                    return 0.005
            return 0.0

        tl_trend = valids[-1][0] < valids[-5][0]  # 训练 loss 是否下降
        vl_rising = sum(1 for i in range(1, len(valids)) if valids[i][1] > valids[i - 1][1])  # 验证 loss 上升次数
        ratio = vl_rising / (len(valids) - 1)

        # 训练 loss 下降但验证 loss 持续上升 → 过拟合，按比例启用 weight_decay
        if tl_trend and ratio > 0.7:
            return 0.02
        if ratio > 0.5:
            return 0.01
        if ratio > 0.3:
            return 0.005
        return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 训练/微调面板共享基类 — PyQt6 版
# ══════════════════════════════════════════════════════════════════════════════


class BaseTrainingPanel(AsyncQueueRunner, QWidget):
    """训练/微调面板的共享基类 — PyQt6 版。

    提供：
    - 共享状态变量（_training / _cancel_flag / _skip_algo_flag / _train_thread / …）
    - Loss 图表构建 (_build_chart_widgets) / 更新 (_update_chart) / 清空 (_clear_chart)
    - 日志构建 (_build_log_widgets) / 追加 (_append_log) / 清空 (_clear_log)
    - 训练质量监控栏 (_build_monitor_bar / _refresh_monitor)
    - 取消/跳过按钮逻辑 (_on_cancel / _on_skip_algo)
    - 训练生命周期：准备 (_prepare_training) → 启动线程 (_launch_worker)
      → 轮询 (_poll_progress / _handle_stage) → 清理 (_cleanup_training)
    """

    def __init__(self, parent: QWidget, main_gui, *, no_frame=False):
        """初始化共享面板基类

        :param parent: 父控件
        :param main_gui: 主窗口引用
        :param no_frame: 如果为 True，不创建 self.frame（由子类自行管理）
        """
        super().__init__(parent)
        self._parent_widget = parent
        self.main = main_gui

        if not no_frame:
            self.setStyleSheet(f"background-color: {C['bg_base']};")

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
        self._canvas: Optional[FigureCanvasQTAgg] = None
        self._ax = None

        # 日志（由 _build_log_widgets 设置）
        self._log_text: Optional[QPlainTextEdit] = None

        # UI 控件引用（由子类 _build_controls 设置）
        self._train_btn: Optional[QPushButton] = None
        self._cancel_btn: Optional[QPushButton] = None
        self._skip_btn: Optional[QPushButton] = None
        self._progress: Optional[QProgressBar] = None
        self._status_lbl: Optional[QLabel] = None

        # 训练质量监控控件（由 _build_monitor_bar 设置）
        self._monitor_icon: Optional[QLabel] = None
        self._monitor_status: Optional[QLabel] = None
        self._monitor_tip: Optional[QLabel] = None

    # ══════════════════════════════════════════════════════════════════════════
    # Chart
    # ══════════════════════════════════════════════════════════════════════════

    def _build_chart_widgets(self, parent, title="") -> QWidget:
        """创建 matplotlib 图表控件。返回 chart_frame。"""
        chart_frame = QWidget(parent)
        chart_frame.setStyleSheet(f"background-color: {C['bg_elevated']};")
        layout = QVBoxLayout(chart_frame)
        layout.setContentsMargins(0, 0, 0, 0)

        if title:
            title_lbl = QLabel(title)
            title_lbl.setStyleSheet(f"color: {C['text_2']}; font-size: 8pt; padding: 2px 4px;")
            layout.addWidget(title_lbl)
        if not mpl_available:
            no_mpl = QLabel("matplotlib 未安装，无法显示图表")
            no_mpl.setStyleSheet(f"color: {C['text_3']}; background-color: {C['bg_elevated']};")
            no_mpl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(no_mpl, 1)
            return chart_frame

        # 初始化 matplotlib 图表的样式和轴
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

        self._canvas = FigureCanvasQTAgg(self._fig)
        self._canvas.setParent(chart_frame)
        self._canvas.setStyleSheet("background-color: transparent;")
        layout.addWidget(self._canvas, 1)
        self._canvas.draw()
        return chart_frame

    def _update_chart(self):
        """刷新 Loss 折线图。子类可重写 _get_chart_series 自定义分组。"""
        if not mpl_available or self._ax is None or self._fig is None or self._canvas is None:
            return
        # 清空并重设样式
        self._ax.clear()
        self._ax.set_facecolor(C["bg_elevated"])
        self._ax.tick_params(colors=C["text_3"], labelsize=7)
        self._ax.set_xlabel("Epoch", color=C["text_3"], fontsize=7)
        self._ax.set_ylabel("Loss", color=C["text_3"], fontsize=7)
        self._ax.grid(True, alpha=0.3, color=C["border"])
        for spine in self._ax.spines.values():
            spine.set_color(C["border"])

        # 按算法分组绘制训练/验证 loss 曲线
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
        """清空图表并释放 matplotlib 资源。"""
        if self._ax is not None and self._fig is not None and self._canvas is not None:
            clear_loss_chart(self._fig, self._canvas)
        # 释放 matplotlib figure，避免内存泄漏
        try:
            import matplotlib.pyplot as plt
            plt.close(self._fig)
        except Exception:
            pass
        if self._canvas is not None:
            try:
                self._canvas.deleteLater()
            except Exception:
                pass

    # ══════════════════════════════════════════════════════════════════════════
    # Log
    # ══════════════════════════════════════════════════════════════════════════

    def _build_log_widgets(self, parent, title="日志") -> QWidget:
        """创建日志文本框区域。返回 log_frame。"""
        log_frame = QWidget(parent)
        log_frame.setStyleSheet(f"background-color: {C['bg_elevated']};")
        layout = QVBoxLayout(log_frame)
        layout.setContentsMargins(0, 0, 0, 0)

        log_hdr = QWidget()
        log_hdr.setStyleSheet(f"background-color: {C['bg_elevated']};")
        hdr_layout = QHBoxLayout(log_hdr)
        hdr_layout.setContentsMargins(4, 2, 4, 2)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {C['text_2']}; font-size: 8pt;")
        hdr_layout.addWidget(title_lbl)
        hdr_layout.addStretch()

        clear_btn = QPushButton("清空")
        clear_btn.setFixedWidth(50)
        clear_btn.clicked.connect(self._clear_log)
        hdr_layout.addWidget(clear_btn)

        layout.addWidget(log_hdr)

        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {C['bg_base']};
                color: {C['text_1']};
                font-family: Consolas;
                font-size: 9pt;
                border: 1px solid {C['border_sub']};
                padding: 2px;
            }}
        """)
        layout.addWidget(self._log_text, 1)

        return log_frame

    def _append_log(self, text: str):
        """向日志文本框追加一条带时间戳的日志"""
        if self._log_text is None:
            return
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {text}"
        self._log_text.appendPlainText(line)
        # 滚动到底部
        sb = self._log_text.verticalScrollBar()
        if sb is not None:
            sb.setValue(sb.maximum())

    def _clear_log(self):
        """清空日志文本框"""
        if self._log_text is not None:
            self._log_text.clear()

    # ══════════════════════════════════════════════════════════════════════════
    # Monitor
    # ══════════════════════════════════════════════════════════════════════════

    def _build_monitor_bar(self, parent) -> QWidget:
        """创建训练质量监控状态栏。返回 monitor_bar。"""
        monitor_bar = QWidget(parent)
        monitor_bar.setStyleSheet(f"background-color: {C['bg_surface']}; border: 1px solid {C['border_sub']};")
        layout = QHBoxLayout(monitor_bar)
        layout.setContentsMargins(6, 2, 8, 2)

        self._monitor_icon = QLabel("●")
        self._monitor_icon.setStyleSheet(f"background-color: {C['bg_surface']}; font-size: 14px;")
        layout.addWidget(self._monitor_icon)

        self._monitor_status = QLabel("等待训练开始…")
        self._monitor_status.setStyleSheet(f"color: {C['text_3']}; background-color: {C['bg_surface']}; font-size: 8pt;")
        layout.addWidget(self._monitor_status, 1)

        self._monitor_tip = QLabel("")
        self._monitor_tip.setStyleSheet(f"color: {C['text_3']}; background-color: {C['bg_surface']}; font-size: 8pt;")
        self._monitor_tip.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._monitor_tip)

        return monitor_bar

    def _refresh_monitor(self):
        """刷新训练质量监控 UI 显示"""
        text, color = self._monitor.get_status_display()
        if self._monitor_status:
            self._monitor_status.setText(text)
            self._monitor_status.setStyleSheet(
                f"color: {color}; background-color: {C['bg_surface']}; font-size: 8pt;"
            )
        tip = self._monitor.get_tip()
        if self._monitor_tip:
            self._monitor_tip.setText(tip)
        icon_map = {"good": "●", "warning": "●", "danger": "●", "info": "●"}
        if self._monitor_icon:
            self._monitor_icon.setText(icon_map.get(self._monitor.level, "●"))

        self._on_monitor_changed()

    def _on_monitor_changed(self):
        """子类可重写以在监控状态变化时添加额外日志。"""
        pass

    # ══════════════════════════════════════════════════════════════════════════
    # Cancel / Skip
    # ══════════════════════════════════════════════════════════════════════════

    def _on_cancel(self):
        """请求取消当前训练"""
        self._cancel_flag[0] = True
        if self._cancel_btn:
            self._cancel_btn.setEnabled(False)
        self._append_log("⏹ 用户请求取消训练")

    def _on_skip_algo(self):
        """请求跳过当前算法"""
        self._skip_algo_flag[0] = True
        if self._skip_btn:
            self._skip_btn.setEnabled(False)
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
            self._train_btn.setEnabled(False)
        if self._cancel_btn:
            self._cancel_btn.setEnabled(True)
        if self._skip_btn:
            self._skip_btn.setEnabled(True)
        if self._progress:
            self._progress.setValue(0)

    # 线程 + 队列 + 轮询机制已抽至 AsyncQueueRunner mixin (_launch_worker/_poll_progress/_handle_stage)

    def _cleanup_training(self):
        """训练结束后恢复 UI。子类可通过 super() 扩展。"""
        self._training = False
        if self._train_btn:
            self._train_btn.setEnabled(True)
        if self._cancel_btn:
            self._cancel_btn.setEnabled(False)
        if self._skip_btn:
            self._skip_btn.setEnabled(False)
        self._train_queue = None
        self._train_thread = None
