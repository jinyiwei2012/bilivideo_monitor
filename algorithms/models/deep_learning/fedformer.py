"""
FEDformer (Frequency Enhanced Decomposed Transformer)
频域增强分解Transformer，ICML 2022

核心思路：
1. FFT 变换到频域，保留 Top-K 频率分量
2. 在频域做幅度+相位增强
3. 频域特征聚合后输出预测
"""

import logging
from typing import Dict, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import FEDformerTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class FEDformerAlgorithm(BaseAlgorithm):
    """FEDformer 频域Transformer"""

    name = "FEDformer频域"
    algorithm_id = "fedformer"
    description = "FFT频域变换+TopK频率增强预测"
    category = "深度学习"
    default_weight = 1.4

    training_window = 12
    training_horizon = 3

    def predict(self, video_data, threshold=100000):
        return try_torch_predict(
            self, video_data, threshold, FEDformerTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        return FEDformerTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon, d_model=32, n_modes=6,
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
                metadata={"method": "fedformer_fallback"}, timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-24:]], dtype=np.float64)
        n = len(views)

        detrended = views - np.polyval(np.polyfit(np.arange(n), views, 1), np.arange(n))
        fft = np.fft.rfft(detrended)
        freqs = np.abs(fft)
        n_modes = min(6, len(freqs) - 1)
        top_idx = np.argsort(freqs)[-n_modes:]

        filtered = np.zeros_like(fft, dtype=complex)
        for idx in top_idx:
            filtered[idx] = fft[idx]

        phase_adj = np.angle(filtered[top_idx]).mean() if len(top_idx) > 0 else 0
        amp_scale = 1.0 + 0.2 * np.tanh(phase_adj)
        for idx in top_idx:
            filtered[idx] *= amp_scale

        reconstructed = np.fft.irfft(filtered, n=n)
        trend = np.polyfit(np.arange(n), views, 1)
        reconstructed += np.polyval(trend, np.arange(n))

        growth = np.mean(np.diff(reconstructed[-5:])) if n >= 5 else velocity * 3600
        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 and predicted_velocity > 0 else float("inf")
        confidence = min(0.85, 0.3 + 0.1 * min(n_modes, 6) + 0.02 * min(n, 20))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={"method": "fedformer_numpy", "n_modes": n_modes}, timestamp=datetime.now(),
        )
