"""
保形预测（Conformal Prediction）— 分布无关的预测区间

为集成预测结果提供有覆盖率保证的预测区间。
核心思路：用历史预测误差的非一致分（nonconformity scores）分位数
校准新预测的区间宽度，不依赖数据分布假设。

用法：
    predictor = ConformalPredictor(alpha=0.1)  # 90% 覆盖率
    interval = predictor.predict_interval(ensemble_prediction)
    # 返回 {"lower": ..., "upper": ..., "coverage": 0.9}

    当真实值到达后：
    predictor.update(ensemble_prediction, actual_value)
"""

import math
import logging
import threading
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# NumPy 可选导入（用于分位数计算），不可用时 fallback 到冷启动模式
try:
    import numpy as np

    _np_available = True
except ImportError:
    _np_available = False


class ConformalPredictor:
    """分布无关的保形预测器。

    维护一组非一致分（相对预测误差），当校准样本足够时使用
    np.quantile 计算 (1 - alpha) 分位数作为区间宽度；
    冷启动阶段使用固定比例 fallback_factor。

    Args:
        alpha: 显著性水平（默认 0.1 → 90% 覆盖率区间）
        min_calibration: 进入校准模式所需的最少样本数
        fallback_factor: 冷启动阶段的固定区间宽度系数
        max_scores: 最多保留的校准分数数（防止无限增长）
    """

    def __init__(
        self,
        alpha: float = 0.1,
        min_calibration: int = 10,
        fallback_factor: float = 0.2,
        max_scores: int = 1000,
    ):
        self.alpha = max(0.01, min(0.5, alpha))
        self.min_calibration = min_calibration
        self.fallback_factor = fallback_factor
        self.max_scores = max_scores
        self._lock = threading.Lock()

        # 非一致分（nonconformity scores）：|y_true - y_pred| / max(y_true, y_pred, 1)
        self._scores: List[float] = []

    # ── 公开接口 ──────────────────────────────────

    def update(self, y_pred: float, y_true: float):
        """用新到达的真实值更新校准集。

        Args:
            y_pred: 集成预测值
            y_true: 实际观测值
        """
        if y_true <= 0 or y_pred <= 0:
            return
        # 非一致分 = 相对误差
        score = abs(y_true - y_pred) / max(y_true, y_pred, 1.0)
        with self._lock:
            self._scores.append(score)
            # 超过上限时裁剪后半段，保留最近的样本
            if len(self._scores) > self.max_scores:
                self._scores = self._scores[-self.max_scores // 2:]

    def predict_interval(self, y_pred: float) -> Dict:
        """为给定预测值计算保形预测区间。

        Args:
            y_pred: 集成预测的播放量

        Returns:
            dict: {lower, upper, coverage, calibrated, interval_width_ratio, calibration_size}
        """
        if y_pred <= 0:
            return {"lower": 0, "upper": 0, "coverage": 1 - self.alpha, "calibrated": False, "interval_width_ratio": 0.0}

        with self._lock:
            n = len(self._scores)

        # 冷启动 vs 校准模式
        if n < self.min_calibration or not _np_available:
            half = self.fallback_factor
            calibrated = False
        else:
            with self._lock:
                q = float(np.quantile(self._scores, 1 - self.alpha))
            half = q
            calibrated = True

        lower = max(0, y_pred * (1 - half))
        upper = y_pred * (1 + half)
        interval_width = (upper - lower) / max(y_pred, 1)

        return {
            "lower": round(lower),
            "upper": round(upper),
            "coverage": 1 - self.alpha,
            "calibrated": calibrated,
            "interval_width_ratio": round(interval_width, 4),
            "calibration_size": n,
        }

    def get_adaptive_confidence(self, y_pred: float) -> float:
        """根据校准状态返回自适应的置信度。

        已校准：区间越窄置信度越高（exp(-width_ratio * 2)）。
        未校准：返回 0.5 中性值。
        """
        interval = self.predict_interval(y_pred)
        if interval["calibrated"]:
            # interval_width_ratio → 0 时置信度 → 1.0；越宽越趋近 0
            return max(0.0, min(1.0, math.exp(-interval["interval_width_ratio"] * 2)))
        return 0.5

    def status(self) -> Dict:
        """返回预测器的当前状态。"""
        with self._lock:
            n = len(self._scores)
            mean_score = sum(self._scores) / n if n > 0 else 0.0
        return {
            "calibrated": n >= self.min_calibration,
            "calibration_size": n,
            "mean_nonconformity": round(mean_score, 4),
            "alpha": self.alpha,
            "coverage": 1 - self.alpha,
        }


# ── 全局单例 ────────────────────────────────────────

_global_predictor: Optional[ConformalPredictor] = None
_predictor_lock = threading.Lock()


def get_conformal_predictor(alpha: float = 0.1) -> ConformalPredictor:
    """获取全局 ConformalPredictor 单例（双检锁惰性初始化）。"""
    global _global_predictor
    with _predictor_lock:
        if _global_predictor is None:
            _global_predictor = ConformalPredictor(alpha=alpha)
        return _global_predictor
