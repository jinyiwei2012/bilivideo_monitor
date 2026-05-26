"""
GARCH (Generalized AutoRegressive Conditional Heteroskedasticity)
建模播放量增量的波动率聚集效应，输出带置信区间的概率预测
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class GarchSimpleAlgorithm(BaseAlgorithm):
    """GARCH 波动率聚集模型"""

    name = "GARCH波动率"
    algorithm_id = "garch_simple"
    description = "广义自回归条件异方差，建模波动聚集效应"
    category = "时间序列"
    default_weight = 0.9

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 10 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            returns = np.diff(views) / np.maximum(views[:-1], 1)

            mu = np.mean(returns)
            eps = returns - mu

            omega = np.var(eps) * 0.1
            alpha = 0.2
            beta = 0.7

            T = len(eps)
            sigma2 = np.zeros(T)
            sigma2[0] = np.var(eps)
            for t in range(1, T):
                sigma2[t] = omega + alpha * eps[t - 1] ** 2 + beta * sigma2[t - 1]

            vol = np.sqrt(sigma2[-1])
            mean_return = np.mean(eps[-min(5, T):]) if T >= 5 else mu

            upside = mean_return + vol
            predicted_velocity = max(0, upside * views[-1] / 3600)

            if predicted_velocity < 1:
                predicted_velocity = velocity

            lower_bound = max(0, (mean_return - vol) * views[-1] / 3600)
            volatility_ratio = vol / max(abs(mean_return), 1e-10)

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                confidence = max(0.05, min(0.75, 0.5 / (1 + volatility_ratio)))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "garch", "volatility": float(vol), "lower_velocity": float(lower_bound)},
                timestamp=datetime.now(),
            )
        except Exception:
            return self._fallback(velocity, current_views, threshold)

    def _fallback(self, velocity, current_views, threshold):
        if velocity <= 0:
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=float("inf"),
                confidence=0.0, current_views=current_views, current_velocity=velocity,
                metadata={"method": "garch", "reason": "fallback"},
                timestamp=datetime.now(),
            )
        remaining = max(0, threshold - current_views)
        predicted_hours = remaining / velocity if remaining > 0 else 0
        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=0.3, current_views=current_views, current_velocity=velocity,
            metadata={"method": "garch", "reason": "fallback"},
            timestamp=datetime.now(),
        )
