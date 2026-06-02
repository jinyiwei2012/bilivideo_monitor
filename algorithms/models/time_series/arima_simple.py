"""
ARIMA预测算法
优先使用 statsmodels ARIMA 真实实现，不可用时回退 numpy 简化版
"""

import logging
from datetime import datetime
from typing import Dict, Any

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_STATSMODELS = False
try:
    from statsmodels.tsa.arima.model import ARIMA
    _HAS_STATSMODELS = True
except ImportError:
    pass

_HAS_PMDARIMA = False
try:
    import pmdarima as pm
    _HAS_PMDARIMA = True
except ImportError:
    pass


class ArimaSimpleAlgorithm(BaseAlgorithm):
    """ARIMA预测算法"""

    name = "ARIMA简化"
    algorithm_id = "arima_simple"
    description = "自回归积分滑动平均预测（statsmodels 优先，numpy 回退）"
    category = "机器学习"
    default_weight = 1.3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        if _HAS_PMDARIMA and len(history) >= 20:
            try:
                result = self._auto_arima_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("AutoARIMA pmdarima 失败: %s", e)

        if _HAS_STATSMODELS and len(history) >= 15:
            try:
                result = self._statsmodels_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("ARIMA statsmodels 失败，回退 numpy: %s", e)

        return self._numpy_predict(video_data, threshold)

    def _auto_arima_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        timestamps, views_vals = [], []
        for h in history:
            ts = h.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts).timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))

        if len(views_vals) < 20:
            return None

        order = np.argsort(timestamps)
        views = np.array(views_vals)[order]

        try:
            model = pm.auto_arima(
                views, seasonal=False, stepwise=True, suppress_warnings=True,
                max_p=5, max_q=5, max_d=2, maxiter=10, trace=False,
                error_action="ignore",
            )
            forecast = model.predict(n_periods=30)
            forecast_views = np.array(forecast)

            target_idx = np.where(forecast_views >= threshold)[0]
            if len(target_idx) > 0 and target_idx[0] < 30:
                predicted_hours = (target_idx[0] + 1) * 24
                aic = getattr(model, "aic", lambda: 1000)() if callable(getattr(model, "aic", None)) else 1000
                confidence = max(0.1, min(0.9, 0.7 - aic * 0.00015))
            else:
                velocity = self.calculate_velocity(video_data)
                remaining = threshold - current_views
                predicted_hours = remaining / velocity if velocity > 0 else float("inf")
                confidence = 0.4

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views,
                current_velocity=self.calculate_velocity(video_data),
                metadata={
                    "method": "auto_arima",
                    "order": str(getattr(model, "order", "?")),
                    "aic": round(float(model.aic()) if callable(getattr(model, "aic", None)) else 0, 1),
                },
                timestamp=datetime.now(),
            )
        except Exception:
            return None

    def _statsmodels_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        timestamps, views_vals = [], []
        for h in history:
            ts = h.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts).timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))

        if len(views_vals) < 15:
            return None

        order = np.argsort(timestamps)
        views = np.array(views_vals)[order]

        try:
            model = ARIMA(views, order=(2, 1, 1))
            fitted = model.fit()
            forecast = fitted.forecast(steps=30)
            forecast_views = np.array(forecast)

            target_idx = np.where(forecast_views >= threshold)[0]
            if len(target_idx) > 0 and target_idx[0] < 30:
                predicted_hours = (target_idx[0] + 1) * 24
                aic = getattr(fitted, "aic", 1000)
                confidence = max(0.1, min(0.85, 0.7 - aic * 0.0002))
            else:
                velocity = self.calculate_velocity(video_data)
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
                current_velocity=self.calculate_velocity(video_data),
                metadata={"method": "arima_statsmodels", "order": "(2,1,1)"},
                timestamp=datetime.now(),
            )
        except Exception:
            return None

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        if len(history) < 3:
            # 数据不足，使用线性预测
            velocity = self.calculate_velocity(video_data)
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
            elif velocity <= 0:
                predicted_hours = float("inf")
            else:
                predicted_hours = remaining / velocity
            confidence = 0.4
        else:
            # 简化ARIMA: 使用最近3个点的趋势
            recent = history[-3:]
            views = [r.get("view_count", 0) for r in recent]

            # 计算一阶差分
            diff1 = [views[i] - views[i - 1] for i in range(1, len(views))]

            # 预测下一个差分
            if len(diff1) >= 2:
                # 简单平均趋势
                trend = sum(diff1) / len(diff1)
            else:
                trend = diff1[0] if diff1 else 0

            # 计算平均时间间隔
            times = [r.get("timestamp", 0) for r in recent]
            time_diffs = [(times[i] - times[i - 1]) / 3600 for i in range(1, len(times))]
            avg_interval = sum(time_diffs) / len(time_diffs) if time_diffs else 1

            # 预测速度
            velocity = trend / avg_interval if avg_interval > 0 else 0

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
            elif velocity <= 0:
                predicted_hours = float("inf")
            else:
                predicted_hours = remaining / velocity

            confidence = min(1.0, 0.5 + len(history) * 0.05)

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "arima_simple", "history_points": len(history)},
            timestamp=datetime.now(),
        )
