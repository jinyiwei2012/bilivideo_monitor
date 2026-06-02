"""
BiTCN (Bidirectional Temporal Convolutional Network)
双向时序卷积网络，在 TCN 基础上增加反向卷积通道

核心思路：
1. 前向 TCN：因果卷积捕捉历史→当前趋势
2. 反向 TCN：反向卷积捕捉远期依赖关系
3. 双向特征拼接后经预测头输出
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import BiTCNTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class BiTCNAlgorithm(BaseAlgorithm):
    """BiTCN 双向时序卷积"""

    name = "BiTCN双向卷积"
    algorithm_id = "bitcn"
    description = "双向时序卷积网络，前向+反向捕捉时序特征"
    category = "深度学习"
    default_weight = 1.4

    training_window = 12
    training_horizon = 3

    def predict(self, video_data, threshold=100000):
        return try_torch_predict(
            self, video_data, threshold, BiTCNTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        return BiTCNTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon,
            channels=32, kernel_size=3, layers=3,
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
                metadata={"method": "bitcn_fallback"},
                timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-20:]], dtype=np.float64)
        n = len(views)

        # 前向 EMA
        fwd_ema = views[-1]
        fwd_alpha = 0.3
        for v in views[::-1]:
            fwd_ema = fwd_alpha * v + (1 - fwd_alpha) * fwd_ema

        # 反向 EMA（远期趋势）
        bwd_ema = views[0]
        bwd_alpha = 0.3
        for v in views:
            bwd_ema = bwd_alpha * v + (1 - bwd_alpha) * bwd_ema

        # 卷积式差分分析
        if n >= 5:
            kernel = np.array([0.1, 0.2, 0.4, 0.2, 0.1])
            if n >= len(kernel):
                diffs = np.diff(views)
                conv_signal = np.convolve(diffs[-len(kernel):], kernel, mode='valid')
                conv_growth = np.mean(conv_signal) if len(conv_signal) > 0 else 0
            else:
                conv_growth = np.mean(np.diff(views))
        else:
            conv_growth = velocity * 3600

        # 融合双向
        forward_growth = max(0, fwd_ema - views[-1]) + np.mean(np.diff(views[-3:])) if n >= 3 else 0
        backward_growth = max(0, views[-1] - bwd_ema) * 0.3
        growth = 0.5 * forward_growth + 0.2 * backward_growth + 0.3 * conv_growth

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity
            confidence = min(0.85, 0.35 + 0.02 * min(n, 25) + 0.1)

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "bitcn_numpy", "data_points": n},
            timestamp=datetime.now(),
        )
