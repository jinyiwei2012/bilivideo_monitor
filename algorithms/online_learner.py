"""
在线学习模块 — 根据预测误差实时调整算法权重

核心机制：
1. 对每个算法维护指数加权移动误差（EWMA）
2. 用 Hedge 算法（指数权重专家混合）动态分配权重
3. 支持暂停/恢复，避免数据不足时权重漂移
"""

import math
import time
import threading
import json
import os
from typing import Dict, List, Tuple, Optional

# 默认参数
DEFAULT_ETA = 0.5          # Hedge 学习率
DEFAULT_MIN_WEIGHT = 0.05  # 最低权重（防止算法被彻底淘汰）
DEFAULT_WARMUP = 5          # 至少需要 N 次反馈才开始调整
DEFAULT_DECAY = 0.95        # EWMA 衰减系数（越大越重视历史）


class _AlgorithmTracker:
    """单个算法的在线学习状态"""

    __slots__ = ('name', 'weight', 'cumulative_loss', 'ewma_loss',
                 'error_count', 'last_error', 'last_update')

    def __init__(self, name: str, initial_weight: float = 1.0):
        self.name = name
        self.weight = initial_weight
        self.cumulative_loss = 0.0   # Hedge 累积损失
        self.ewma_loss = 0.0         # 指数加权移动误差
        self.error_count = 0
        self.last_error: Optional[float] = None
        self.last_update: float = 0.0


class OnlineLearner:
    """在线学习器 — 对所有算法的权重进行动态调整。

    使用方法
    --------
    >>> learner = OnlineLearner(['线性增长', '指数平滑', 'Gompertz'])
    >>> # 每次「实际值」到达后调用
    >>> learner.update('线性增长', predicted=102000, actual=103500)
    >>> # 获取当前推荐权重
    >>> weights = learner.get_weights()
    """

    def __init__(
        self,
        algorithm_names: Optional[List[str]] = None,
        eta: float = DEFAULT_ETA,
        min_weight: float = DEFAULT_MIN_WEIGHT,
        warmup: int = DEFAULT_WARMUP,
        decay: float = DEFAULT_DECAY,
    ):
        self.eta = eta
        self.min_weight = min_weight
        self.warmup = warmup
        self.decay = decay
        self._lock = threading.Lock()

        self._trackers: Dict[str, _AlgorithmTracker] = {}
        if algorithm_names:
            for name in algorithm_names:
                self._trackers[name] = _AlgorithmTracker(name)

        # 全局步数
        self._step = 0

    # ── 公共接口 ──────────────────────────────────

    def register(self, name: str, initial_weight: float = 1.0):
        """注册一个新算法。"""
        with self._lock:
            if name not in self._trackers:
                self._trackers[name] = _AlgorithmTracker(name, initial_weight)

    def unregister(self, name: str):
        """移除一个算法。"""
        with self._lock:
            self._trackers.pop(name, None)

    def update(self, name: str, predicted: float, actual: float):
        """用最新实际值更新算法状态。

        Parameters
        ----------
        name : str          算法名称
        predicted : float   上次预测值
        actual : float      当前实际观测值
        """
        if name not in self._trackers:
            return

        # 计算误差
        if actual <= 0:
            return
        error = abs(predicted - actual) / actual  # 相对误差 [0, +∞)

        with self._lock:
            t = self._trackers[name]
            t.last_error = error
            t.last_update = time.time()
            t.error_count += 1

            # EWMA 误差
            if t.ewma_loss == 0:
                t.ewma_loss = error
            else:
                t.ewma_loss = self.decay * t.ewma_loss + (1 - self.decay) * error

            # Hedge 累积损失
            # 使用 logloss 风格：loss = ln(1 + error)
            t.cumulative_loss += math.log(1 + error)

            self._step += 1

    def get_weights(self) -> Dict[str, float]:
        """获取当前在线学习推荐的权重字典。

        如果总反馈次数 < warmup，返回均匀权重。
        """
        with self._lock:
            total_updates = sum(t.error_count for t in self._trackers.values())
            if total_updates < self.warmup:
                # 冷启动：返回均匀权重
                n = len(self._trackers) or 1
                return {name: 1.0 / n for name in self._trackers}

            # Hedge 混合权重
            weights = {}
            min_loss = min(
                (t.cumulative_loss for t in self._trackers.values()),
                default=0
            )
            for name, t in self._trackers.items():
                # w_i ∝ exp(-η * (L_i - min_L))
                raw = math.exp(-self.eta * (t.cumulative_loss - min_loss))
                weights[name] = max(self.min_weight, raw)

            # 归一化
            total = sum(weights.values())
            if total > 0:
                weights = {k: v / total for k, v in weights.items()}

            return weights

    def get_algorithm_stats(self) -> Dict[str, Dict]:
        """获取所有算法的在线学习统计。"""
        with self._lock:
            result = {}
            for name, t in self._trackers.items():
                result[name] = {
                    'name': t.name,
                    'ewma_loss': round(t.ewma_loss, 4),
                    'cumulative_loss': round(t.cumulative_loss, 4),
                    'error_count': t.error_count,
                    'last_error': round(t.last_error, 4) if t.last_error is not None else None,
                    'weight': round(self._quick_weight(name), 4),
                }
            return result

    def save(self, filepath: str):
        """将学习状态持久化到 JSON。"""
        with self._lock:
            data = {
                'step': self._step,
                'eta': self.eta,
                'decay': self.decay,
                'trackers': {},
            }
            for name, t in self._trackers.items():
                data['trackers'][name] = {
                    'cumulative_loss': t.cumulative_loss,
                    'ewma_loss': t.ewma_loss,
                    'error_count': t.error_count,
                    'last_error': t.last_error,
                    'last_update': t.last_update,
                }
            os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, filepath: str):
        """从 JSON 恢复学习状态。"""
        if not os.path.exists(filepath):
            return
        with self._lock:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._step = data.get('step', 0)
                self.eta = data.get('eta', DEFAULT_ETA)
                self.decay = data.get('decay', DEFAULT_DECAY)
                for name, td in data.get('trackers', {}).items():
                    if name in self._trackers:
                        t = self._trackers[name]
                        t.cumulative_loss = td.get('cumulative_loss', 0)
                        t.ewma_loss = td.get('ewma_loss', 0)
                        t.error_count = td.get('error_count', 0)
                        t.last_error = td.get('last_error')
                        t.last_update = td.get('last_update', 0)
            except Exception as e:
                print(f"OnlineLearner 加载失败: {e}")

    def reset(self):
        """重置所有学习状态。"""
        with self._lock:
            self._step = 0
            for t in self._trackers.values():
                t.cumulative_loss = 0.0
                t.ewma_loss = 0.0
                t.error_count = 0
                t.last_error = None

    # ── 内部方法 ──────────────────────────────────

    def _quick_weight(self, name: str) -> float:
        """不加锁快速获取权重（调用方需持有 _lock）。"""
        weights = self.get_weights()
        return weights.get(name, 1.0)


# ── 全局单例 ────────────────────────────────────────
_global_learner: Optional[OnlineLearner] = None
_learner_lock = threading.Lock()


def get_online_learner(algorithm_names: Optional[List[str]] = None) -> OnlineLearner:
    """获取全局 OnlineLearner 单例。"""
    global _global_learner
    with _learner_lock:
        if _global_learner is None:
            _global_learner = OnlineLearner(algorithm_names)
        elif algorithm_names:
            for name in algorithm_names:
                _global_learner.register(name)
        return _global_learner
