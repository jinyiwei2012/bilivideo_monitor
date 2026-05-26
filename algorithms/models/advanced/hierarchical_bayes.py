"""
层级贝叶斯模型 (Hierarchical Bayesian Model)
利用UP主级别的超参数共享信息，将新视频纳入层级结构进行收缩估计
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class HierarchicalBayesAlgorithm(BaseAlgorithm):
    """层级贝叶斯模型"""

    name = "层级贝叶斯"
    algorithm_id = "hierarchical_bayes"
    description = "利用UP主历史信息的层级贝叶斯收缩估计"
    category = "高级分析"
    default_weight = 1.2

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)
        up_avg_views = video_data.get("up_average_views", 0)

        if len(history) < 3 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)

            mu_up = max(up_avg_views, 1000) if up_avg_views > 0 else current_views

            mu_prior = max(mu_up, current_views)
            sigma_prior = mu_prior * 0.5

            local_mean = np.mean(views)
            local_var = np.var(views) + 1e-6

            sigma_likelihood = np.sqrt(local_var / max(len(views), 1))
            posterior_mean = (mu_prior / (sigma_prior**2) + local_mean / (sigma_likelihood**2)) / (
                1 / (sigma_prior**2) + 1 / (sigma_likelihood**2)
            )

            posterior_var = 1 / (1 / (sigma_prior**2) + 1 / (sigma_likelihood**2))

            shrinkage = local_var / (local_var + sigma_prior**2)
            shrunk_velocity = (1 - shrinkage) * velocity + shrinkage * (mu_up / 3600)

            predicted_velocity = max(0, shrunk_velocity)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                posterior_ci = 1.96 * np.sqrt(posterior_var)
                cv = posterior_ci / max(posterior_mean, 1)
                confidence = max(0.1, min(0.85, 0.5 - cv * 2 + 0.3 * (1 - shrinkage)))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={
                    "method": "hierarchical_bayes",
                    "shrinkage": float(shrinkage),
                    "posterior_mean": float(posterior_mean),
                    "up_avg_views": int(up_avg_views),
                },
                timestamp=datetime.now(),
            )
        except Exception:
            return self._fallback(velocity, current_views, threshold)

    def _fallback(self, velocity, current_views, threshold):
        if velocity <= 0:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=float("inf"),
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "hierarchical_bayes", "reason": "fallback"},
                timestamp=datetime.now(),
            )
        remaining = max(0, threshold - current_views)
        predicted_hours = remaining / velocity if remaining > 0 else 0
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=0.3,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "hierarchical_bayes", "reason": "fallback"},
            timestamp=datetime.now(),
        )
