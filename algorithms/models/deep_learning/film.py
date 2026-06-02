"""
FiLM (Frequency improved Legendre Memory Model)
频率改进的 Legendre 记忆模型，NeurIPS 2022

核心思路：
1. Legendre 多项式基底对时间维做正交投影
2. 频率混合层捕捉时序中的周期性模式
3. MLP 预测头输出
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import FiLMTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class FiLMAlgorithm(BaseAlgorithm):
    """FiLM 频率 Legendre 记忆"""

    name = "FiLM频率记忆"
    algorithm_id = "film"
    description = "Legendre多项式基底+频率混合预测"
    category = "深度学习"
    default_weight = 1.3

    training_window = 12
    training_horizon = 3

    def predict(self, video_data, threshold=100000):
        return try_torch_predict(
            self, video_data, threshold, FiLMTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        return FiLMTorchModel(
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
                metadata={"method": "film_fallback"},
                timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-20:]], dtype=np.float64)
        n = len(views)

        # Legendre 多项式拟合（3阶）
        x = np.arange(n) / max(n - 1, 1) * 2 - 1  # [-1, 1]
        P0 = np.ones(n)
        P1 = x
        P2 = 0.5 * (3 * x**2 - 1)
        P3 = 0.5 * (5 * x**3 - 3 * x)
        polys = np.column_stack([P0, P1, P2, P3])
        coeffs = np.linalg.lstsq(polys, views, rcond=None)[0]
        fitted = polys @ coeffs

        # FFT 频谱分析
        fft = np.fft.rfft(views - fitted)
        freqs = np.abs(fft)
        dominant_idx = np.argmax(freqs[1:]) + 1 if len(freqs) > 1 else 0
        period = n / dominant_idx if dominant_idx > 0 else n

        # 趋势 + 周期混合
        trend_growth = coeffs[1] * 2 / n if n > 1 else 0
        cycle_factor = 1 + 0.3 * (freqs[dominant_idx] / max(np.sum(freqs), 1))
        growth = max(0, trend_growth * cycle_factor)

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity
            confidence = min(0.85, 0.3 + 0.02 * min(n, 25) + 0.1 * min(1, cycle_factor))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "film_numpy", "dominant_period": round(period, 1), "data_points": n},
            timestamp=datetime.now(),
        )
