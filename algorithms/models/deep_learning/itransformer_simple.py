"""
iTransformer (倒置Transformer)
将Transformer反转：每个变量时间序列作为token，注意力捕捉跨指标相关性
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class ITransformerSimpleAlgorithm(BaseAlgorithm):
    """iTransformer 倒置Transformer"""

    name = "iTransformer倒置"
    algorithm_id = "itransformer_simple"
    description = "倒置Transformer，变量作为token捕捉跨指标相关性"
    category = "深度学习"
    default_weight = 1.2

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

            metrics = np.column_stack([views, likes, coins, favs]).T
            metrics = np.diff(metrics) / np.maximum(metrics[:, :-1], 1)
            metrics = np.nan_to_num(metrics)

            n_vars, seq_len = metrics.shape
            if seq_len < 2:
                return self._fallback(velocity, current_views, threshold)

            Q = metrics @ metrics.T / np.sqrt(n_vars)
            attn = np.maximum(Q, 0)
            attn = attn / (np.sum(attn, axis=-1, keepdims=True) + 1e-10)

            W_v = np.random.RandomState(42).randn(seq_len, 1) * 0.01
            values = metrics @ W_v
            context = attn @ values

            gate = np.tanh(context)
            trends = np.mean(gate, axis=1)

            view_trend = float(trends[0])
            like_trend = float(trends[1]) if len(trends) > 1 else 0

            predicted_velocity = max(0, velocity * (1 + view_trend + 0.2 * like_trend))
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                cross_corr = float(np.mean(np.abs(attn[0, 1:]))) if attn.shape[1] > 1 else 0.5
                confidence = max(0.1, min(0.85, 0.4 + cross_corr * 0.5))

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
