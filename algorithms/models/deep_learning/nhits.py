"""
N-HiTS (Neural Hierarchical Interpolation for Time Series)
多尺度分层插值预测，AAAI 2023

核心思路：
1. 堆叠多个 block，每个 block 输出 backcast + forecast
2. 每层对输入做 MaxPool 下采样，实现多尺度特征提取
3. 残差连接：每层预测相加，残差回传下层
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import NHiTSTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class NHitsAlgorithm(BaseAlgorithm):
    """N-HiTS 多尺度分层插值"""

    name = "N-HiTS多尺度"
    algorithm_id = "nhits"
    description = "多尺度分层插值预测，堆叠残差块"
    category = "深度学习"
    default_weight = 1.5

    training_window = 12
    training_horizon = 3

    def predict(self, video_data, threshold=100000):
        return try_torch_predict(
            self, video_data, threshold, NHiTSTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        return NHiTSTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon,
            n_blocks=3, n_pool_kernel=2, hidden=64,
        )

    def get_training_features(self) -> List[str]:
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 6 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "nhits_fallback"},
                timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-15:]], dtype=np.float64)

        # 模拟多尺度分解
        scales = []
        scale_views = views.copy()
        for k in [1, 2, 4]:
            if len(scale_views) >= k:
                pooled = np.array([np.mean(scale_views[i:i+k]) for i in range(0, len(scale_views) - k + 1, k)])
                if len(pooled) >= 2:
                    growth = np.mean(np.diff(pooled))
                    scales.append(growth / k)

        if scales:
            growth = np.mean(scales)
        else:
            growth = velocity * 3600

        # 残差修正
        recent_growth = views[-1] - views[-2] if len(views) >= 2 else growth
        predicted_growth = 0.6 * growth + 0.4 * recent_growth

        predicted_velocity = max(0, predicted_growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity
            n_scales = len(scales)
            confidence = min(0.85, 0.4 + 0.1 * n_scales + 0.05 * min(len(views), 20) * 0.05)

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "nhits_numpy", "scales": len(scales), "data_points": len(views)},
            timestamp=datetime.now(),
        )
