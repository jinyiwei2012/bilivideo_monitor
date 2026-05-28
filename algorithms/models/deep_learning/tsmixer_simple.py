"""
TSMixer (MLP Mixer)
纯MLP架构，交替在时间维和通道维做MLP混合，轻量化不易过拟合
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import TSMixerTorchModel, try_torch_predict


class TsmixerSimpleAlgorithm(BaseAlgorithm):
    """TSMixer MLP混合器"""

    name = "TSMixer混合器"
    algorithm_id = "tsmixer_simple"
    description = "纯MLP架构，时间维与通道维交替混合"
    category = "深度学习"
    default_weight = 1.2

    training_window = 10
    training_horizon = 3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        return try_torch_predict(
            self,
            video_data,
            threshold,
            TSMixerTorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        return TSMixerTorchModel(in_features=getattr(self, '_training_n_features', 5), window=10, horizon=self.training_horizon)

    def get_training_features(self) -> List[str]:
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 6 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            likes = np.array([h.get("like", 0) for h in history], dtype=np.float64)
            coins = np.array([h.get("coin", 0) for h in history], dtype=np.float64)
            favs = np.array([h.get("favorite", 0) for h in history], dtype=np.float64)

            pct_views = np.diff(views) / np.maximum(views[:-1], 1)
            pct_likes = np.diff(likes) / np.maximum(likes[:-1], 1)
            pct_coins = np.diff(coins) / np.maximum(coins[:-1], 1)
            pct_favs = np.diff(favs) / np.maximum(favs[:-1], 1)

            X = np.column_stack([pct_views, pct_likes, pct_coins, pct_favs])
            X = np.where(np.isfinite(X), X, 0)

            W_time = np.random.RandomState(42).randn(X.shape[1], 4) * 0.1
            H_time = np.maximum(X @ W_time, 0)

            W_channel = np.random.RandomState(43).randn(H_time.shape[1], 1) * 0.1
            H_channel = np.maximum(H_time @ W_channel, 0)

            W_out = np.random.RandomState(44).randn(H_channel.shape[0], 1) * 0.01
            v_pred = H_channel.T @ W_out

            predicted_velocity = max(0, float(v_pred[0, 0]) * abs(np.mean(views[-5:])) / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                confidence = min(0.8, 0.4 + 0.05 * np.log1p(len(history)))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "tsmixer", "window": len(history)},
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
                metadata={"method": "tsmixer", "reason": "fallback"},
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
            metadata={"method": "tsmixer", "reason": "fallback"},
            timestamp=datetime.now(),
        )
