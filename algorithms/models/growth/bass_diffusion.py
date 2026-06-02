"""
Bass扩散模型 (Bass Diffusion Model)
经典创新扩散理论，模型化视频播放量在社会网络中的传播过程

公式：dN/dt = (p + q*N/M) * (M - N)
p=创新系数, q=模仿系数, M=市场容量
"""

import logging
import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)


class BassDiffusionAlgorithm(BaseAlgorithm):
    """Bass扩散模型"""

    name = "Bass扩散"
    algorithm_id = "bass_diffusion"
    description = "创新扩散理论建模视频传播曲线"
    category = "扩散模型"
    default_weight = 1.2

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 5 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "bass_fallback"}, timestamp=datetime.now(),
            )

        try:
            views = np.array([h.get("view_count", 0) for h in history[-30:]], dtype=np.float64)
            n = len(views)
            cum_views = views

            # 市场容量估计：当前播放量的 3-10 倍
            M = max(current_views * 5, threshold * 1.2)

            # 用差分近似 dN/dt
            dN = np.diff(cum_views)
            N = cum_views[:-1]
            mask = dN > 0

            if np.sum(mask) < 3:
                return self._fallback(velocity, current_views, threshold)

            # 最小二乘估计 p, q
            y = dN[mask] / (M - N[mask])
            X = np.column_stack([np.ones(len(y)), N[mask] / M])
            try:
                coeffs = np.linalg.lstsq(X, y, rcond=None)[0]
                p, q = max(0.001, coeffs[0]), max(0.001, coeffs[1])
            except np.linalg.LinAlgError:
                p, q = 0.01, 0.05

            # 用估计的 p, q 模拟到达 threshold
            t = np.arange(0, 365 * 24, 1)
            F = (1 - np.exp(-(p + q) * t)) / (1 + q / p * np.exp(-(p + q) * t))
            N_pred = M * F + current_views * (1 - F)
            target_idx = np.where(N_pred >= threshold)[0]
            predicted_hours = target_idx[0] if len(target_idx) > 0 else remaining / velocity
            confidence = min(0.85, 0.4 + 0.15 * min(q / p, 3) + 0.02 * min(n, 20))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={"method": "bass_diffusion", "p": round(p, 4), "q": round(q, 4), "M": M},
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.debug("Bass diffusion failed: %s", e)
            return self._fallback(velocity, current_views, threshold)

    def _fallback(self, velocity, current_views, threshold):
        remaining = threshold - current_views
        predicted_hours = remaining / velocity if velocity > 0 else float("inf")
        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=0.3, current_views=current_views, current_velocity=velocity,
            metadata={"method": "bass_fallback"}, timestamp=datetime.now(),
        )
