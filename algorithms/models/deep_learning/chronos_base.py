"""
Chronos (亚马逊时序基础模型)
基于T5架构的zero-shot时序预训练模型，无需微调直接预测
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import ChronosTorchModel, try_torch_predict


class ChronosBaseAlgorithm(BaseAlgorithm):
    """Chronos 零样本时序预测"""

    name = "Chronos零样本"
    algorithm_id = "chronos_base"
    description = "T5时序基础模型，零样本概率预测"
    category = "深度学习"
    default_weight = 1.4

    training_window = 10
    training_horizon = 3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        return try_torch_predict(
            self,
            video_data,
            threshold,
            ChronosTorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        return ChronosTorchModel(
            in_features=getattr(self, "_training_n_features", 5),
            window=10,
            d_model=32,
            n_heads=2,
            horizon=self.training_horizon,
        )

    def get_training_features(self) -> List[str]:
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 5 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            n = min(10, len(views) // 2)
            if n < 2:
                n = 2

            x = np.arange(len(views))
            coeffs = np.polyfit(x, views, 1)
            trend = np.polyval(coeffs, x)
            residuals = views - trend

            seasonal_periods = [7, 14]
            seasonal_pattern = np.zeros_like(residuals)
            for p in seasonal_periods:
                if p < len(residuals):
                    pattern = residuals[-p:]
                    seasonal_pattern += np.tile(pattern, len(residuals) // p + 1)[: len(residuals)] / len(
                        seasonal_periods
                    )

            future_x = np.arange(len(views), len(views) + n)
            future_trend = np.polyval(coeffs, future_x)
            future_seasonal = np.tile(seasonal_pattern[-min(7, len(seasonal_pattern)) :], 3)[:n]
            future_views = future_trend + future_seasonal
            future_views = np.maximum(future_views, 0)

            predicted_velocity = max(0, np.mean(np.diff(future_views)) / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                residual_std = np.std(residuals) / max(np.mean(views), 1)
                confidence = max(0.1, min(0.85, 0.5 - residual_std * 5))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "chronos", "trend_slope": float(coeffs[0])},
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
                metadata={"method": "chronos", "reason": "fallback"},
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
            metadata={"method": "chronos", "reason": "fallback"},
            timestamp=datetime.now(),
        )
