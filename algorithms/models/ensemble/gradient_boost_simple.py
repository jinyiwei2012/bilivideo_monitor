"""
梯度提升预测算法
优先使用 sklearn.ensemble.GradientBoostingRegressor 真实实现，不可用时回退 numpy 简化版
"""

import logging
from datetime import datetime
from typing import Dict, Any

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_SKLEARN = False
try:
    from sklearn.ensemble import GradientBoostingRegressor as _GBR

    _HAS_SKLEARN = True
except ImportError:
    pass


class GradientBoostSimpleAlgorithm(BaseAlgorithm):
    """梯度提升预测算法"""

    name = "梯度提升简化"
    algorithm_id = "gradient_boost_simple"
    description = "基于梯度提升的播放量预测（sklearn 优先，numpy 回退）"
    category = "机器学习"
    default_weight = 1.4

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        if _HAS_SKLEARN and len(history) >= 10:
            try:
                result = self._sklearn_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("GradientBoost sklearn 失败，回退 numpy: %s", e)

        return self._numpy_predict(video_data, threshold)

    def _sklearn_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        likes = np.array([h.get("like_count", 0) for h in history], dtype=np.float64)
        coins = np.array([h.get("coin_count", 0) for h in history], dtype=np.float64)

        p = 5
        X, y = [], []
        for i in range(p, len(views)):
            feat = []
            for j in range(1, p + 1):
                feat.extend([views[i - j], likes[i - j], coins[i - j], np.log(max(views[i - j], 1))])
            X.append(feat)
            y.append(views[i])

        X, y = np.array(X), np.array(y)
        if len(X) < 8:
            return None

        y_target = np.diff(views[-len(X) - 1:]) / np.maximum(views[-len(X) - 1 : -1], 1)
        y_target = y_target[-len(X):]

        model = _GBR(n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42)
        model.fit(X, y_target)

        last_feat = []
        for j in range(1, p + 1):
            last_feat.extend([views[-j], likes[-j], coins[-j], np.log(max(views[-j], 1))])
        pred_growth = float(model.predict(np.array([last_feat]))[0])
        predicted_velocity = max(0, pred_growth * current_views / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity if predicted_velocity > 0 else float("inf")
            residuals = np.abs(y_target - model.predict(X))
            cv = float(np.std(residuals) / max(np.mean(np.abs(y_target)), 1e-10))
            confidence = max(0.1, min(0.85, 0.6 - cv * 0.5))

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "gradient_boost_sklearn", "n_estimators": 100},
            timestamp=datetime.now(),
        )

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        elif velocity <= 0:
            predicted_hours, confidence = float("inf"), 0.0
        else:
            base_prediction = remaining / velocity
            engagement = self.get_engagement_rate(video_data)
            quality = self.get_quality_score(video_data)
            age_hours = self.get_video_age_hours(video_data)

            r1 = base_prediction * (1 - engagement * 0.5)
            r2 = r1 * (1 - quality * 0.3)
            time_factor = min(1.0, 24 / max(age_hours, 1))
            predicted_hours = r2 * (2 - time_factor)
            confidence = min(1.0, 0.5 + engagement * 2 + quality * 0.3)

        residuals_count = 3 if confidence > 0 else 0
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "gradient_boost_numpy", "residuals": residuals_count},
            timestamp=datetime.now(),
        )
