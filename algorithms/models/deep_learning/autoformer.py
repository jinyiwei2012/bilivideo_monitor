"""
Autoformer (Auto-Correlation Transformer)
自相关机制替代自注意力，NeurIPS 2021

核心思路：
1. 用 FFT 计算序列自相关代替点积注意力
2. 时序分解：移动平均提取趋势 + 自相关提取季节
3. 渐进式分解架构，逐层提取不同时间尺度
"""

import logging
from typing import Dict, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import AutoformerTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class AutoformerAlgorithm(BaseAlgorithm):
    """Autoformer 自相关Transformer"""

    name = "Autoformer自相关"
    algorithm_id = "autoformer"
    description = "自相关机制替代注意力，趋势-季节渐进分解"
    category = "深度学习"
    default_weight = 1.5

    training_window = 12
    training_horizon = 3

    def predict(self, video_data, threshold=100000):
        return try_torch_predict(
            self, video_data, threshold, AutoformerTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        return AutoformerTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon, d_model=32, n_heads=2,
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
                metadata={"method": "autoformer_fallback"}, timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-24:]], dtype=np.float64)
        n = len(views)

        # 移动平均趋势
        ma_kernel = 3
        if n >= ma_kernel * 2:
            trend = np.convolve(views, np.ones(ma_kernel) / ma_kernel, mode='valid')
        else:
            trend = views

        # 季节性 = 原始 - 趋势
        seasonal = views[-len(trend):] - trend if len(trend) > 0 else views - np.mean(views)

        # 自相关分析
        if len(seasonal) >= 4:
            ac = np.correlate(seasonal - np.mean(seasonal), seasonal - np.mean(seasonal), mode='full')
            ac = ac[len(ac) // 2:]
            ac = ac / (ac[0] + 1e-8)
            peak_lag = np.argmax(ac[1:min(8, len(ac))]) + 1 if len(ac) > 1 else 1
        else:
            peak_lag = 1

        trend_growth = np.mean(np.diff(trend)) if len(trend) >= 2 else velocity * 3600
        seasonal_growth = np.mean(np.diff(seasonal)) if len(seasonal) >= 2 else 0
        growth = 0.6 * trend_growth + 0.4 * seasonal_growth

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = (remaining / predicted_velocity) if remaining > 0 and predicted_velocity > 0 else (remaining / velocity if velocity > 0 else float("inf"))
        confidence = min(0.85, 0.35 + 0.02 * min(n, 20))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={"method": "autoformer_numpy", "peak_lag": peak_lag, "data_points": n},
            timestamp=datetime.now(),
        )
