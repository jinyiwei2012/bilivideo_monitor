"""
iTransformer (倒置Transformer)
将Transformer反转：每个变量时间序列作为token，注意力捕捉跨指标相关性
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import ITransformerTorchModel, try_torch_predict


class ITransformerSimpleAlgorithm(BaseAlgorithm):
    """iTransformer 倒置Transformer"""

    name = "iTransformer倒置"
    algorithm_id = "itransformer_simple"
    description = "倒置Transformer，变量作为token捕捉跨指标相关性"
    category = "深度学习"
    default_weight = 1.2

    training_window = 10
    training_horizon = 3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        return try_torch_predict(
            self, video_data, threshold, ITransformerTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        return ITransformerTorchModel(in_features=5, window=10, d_model=32, n_heads=4, horizon=self.training_horizon)

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
            likes = np.array([h.get("like", 0) for h in history], dtype=np.float64)
            coins = np.array([h.get("coin", 0) for h in history], dtype=np.float64)
            favs = np.array([h.get("favorite", 0) for h in history], dtype=np.float64)

            metrics = np.column_stack([views, likes, coins, favs]).T
            metrics = np.diff(metrics) / np.maximum(metrics[:, :-1], 1)
            metrics = np.nan_to_num(metrics)

            n_vars = metrics.shape[0]
            Q = metrics @ metrics.T / np.sqrt(n_vars)
            attn = np.maximum(Q, 0)
            attn = attn / (np.sum(attn, axis=-1, keepdims=True) + 1e-10)

            W_v = np.random.RandomState(42).randn(metrics.shape[1], 1) * 0.01
            values = metrics @ W_v
            context = attn @ values
            gate = np.tanh(context)
            trends = gate.flatten()

            view_trend = float(trends[0]) if len(trends) > 0 else 0
            predicted_velocity = max(0, velocity * (1 + view_trend))
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                confidence = max(0.1, min(0.8, 0.5))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "itransformer", "n_vars": n_vars},
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
                metadata={"method": "itransformer", "reason": "fallback"},
                timestamp=datetime.now(),
            )
        remaining = max(0, threshold - current_views)
        predicted_hours = remaining / velocity if remaining > 0 else 0
        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=0.3, current_views=current_views, current_velocity=velocity,
            metadata={"method": "itransformer", "reason": "fallback"},
            timestamp=datetime.now(),
        )
