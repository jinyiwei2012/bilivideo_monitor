"""
Mamba S6 (选择性状态空间模型)
基于选择性SSM的高效长程依赖建模，线性复杂度
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import MambaS6TorchModel, try_torch_predict


class MambaS6Algorithm(BaseAlgorithm):
    """Mamba S6 状态空间模型"""

    name = "Mamba S6"
    algorithm_id = "mamba_s6"
    description = "选择性状态空间模型，高效长程依赖建模"
    category = "深度学习"
    default_weight = 1.3

    training_window = 10
    training_horizon = 3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        return try_torch_predict(
            self,
            video_data,
            threshold,
            MambaS6TorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        return MambaS6TorchModel(in_features=getattr(self, '_training_n_features', 5), d_state=4, horizon=self.training_horizon)

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
            dt = 1.0
            A = np.array([[0.9, 0.1], [-0.05, 0.95]])
            B = np.array([[0.1], [0.05]])
            C = np.array([[1.0, 0.0]])

            state = np.zeros((2, 1))
            for v in views:
                delta_B = B * (views[-1] / max(views[0], 1))
                state = A @ state + delta_B * dt

            pred_output = (C @ state)[0, 0]
            predicted_velocity = max(0, float(pred_output) / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                confidence = 0.5

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "mamba_s6", "state_dim": 2},
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
                metadata={"method": "mamba_s6", "reason": "fallback"},
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
            metadata={"method": "mamba_s6", "reason": "fallback"},
            timestamp=datetime.now(),
        )
