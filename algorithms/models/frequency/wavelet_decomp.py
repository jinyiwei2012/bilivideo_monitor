"""
小波分解预测 (Wavelet Decomposition)
用离散小波变换将时序分解为多级近似系数+细节系数，过滤噪声后重建预测
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class WaveletDecompositionAlgorithm(BaseAlgorithm):
    """小波分解预测"""

    name = "小波分解"
    algorithm_id = "wavelet_decomp"
    description = "离散小波变换分解，噪声过滤后趋势外推"
    category = "频域分析"
    default_weight = 1.2

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
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
                metadata={"method": "wavelet_fallback"}, timestamp=datetime.now(),
            )

        try:
            views = np.array([h.get("view_count", 0) for h in history[-32:]], dtype=np.float64)
            n = len(views)

            # Haar 小波分解 (离散小波变换)
            coeffs = views.copy()
            levels = []
            while len(coeffs) >= 2:
                approx = (coeffs[::2] + coeffs[1::2]) / 2.0
                detail = (coeffs[::2] - coeffs[1::2]) / 2.0
                levels.append((approx, detail))
                coeffs = approx

            # 在最低频分量上做趋势拟合
            lowest = levels[-1][0] if levels else views
            x = np.linspace(0, 1, len(lowest))
            trend = np.polyfit(x, lowest, 1)

            # 重建：逐级上采样
            reconstructed = np.polyval(trend, x)
            for i in range(len(levels) - 2, -1, -1):
                approx_prev, detail_prev = levels[i]
                upsampled = np.repeat(reconstructed, 2)[:len(approx_prev)]
                detail_filtered = detail_prev * 0.3  # 噪声过滤
                reconstructed = upsampled + detail_filtered

            if len(reconstructed) >= 2:
                growth = np.mean(np.diff(reconstructed[-min(5, len(reconstructed)):]))
            else:
                growth = velocity * 3600

            predicted_velocity = max(0, growth / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 and predicted_velocity > 0 else float("inf")
            n_levels = len(levels)
            confidence = min(0.85, 0.35 + 0.08 * min(n_levels, 4) + 0.02 * min(n, 25))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={"method": "wavelet", "levels": n_levels, "data_points": n},
                timestamp=datetime.now(),
            )
        except Exception:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "wavelet_error"}, timestamp=datetime.now(),
            )
