"""
在线学习模块 — 根据预测误差实时调整算法权重

核心机制：
    1. 对每个算法维护指数加权移动平均误差（EWMA）
    2. 用 Hedge 算法（指数权重专家混合 / Exponentiated Gradient）
       根据历史累积损失动态分配权重
    3. 支持学习率自适应：根据误差波动率调高/调低 eta
    4. 冷启动保护：数据不足时返回均匀权重，防止权重漂移
"""

import math
import time
import threading
import logging
import json
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 默认参数
DEFAULT_ETA = 0.5  # Hedge 学习率
DEFAULT_MIN_WEIGHT = 0.05  # 最低权重（防止算法被彻底淘汰出局）
DEFAULT_WARMUP = 5  # 至少需要 N 次反馈才开始调整
DEFAULT_DECAY = 0.95  # EWMA 衰减系数（越大越重视历史）


class _AlgorithmTracker:
    """单个算法的在线学习内部状态。

    使用 __slots__ 节省内存（算法数量可能很多）。
    """

    __slots__ = (
        "name",
        "weight",
        "cumulative_loss",
        "ewma_loss",
        "error_count",
        "last_error",
        "last_update",
        "recent_errors",
    )

    def __init__(self, name: str, initial_weight: float = 1.0):
        self.name = name
        self.weight = initial_weight
        self.cumulative_loss = 0.0  # Hedge 累积损失
        self.ewma_loss = 0.0  # 指数加权移动平均误差
        self.error_count = 0  # 已收到反馈的次数
        self.last_error: float | None = None
        self.last_update: float = 0.0  # 上次更新时间戳
        self.recent_errors: List[float] = []  # 最近 N 次误差，用于波动率检测


class OnlineLearner:
    """在线学习器 — 基于 Hedge 算法动态调整所有算法的权重。

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
            eta: Hedge 学习率
            min_weight: 最低权重阈值
            warmup: 冷启动样本数
            decay: EWMA 衰减系数
        """
        self.eta = eta
        self.min_weight = min_weight
        self.warmup = warmup
        self.decay = decay
        self._lock = threading.RLock()

        self._trackers: Dict[str, _AlgorithmTracker] = {}
        if algorithm_names:
            for name in algorithm_names:
                self._trackers[name] = _AlgorithmTracker(name)

        # 全局步数（用于触发周期性操作，如学习率调整）
        self._step = 0

    # ── 公共接口 ──────────────────────────────────

    def register(self, name: str, initial_weight: float = 1.0):
        """注册一个新的算法到在线学习中。"""
        with self._lock:
            if name not in self._trackers:
                self._trackers[name] = _AlgorithmTracker(name, initial_weight)

    def unregister(self, name: str):
        """从在线学习中移除一个算法。"""
        with self._lock:
            self._trackers.pop(name, None)

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
        # 使用 max(1, ...) 防止除零，同时避免静止期误差频繁为 0
        base = max(predicted, actual, 1.0)
        error = abs(predicted - actual) / base

        with self._lock:
            t = self._trackers[name]
            t.last_error = error
            t.last_update = time.time()
            t.error_count += 1

            # 更新 EWMA 误差
            if abs(t.ewma_loss) < 1e-10:
                t.ewma_loss = error
            else:
                t.ewma_loss = self.decay * t.ewma_loss + (1 - self.decay) * error

            # Hedge 累积损失（logloss 风格，确保非负且有界增长）
            t.cumulative_loss += math.log(1 + error)

            # 维护近期误差滑动窗口，用于自适应学习率
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
        暖启动阶段使用 Hedge 指数权重混合。
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

            # 暖启动算法：用 Hedge 公式计算权重
            if warm_items:
                min_loss = min(self._trackers[n].cumulative_loss for n in warm_items)
                for name in warm_items:
                    t = self._trackers[name]
                    raw = math.exp(-self.eta * (t.cumulative_loss - min_loss))
                    weights[name] = max(self.min_weight, raw)

            # 冷启动算法：均匀权重
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
        """获取所有算法的在线学习统计信息（供 UI / 调试使用）。"""
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
        """将在线学习完整状态持久化到 JSON 文件。"""
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
        """从 JSON 文件恢复在线学习状态。"""
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
        """重置所有学习状态到初始值。"""
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
            - CV 高（分布漂移 / 突发变化）→ 增大 eta 加速适应
            - CV 低（稳定状态）→ 减小 eta 使权重更稳健
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
            cv = (variance**0.5) / mean_err
            # eta 限制在 [0.1, 1.5]，CV 越高 eta 越大
            new_eta = max(0.1, min(1.5, DEFAULT_ETA * (0.5 + cv * 1.5)))
            if abs(new_eta - self.eta) > 0.05:
                logger.debug("[online_learner] eta 自适应: %.3f → %.3f (CV=%.2f)", self.eta, new_eta, cv)
                self.eta = new_eta

    # ── 内部方法 ──────────────────────────────────

    def _quick_weight(self, name: str) -> float:
        """不加锁快速获取权重（调用方必须已持有 _lock）。"""
        weights = self.get_weights()
        return weights.get(name, 1.0)


# ── 全局单例 ────────────────────────────────────────
_global_learner: Optional[OnlineLearner] = None
_learner_lock = threading.Lock()


def get_online_learner(algorithm_names: Optional[List[str]] = None) -> OnlineLearner:
    """获取全局 OnlineLearner 单例（双检锁惰性初始化）。

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
            # 单例已存在，仅注册新名称
            for name in algorithm_names:
                _global_learner.register(name)
        return _global_learner
