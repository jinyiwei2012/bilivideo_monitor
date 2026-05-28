"""
保形预测（Conformal Prediction）— 分布无关的预测区间

为集成预测结果提供有覆盖率保证的预测区间。
核心思路：用历史预测误差的分位数校准新预测的区间宽度。

用法：
    predictor = ConformalPredictor(alpha=0.1)  # 90% 覆盖率
    interval = predictor.predict_interval(ensemble_prediction)
    # 返回 {"lower": ..., "upper": ..., "coverage": 0.9}

    # 当真实值到达后
    predictor.update(ensemble_prediction, actual_value)
"""

import math
import logging
import threading
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# NumPy 可选导入
try:
    import numpy as np

    _np_available = True
except ImportError:
    _np_available = False


class ConformalPredictor:
    """分布无关保形预测器。

    Args:
        alpha: 显著性水平（默认 0.1 → 90% 覆盖率区间）。
        min_calibration: 校准所需的最小样本数，低于此值使用启发式区间。
        fallback_factor: 冷启动时区间的宽度系数。
        max_scores: 最多保留的校准分数数（防止无限增长）。
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

        # 非一致分（nonconformity scores）: |y_true - y_pred| / max(y_true, 1)
        self._scores: List[float] = []

    # ── 公开接口 ──────────────────────────────────

    def update(self, y_pred: float, y_true: float):
        """用新的真实值更新校准集。

        Args:
            y_pred: 集成预测值。
            y_true: 实际观测值。
        """
        if y_true <= 0 or y_pred <= 0:
            return
        score = abs(y_true - y_pred) / max(y_true, y_pred, 1.0)
        with self._lock:
            self._scores.append(score)
            if len(self._scores) > self.max_scores:
                self._scores = self._scores[-self.max_scores // 2 :]

    def predict_interval(self, y_pred: float) -> Dict:
        """返回预测区间。

        Args:
            y_pred: 集成预测的 playload 量。

        Returns:
            {lower, upper, coverage, calibrated, interval_width_ratio}
        """
        if y_pred <= 0:
            return {"lower": 0, "upper": 0, "coverage": 1 - self.alpha, "calibrated": False, "interval_width_ratio": 0.0}

        with self._lock:
            n = len(self._scores)

        if n < self.min_calibration or not _np_available:
            # 冷启动：用固定比例区间
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
        """根据校准状态返回置信度。

        已校准：区间越窄置信度越高（exp(-width_ratio)）。
        未校准：返回 0.5（中性）。
        """
        interval = self.predict_interval(y_pred)
        if interval["calibrated"]:
            # interval_width_ratio ~ 0（超窄）→ 1.0, 宽 → 趋近 0
            return max(0.0, min(1.0, math.exp(-interval["interval_width_ratio"] * 2)))
        return 0.5

    def status(self) -> Dict:
        """返回预测器状态。"""
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
    """获取全局 ConformalPredictor 单例。"""
    global _global_predictor
    with _predictor_lock:
        if _global_predictor is None:
            _global_predictor = ConformalPredictor(alpha=alpha)
        return _global_predictor
