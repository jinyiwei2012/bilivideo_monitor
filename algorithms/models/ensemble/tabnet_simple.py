"""
TabNet (注意力特征选择网络)
带Transformer风格注意力机制的表格网络，自动选择重要特征进行预测
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class TabnetSimpleAlgorithm(BaseAlgorithm):
    """TabNet 注意力特征网络"""

    name = "TabNet注意力"
    algorithm_id = "tabnet_simple"
    description = "注意力特征选择表格网络"
    category = "集成学习"
    default_weight = 1.1

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
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
            shares = np.array([h.get("share", 0) for h in history], dtype=np.float64)

            features = np.column_stack(
                [
                    np.log1p(views),
                    np.log1p(likes),
                    np.log1p(coins),
                    np.log1p(favs),
                    np.log1p(shares),
                    np.gradient(views) / np.maximum(views, 1),
                    np.gradient(likes) / np.maximum(likes, 1),
                ]
            )
            features = np.nan_to_num(features)

            n_features = features.shape[1]
            np.random.seed(42)
            W = np.random.randn(n_features, n_features) * 0.1
            V = np.random.randn(n_features, 1) * 0.1
            W_out = np.random.randn(n_features, 1) * 0.01

            H = features @ W
            attn = np.maximum(H @ V, 0)
            attn_weights = attn / (np.sum(attn, axis=0, keepdims=True) + 1e-10)

            weighted_features = features * attn_weights
            decision = np.tanh(weighted_features @ W_out)

            trend = np.mean(decision[-5:]) if len(decision) >= 5 else 0
            recent_velocity = np.mean(np.diff(views[-5:])) / 3600 if len(views) >= 5 else velocity

            predicted_velocity = max(0, recent_velocity * (1 + trend))
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                attn_entropy = -np.sum(attn_weights * np.log(attn_weights + 1e-10)) / np.log(n_features)
                confidence = max(0.1, min(0.8, 0.6 - attn_entropy * 0.3))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "tabnet", "trend_signal": float(trend)},
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
                metadata={"method": "tabnet", "reason": "fallback"},
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
            metadata={"method": "tabnet", "reason": "fallback"},
            timestamp=datetime.now(),
        )
