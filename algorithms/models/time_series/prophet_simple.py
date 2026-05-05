"""
Prophet风格分解预测
基于趋势 + 季节性傅里叶分解的预测方法
灵感来自 Facebook Prophet 模型
"""

import numpy as np
from typing import List, Dict, Any
from datetime import datetime
import logging

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)


class ProphetSimpleAlgorithm(BaseAlgorithm):
    """Prophet风格分解预测算法

    使用线性趋势 + 傅里叶级数逼近周季节性，
    将时间序列分解为可解释的趋势和周期成分。

    参考: Taylor & Letham (2018) "Forecasting at Scale", American Statistician
    """

    name = "Prophet风格"
    algorithm_id = "prophet_simple"
    description = "趋势+傅里叶季节性分解预测"
    category = "时间序列"
    default_weight = 1.2

    def __init__(self):
        super().__init__()
        self.n_changepoints = 3
        self.seasonality_prior = 0.5
        self.fourier_order = 3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=0,
                confidence=1.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "prophet"},
                timestamp=datetime.now(),
            )

        if len(history) < 7 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.3,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "prophet", "notes": "insufficient_data"},
                timestamp=datetime.now(),
            )

        try:
            result = self._prophet_forecast(history, current_views, threshold)
            if result is None:
                predicted_hours = remaining / velocity
                return PredictionResult(
                    algorithm_name=self.name,
                    algorithm_id=self.algorithm_id,
                    target_threshold=threshold,
                    predicted_hours=predicted_hours,
                    confidence=0.3,
                    current_views=current_views,
                    current_velocity=velocity,
                    metadata={"method": "prophet_fallback"},
                    timestamp=datetime.now(),
                )

            predicted_hours, confidence = result
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "prophet", "data_points": len(history)},
                timestamp=datetime.now(),
            )

        except Exception as e:
            logger.warning(f"Prophet预测失败: {e}")
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"error": str(e)},
                timestamp=datetime.now(),
            )

    def _prophet_forecast(self, history, current_views, threshold):
        """Prophet风格预测核心"""
        # 提取时间序列（以天为单位）
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

        if len(t_days) < 7:
            return None

        t = np.array(t_days)
        y = np.array(views)
        n = len(t)

        # 1. 构建线性趋势设计矩阵（含变点）
        n_cp = min(self.n_changepoints, n - 2)
        cp_idx = np.linspace(0, n - 1, n_cp + 2, dtype=int)[1:-1]
        cp_t = t[cp_idx] if len(cp_idx) > 0 else np.array([t[-1]])

        # 趋势特征: [1, t, (t-cp1)+, (t-cp2)+, ...]
        X_trend = [np.ones(n), t.copy()]
        for cp in cp_t:
            X_trend.append(np.maximum(0, t - cp))
        X_trend = np.column_stack(X_trend)

        # 2. 构建傅里叶季节性特征（周周期 = 7天）
        period = 7.0
        X_seasonal = []
        for order in range(1, self.fourier_order + 1):
            X_seasonal.append(np.sin(2 * np.pi * order * t / period))
            X_seasonal.append(np.cos(2 * np.pi * order * t / period))
        X_seasonal = np.column_stack(X_seasonal) if X_seasonal else np.zeros((n, 0))

        # 3. 拼接设计矩阵
        X = np.column_stack([X_trend, X_seasonal])

        # 4. 岭回归拟合（用L2正则化控制季节性强度）
        lam = 1.0 / max(self.seasonality_prior, 0.01)
        n_features = X.shape[1]
        n_trend = X_trend.shape[1]

        # 正则化矩阵：趋势部分不惩罚，季节性部分惩罚
        reg_matrix = np.diag([0] * n_trend + [lam] * (n_features - n_trend))
        try:
            beta = np.linalg.solve(X.T @ X + reg_matrix, X.T @ y)
        except np.linalg.LinAlgError:
            beta = np.linalg.lstsq(X.T @ X + reg_matrix, X.T @ y, rcond=None)[0]

        # 5. 外推预测
        days_ahead = min(365, int((threshold - current_views) / max(np.mean(np.diff(y)), 1)) + 7)
        days_ahead = max(7, days_ahead)

        future_t = np.arange(n, n + days_ahead)
        future_X_trend = [np.ones(days_ahead), future_t.copy()]
        for cp in cp_t:
            future_X_trend.append(np.maximum(0, future_t - cp))
        future_X_trend = np.column_stack(future_X_trend)

        future_X_seasonal = []
        for order in range(1, self.fourier_order + 1):
            future_X_seasonal.append(np.sin(2 * np.pi * order * future_t / period))
            future_X_seasonal.append(np.cos(2 * np.pi * order * future_t / period))
        future_X_seasonal = np.column_stack(future_X_seasonal) if future_X_seasonal else np.zeros((days_ahead, 0))

        future_X = np.column_stack([future_X_trend, future_X_seasonal])
        forecast = future_X @ beta

        # 6. 找达标时间
        target_days = None
        for i in range(days_ahead):
            if forecast[i] >= threshold:
                target_days = i + 1
                break

        if target_days is None or target_days > 3650:
            return None

        predicted_hours = target_days * 24

        # 7. 置信度
        fitted = X @ beta
        residuals = y - fitted
        scale = np.std(y)
        if scale > 0:
            fit_quality = max(0.0, 1.0 - np.std(residuals) / scale)
        else:
            fit_quality = 0.5
        confidence = min(0.9, 0.4 + 0.3 * fit_quality + 0.2 * min(1.0, n / 20))

        return (predicted_hours, confidence)
