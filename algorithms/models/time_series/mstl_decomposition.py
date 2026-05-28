"""
MSTL (Multiple Seasonal-Trend decomposition using LOESS)
迭代分解多重季节分量 + 趋势，对每类成分分别预测后合成
"""

import numpy as np
import warnings
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

try:
    from statsmodels.tsa.seasonal import MSTL as _MSTL

    _HAS_MSTL = True
except ImportError:
    _HAS_MSTL = False


class MstlDecompositionAlgorithm(BaseAlgorithm):
    """MSTL 多重季节分解"""

    name = "MSTL多重季节"
    algorithm_id = "mstl_decomposition"
    description = "多重季节分解+趋势预测合成"
    category = "时间序列"
    default_weight = 1.1

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 10 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)

            if _HAS_MSTL and len(views) >= 14:
                try:
                    # 动态选择周期：避免 period > len/2 触发 statsmodels 警告
                    max_period = min(14, len(views) // 2)
                    periods = [p for p in [7, 14] if p <= max_period] or [max(3, max_period)]
                    with warnings.catch_warnings():
                        warnings.filterwarnings("ignore", message="A period")
                        stl = _MSTL(views, periods=periods)
                        res = stl.fit()
                    trend = res.trend
                    seasonal = res.seasonal
                    trend_grad = np.gradient(trend)
                    trend_vel = np.mean(trend_grad[-3:]) / 3600
                except Exception:
                    trend_vel = velocity
                    seasonal = np.zeros_like(views)
            else:
                from scipy.signal import savgol_filter

                window = min(7, len(views) - 1 if len(views) % 2 == 0 else len(views))
                if window < 3:
                    window = 3
                if window % 2 == 0:
                    window += 1
                trend = savgol_filter(views, window, 1)
                seasonal = views - trend
                trend_vel = np.mean(np.diff(trend[-5:])) / 3600 if len(trend) >= 5 else velocity

            seasonal_pattern = seasonal[-min(7, len(seasonal)) :]
            pred_seasonal = np.tile(seasonal_pattern, 3)[:7]
            pred_seasonal_effect = np.mean(pred_seasonal) / max(np.mean(views[-7:]), 1)

            predicted_velocity = max(0, trend_vel * (1 + 0.3 * pred_seasonal_effect))
            if predicted_velocity < velocity * 0.3:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                confidence = min(0.8, 0.4 + 0.04 * np.log1p(len(history)))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "mstl", "history_len": len(history)},
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
                metadata={"method": "mstl", "reason": "fallback"},
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
            metadata={"method": "mstl", "reason": "fallback"},
            timestamp=datetime.now(),
        )
