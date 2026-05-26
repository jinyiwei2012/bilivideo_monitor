"""
Theta预测方法
M3预测竞赛获胜方法，通过两条Theta线组合进行预测
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
import logging

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)


class ThetaForecastAlgorithm(BaseAlgorithm):
    """Theta预测算法

    Theta方法通过改变时间序列的曲率生成两条不同的外推线，
    然后组合它们得到最终预测。对趋势型数据表现优异。

    参考: Assimakopoulos & Nikolopoulos (2000), International Journal of Forecasting
    """

    name = "Theta预测"
    algorithm_id = "theta_forecast"
    description = "M3预测竞赛获胜方法，双线组合预测"
    category = "时间序列"
    default_weight = 1.2

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return self._make_result(0, 1.0, current_views, velocity, {"method": "theta"}, threshold)

        if len(history) < 4 or velocity <= 0:
            return self._make_result(
                remaining / velocity if velocity > 0 else float("inf"),
                0.3,
                current_views,
                velocity,
                {"method": "theta", "notes": "insufficient_data"},
                threshold,
            )

        views_sorted = self._extract_views(history)
        if views_sorted is None or len(views_sorted) < 4:
            return self._make_result(
                remaining / velocity,
                0.3,
                current_views,
                velocity,
                {"method": "theta_fallback"},
                threshold,
            )

        try:
            return self._compute_theta(views_sorted, current_views, velocity, remaining, threshold)
        except Exception as e:
            logger.warning(f"Theta预测失败: {e}")
            return self._make_result(
                remaining / velocity if velocity > 0 else float("inf"),
                0.0,
                current_views,
                velocity,
                {"error": str(e)},
                threshold,
            )

    def _extract_views(self, history):
        """从历史记录中提取并排序播放量序列"""
        timestamps, views_vals = [], []
        for h in history:
            ts = h.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(str(ts)[:19].replace("T"," ")).timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))
        if len(views_vals) < 4:
            return None
        order = np.argsort(timestamps)
        return np.array(views_vals)[order]

    def _compute_theta(self, views_sorted, current_views, velocity, remaining, threshold):
        """执行Theta算法核心计算"""
        n = len(views_sorted)
        x = np.arange(n, dtype=float)

        coeffs = np.polyfit(x, views_sorted, 1)
        trend_vals = np.polyval(coeffs, x)
        theta_2 = 2 * views_sorted - trend_vals
        alpha = 0.3
        smoothed = np.zeros(n)
        smoothed[0] = theta_2[0]
        for i in range(1, n):
            smoothed[i] = alpha * theta_2[i] + (1 - alpha) * smoothed[i - 1]

        growth_per_day = np.mean(np.diff(views_sorted)) if n > 1 else velocity * 24
        n_future = min(365, max(10, int((threshold - current_views) / max(growth_per_day, 1)) + 5))
        future_x = np.arange(n, n + n_future)

        forecast_0 = np.polyval(coeffs, future_x)
        ses_last = smoothed[-1]
        forecast_2 = np.empty(n_future)
        for i in range(n_future):
            w = min(1.0, i / max(n_future // 2, 1))
            forecast_2[i] = (1 - w) * ses_last + w * forecast_0[i]

        combined = 0.5 * forecast_0 + 0.5 * forecast_2
        target_days = next((i + 1 for i in range(n_future) if combined[i] >= threshold), None)

        if target_days is None or target_days > 3650:
            predicted_hours = remaining / velocity
            confidence = 0.4
        else:
            predicted_hours = target_days * 24
            residuals = views_sorted - trend_vals
            scale = np.std(views_sorted)
            fit_quality = max(0.0, 1.0 - np.std(residuals) / max(scale, 1))
            confidence = min(0.9, 0.4 + 0.3 * fit_quality + 0.2 * min(1.0, n / 20))

        return self._make_result(
            predicted_hours,
            confidence,
            current_views,
            velocity,
            {
                "method": "theta",
                "trend_slope": coeffs[0],
                "ses_last": float(ses_last),
                "forecast_horizon": n_future,
                "data_points": n,
            },
            threshold,
        )

    def _make_result(self, predicted_hours, confidence, current_views, velocity, metadata, threshold):
        """构造 PredictionResult"""
        metadata.setdefault("method", "theta")
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata=metadata,
            timestamp=datetime.now(),
        )
