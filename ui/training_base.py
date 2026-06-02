"""
训练面板基类模块
===============

提取 ``TrainingPanel`` 与 ``FinetunePanel`` 的共享逻辑。

包含两个核心类：
  1. **TrainingMonitor** — 实时训练质量监控器
     - 自动检测：NaN、Loss 爆炸、过拟合、欠拟合、震荡、不再收敛
     - 动态学习率系数计算（针对不同问题类型）
     - 动态梯度裁剪阈值计算
     - 动态权重衰减系数计算
  2. **BaseTrainingPanel** — 训练/微调面板共享基类
     - Chart 图表（_build_chart_widgets / _update_chart / _clear_chart）
     - Log 日志（_build_log_widgets / _append_log / _clear_log）
     - Monitor 监控栏（_build_monitor_bar / _refresh_monitor）
     - 取消/跳过按钮逻辑（_on_cancel / _on_skip_algo）
     - 训练生命周期管理（_prepare_training → _launch_worker → _poll_progress → _cleanup_training）

子类必须实现 ``_handle_stage(msg)`` 方法以处理训练进度消息。
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
    """
    实时训练质量监控器 — 自动判断模型好坏并给出建议。

    内部维护一个 (epoch, train_loss, val_loss) 列表，每添加一个 epoch 数据点
    就重新评估训练质量。评估按优先级依次检查：
      NaN > 爆炸 > 过拟合 > 不收敛 > 震荡 > 欠拟合

    检测到问题后通过 ``_set_finding()`` 记录最高优先级的发现，
    最终由 ``_apply_finding()`` 更新 status / level / suggestions。
    """

    def __init__(self):
        """初始化监控器，重置所有状态"""
        self.reset()

    def reset(self):
        """
        重置所有监控状态。
        在每次新的训练启动时调用，清空历史数据点。
        """
        self._points: List[tuple] = []  # [(epoch, train_loss, val_loss)]
        self.status = "等待数据…"       # 状态描述文本
        self.level = "info"             # 状态等级：good | warning | danger | info
        self.suggestions: List[str] = []  # 改进建议列表
        self._overfit_streak = 0        # 过拟合连续计数（用于判断持久性）
        self._no_improve_streak = 0     # 不收敛连续计数

    # 级别 → (图标+标签, 颜色) 的映射
    STATUS_LABELS = {
        "good": ("🟢 训练良好", C["success"]),
        "warning": ("🟡 注意", C["warning"]),
        "danger": ("🔴 异常", C["danger"]),
        "info": ("🔵 收集中", C["text_3"]),
    }

    def update(self, epoch: int, train_loss: float, val_loss: float):
        """
        添加一个新的 epoch 数据点并重新评估训练质量。

        :param epoch: 当前 epoch 编号
        :param train_loss: 训练损失值
        :param val_loss: 验证损失值（-1 表示无验证）
        """
        self._points.append((epoch, train_loss, val_loss))
        self._evaluate()

    def _set_finding(self, level, status, suggestions):
        """
        按优先级记录监控发现。
        只有当新问题优先级大于当前已记录的最高优先级时才会覆盖。
        优先级：danger(3) > warning(2) > good(1) > info(0)

        :param level: 问题等级
        :param status: 状态描述
        :param suggestions: 建议列表
        """
        priority = {"danger": 3, "warning": 2, "good": 1, "info": 0}
        if priority.get(level, 0) > priority.get(self._finding_level, 0):
            self._finding_level = level
            self._finding_status = status
            self._finding_suggestions = suggestions

    def _check_nan(self, pts):
        """
        检查 loss 是否为 NaN（训练失败的最严重问题）。

        :returns: True 表示检测到 NaN
        """
        for _, tl, vl in pts:
            if math.isnan(tl) or (vl >= 0 and math.isnan(vl)):
                self.status = "Loss = NaN — 训练失败"
                self.level = "danger"
                self.suggestions = ["降低学习率", "检查数据中是否有 NaN", "添加 gradient clipping"]
                return True
        return False

    def _check_loss_explosion(self, pts):
        """
        检查 loss 是否发生爆炸性增长。
        如果最新 loss 是上一轮的 2 倍以上，判定为爆炸（>5x 为 danger，否则 warning）。
        """
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
        """
        检查是否过拟合：训练 loss 下降但验证 loss 持续上升。
        使用最近 5 个 epoch 的验证 loss 趋势判断。
        连续 4+ 轮过拟合 = danger，2+ 轮 = warning。
        """
        if n < 5 or not all(vl >= 0 for _, _, vl in pts[-5:]):
            return
        tl_trend = pts[-1][1] < pts[-5][1]  # 训练 loss 是否有下降趋势
        vl_trend = [pts[i][2] for i in range(-5, 0)]
        vl_up = sum(1 for i in range(1, len(vl_trend)) if vl_trend[i] > vl_trend[i - 1])  # 验证 loss 连续上升次数
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
        """
        检查是否不再收敛：验证 loss 已停止下降。
        比较最近 4 epoch 的最佳 loss 和之前的最佳 loss，若差距 < 0.5% 则判定为停滞。
        """
        if n < 8 or not all(vl >= 0 for _, _, vl in pts[-8:]):
            return
        best_before = min(vl for _, _, vl in pts[:-4])  # 前 4 epoch 之前的最佳
        best_recent = min(vl for _, _, vl in pts[-4:])   # 最近 4 epoch 的最佳
        if best_before > 0 and best_recent >= best_before * 0.995:  # 改善不足 0.5%
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
        """
        检查 loss 是否震荡：变异系数大（>20%）且方向频繁变化（>=2 次）。
        """
        if n < 5:
            return
        recent = [tl for _, tl, _ in pts[-5:]]
        mean_tl = sum(recent) / len(recent)
        if mean_tl < 1e-8:
            return
        max_dev = max(abs(v - mean_tl) for v in recent)
        cv = max_dev / mean_tl  # 变异系数（coefficient of variation）
        dir_changes = sum(1 for i in range(2, len(recent)) if (recent[i] - recent[i-1]) * (recent[i-1] - recent[i-2]) < 0)
        if cv > 0.2 and dir_changes >= 2:
            self._set_finding("warning", "Loss 震荡 — 训练不稳定", ["降低学习率", "增大 batch size"])

    def _check_underfitting(self, pts, n):
        """
        检查是否欠拟合：训练初期到后期的 loss 下降不足 3%。
        比较前 3 个 epoch 和最后 3 个 epoch 的平均 loss。
        """
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
        """
        根据发现的最高优先级问题，更新最终状态。
        无问题时根据当前数据量给出良好状态描述。
        """
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
        """
        执行完整的训练质量评估流水线。
        按优先级依次检测：NaN > 爆炸 > 过拟合 > 不收敛 > 震荡 > 欠拟合
        """
        pts = self._points
        n = len(pts)
        self.suggestions.clear()
        self._finding_level = "good"
        self._finding_status = "训练正常"
        self._finding_suggestions = []

        # NaN 检测（最高优先级，检测到立即返回）
        if self._check_nan(pts):
            return

        if n < 3:  # 数据不足，等待收集中
            self.status = f"收集数据 ({n}/3 epoch)…"
            self.level = "info"
            return

        # 依次执行各级检查
        self._check_loss_explosion(pts)
        self._check_overfitting(pts, n)
        self._check_no_improvement(pts, n)
        self._check_oscillation(pts, n)
        self._check_underfitting(pts, n)
        self._apply_finding(pts, n)

    def get_status_display(self):
        """
        获取用于 UI 显示的状态文本和颜色。

        :returns: (status_text, color) 元组
        """
        label, color = self.STATUS_LABELS.get(self.level, ("", C["text_3"]))
        return f"{label}  {self.status}", color

    def get_tip(self) -> str:
        """
        返回一条当前最关键的简短建议。

        :returns: 建议文本，无建议时返回空字符串
        """
        if self.suggestions:
            return "💡 " + self.suggestions[0]
        return ""

    # ── 动态 LR 系数计算 ─────────────────────────

    def compute_lr_scale(self, issue_type: str) -> float:
        """
        根据实际 loss 数据动态计算学习率缩放系数。

        :param issue_type: 问题类型
           - "explosion": 按跳升比例大幅降低 LR
           - "oscillation": 按变异系数降低 LR
           - "overfitting": 按验证 loss 上升比例降低 LR
           - "underfitting": 按实际下降速度与目标速度的比值提高 LR
        :returns: 学习率缩放系数（>1 增大 LR，<1 减小 LR）
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
                scale = 1.0 / max(jump_ratio, 1.5)  # 跳升越大，LR 降越多
                return max(0.1, min(0.6, scale))
            return 0.5

        # 震荡：按变异系数降低 LR
        if issue_type == "oscillation":
            recent = [p[1] for p in pts[-min(6, n) :]]
            mean = sum(recent) / len(recent)
            if mean > 1e-8:
                max_dev = max(abs(v - mean) for v in recent)
                cv = max_dev / mean  # 变异系数
                scale = 1.0 / (1.0 + cv * 3.0)  # 震荡越大，LR 降越多
                return max(0.3, min(0.9, scale))
            return 0.7

        # 过拟合：按验证 loss 上升比例降低 LR
        if issue_type == "overfitting":
            recent_vl = [p[2] for p in pts[-4:] if p[2] >= 0]
            if len(recent_vl) >= 3:
                vl_increasing = sum(1 for i in range(1, len(recent_vl)) if recent_vl[i] > recent_vl[i-1])
                ratio = vl_increasing / (len(recent_vl) - 1)  # 上升比例
                scale = 1.0 - ratio * 0.5  # 上升越多，LR 降越多
                return max(0.3, min(0.85, scale))
            return 0.7

        # 欠拟合：按实际下降速度与目标速度的比值提高 LR
        if issue_type == "underfitting":
            early_avg = sum(p[1] for p in pts[:3]) / 3       # 前 3 epoch 平均
            late_avg = sum(p[1] for p in pts[-3:]) / 3       # 后 3 epoch 平均
            if early_avg > 1e-8 and late_avg > 0:
                drop_ratio = (early_avg - late_avg) / early_avg  # 下降比例
                per_epoch = drop_ratio / max(1, n - 1)           # 每 epoch 下降率
                target_per_epoch = 0.015                          # 目标：每 epoch 下降 1.5%
                scale = target_per_epoch / max(1e-4, per_epoch)
                return max(1.05, min(2.5, scale))
            return 1.5

        return 1.0

    # ── 动态梯度裁剪系数 ──────────────────────

    def compute_grad_clip(self, issue_type: str) -> float:
        """
        根据 loss 动态计算梯度裁剪阈值。

        :param issue_type: "explosion" | "oscillation"
        :returns: 裁剪阈值（>0 启用），数值越小裁剪越强。0 表示不启用。
        """
        pts = self._points
        n = len(pts)
        if n < 2:
            return 0.0

        # 爆炸：跳升越大，裁剪阈值越小
        if issue_type == "explosion":
            prev = pts[-2][1]
            curr = pts[-1][1]
            if prev > 1e-8 and curr > prev:
                jump_ratio = curr / prev
                return max(0.1, min(10.0, 2.0 / max(1.5, jump_ratio - 0.5)))
            return 1.0

        # 震荡：变异系数越大，裁剪阈值越小
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
        """
        根据过拟合程度动态计算 weight_decay。

        判断逻辑：
          训练 loss 下降但验证 loss 持续上升 → 过拟合。
          验证 loss 上升的 epoch 占比越高，weight_decay 越大。

        :returns: 适用的 weight_decay 值（0 表示不启用）
        """
        pts = self._points
        n = len(pts)
        if n < 5:
            return 0.0

        # 有验证 loss 的情况
        valids = [(tl, vl) for _, tl, vl in pts[-8:] if vl >= 0]
        if len(valids) < 5:
            # 只有训练 loss：后期下降很少时启用小幅度 weight_decay
            train_only = [tl for _, tl, _ in pts[-8:]]
            if len(train_only) >= 5:
                early = sum(train_only[:3]) / 3
                late = sum(train_only[-3:]) / 3
                if early > 1e-8 and late / early > 0.95:  # 下降 < 5%
                    return 0.005
            return 0.0

        tl_trend = valids[-1][0] < valids[-5][0]  # 训练 loss 是否下降
        vl_rising = sum(1 for i in range(1, len(valids)) if valids[i][1] > valids[i-1][1])  # 验证 loss 上升次数
        ratio = vl_rising / (len(valids) - 1)  # 验证 loss 上升占比

        # 按过拟合程度分级返回 weight_decay
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
    """
    训练/微调面板的共享基类。

    提供：
      - 共享状态变量（_training / _cancel_flag / _skip_algo_flag / _train_thread / …）
      - Loss 图表构建 / 更新 / 清空
      - 日志构建 / 追加 / 清空
      - 训练质量监控栏构建 / 刷新
      - 取消/跳过按钮逻辑
      - 训练生命周期：准备 → 启动线程 → 轮询 → 清理

    子类需要实现：
      - ``_handle_stage(msg) -> bool``：处理单条进度消息
      - 可重写 ``_get_chart_series()`` 来自定义图表分组
      - 可重写 ``_on_monitor_changed()`` 添加监控状态变化时的额外日志
    """

    def __init__(self, parent: tk.Widget, main_gui):
        """
        初始化共享面板基类。

        :param parent: 父容器 Widget
        :param main_gui: 主界面实例
        """
        self.parent = parent
        self.main = main_gui
        self.frame = tk.Frame(parent, bg=C["bg_base"])

        # ── 训练线程状态 ──
        self._training = False                # 是否正在训练
        self._cancel_flag = [False]           # 取消标志（列表包装以便跨闭包修改）
        self._skip_algo_flag = [False]        # 跳过当前算法标志
        self._train_thread: Optional[threading.Thread] = None
        self._train_queue: Optional[_q.Queue] = None
        self._train_t0: Optional[float] = None  # 训练开始时间戳

        # Loss 历史
        self._loss_history: List[Dict[str, Any]] = []
        self._current_aid = ""  # 当前正在训练的算法 ID

        # 训练质量监控器
        self._monitor = TrainingMonitor()
        self._last_monitor_level = ""
        self._last_monitor_status = ""
        self._last_monitor_log_epoch = 0

        # 图表（由 _build_chart_widgets 设置）
        self._fig: Optional[Figure] = None
        self._canvas: Optional[FigureCanvasTkAgg] = None
        self._ax = None  # matplotlib Axes

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
    # Chart（Loss 图表）
    # ══════════════════════════════════════════════════════════════════════════

    def _build_chart_widgets(self, parent, title="") -> tk.Frame:
        """
        创建 matplotlib 图表控件。

        初始化 Figure → Axes → FigureCanvasTkAgg。
        设置轴标签、网格、颜色等样式。

        :param parent: 父容器
        :param title: 图表标题（显示在左上角）
        :returns: chart_frame（包含图表内容的 Frame）
        """
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

        self._canvas = FigureCanvasTkAgg(self._fig, master=chart_frame)
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
        self._canvas.draw()
        return chart_frame

    def _update_chart(self):
        """
        刷新 Loss 折线图。
        按算法分组绘制训练 loss（实线）和验证 loss（虚线）。
        子类可重写 _get_chart_series 自定义分组逻辑。
        """
        if not mpl_available or self._ax is None:
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
            # 验证 loss 只绘制有效值（>= 0）
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
        """
        返回图表系列数据。

        :returns: [(系列名, 条目列表)]，默认按 algo 字段分组。
                  子类可重写以过滤特定算法。
        """
        algos = set(d["algo"] for d in self._loss_history)
        return [(a, [d for d in self._loss_history if d["algo"] == a]) for a in sorted(algos)]

    def _clear_chart(self):
        """清空图表"""
        clear_loss_chart(self._ax, self._fig, self._canvas)

    # ══════════════════════════════════════════════════════════════════════════
    # Log（训练日志）
    # ══════════════════════════════════════════════════════════════════════════

    def _build_log_widgets(self, parent, title="日志") -> tk.Frame:
        """
        创建日志文本框区域。
        包含标题 + 清空按钮 + 带滚动条的只读 Text。

        :param parent: 父容器
        :param title: 日志区标题
        :returns: log_frame
        """
        log_frame = tk.Frame(parent, bg=C["bg_elevated"])

        # 日志标题行
        log_hdr = tk.Frame(log_frame, bg=C["bg_elevated"])
        log_hdr.pack(fill=tk.X)
        tk.Label(log_hdr, text=title, bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(
            side=tk.LEFT, padx=4, pady=(2, 0)
        )
        ttk.Button(log_hdr, text="清空", command=self._clear_log, width=4).pack(side=tk.RIGHT, padx=4)

        # 日志文本框（使用 readonly state 防止用户编辑）
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
        """
        向日志文本框追加一条带时间戳的日志。
        自动滚动到末尾。

        :param text: 日志内容（不含时间戳，会自动添加）
        """
        if self._log_text is None:
            return
        ts = time.strftime("%H:%M:%S")  # 时间戳格式 HH:MM:SS
        line = f"[{ts}] {text}\n"
        self._log_text.config(state="normal")   # 临时解锁
        self._log_text.insert(tk.END, line)
        self._log_text.see(tk.END)              # 自动滚动到最新
        self._log_text.config(state="disabled")  # 重新锁定

    def _clear_log(self):
        """清空日志文本框"""
        if self._log_text is None:
            return
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", tk.END)
        self._log_text.config(state="disabled")

    # ══════════════════════════════════════════════════════════════════════════
    # Monitor（训练质量监控栏）
    # ══════════════════════════════════════════════════════════════════════════

    def _build_monitor_bar(self, parent) -> tk.Frame:
        """
        创建训练质量监控状态栏。
        包含：图标、状态文本、简短建议

        :param parent: 父容器
        :returns: monitor_bar Frame
        """
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
        """
        刷新训练质量监控 UI 显示。
        从 _monitor 获取最新状态和颜色，更新所有标签。
        触发 _on_monitor_changed 钩子。
        """
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
        """
        子类可重写此钩子以在监控状态变化时添加额外日志。
        默认不执行任何操作。
        """
        pass

    # ══════════════════════════════════════════════════════════════════════════
    # Cancel / Skip（取消/跳过按钮逻辑）
    # ══════════════════════════════════════════════════════════════════════════

    def _on_cancel(self):
        """
        请求取消当前训练。
        设置 _cancel_flag[0] = True，禁用取消按钮，记录日志。
        """
        self._cancel_flag[0] = True
        if self._cancel_btn:
            self._cancel_btn.config(state="disabled")
        self._append_log("⏹ 用户请求取消训练")

    def _on_skip_algo(self):
        """
        请求跳过当前正在训练的算法，继续训练下一个。
        设置 _skip_algo_flag[0] = True，禁用跳过按钮，记录日志。
        """
        self._skip_algo_flag[0] = True
        if self._skip_btn:
            self._skip_btn.config(state="disabled")
        self._append_log("⏭ 用户请求跳过当前算法")

    # ══════════════════════════════════════════════════════════════════════════
    # Training lifecycle（训练生命周期管理）
    # ══════════════════════════════════════════════════════════════════════════

    def _prepare_training(self):
        """
        训练前准备：重置状态、锁定 UI。
          - 设置 _training = True
          - 重置取消/跳过标志
          - 重置监控器和 loss 历史
          - 清空图表和日志
          - 禁用训练按钮，启用取消/跳过按钮
          - 进度条归零
        """
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
        """
        创建队列并启动工作线程 + 轮询循环。

        :param worker_func: 工作线程的主函数
        """
        self._train_t0 = time.time()
        self._train_queue = _q.Queue()
        self._train_thread = threading.Thread(target=worker_func, daemon=True)
        self._train_thread.start()
        self.frame.after(150, self._poll_progress)  # 150ms 后开始轮询

    def _poll_progress(self):
        """
        主轮询循环：不断从队列取消息 → _handle_stage → 完成时 _cleanup_training。
        每次轮询间隔 200ms。
        """
        if self._train_queue is None:
            return
        done_all = False
        try:
            while True:  # 一次性处理所有积压消息
                msg = self._train_queue.get_nowait()
                if self._handle_stage(msg):
                    done_all = True
        except _q.Empty:
            pass
        if done_all:
            self._cleanup_training()
        else:
            self.frame.after(200, self._poll_progress)  # 继续轮询

    def _handle_stage(self, msg) -> bool:
        """
        处理单条进度消息。

        :param msg: 训练回调发来的消息字典
        :returns: True 表示训练全部结束，可进入清理
        :raises NotImplementedError: 子类必须实现此方法
        """
        raise NotImplementedError

    def _cleanup_training(self):
        """
        训练结束后恢复 UI。
        子类可通过 super()._cleanup_training() 扩展此方法，
        添加额外的清理逻辑（如刷新算法列表、发送通知等）。
        """
        self._training = False
        if self._train_btn:
            self._train_btn.config(state="normal")
        if self._cancel_btn:
            self._cancel_btn.config(state="disabled")
        if self._skip_btn:
            self._skip_btn.config(state="disabled")
        self._train_queue = None
        self._train_thread = None
