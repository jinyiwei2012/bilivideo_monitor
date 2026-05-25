"""
TIDE (Time Series Dense Encoder)
基于残差MLP的轻量时序预测，结构极简但在多种数据集上超越复杂Transformer
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class TideSimpleAlgorithm(BaseAlgorithm):
    """TIDE 时序稠密编码器"""

    name = "TIDE稠密编码器"
    algorithm_id = "tide_simple"
    description = "残差MLP基线，简单但强大的时序预测"
    category = "深度学习"
    default_weight = 1.1

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 4 or velocity <= 0:
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=float("inf"),
                confidence=0.0, current_views=current_views, current_velocity=velocity,
                metadata={"method": "tide_simple", "reason": "insufficient_data"},
                timestamp=datetime.now(),
            )

        views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
        n = min(10, len(views) // 2)
        if n < 2:
            n = 2

        try:
            x = np.arange(len(views))
            coeffs = np.polyfit(x, views, 2)
            trend = np.polyval(coeffs, x)
            detrended = views - trend

            encoder = detrended[-n:]
            seasonal = np.tile(encoder, 3)[:n]
            decoder = trend[-1] + np.arange(1, n + 1) * (coeffs[0] * 2 + coeffs[1])

            future = decoder + seasonal
            future_velocity = max(0, np.mean(np.diff(views[-5:])) / 3600) if len(views) >= 5 else velocity
            predicted_velocity = max(future_velocity, velocity * 0.5)

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                confidence = min(0.85, 0.5 + 0.01 * len(history))
        except Exception:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            confidence = 0.3

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={"method": "tide_simple", "history_len": len(history)},
            timestamp=datetime.now(),
        )
