"""
CausalImpact (因果推断)
贝叶斯结构时间序列模型，交互指标作为协变量，量化每个渠道的因果贡献
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class CausalImpactAlgorithm(BaseAlgorithm):
    """CausalImpact 因果推断"""

    name = "CausalImpact因果"
    algorithm_id = "causal_impact"
    description = "贝叶斯结构时间序列，量化互动指标因果贡献"
    category = "高级分析"
    default_weight = 1.0

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 10 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            likes = np.array([h.get("like", 0) for h in history], dtype=np.float64)
            coins = np.array([h.get("coin", 0) for h in history], dtype=np.float64)
            favs = np.array([h.get("favorite", 0) for h in history], dtype=np.float64)
            shares = np.array([h.get("share", 0) for h in history], dtype=np.float64)

            covariates = np.column_stack([
                np.log1p(likes),
                np.log1p(coins),
                np.log1p(favs),
                np.log1p(shares),
                np.gradient(likes),
                np.gradient(coins),
            ])
            covariates = np.nan_to_num(covariates)

            split = max(len(views) // 2, 3)
            y_pre = views[:split]
            X_pre = covariates[:split]
            y_post = views[split:]
            X_post = covariates[split:]

            X_pre = np.column_stack([np.ones(len(X_pre)), X_pre])
            X_post = np.column_stack([np.ones(len(X_post)), X_post])

            beta = np.linalg.lstsq(X_pre, y_pre, rcond=None)[0]
            y_pred = X_post @ beta

            impact = y_post - y_pred
            cum_impact = np.cumsum(impact)

            recent_impact = np.mean(impact[-min(5, len(impact)):]) if len(impact) >= 1 else 0
            impact_velocity = recent_impact / 3600

            base_velocity = velocity * 0.7
            predicted_velocity = max(0, base_velocity + impact_velocity)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                r2 = 1 - np.sum((y_post - y_pred) ** 2) / max(np.sum((y_post - np.mean(y_post)) ** 2), 1)
                confidence = max(0.1, min(0.85, 0.5 + 0.3 * max(0, r2)))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "causal_impact", "cum_impact": float(cum_impact[-1]) if len(cum_impact) > 0 else 0, "r2": float(r2)},
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
                metadata={"method": "causal_impact", "reason": "fallback"},
                timestamp=datetime.now(),
            )
        remaining = max(0, threshold - current_views)
        predicted_hours = remaining / velocity if remaining > 0 else 0
        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=0.3, current_views=current_views, current_velocity=velocity,
            metadata={"method": "causal_impact", "reason": "fallback"},
            timestamp=datetime.now(),
        )
