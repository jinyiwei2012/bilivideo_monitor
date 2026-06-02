"""
WPMixer (Wavelet Packet Mixer)
高效多分辨率混合器，AAAI 2025

核心思路：
1. 多分辨率分支：原始/2x下采样/4x下采样
2. 每个分支独立的 MLP Mixer
3. 跨分辨率融合输出
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import WPMixerTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class WPMixerAlgorithm(BaseAlgorithm):
    """WPMixer 小波包混合器"""

    name = "WPMixer多分辨率"
    algorithm_id = "wpmixer"
    description = "多分辨率小波包混合预测，高效轻量级"
    category = "深度学习"
    default_weight = 1.4

    training_window = 12
    training_horizon = 3

    def predict(self, video_data, threshold=100000):
        return try_torch_predict(
            self, video_data, threshold, WPMixerTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        return WPMixerTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon, d_model=32,
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
                metadata={"method": "wpmixer_fallback"},
                timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-24:]], dtype=np.float64)
        n = len(views)

        # 多分辨率分析
        resolutions = []
        for r in [1, 2, 4]:
            if n >= r * 2:
                sampled = views[::r]
                diffs = np.diff(sampled)
                if len(diffs) > 0:
                    resolutions.append(np.mean(diffs) / r)

        if not resolutions:
            growth = velocity * 3600
        else:
            # 加权：低分辨率给长周期趋势，高分辨率给短期波动
            weights = [0.5, 0.3, 0.2][:len(resolutions)]
            growth = sum(w * r for w, r in zip(weights, resolutions)) / sum(weights)

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity
            n_res = len(resolutions)
            confidence = min(0.85, 0.35 + 0.1 * n_res + 0.02 * min(n, 25))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "wpmixer_numpy", "resolutions": n_res, "data_points": n},
            timestamp=datetime.now(),
        )
