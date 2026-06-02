"""
SegRNN (Segment Recurrent Neural Network)
分段循环神经网络，arXiv 2023

核心思路：
1. 将长序列切分为多个等长 segment
2. 每个 segment 独立编码
3. GRU 串联所有 segment 的编码
4. 输出预测
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import SegRNNTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class SegRNNAlgorithm(BaseAlgorithm):
    """SegRNN 分段循环网络"""

    name = "SegRNN分段"
    algorithm_id = "segrnn"
    description = "分段编码+GRU串联，处理长序列高效"
    category = "深度学习"
    default_weight = 1.3

    training_window = 12
    training_horizon = 3

    def predict(self, video_data, threshold=100000):
        return try_torch_predict(
            self, video_data, threshold, SegRNNTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        return SegRNNTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon,
            seg_len=3, d_model=32,
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
                metadata={"method": "segrnn_fallback"},
                timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-18:]], dtype=np.float64)
        n = len(views)

        # 分段处理
        seg_len = 3
        segments = []
        for i in range(0, n - seg_len + 1, seg_len):
            seg = views[i:i + seg_len]
            if len(seg) >= 2:
                segments.append(np.mean(np.diff(seg)))

        if not segments:
            growth = velocity * 3600
        else:
            # 模拟 GRU：加权平均，近期权重高
            weights = np.exp(np.linspace(0, 1, len(segments)))
            weights = weights / weights.sum()
            growth = np.sum(np.array(segments) * weights)

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity
            confidence = min(0.85, 0.3 + 0.03 * min(len(segments), 6) + 0.02 * min(n, 20))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "segrnn_numpy", "segments": len(segments), "data_points": n},
            timestamp=datetime.now(),
        )
