"""
频域分解 (Fourier/Wavelet Decomposition)
将播放量序列转换到频域，分解出周期成分，在频域预测后逆变换
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class FourierWaveletAlgorithm(BaseAlgorithm):
    """频域分解预测"""

    name = "频域分解"
    algorithm_id = "fourier_wavelet"
    description = "傅里叶/小波频域分解，捕捉周期模式"
    category = "高级分析"
    default_weight = 1.0

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 6 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            detrended = views - np.polyval(np.polyfit(np.arange(len(views)), views, 1), np.arange(len(views)))

            fft = np.fft.rfft(detrended)
            n_harmonics = max(1, len(fft) // 4)
            fft_filtered = np.zeros_like(fft, dtype=complex)
            fft_filtered[:n_harmonics] = fft[:n_harmonics]

            reconstructed = np.fft.irfft(fft_filtered, n=len(detrended))

            window = min(3, len(reconstructed))
            if window < 1:
                window = 1
            wave_diff = np.diff(reconstructed[-window:])
            wave_velocity = np.mean(wave_diff) / 3600 if len(wave_diff) > 0 else 0

            trend_coeffs = np.polyfit(np.arange(len(views)), views, 1)
            trend_velocity = trend_coeffs[0] / 3600

            predicted_velocity = max(0, trend_velocity + wave_velocity)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                periodicity = (
                    np.std(reconstructed[-14:]) / max(np.std(detrended), 1) if len(reconstructed) >= 14 else 0.5
                )
                confidence = max(0.1, min(0.8, 0.5 - periodicity * 0.3))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "fourier_wavelet", "harmonics": n_harmonics},
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
                metadata={"method": "fourier_wavelet", "reason": "fallback"},
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
            metadata={"method": "fourier_wavelet", "reason": "fallback"},
            timestamp=datetime.now(),
        )
