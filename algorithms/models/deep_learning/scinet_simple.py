"""
SCINet (Sample Convolution and Interaction Network)
二叉树结构逐层下采样-卷积-交互，捕捉不同时间尺度的模式
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class ScinetSimpleAlgorithm(BaseAlgorithm):
    """SCINet 样本卷积交互网络"""

    name = "SCINet卷积交互"
    algorithm_id = "scinet_simple"
    description = "二叉树下采样-卷积-交互，多尺度模式捕捉"
    category = "深度学习"
    default_weight = 1.3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 8 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            likes = np.array([h.get("like", 0) for h in history], dtype=np.float64)

            def _sci_block(x):
                n = len(x)
                half = n // 2
                even = x[::2]
                odd = x[1::2]
                if len(even) > len(odd):
                    even = even[:len(odd)]
                diff = even - odd
                k = np.array([0.5, 0.5])

                def conv1d(signal, kernel):
                    k_len = len(kernel)
                    result = np.convolve(signal, kernel, mode='same')[:len(signal)]
                    return result

                even_filt = conv1d(even, k)
                odd_filt = conv1d(odd, k)
                even_out = even - odd_filt
                odd_out = odd + even_filt
                return even_out, odd_out, diff

            def _interact(even, odd, diff):
                gate_e = np.tanh(diff[:len(even)] if len(diff) >= len(even) else np.pad(diff, (0, len(even) - len(diff))))
                gate_o = np.tanh(diff[:len(odd)] if len(diff) >= len(odd) else np.pad(diff, (0, len(odd) - len(diff))))
                return even + gate_e * odd[:len(even)], odd + gate_o * even[:len(odd)]

            combined = views + likes * 0.1
            even1, odd1, diff1 = _sci_block(combined)
            even2, odd2, diff2 = _sci_block(even1[:len(even1) // 2 * 2]) if len(even1) >= 4 else (even1, odd1[:1], diff1[:1])

            even1_int, odd1_int = _interact(even1, odd1, diff1)

            if len(even2) > 0 and len(odd2) > 0:
                even2_int, odd2_int = _interact(even2, odd2, diff2)
                scale2_trend = np.mean(np.abs(even2_int[-3:])) if len(even2_int) >= 3 else 0
            else:
                scale2_trend = 0

            scale1_trend = np.mean(np.abs(even1_int[-3:])) if len(even1_int) >= 3 else 0
            multi_scale_trend = (scale1_trend + scale2_trend) / 2

            recent_diff = np.mean(np.diff(views[-5:])) if len(views) >= 5 else velocity * 3600
            predicted_velocity = max(0, (recent_diff + multi_scale_trend * 100) / 3600)

            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                scale_variance = np.var([scale1_trend, scale2_trend]) + 1e-10
                confidence = max(0.1, min(0.8, 0.5 - np.log1p(scale_variance) * 0.05))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "scinet", "scales": 2},
                timestamp=datetime.now(),
            )
        except Exception:
            return self._fallback(velocity, current_views, threshold)

    def _fallback(self, velocity, current_views, threshold):
        if velocity <= 0:
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=float("inf"),
                confidence=0.0, current_views=current_views, current_velocity=velocity,
                metadata={"method": "scinet", "reason": "fallback"},
                timestamp=datetime.now(),
            )
        remaining = max(0, threshold - current_views)
        predicted_hours = remaining / velocity if remaining > 0 else 0
        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=0.3, current_views=current_views, current_velocity=velocity,
            metadata={"method": "scinet", "reason": "fallback"},
            timestamp=datetime.now(),
        )
