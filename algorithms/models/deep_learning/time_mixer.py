"""
TimeMixer (Decomposable Multiscale Mixing)
多尺度可分解混合模型，ICLR 2024

核心思路：
1. 多尺度时间下采样（AvgPool 不同 kernel）
2. 每个尺度独立的 MLP Mixer
3. 跨尺度融合 + 预测头
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import TimeMixerTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class TimeMixerAlgorithm(BaseAlgorithm):
    """TimeMixer 多尺度混合"""

    name = "TimeMixer混合"
    algorithm_id = "time_mixer"
    description = "多尺度下采样+MLP Mixer混合预测"
    category = "深度学习"
    default_weight = 1.5

    training_window = 12
    training_horizon = 3

    def predict(self, video_data, threshold=100000):
        return try_torch_predict(
            self, video_data, threshold, TimeMixerTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        return TimeMixerTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon,
            d_model=32, scales=3,
        )

    def get_training_features(self) -> List[str]:
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 8 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "time_mixer_fallback"},
                timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-20:]], dtype=np.float64)

        # 多尺度增长分析
        scale_growths = []
        for scale in [1, 3, 7]:
            if len(views) >= scale * 2:
                sampled = views[::scale]
                if len(sampled) >= 2:
                    diffs = np.diff(sampled)
                    scale_growths.append(np.mean(diffs) / scale)
                elif scale == 1 and len(views) >= 2:
                    scale_growths.append(np.mean(np.diff(views)))

        if not scale_growths:
            growth = velocity * 3600
        else:
            # 加权融合：短期权重高
            weights = [0.5, 0.3, 0.2]
            growth = sum(w * g for w, g in zip(weights[:len(scale_growths)], scale_growths))
            growth /= sum(weights[:len(scale_growths)])

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity
            n_scales = len(scale_growths)
            confidence = min(0.85, 0.35 + 0.12 * n_scales + 0.02 * min(len(views), 25))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "time_mixer_numpy", "scales": n_scales, "data_points": len(views)},
            timestamp=datetime.now(),
        )
