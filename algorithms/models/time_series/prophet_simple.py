"""
Prophet 预测算法 — 真实实现 + numpy 降级

优先使用 prophet.Prophet 拟合趋势 + 季节性分解；
若库不可用、数据不足或拟合失败，回退到同算法的 numpy 简化版

参考: Taylor & Letham (2018) "Forecasting at Scale", American Statistician
"""

import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_PROPHET = False
try:
    from prophet import Prophet

    _HAS_PROPHET = True
except ImportError:
    pass


class ProphetSimpleAlgorithm(BaseAlgorithm):
    """Prophet 预测算法"""

    name = "Prophet"
    algorithm_id = "prophet"
    description = "基于 Facebook Prophet 的趋势+季节性分解预测"
    category = "时间序列"
    default_weight = 1.3

    def __init__(self):
        super().__init__()
        self.n_changepoints = 3
        self.seasonality_prior = 0.5
        self.fourier_order = 3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=0, confidence=1.0,
                current_views=current_views, current_velocity=velocity,
                metadata={"method": "prophet", "note": "already_reached"},
                timestamp=datetime.now(),
            )

        if len(history) < 7 or velocity <= 0:
            return self._numpy_predict(current_views, velocity, remaining, threshold)

        if _HAS_PROPHET:
            try:
                result = self._prophet_predict(history, current_views, threshold)
                if result is not None:
                    predicted_hours, confidence = result
                    return PredictionResult(
                        algorithm_name=self.name, algorithm_id=self.algorithm_id,
                        target_threshold=threshold, predicted_hours=predicted_hours,
                        confidence=confidence, current_views=current_views,
                        current_velocity=velocity,
                        metadata={"method": "prophet", "data_points": len(history)},
                        timestamp=datetime.now(),
                    )
            except Exception as e:
                logger.debug("Prophet 预测失败，回退 numpy: %s", e)

        return self._numpy_forecast(history, current_views, velocity, remaining, threshold)

    def _prophet_predict(self, history, current_views, threshold) -> Optional[Tuple[float, float]]:
        df = self._build_prophet_df(history)
        if df is None or len(df) < 7:
            return None

        model = Prophet(
            changepoint_prior_scale=0.05,
            weekly_seasonality=True,
            daily_seasonality=False,
            yearly_seasonality=False,
        )
        model.fit(df)

        periods = min(365, max(30, int((threshold - current_views) / max(1, np.mean(np.diff(df["y"])))) + 7))
        future = model.make_future_dataframe(periods=periods)
        forecast = model.predict(future)

        forecast_values = forecast["yhat"].values[-periods:]
        for i in range(periods):
            if forecast_values[i] >= threshold:
                predicted_hours = (i + 1) * 24
                break
        else:
            return None

        # 置信度基于预测区间宽度
        yhat_lower = forecast["yhat_lower"].values[-periods:]
        yhat_upper = forecast["yhat_upper"].values[-periods:]
        if i < len(yhat_upper):
            interval_width = yhat_upper[i] - yhat_lower[i]
            scale = max(abs(threshold), 1)
            confidence = max(0.1, min(0.85, 0.6 - (interval_width / scale) * 0.3))
        else:
            confidence = 0.3

        return (predicted_hours, confidence)

    def _build_prophet_df(self, history):
        try:
            import pandas as pd

            records = []
            for h in history:
                ts = h.get("timestamp", 0)
                if hasattr(ts, "timestamp"):
                    dt = datetime.fromtimestamp(ts.timestamp())
                elif isinstance(ts, (int, float)):
                    dt = datetime.fromtimestamp(ts)
                else:
                    continue
                records.append({"ds": dt, "y": float(h.get("view_count", 0))})

            if len(records) < 7:
                return None
            return pd.DataFrame(records)
        except Exception:
            return None

    def _numpy_forecast(self, history, current_views, velocity, remaining, threshold) -> PredictionResult:
        try:
            t, y = self._extract_time_series(history)
            if t is None or len(t) < 7:
                return self._numpy_predict(current_views, velocity, remaining, threshold)

            n = len(t)
            period = 7.0
            cp_t = self._compute_changepoints(t, n)

            X_trend = self._build_trend_features(t, cp_t)
            X_seasonal = self._build_seasonal_features(t, period)
            X = np.column_stack([X_trend, X_seasonal])
            n_trend = X_trend.shape[1]

            beta = self._fit_ridge(X, y, n_trend)

            forecast_result = self._compute_forecast(X, beta, n, cp_t, period, current_views, threshold, y)
            if forecast_result is None:
                return self._numpy_predict(current_views, velocity, remaining, threshold)

            predicted_hours, confidence = forecast_result
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "prophet_numpy", "data_points": len(history)},
                timestamp=datetime.now(),
            )
        except Exception:
            return self._numpy_predict(current_views, velocity, remaining, threshold)

    def _numpy_predict(self, current_views, velocity, remaining, threshold) -> PredictionResult:
        if velocity <= 0:
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=float("inf"),
                confidence=0.0, current_views=current_views, current_velocity=velocity,
                metadata={"method": "prophet_fallback"},
                timestamp=datetime.now(),
            )
        predicted_hours = remaining / velocity
        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=0.3, current_views=current_views, current_velocity=velocity,
            metadata={"method": "prophet_fallback"},
            timestamp=datetime.now(),
        )

    # ── numpy 回退的辅助方法 ────────────────────────────

    def _extract_time_series(self, history):
        t_days = []
        views = []
        base_time = None
        for h in history:
            ts = h.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                epoch = ts.timestamp()
            elif isinstance(ts, (int, float)):
                epoch = ts
            elif isinstance(ts, str):
                dt_obj = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                epoch = dt_obj.timestamp()
            else:
                continue
            if base_time is None:
                base_time = epoch
            t_days.append((epoch - base_time) / 86400.0)
            views.append(float(h.get("view_count", 0)))
        if len(t_days) < 7 or not views:
            return None, None
        return np.array(t_days), np.array(views)

    def _compute_changepoints(self, t, n):
        n_cp = min(self.n_changepoints, n - 2)
        cp_idx = np.linspace(0, n - 1, n_cp + 2, dtype=int)[1:-1]
        return t[cp_idx] if len(cp_idx) > 0 else np.array([t[-1]])

    def _build_trend_features(self, time_array, cp_t):
        features = [np.ones(len(time_array)), time_array.copy()]
        for cp in cp_t:
            features.append(np.maximum(0, time_array - cp))
        return np.column_stack(features)

    def _build_seasonal_features(self, time_array, period):
        features = []
        for order in range(1, self.fourier_order + 1):
            features.append(np.sin(2 * np.pi * order * time_array / period))
            features.append(np.cos(2 * np.pi * order * time_array / period))
        n = len(time_array)
        return np.column_stack(features) if features else np.zeros((n, 0))

    def _fit_ridge(self, X, y, n_trend):
        lam = 1.0 / max(self.seasonality_prior, 0.01)
        n_features = X.shape[1]
        reg_matrix = np.diag([0] * n_trend + [lam] * (n_features - n_trend))
        try:
            return np.linalg.solve(X.T @ X + reg_matrix, X.T @ y)
        except np.linalg.LinAlgError:
            return np.linalg.lstsq(X.T @ X + reg_matrix, X.T @ y, rcond=None)[0]

    def _compute_forecast(self, X, beta, n, cp_t, period, current_views, threshold, y):
        days_ahead = min(365, int((threshold - current_views) / max(np.mean(np.diff(y)), 1)) + 7)
        days_ahead = max(7, days_ahead)
        future_t = np.arange(n, n + days_ahead)
        future_X_trend = self._build_trend_features(future_t, cp_t)
        future_X_seasonal = self._build_seasonal_features(future_t, period)
        future_X = np.column_stack([future_X_trend, future_X_seasonal])
        forecast = future_X @ beta
        for i in range(days_ahead):
            if forecast[i] >= threshold:
                target_days = i + 1
                break
        else:
            return None
        if target_days > 3650:
            return None
        predicted_hours = target_days * 24
        fitted = X @ beta
        residuals = y - fitted
        scale = np.std(y)
        fit_quality = max(0.0, 1.0 - np.std(residuals) / scale) if scale > 0 else 0.5
        confidence = min(0.9, 0.4 + 0.3 * fit_quality + 0.2 * min(1.0, n / 20))
        return (predicted_hours, confidence)
