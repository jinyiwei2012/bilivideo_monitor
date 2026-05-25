"""
Chronos (亚马逊时序基础模型)
基于T5架构的zero-shot时序预训练模型，无需微调直接预测
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

_HAS_CHRONOS = False
try:
    from chronos import ChronosPipeline
    import torch
    _HAS_CHRONOS = True
except ImportError:
    pass


class ChronosBaseAlgorithm(BaseAlgorithm):
    """Chronos 零样本时序预测"""

    name = "Chronos零样本"
    algorithm_id = "chronos_base"
    description = "亚马逊T5时序基础模型，零样本概率预测"
    category = "深度学习"
    default_weight = 1.4

    _pipeline = None

    def _get_pipeline(self):
        if ChronosBaseAlgorithm._pipeline is None and _HAS_CHRONOS:
            try:
                ChronosBaseAlgorithm._pipeline = ChronosPipeline.from_pretrained(
                    "amazon/chronos-t5-small",
                    device_map="cpu",
                )
            except Exception:
                pass
        return ChronosBaseAlgorithm._pipeline

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 5 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        pipe = self._get_pipeline()
        if pipe is None:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)

            forecast = pipe.predict(
                torch.tensor(views, dtype=torch.float32),
                prediction_length=24,
            )
            median = np.median(forecast[0].numpy(), axis=0)

            predicted_velocity = max(0, np.mean(np.diff(median[:7])) / 3600) if len(median) >= 7 else velocity
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                quantiles = np.percentile(forecast[0].numpy(), [10, 90], axis=0)
                interval_width = np.mean(quantiles[1, :7] - quantiles[0, :7]) / max(np.mean(median[:7]), 1)
                confidence = max(0.1, min(0.9, 0.7 - interval_width * 2))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "chronos", "model": "chronos-t5-small"},
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
                metadata={"method": "chronos", "reason": "fallback"},
                timestamp=datetime.now(),
            )
        remaining = max(0, threshold - current_views)
        predicted_hours = remaining / velocity if remaining > 0 else 0
        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=0.3, current_views=current_views, current_velocity=velocity,
            metadata={"method": "chronos", "reason": "fallback"},
            timestamp=datetime.now(),
        )
