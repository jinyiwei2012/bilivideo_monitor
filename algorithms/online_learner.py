"""
在线学习模块 — 根据预测误差实时调整算法权重

核心机制：
    1. 对每个算法维护指数加权移动平均误差（EWMA）
    2. 用 Hedge 算法（指数权重专家混合 / Exponentiated Gradient）
       根据历史累积损失动态分配权重
    3. 支持学习率自适应：根据误差波动率调高/调低 eta
    4. 冷启动保护：数据不足时返回均匀权重，防止权重漂移

高级在线学习算法（可选）：
    - OGD (Online Gradient Descent)：直接沿梯度方向更新权重向量
    - FTRL (Follow The Regularized Leader)：自适应学习率 + L1 稀疏化

持久化：
    save() / load() 将学习状态保存到 JSON 文件，重启后不丢失经验。
"""

from __future__ import annotations

import math
import time
import threading
import logging
import json
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 默认参数 ──────────────────────────────────
# 这些参数控制 Hedge 算法的行为，可根据需要调整
DEFAULT_ETA = 0.5        # Hedge 学习率（越大权重对误差越敏感）
DEFAULT_MIN_WEIGHT = 0.05  # 最低权重（防止算法被彻底淘汰出局）
DEFAULT_WARMUP = 5       # 至少需要 N 次反馈才开始调整（冷启动保护）
DEFAULT_DECAY = 0.95     # EWMA 衰减系数（越大越重视历史，越平滑）
MAX_TRACKERS = 5000      # 最大追踪器数量，超出时清理最久未更新的


class _AlgorithmTracker:
    """单个算法的在线学习内部状态。

    追踪每个算法的误差累积、最近表现、权重等信息。
    使用 __slots__ 节省内存（因为可能有几十到上百个算法）。
    """

    __slots__ = ("name", "weight", "cumulative_loss", "ewma_loss", "error_count",
                 "last_error", "last_update", "recent_errors",
                 "_ftrl_g2", "_ftrl_g", "_ftrl_z")

    def __init__(self, name: str, initial_weight: float = 1.0):
        self.name = name  # 算法名称
        self.weight = initial_weight  # 当前权重
        self.cumulative_loss = 0.0     # Hedge 累积损失（∑ log(1+error)）
        self.ewma_loss = 0.0           # 指数加权移动平均误差（近期表现指标）
        self.error_count = 0           # 已收到反馈的次数
        self.last_error: float | None = None  # 最近一次的相对误差
        self.last_update: float = 0.0   # 上次更新时间戳（epoch seconds）
        self.recent_errors: List[float] = []  # 最近 N 次误差，用于波动率检测


class OnlineLearner:
    """在线学习器 — 基于 Hedge 算法动态调整所有算法的权重。

    核心思想：将每个预测算法视为一个"专家"，
    Hedge 算法根据各专家的历史表现动态分配权重。
    表现好的专家获得更高权重，但不完全淘汰表现差的（min_weight 保护）。

    用法
    ----
    >>> learner = OnlineLearner(['线性增长', '指数平滑', 'Gompertz'])
    >>> learner.update('线性增长', predicted=102000, actual=103500)
    >>> weights = learner.get_weights()  # 返回 {算法名: 权重} 字典
    """

    def __init__(
        self,
        algorithm_names: Optional[List[str]] = None,
        eta: float = DEFAULT_ETA,
        min_weight: float = DEFAULT_MIN_WEIGHT,
        warmup: int = DEFAULT_WARMUP,
        decay: float = DEFAULT_DECAY,
    ):
        """初始化在线学习器。

        Args:
            algorithm_names: 初始注册的算法名称列表
            eta: Hedge 学习率（默认 0.5）
            min_weight: 最低权重阈值（默认 0.05）
            warmup: 冷启动样本数（默认 5）
            decay: EWMA 衰减系数（默认 0.95）
        """
        self.eta = eta
        self.min_weight = min_weight
        self.warmup = warmup
        self.decay = decay
        self._lock = threading.RLock()  # 可重入锁，支持嵌套调用

        # 算法跟踪器字典：名称 → _AlgorithmTracker
        self._trackers: Dict[str, _AlgorithmTracker] = {}
        if algorithm_names:
            for name in algorithm_names:
                self._trackers[name] = _AlgorithmTracker(name)

        # 全局步数（用于触发周期性操作，如学习率调整）
        self._step = 0

    # ── 公共接口 ──────────────────────────────────

    def register(self, name: str, initial_weight: float = 1.0):
        """注册一个新的算法到在线学习中。

        Args:
            name: 算法名称
            initial_weight: 初始权重（默认 1.0）
        """
        with self._lock:
            if name not in self._trackers:
                self._trackers[name] = _AlgorithmTracker(name, initial_weight)

    def unregister(self, name: str):
        """从在线学习中移除一个算法。

        Args:
            name: 算法名称
        """
        with self._lock:
            self._trackers.pop(name, None)

    def remove_by_prefix(self, prefix: str):
        """按前缀移除追踪器（删除视频时调用，清理该视频的所有算法追踪器）。

        Args:
            prefix: 键名前缀（如 bvid + "/"）
        """
        with self._lock:
            to_remove = [k for k in self._trackers if k.startswith(prefix)]
            for k in to_remove:
                del self._trackers[k]
            if to_remove:
                logger.debug("[online_learner] 清理 %d 个追踪器 (prefix=%s)", len(to_remove), prefix)

    def cleanup_stale(self, max_age_seconds: float = 86400):
        """清理过期追踪器（超过 max_age_seconds 未更新的条目）。

        定期调用以防止内存无限增长。当追踪器总数超过 MAX_TRACKERS 时，
        优先清理最久未更新的条目。

        Args:
            max_age_seconds: 最大空闲时间（秒），默认 24 小时
        """
        now = time.time()
        with self._lock:
            # 按 last_update 升序排列（最旧的在前）
            sorted_trackers = sorted(self._trackers.items(),
                                     key=lambda kv: kv[1].last_update)
            removed = 0
            for name, t in sorted_trackers:
                # 超过容量上限或超过最大空闲时间，则移除
                if len(self._trackers) - removed > MAX_TRACKERS or \
                   (t.last_update > 0 and now - t.last_update > max_age_seconds):
                    del self._trackers[name]
                    removed += 1
                else:
                    break
            if removed:
                logger.debug("[online_learner] 清理 %d 个过期追踪器 (剩余 %d)", removed, len(self._trackers))

    def update(self, name: str, predicted: float, actual: float):
        """用最新真实值更新指定算法的学习状态。

        Parameters
        ----------
        name : str          算法名称
        predicted : float   上次预测值
        actual : float      当前实际观测值
        """
        if name not in self._trackers:
            logger.debug("在线学习跳过 %s: 未注册的算法", name)
            return

        if actual <= 0:
            logger.debug("在线学习跳过 %s: actual=%s <= 0", name, actual)
            return

        # 计算相对误差：error = |predicted - actual| / max(predicted, actual, 1)
        # 使用相对误差而非绝对误差，避免播放量量级的影响
        # max(1, ...) 防止除零，同时避免静止期误差频繁为 0
        base = max(predicted, actual, 1.0)
        error = abs(predicted - actual) / base

        with self._lock:
            t = self._trackers[name]
            t.last_error = error
            t.last_update = time.time()
            t.error_count += 1

            # 更新 EWMA 误差（指数加权移动平均）
            # 首次设置直接用当前误差，之后按 decay 权重混合
            if abs(t.ewma_loss) < 1e-10:
                t.ewma_loss = error
            else:
                t.ewma_loss = self.decay * t.ewma_loss + (1 - self.decay) * error

            # Hedge 累积损失（logloss 风格，确保非负且有界增长）
            # log(1+error) ∈ [0, log(2)] for error ∈ [0, 1]
            t.cumulative_loss += math.log(1 + error)

            # 维护近期误差滑动窗口（最多 10 条），用于自适应学习率
            t.recent_errors.append(error)
            if len(t.recent_errors) > 10:
                t.recent_errors.pop(0)

            self._step += 1

            # 每 5 步触发一次学习率自适应调整
            if self._step % 5 == 0:
                self._adjust_eta()

    def get_weights(self) -> Dict[str, float]:
        """获取当前推荐的权重字典。

        冷启动阶段（error_count < warmup）返回均匀权重；
        暖启动阶段使用 Hedge 指数权重混合：
            w_i ∝ exp(-eta * (cumulative_loss_i - min_loss))

        最后归一化使所有权重和为 1。

        Returns:
            dict: {算法名: 归一化权重} 字典
        """
        with self._lock:
            weights = {}
            warm_items = []
            cold_items = []
            # 区分冷启动与暖启动算法
            for name, t in self._trackers.items():
                if t.error_count < self.warmup:
                    cold_items.append(name)
                else:
                    warm_items.append(name)

            # 暖启动算法：用 Hedge 公式计算指数权重
            if warm_items:
                # 减去最小损失避免指数溢出（softmax trick）
                min_loss = min(self._trackers[n].cumulative_loss for n in warm_items)
                for name in warm_items:
                    t = self._trackers[name]
                    raw = math.exp(-self.eta * (t.cumulative_loss - min_loss))
                    weights[name] = max(self.min_weight, raw)

            # 冷启动算法：均匀权重（避免在数据不足时对初学者不公平）
            n_cold = len(cold_items)
            if n_cold:
                cold_weight = 1.0 / max(len(self._trackers), 1)
                for name in cold_items:
                    weights[name] = cold_weight

            # 归一化，使权重之和为 1
            total = sum(weights.values())
            if total > 0:
                weights = {k: v / total for k, v in weights.items()}

            return weights

    def get_algorithm_stats(self) -> Dict[str, Dict]:
        """获取所有算法的在线学习统计信息（供 UI / 调试使用）。

        Returns:
            dict: {算法名: {name, ewma_loss, cumulative_loss, error_count, last_error, weight}}
        """
        with self._lock:
            result = {}
            for name, t in self._trackers.items():
                result[name] = {
                    "name": t.name,
                    "ewma_loss": round(t.ewma_loss, 4),
                    "cumulative_loss": round(t.cumulative_loss, 4),
                    "error_count": t.error_count,
                    "last_error": round(t.last_error, 4) if t.last_error is not None else None,
                    "weight": round(self._quick_weight(name), 4),
                }
            return result

    def save(self, filepath: str):
        """将在线学习完整状态持久化到 JSON 文件。

        保存内容包括：步数、eta、decay、各算法的累积损失/EWMA/错误计数。

        Args:
            filepath: JSON 文件路径
        """
        with self._lock:
            data = {
                "step": self._step,
                "eta": self.eta,
                "decay": self.decay,
                "trackers": {},
            }
            for name, t in self._trackers.items():
                data["trackers"][name] = {
                    "cumulative_loss": t.cumulative_loss,
                    "ewma_loss": t.ewma_loss,
                    "error_count": t.error_count,
                    "last_error": t.last_error,
                    "last_update": t.last_update,
                }
            os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, filepath: str):
        """从 JSON 文件恢复在线学习状态。

        如果文件不存在则静默跳过。

        Args:
            filepath: JSON 文件路径
        """
        if not os.path.exists(filepath):
            return
        with self._lock:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._step = data.get("step", 0)
                self.eta = data.get("eta", DEFAULT_ETA)
                self.decay = data.get("decay", DEFAULT_DECAY)
                for name, td in data.get("trackers", {}).items():
                    if name in self._trackers:
                        t = self._trackers[name]
                        t.cumulative_loss = td.get("cumulative_loss", 0)
                        t.ewma_loss = td.get("ewma_loss", 0)
                        t.error_count = td.get("error_count", 0)
                        t.last_error = td.get("last_error")
                        t.last_update = td.get("last_update", 0)
            except Exception as e:
                logger.warning("OnlineLearner 加载失败: %s", e)

    def reset(self):
        """重置所有学习状态到初始值（清空历史经验）。"""
        with self._lock:
            self._step = 0
            for t in self._trackers.values():
                t.cumulative_loss = 0.0
                t.ewma_loss = 0.0
                t.error_count = 0
                t.last_error = None
                t.recent_errors.clear()

    # ── 自适应学习率 ──────────────────────────

    def _adjust_eta(self):
        """根据最近误差的变异系数（CV）动态调整 Hedge 学习率 eta。

        原理：
            - CV 高（分布漂移 / 突发变化）→ 增大 eta 加速适应新分布
            - CV 低（稳定状态）→ 减小 eta 使权重更稳健，减少噪声影响

        eta 被限制在 [0.1, 1.5] 范围内。
        """
        with self._lock:
            all_errors = []
            for t in self._trackers.values():
                all_errors.extend(t.recent_errors)
            if len(all_errors) < 5:
                return
            mean_err = sum(all_errors) / len(all_errors)
            if mean_err < 1e-8:
                return
            variance = sum((e - mean_err) ** 2 for e in all_errors) / len(all_errors)
            cv = (variance ** 0.5) / mean_err  # 变异系数 = σ / μ
            # eta 限制在 [0.1, 1.5]，CV 越高 eta 越大
            new_eta = max(0.1, min(1.5, DEFAULT_ETA * (0.5 + cv * 1.5)))
            if abs(new_eta - self.eta) > 0.05:
                logger.debug("[online_learner] eta 自适应: %.3f → %.3f (CV=%.2f)", self.eta, new_eta, cv)
                self.eta = new_eta

    # ── OGD / FTRL 高级在线学习 ──────────────────

    def update_ogd(self, name: str, gradient: float, lr: float = 0.01, l2_lambda: float = 0.001):
        """Online Gradient Descent 更新单个算法的权重。

        适用场景：算法预测值可直接求导（如线性模型、MLP 部分参数）。
        相比 Hedge（纯权重重新分配），OGD 直接沿梯度方向更新权重向量。

        Args:
            name: 算法名称
            gradient: 当前步的梯度（损失对权重的导数）
            lr: 学习率（默认 0.01）
            l2_lambda: L2 正则化系数（默认 0.001）
        """
        if name not in self._trackers:
            return
        with self._lock:
            t = self._trackers[name]
            # 首次使用 OGD 时初始化权重为 1.0
            if abs(t.weight) < 1e-10 and abs(t.ewma_loss) < 1e-10:
                t.weight = 1.0
            t.weight = t.weight - lr * (gradient + l2_lambda * t.weight)  # 沿梯度下降
            t.weight = max(self.min_weight, min(5.0, t.weight))  # 裁剪权重范围
            t.error_count += 1
            t.last_update = time.time()

    def update_ftrl(
        self, name: str, gradient: float,
        lr: float = 0.01, l1_lambda: float = 0.001, l2_lambda: float = 0.001,
        beta: float = 1.0,
    ):
        """Follow The Regularized Leader (FTRL-Proximal) 更新单个算法权重。

        FTRL 在在线学习中表现优异，尤其适合稀疏特征场景。
        相比 OGD，FTRL 对每个维度独立自适应学习率，L1 正则产生稀疏解。

        Args:
            name: 算法名称
            gradient: 当前梯度
            lr: 基础学习率（默认 0.01）
            l1_lambda: L1 正则系数（默认 0.001），产生稀疏性
            l2_lambda: L2 正则系数（默认 0.001），防止过拟合
            beta: 自适应学习率平滑系数（默认 1.0）
        """
        if name not in self._trackers:
            return
        with self._lock:
            t = self._trackers[name]
            # 累积梯度平方（用于自适应学习率分母）
            g2 = getattr(t, "_ftrl_g2", 0.0)
            g2_new = g2 + gradient * gradient
            t._ftrl_g2 = g2_new  # type: ignore

            # 累积梯度（带动量平滑）
            g_accum = getattr(t, "_ftrl_g", 0.0)
            g_accum_new = beta * g_accum + (1 - beta) * gradient
            t._ftrl_g = g_accum_new  # type: ignore

            # FTRL 更新公式核心
            sigma = (math.sqrt(g2_new) - math.sqrt(g2)) / lr
            z = getattr(t, "_ftrl_z", 0.0)
            z_new = z + gradient - sigma * t.weight
            t._ftrl_z = z_new  # type: ignore

            # 软阈值（L1 正则产生稀疏解）
            eta = lr / (math.sqrt(g2_new) + l2_lambda)
            if abs(z_new) <= l1_lambda:
                t.weight = 0.0  # L1 正则将小权重直接归零
            else:
                t.weight = -(z_new - l1_lambda * math.copysign(1, z_new)) * eta

            t.weight = max(self.min_weight, min(5.0, t.weight))  # 裁剪
            t.error_count += 1
            t.last_update = time.time()

    # ── 内部方法 ──────────────────────────────────

    def _quick_weight(self, name: str) -> float:
        """不加锁快速获取权重（调用方必须已持有 _lock）。

        Args:
            name: 算法名称

        Returns:
            float: 归一化权重值
        """
        weights = self.get_weights()
        return weights.get(name, 1.0)


# ── 全局单例 ────────────────────────────────────────
_global_learner: Optional[OnlineLearner] = None
_learner_lock = threading.Lock()


def get_online_learner(algorithm_names: Optional[List[str]] = None) -> OnlineLearner:
    """获取全局 OnlineLearner 单例（双检锁惰性初始化）。

    首次调用时创建实例，后续调用返回同一实例。
    如果传入新的算法名称，会自动注册。

    Args:
        algorithm_names: 首次创建时注册的算法名称列表

    Returns:
        OnlineLearner 实例
    """
    global _global_learner
    with _learner_lock:
        if _global_learner is None:
            _global_learner = OnlineLearner(algorithm_names)
        elif algorithm_names:
            # 单例已存在，仅注册新名称（不重建）
            for name in algorithm_names:
                _global_learner.register(name)
        return _global_learner
