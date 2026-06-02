"""
LightTS (Light Sampling-oriented MLP Structures)
轻量采样MLP，arXiv 2022

核心：对输入做步长采样降维后，用轻量MLP预测
"""

import logging
from typing import Dict, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import LightTSTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class LightTSAlgorithm(BaseAlgorithm):
    """LightTS 轻量采样"""

    name = "LightTS轻量"
    algorithm_id = "lightts"
    description = "步长采样降维+轻量MLP预测"
    category = "深度学习"
    default_weight = 1.3

    training_window = 12
    training_horizon = 3

    def predict(self, video_data, threshold=100000):
        return try_torch_predict(
            self, video_data, threshold, LightTSTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        return LightTSTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon, d_model=32, stride=2,
        )

    def get_training_features(self) -> List[str]:
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 6 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "lightts_fallback"}, timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-18:]], dtype=np.float64)
        n = len(views)

        # 步长采样
        stride = 2
        sampled = views[::stride]
        diffs = np.diff(sampled) if len(sampled) >= 2 else np.diff(views)
        growth = np.mean(diffs) * stride

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 and predicted_velocity > 0 else float("inf")
        confidence = min(0.85, 0.3 + 0.02 * min(n, 20))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={"method": "lightts_numpy", "data_points": n}, timestamp=datetime.now(),
        )
