"""
SCINet (Sample Convolution and Interaction Network)
二叉树结构逐层下采样-卷积-交互，捕捉不同时间尺度的模式
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import SCINetTorchModel, try_torch_predict


class ScinetSimpleAlgorithm(BaseAlgorithm):
    """SCINet 样本卷积交互网络"""

    name = "SCINet卷积交互"
    algorithm_id = "scinet_simple"
    description = "二叉树下采样-卷积-交互，多尺度模式捕捉"
    category = "深度学习"
    default_weight = 1.3

    training_window = 10
    training_horizon = 3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        return try_torch_predict(
            self, video_data, threshold, SCINetTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        return SCINetTorchModel(in_features=5, hidden=16, horizon=self.training_horizon)

    def get_training_features(self) -> List[str]:
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 8 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)

            def _sci_block(x):
                even = x[::2]
                odd = x[1::2]
                if len(even) > len(odd):
                    even = even[:len(odd)]
                diff = even - odd
                k = np.array([0.5, 0.5])

                def conv1d(signal, kernel):
                    return np.convolve(signal, kernel, mode='same')[:len(signal)]

                even_filt = conv1d(even, k)
                even_out = even - even_filt
                odd_out = odd + even_filt
                return even_out, odd_out, diff

            def _interact(even, odd, diff):
                gate_e = np.tanh(diff[:len(even)] if len(diff) >= len(even) else np.pad(diff, (0, len(even) - len(diff))))
                gate_o = np.tanh(diff[:len(odd)] if len(diff) >= len(odd) else np.pad(diff, (0, len(odd) - len(diff))))
                return even + gate_e * odd[:len(even)], odd + gate_o * even[:len(odd)]

            combined = views
            even1, odd1, diff1 = _sci_block(combined)
            even1_int, odd1_int = _interact(even1, odd1, diff1)

            if len(even1_int) >= 4:
                even2, odd2, diff2 = _sci_block(even1_int[:len(even1_int) // 2 * 2])
                if len(even2) > 0 and len(odd2) > 0:
                    even2_int, odd2_int = _interact(even2, odd2, diff2)
                    scale2_trend = np.mean(np.abs(even2_int[-3:])) if len(even2_int) >= 3 else 0
                else:
                    scale2_trend = 0
            else:
                scale2_trend = 0

            scale1_trend = np.mean(np.abs(even1_int[-3:])) if len(even1_int) >= 3 else 0
            recent_diff = np.mean(np.diff(views[-5:])) if len(views) >= 5 else velocity * 3600
            predicted_velocity = max(0, (recent_diff + (scale1_trend + scale2_trend) * 50) / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                confidence = max(0.1, min(0.8, 0.5))

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
