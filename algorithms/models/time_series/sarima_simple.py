"""
SARIMA季节性预测
优先使用 statsmodels SARIMAX 真实实现，不可用时回退 numpy 简化版
"""

import logging
import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_STATSMODELS = False
try:
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    _HAS_STATSMODELS = True
except ImportError:
    pass

_HAS_PMDARIMA = False
try:
    import pmdarima as pm
    _HAS_PMDARIMA = True
except ImportError:
    pass


class SARIMASimpleAlgorithm(BaseAlgorithm):
    """SARIMA (Seasonal ARIMA) 季节性差分自回归移动平均"""

    name = "SARIMA季节预测"
    algorithm_id = "sarima_simple"
    description = "季节性差分自回归移动平均（statsmodels 优先，numpy 回退）"
    category = "时间序列"
    default_weight = 1.2

    def __init__(self):
        super().__init__()
        self.p, self.d, self.q = 1, 1, 1
        self.P, self.D, self.Q, self.m = 1, 0, 0, 7

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        if _HAS_PMDARIMA and len(history) >= 24:
            try:
                result = self._auto_sarima_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("AutoSARIMA pmdarima 失败: %s", e)

        if _HAS_STATSMODELS and len(history) >= 15:
            try:
                result = self._statsmodels_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("SARIMA statsmodels 失败: %s", e)

        return self._numpy_predict(video_data, threshold)

    def _auto_sarima_predict(self, video_data, threshold):
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)
        views_sorted = self._prepare_series(history)
        n = len(views_sorted)
        if n < 24:
            return None
        try:
            model = pm.auto_arima(
                views_sorted, seasonal=True, m=min(7, n // 4), stepwise=True,
                suppress_warnings=True, max_p=5, max_q=5, max_P=2, max_Q=2,
                maxiter=10, trace=False, error_action="ignore",
            )
            forecast = model.predict(n_periods=30)
            forecast_views = np.array(forecast)
            target_idx = np.where(forecast_views >= threshold)[0]
            if len(target_idx) > 0 and target_idx[0] < 30:
                predicted_hours = (target_idx[0] + 1) * 24
                aic = float(model.aic()) if callable(getattr(model, "aic", None)) else 1000
                confidence = max(0.1, min(0.9, 0.7 - aic * 0.00015))
            else:
                remaining = threshold - current_views
                predicted_hours = remaining / velocity if velocity > 0 else float("inf")
                confidence = 0.4
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views,
                current_velocity=velocity,
                metadata={
                    "method": "auto_sarima",
                    "order": str(getattr(model, "order", "?")),
                    "seasonal_order": str(getattr(model, "seasonal_order", "?")),
                    "aic": round(aic, 1) if "aic" in dir() else 0,
                },
                timestamp=datetime.now(),
            )
        except Exception:
            return None

    def _statsmodels_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        views_sorted = self._prepare_series(history)
        n = len(views_sorted)
        if n < 15:
            return None

        try:
            model = SARIMAX(
                views_sorted,
                order=(self.p, self.d, self.q),
                seasonal_order=(self.P, self.D, self.Q, min(self.m, n // 2)),
                enforce_stationarity=False,
                enforce_invertibility=False,
            )
            fitted = model.fit(disp=False)
            forecast = fitted.forecast(steps=30)
            forecast_views = np.array(forecast)

            target_idx = np.where(forecast_views >= threshold)[0]
            if len(target_idx) > 0 and target_idx[0] < 30:
                predicted_hours = (target_idx[0] + 1) * 24
                aic = getattr(fitted, "aic", 1000)
                confidence = max(0.1, min(0.85, 0.7 - aic * 0.0002))
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
                metadata={
                    "method": "sarima_statsmodels",
                    "order": f"({self.p},{self.d},{self.q})x({self.P},{self.D},{self.Q},{self.m})",
                    "aic": round(float(aic), 1) if "aic" in dir() else 0,
                },
                timestamp=datetime.now(),
            )
        except Exception:
            return None

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return self._build_result(threshold, 0, 1.0, velocity, current_views, method="sarima_already")

        if len(history) < max(4, self.m + 2) or velocity <= 0:
            hours = remaining / velocity if velocity > 0 else float("inf")
            return self._build_result(threshold, hours, 0.3, velocity, current_views, notes="insufficient_data")

        views_sorted = self._prepare_series(history)
        n = len(views_sorted)
        if n < 4:
            hours = remaining / velocity
            return self._build_result(threshold, hours, 0.3, velocity, current_views, method="sarima_fallback")

        try:
            diff_series = self._differencing(views_sorted)
            diff_series = self._seasonal_differencing(diff_series)

            if len(diff_series) < 2:
                hours = remaining / velocity
                return self._build_result(threshold, hours, 0.3, velocity, current_views, method="sarima_diff_failed")

            y_centered = diff_series - np.mean(diff_series)
            p = min(self.p, len(y_centered) - 1)
            ar_coeffs = self._estimate_ar(y_centered, p)

            q = min(self.q, len(y_centered) - p - 1)
            residuals = self._compute_residuals(y_centered, ar_coeffs, p)
            ma_coeffs = self._estimate_ma(y_centered, residuals, q)

            seasonal_pattern = self._compute_seasonal_pattern(views_sorted, self.m)

            growth_rate = float(np.mean(np.diff(views_sorted))) if n > 1 else velocity * 24
            forecast_days = min(365, max(14, int((threshold - current_views) / max(growth_rate, 1)) + 7))

            pred_values = self._forecast(
                views_sorted, ar_coeffs, ma_coeffs, seasonal_pattern, p, q, self.m, forecast_days
            )

            # 寻找达标点
            combined = np.array(pred_values[n:])
            target_idx = np.where(combined >= threshold)[0]

            if len(target_idx) > 0 and target_idx[0] < 300:
                predicted_hours = (target_idx[0] + 1) * 24
                seasonal_strength = 0.0
                if self.m > 0 and len(seasonal_pattern) > 0:
                    seasonal_strength = min(1.0, float(np.std(seasonal_pattern) / max(np.std(views_sorted), 1)))
                n_points_conf = min(1.0, n / 30)
                conf = min(0.9, 0.35 + 0.25 * n_points_conf + 0.2 * seasonal_strength + 0.1 * min(1.0, velocity / 100))
            else:
                predicted_hours = remaining / velocity
                conf = 0.35

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=conf,
                current_views=current_views,
                current_velocity=velocity,
                metadata={
                    "method": "sarima",
                    "ar_order": p,
                    "diff_order": self.d,
                    "ma_order": q,
                    "seasonal_period": self.m,
                    "seasonal_strength": round(seasonal_strength, 3) if self.m > 0 else 0,
                    "forecast_horizon": forecast_days,
                    "data_points": n,
                },
                timestamp=datetime.now(),
            )
        except Exception as e:
            hours = remaining / velocity if velocity > 0 else float("inf")
            return self._build_result(threshold, hours, 0.0, velocity, current_views, error=str(e))

    # ── 子步骤 ─────────────────────────────────────────
    @staticmethod
    def _prepare_series(history: List[Dict]) -> np.ndarray:
        """从历史记录提取并按时间排序播放量数组"""
        timestamps, views_vals = [], []
        for h in history:
            ts = h.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(str(ts)[:19].replace("T", " ")).timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))
        if len(views_vals) < 1:
            return np.array([])
        order = np.argsort(timestamps)
        return np.array(views_vals)[order]

    def _differencing(self, series: np.ndarray) -> np.ndarray:
        """d 阶差分"""
        diff = series.copy()
        for _ in range(self.d):
            diff = np.diff(diff)
            if len(diff) == 0:
                break
        return diff

    def _seasonal_differencing(self, series: np.ndarray) -> np.ndarray:
        """D 阶季节性差分"""
        if not (self.m > 0 and self.D > 0 and len(series) > self.m):
            return series
        diff = series.copy()
        for _ in range(self.D):
            if len(diff) > self.m:
                diff = diff[self.m :] - diff[: -self.m]
        return diff

    @staticmethod
    def _estimate_ar(y_centered: np.ndarray, p: int) -> np.ndarray:
        """AR 系数估计 (Yule-Walker / 最小二乘)"""
        if p <= 0:
            return np.zeros(0)
        ar_matrix = np.column_stack([y_centered[p - i - 1 : len(y_centered) - i - 1] for i in range(p)])
        if ar_matrix.shape[0] <= p or ar_matrix.shape[1] <= 0:
            return np.zeros(p)
        try:
            return np.linalg.lstsq(ar_matrix, y_centered[p:], rcond=None)[0]
        except np.linalg.LinAlgError:
            return np.zeros(p)

    @staticmethod
    def _compute_residuals(y_centered: np.ndarray, ar_coeffs: np.ndarray, p: int) -> np.ndarray:
        """计算 AR 残差"""
        residuals = y_centered.copy()
        if p > 0 and len(ar_coeffs) == p:
            for i in range(p, len(y_centered)):
                residuals[i] = y_centered[i] - np.dot(ar_coeffs, y_centered[i - p : i])
        return residuals

    @staticmethod
    def _estimate_ma(y_centered: np.ndarray, residuals: np.ndarray, q: int) -> np.ndarray:
        """MA 系数估计"""
        if q <= 0:
            return np.zeros(0)
        ma_matrix = np.column_stack([residuals[q - j - 1 : len(residuals) - j - 1] for j in range(q)])
        if ma_matrix.shape[0] <= q or ma_matrix.shape[1] <= 0:
            return np.zeros(q)
        try:
            return np.linalg.lstsq(ma_matrix, y_centered[q:], rcond=None)[0]
        except np.linalg.LinAlgError:
            return np.zeros(q)

    @staticmethod
    def _compute_seasonal_pattern(views_sorted: np.ndarray, m: int) -> np.ndarray:
        """逐周期平均提取季节性模式"""
        n = len(views_sorted)
        if m <= 0 or m >= n:
            return np.zeros(m) if m <= n else np.zeros(n)
        n_full = n // m
        if n_full < 1:
            return np.zeros(m)
        seasonal_vals = views_sorted[: n_full * m].reshape(n_full, m)
        trend = float(np.mean(views_sorted))
        return np.mean(seasonal_vals, axis=0) - trend

    @staticmethod
    def _forecast(
        views_sorted: np.ndarray,
        ar_coeffs: np.ndarray,
        ma_coeffs: np.ndarray,
        seasonal_pattern: np.ndarray,
        p: int,
        q: int,
        m: int,
        days: int,
    ) -> list:
        """迭代多步预测"""
        growth_rate = float(np.mean(np.diff(views_sorted))) if len(views_sorted) > 1 else 0
        pred_values = list(views_sorted)
        last_residual = 0.0

        for i in range(days):
            idx = len(pred_values)
            ar_term = float(np.dot(ar_coeffs, pred_values[idx - p : idx])) if p > 0 and len(ar_coeffs) == p else 0.0
            ma_term = float(np.dot(ma_coeffs, [last_residual] * q)) if q > 0 and len(ma_coeffs) == q else 0.0
            seas_term = float(seasonal_pattern[i % m]) if m > 0 else 0.0

            next_val = ar_term + ma_term + seas_term + 0.1 * growth_rate
            if next_val < pred_values[-1]:
                next_val = pred_values[-1] + max(growth_rate * 0.3, 0)
            pred_values.append(next_val)

            if len(pred_values) > p + q:
                actual = float(views_sorted[-1]) if i == 0 else pred_values[-2]
                last_residual = actual - (ar_term + seas_term)

        return pred_values

    @staticmethod
    def _build_result(
        threshold: int,
        hours: float,
        conf: float,
        velocity: float,
        current_views: int,
        method: str = "sarima",
        notes: str = "",
        error: str = "",
    ) -> PredictionResult:
        """构造失败/回退结果"""
        meta = {"method": method}
        if notes:
            meta["notes"] = notes
        if error:
            meta["error"] = error
        return PredictionResult(
            algorithm_name="SARIMA季节预测",
            algorithm_id="sarima_simple",
            target_threshold=threshold,
            predicted_hours=hours,
            confidence=conf,
            current_views=current_views,
            current_velocity=velocity,
            metadata=meta,
            timestamp=datetime.now(),
        )
