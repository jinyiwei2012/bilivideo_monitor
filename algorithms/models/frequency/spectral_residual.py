"""
频谱残差预测 (Spectral Residual)
用频谱残差法检测时序异常/突变点，区分正常趋势与突发事件

核心：FFT → 对数幅度 → 均值滤波 → 残差 → iFFT → 显著区域
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class SpectralResidualAlgorithm(BaseAlgorithm):
    """频谱残差"""

    name = "频谱残差"
    algorithm_id = "spectral_residual"
    description = "FFT对数幅度谱残差检测，区分趋势与突发信号"
    category = "频域分析"
    default_weight = 1.1

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 10 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "spectral_fallback"}, timestamp=datetime.now(),
            )

        try:
            views = np.array([h.get("view_count", 0) for h in history[-32:]], dtype=np.float64)
            n = len(views)

            # 去趋势
            detrended = views - np.polyval(np.polyfit(np.arange(n), views, 1), np.arange(n))

            # FFT → 对数幅度谱
            fft = np.fft.fft(detrended)
            log_amp = np.log(np.abs(fft) + 1e-10)

            # 均值滤波得到背景谱
            kernel = min(5, len(log_amp) // 2)
            if kernel >= 3:
                kernel_arr = np.ones(kernel) / kernel
                bg = np.convolve(log_amp, kernel_arr, mode='same')
            else:
                bg = np.mean(log_amp)

            # 频谱残差 = log谱 - 背景谱
            residual = log_amp - bg

            # iFFT → 显著图
            salient = np.abs(np.fft.ifft(np.exp(residual + 1j * np.angle(fft))))

            # 显著区域提取：大于1.5倍标准差
            threshold_val = 1.5 * np.std(salient) + np.mean(salient)
            burst_region = salient > threshold_val

            # 趋势分量 = 非显著区域
            trend_component = views.copy()
            if np.any(~burst_region):
                trend_component[burst_region] = np.interp(
                    np.where(burst_region)[0],
                    np.where(~burst_region)[0],
                    views[~burst_region],
                )

            # 趋势外推
            if len(trend_component) >= 5:
                growth = np.mean(np.diff(trend_component[-5:]))
            else:
                growth = velocity * 3600

            predicted_velocity = max(0, growth / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")

            burst_ratio = np.sum(burst_region) / max(len(burst_region), 1)
            confidence = max(0.1, min(0.85, 0.5 * (1 - burst_ratio) + 0.02 * min(n, 25)))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={"method": "spectral_residual", "burst_ratio": round(burst_ratio, 3), "data_points": n},
                timestamp=datetime.now(),
            )
        except Exception:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "spectral_error"}, timestamp=datetime.now(),
            )
