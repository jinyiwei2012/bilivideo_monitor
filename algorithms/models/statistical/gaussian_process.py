"""
高斯过程回归 (Gaussian Process Regression)
概率预测方法，输出预测值+不确定度

优先使用 sklearn GaussianProcessRegressor，不可用时回退 numpy 简化版
"""

import logging
import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_SKLEARN = False
try:
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, WhiteKernel

    _HAS_SKLEARN = True
except ImportError:
    pass


class GaussianProcessAlgorithm(BaseAlgorithm):
    """高斯过程回归"""

    name = "高斯过程"
    algorithm_id = "gaussian_process"
    description = "概率高斯过程回归，输出点预测+不确定性"
    category = "统计模型"
    default_weight = 1.3

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 8:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "gp_fallback"}, timestamp=datetime.now(),
            )

        if _HAS_SKLEARN and len(history) >= 15:
            try:
                result = self._sklearn_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("GP sklearn failed: %s", e)

        return self._numpy_predict(video_data, threshold)

    def _sklearn_predict(self, video_data, threshold):
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)
        history = video_data.get("history_data", [])

        views = np.array([h.get("view_count", 0) for h in history[-30:]], dtype=np.float64)
        n = len(views)
        X = np.arange(n).reshape(-1, 1)

        kernel = RBF(length_scale=3.0) + WhiteKernel(noise_level=0.1)
        gp = GaussianProcessRegressor(kernel=kernel, normalize_y=True, n_restarts_optimizer=3)
        gp.fit(X, views)

        X_pred = np.arange(n, n + 10).reshape(-1, 1)
        y_pred, y_std = gp.predict(X_pred, return_std=True)

        growth = np.mean(np.diff(y_pred)) if len(y_pred) >= 2 else velocity * 3600
        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity
            uncertainty = float(np.mean(y_std)) / max(float(np.mean(y_pred)), 1)
            confidence = max(0.1, min(0.9, 0.7 / (1 + uncertainty * 3)))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={"method": "gp_sklearn", "uncertainty": round(uncertainty, 4)},
            timestamp=datetime.now(),
        )

    def _numpy_predict(self, video_data, threshold):
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)
        history = video_data.get("history_data", [])

        views = np.array([h.get("view_count", 0) for h in history[-20:]], dtype=np.float64)
        n = len(views)

        # 简化 GP: RBF协方差→加权平均
        x = np.arange(n)
        rbf = np.exp(-0.5 * ((x[:, None] - x[None, :]) / (n / 4)) ** 2)
        rbf += np.eye(n) * 0.1
        try:
            alpha = np.linalg.solve(rbf, views)
        except np.linalg.LinAlgError:
            alpha = views

        # 预测
        x_pred = np.arange(n + 5)
        k_star = np.exp(-0.5 * ((x_pred[:, None] - x[None, :]) / (n / 4)) ** 2)
        y_pred = k_star @ alpha
        growth = np.mean(np.diff(y_pred[-5:])) if n >= 5 else velocity * 3600

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 and predicted_velocity > 0 else float("inf")
        confidence = min(0.85, 0.35 + 0.02 * min(n, 20))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={"method": "gp_numpy", "data_points": n}, timestamp=datetime.now(),
        )
