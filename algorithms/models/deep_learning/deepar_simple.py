"""
DeepAR (概率自回归模型)
基于RNN的概率预测，输出未来播放量的概率分布
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import DeepARTorchModel, try_torch_predict


class DeeparSimpleAlgorithm(BaseAlgorithm):
    """DeepAR 概率自回归"""

    name = "DeepAR概率"
    algorithm_id = "deepar_simple"
    description = "概率自回归，输出未来播放量概率分布"
    category = "深度学习"
    default_weight = 1.3

    training_window = 10
    training_horizon = 3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        return try_torch_predict(
            self, video_data, threshold, DeepARTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        return DeepARTorchModel(in_features=5, hidden=32, horizon=self.training_horizon)

    def get_training_features(self) -> List[str]:
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 8 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            returns = np.diff(views) / np.maximum(views[:-1], 1)
            mu_ret = np.mean(returns)
            sigma_ret = np.std(returns) + 1e-10

            n_samples = 200
            np.random.seed(42)
            future_returns = np.random.normal(mu_ret, sigma_ret, (n_samples, 30))
            future_views_samples = np.zeros((n_samples, 30))
            future_views_samples[:, 0] = views[-1] * (1 + future_returns[:, 0])
            for t in range(1, 30):
                future_views_samples[:, t] = future_views_samples[:, t - 1] * (1 + future_returns[:, t])
            future_views_samples = np.maximum(future_views_samples, 0)

            remaining = threshold - current_views
            if remaining <= 0:
                return PredictionResult(
                    algorithm_name=self.name, algorithm_id=self.algorithm_id,
                    target_threshold=threshold, predicted_hours=0, confidence=1.0,
                    current_views=current_views, current_velocity=velocity,
                    metadata={"method": "deepar", "mu_return": float(mu_ret), "sigma_return": float(sigma_ret)},
                    timestamp=datetime.now(),
                )

            velocity_samples = np.mean(np.diff(future_views_samples[:, :7]) / 3600, axis=1)
            median_velocity = max(0, np.median(velocity_samples))
            if median_velocity < 1:
                median_velocity = velocity

            predicted_hours = remaining / median_velocity
            prob_reach = np.mean(future_views_samples[:, -1] >= threshold)
            uncertainty = sigma_ret / max(abs(mu_ret), 1e-10)
            confidence = max(0.05, min(0.85, prob_reach * 0.8 + 0.1 / (1 + uncertainty)))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={"method": "deepar", "mu_return": float(mu_ret), "sigma_return": float(sigma_ret), "prob_reach": float(prob_reach)},
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
                metadata={"method": "deepar", "reason": "fallback"},
                timestamp=datetime.now(),
            )
        remaining = max(0, threshold - current_views)
        predicted_hours = remaining / velocity if remaining > 0 else 0
        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=0.3, current_views=current_views, current_velocity=velocity,
            metadata={"method": "deepar", "reason": "fallback"},
            timestamp=datetime.now(),
        )
