"""
NLinear (Normalization-Linear)
极简但高效的线性预测模型，AAAI 2023

核心思路：先对输入做实例归一化，然后单层线性映射 window→horizon。
论文证明在很多任务上简化模型打平甚至超越复杂的 Transformer。
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import NLinearTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class NLinearAlgorithm(BaseAlgorithm):
    """NLinear 极简线性预测"""

    name = "NLinear线性"
    algorithm_id = "nlinear"
    description = "实例归一化 + 单层线性映射，极简高效"
    category = "深度学习"
    default_weight = 1.5

    training_window = 10
    training_horizon = 3

    def predict(self, video_data, threshold=100000):
        return try_torch_predict(
            self, video_data, threshold, NLinearTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        return NLinearTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon,
        )

    def get_training_features(self) -> List[str]:
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 5 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3 if velocity > 0 else 0.0,
                current_views=current_views, current_velocity=velocity,
                metadata={"method": "nlinear_fallback"},
                timestamp=datetime.now(),
            )

        views = []
        for h in history:
            v = h.get("view_count", 0)
            if v > 0:
                views.append(float(v))

        if len(views) < 5:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.4, current_views=current_views, current_velocity=velocity,
                metadata={"method": "nlinear_fallback"},
                timestamp=datetime.now(),
            )

        # 归一化：减均值除标准差
        import numpy as np
        arr = np.array(views[-15:])
        mean = np.mean(arr)
        std = np.std(arr) + 1e-5
        normalized = (arr - mean) / std

        # 线性外推
        if len(normalized) >= 5:
            x = np.arange(len(normalized))
            coef = np.polyfit(x, normalized, 1)
            future = np.polyval(coef, np.arange(len(normalized), len(normalized) + 5))
            future_views = future * std + mean
            growth = max(0, np.mean(np.diff(future_views)))
        else:
            growth = velocity * 3600

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity
            confidence = min(0.85, 0.4 + len(views) * 0.02)

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "nlinear_numpy", "data_points": len(views)},
            timestamp=datetime.now(),
        )
