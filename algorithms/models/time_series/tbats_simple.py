"""
TBATS (Trigonometric seasonal, Box-Cox, ARMA, Trend, Seasonal)
优先使用 tbats 库真实实现，不可用时回退 numpy 简化版
"""

import logging
import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_TBATS = False
try:
    from tbats import TBATS as _TBATS

    _HAS_TBATS = True
except ImportError:
    pass


class TbatsSimpleAlgorithm(BaseAlgorithm):
    """TBATS 三角函数季节分解"""

    name = "TBATS季节分解"
    algorithm_id = "tbats_simple"
    description = "三角函数多重季节分解（tbats 库优先，numpy 回退）"
    category = "时间序列"
    default_weight = 1.2

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 8 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        if _HAS_TBATS and len(history) >= 15:
            try:
                result = self._tbats_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("TBATS 库失败，回退 numpy: %s", e)

        return self._numpy_predict(video_data, threshold)

    def _tbats_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)

        if len(views) < 15:
            return None

        try:
            estimator = _TBATS(seasonal_periods=[7, 14], use_box_cox=True)
            fitted = estimator.fit(views)
            forecast = fitted.forecast(steps=14)
            forecast_views = np.array(forecast)

            target_idx = np.where(forecast_views >= threshold)[0]
            if len(target_idx) > 0 and target_idx[0] < 14:
                predicted_hours = (target_idx[0] + 1) * 24
                confidence = max(0.1, min(0.85, 0.6 - np.std(forecast_views) / max(np.mean(forecast_views), 1) * 5))
            else:
                remaining = threshold - current_views
                predicted_hours = remaining / velocity if velocity > 0 else float("inf")
                confidence = 0.35

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "tbats_lib", "periods": [7, 14]},
                timestamp=datetime.now(),
            )
        except Exception:
            return None

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 8 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)

            boxcox_lambda = 0.5
            transformed = (views**boxcox_lambda - 1) / boxcox_lambda if boxcox_lambda != 0 else np.log(views)

            n = len(transformed)
            t = np.arange(n)
            periods = [7, 14]
            seasonal_components = np.zeros(n)
            for p in periods:
                if p > n // 2:
                    continue
                cos_wave = np.cos(2 * np.pi * t / p)
                sin_wave = np.sin(2 * np.pi * t / p)
                amp_cos = np.sum(transformed * cos_wave) / n
                amp_sin = np.sum(transformed * sin_wave) / n
                seasonal_components += amp_cos * cos_wave + amp_sin * sin_wave

            detrended = transformed - seasonal_components
            trend_coeffs = np.polyfit(t, detrended, 1)
            trend = np.polyval(trend_coeffs, t)
            resid = detrended - trend

            ar_coeffs = np.polyfit(resid[:-1], resid[1:], 1) if len(resid) > 1 else [0]
            ar_pred = ar_coeffs[0] * resid[-1] if len(ar_coeffs) > 0 else 0

            future_steps = 7
            future_t = np.arange(n, n + future_steps)
            future_seasonal = np.zeros(future_steps)
            for p in periods:
                if p > n // 2:
                    continue
                future_seasonal += amp_cos * np.cos(2 * np.pi * future_t / p) + amp_sin * np.sin(
                    2 * np.pi * future_t / p
                )

            future_trend = np.polyval(trend_coeffs, future_t)
            future_ar = np.array([ar_pred * (ar_coeffs[0] ** i) for i in range(future_steps)])
            future_transformed = future_trend + future_seasonal + future_ar

            future_views = (future_transformed * boxcox_lambda + 1) ** (1 / boxcox_lambda)
            predicted_velocity = max(0, np.mean(np.diff(future_views)) / 3600)

            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                forecast_var = np.var(future_views) if len(future_views) > 1 else 1
                cv = np.sqrt(forecast_var) / max(np.mean(future_views), 1)
                confidence = max(0.1, min(0.85, 0.6 - cv * 5))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "tbats", "periods": list(periods)},
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
                metadata={"method": "tbats", "reason": "fallback"},
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
            metadata={"method": "tbats", "reason": "fallback"},
            timestamp=datetime.now(),
        )
