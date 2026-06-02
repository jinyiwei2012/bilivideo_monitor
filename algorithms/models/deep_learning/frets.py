"""
FreTS (Frequency-domain MLPs)
频域多层感知机，NeurIPS 2023

核心思路：
1. FFT 将时序变换到频域
2. 在频域用 MLP 处理幅度
3. iFFT 变换回时域
4. 频域建模自然捕捉周期性
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import FreTSTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class FreTSAlgorithm(BaseAlgorithm):
    """FreTS 频域 MLP"""

    name = "FreTS频域"
    algorithm_id = "frets"
    description = "FFT频域变换+MLP处理+iFFT还原，捕捉周期性"
    category = "深度学习"
    default_weight = 1.3

    training_window = 12
    training_horizon = 3

    def predict(self, video_data, threshold=100000):
        return try_torch_predict(
            self, video_data, threshold, FreTSTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        return FreTSTorchModel(
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
                metadata={"method": "frets_fallback"},
                timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-20:]], dtype=np.float64)
        n = len(views)

        # FFT 频域分析
        detrended = views - np.polyval(np.polyfit(np.arange(n), views, 1), np.arange(n))
        fft = np.fft.rfft(detrended)
        freqs = np.abs(fft)
        n_freq = len(freqs)

        # 频域滤波：保留前 60% 的主要频率分量
        cutoff = max(1, int(n_freq * 0.6))
        filtered_fft = np.zeros_like(fft, dtype=complex)
        sorted_idx = np.argsort(freqs)[::-1]
        keep_count = min(cutoff, n_freq)
        for idx in sorted_idx[:keep_count]:
            filtered_fft[idx] = fft[idx]
        reconstructed = np.fft.irfft(filtered_fft, n=n)

        # 趋势恢复
        trend = np.polyfit(np.arange(n), views, 1)
        reconstructed += np.polyval(trend, np.arange(n))

        if n >= 5:
            growth = np.mean(np.diff(reconstructed[-5:]))
        else:
            growth = velocity * 3600

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity
            # 置信度：信号主导频率越清晰越好
            top_freq_ratio = freqs[sorted_idx[0]] / max(np.sum(freqs), 1) if len(sorted_idx) > 0 else 0.3
            confidence = min(0.85, 0.3 + 0.3 * top_freq_ratio + 0.02 * min(n, 20))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "frets_numpy", "freq_components": keep_count, "data_points": n},
            timestamp=datetime.now(),
        )
