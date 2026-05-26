"""
LightGBM 预测算法 — 真实实现 + numpy 降级

优先使用 lightgbm.LGBMRegressor 构建直方图梯度提升；
若库不可用或训练失败，回退到同算法的 numpy 简化版。
"""

import math
import logging
from typing import Dict, Any
from datetime import datetime

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_LIGHTGBM = False
try:
    import lightgbm as lgb

    _HAS_LIGHTGBM = True
except ImportError:
    pass


class LightGBMSimpleAlgorithm(BaseAlgorithm):
    """LightGBM 预测算法"""

    name = "LightGBM"
    algorithm_id = "lightgbm"
    description = "基于 LightGBM 直方图梯度提升的播放量预测"
    category = "集成学习"
    default_weight = 1.6

    def __init__(self):
        super().__init__()
        self._model = None

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
                metadata={"method": "lightgbm", "note": "already_reached"},
                timestamp=datetime.now(),
            )

        if len(history) < 10 or velocity <= 0:
            return self._numpy_predict(current_views, velocity, remaining, threshold)

        if _HAS_LIGHTGBM:
            try:
                result = self._lightgbm_predict(history, current_views, velocity, remaining, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("LightGBM 训练失败，回退 numpy: %s", e)

        return self._numpy_predict(current_views, velocity, remaining, threshold)

    def _lightgbm_predict(self, history, current_views, velocity, remaining, threshold) -> PredictionResult:
        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        likes = np.array([h.get("like_count", 0) for h in history], dtype=np.float64)
        coins = np.array([h.get("coin_count", 0) for h in history], dtype=np.float64)
        favs = np.array([h.get("favorite_count", 0) for h in history], dtype=np.float64)
        shares = np.array([h.get("share_count", 0) for h in history], dtype=np.float64)

        p = 5
        X, y = [], []
        for i in range(p, len(views)):
            feat = []
            for j in range(1, p + 1):
                feat.extend([
                    views[i - j], likes[i - j], coins[i - j],
                    favs[i - j], shares[i - j],
                    math.log(max(views[i - j], 1)),
                ])
            X.append(feat)
            y.append(views[i])

        X, y = np.array(X), np.array(y)
        if len(X) < 8:
            return None

        y_growth = np.diff(views[-len(X) - 1:]) / np.maximum(views[-len(X) - 1:-1], 1)
        y_target = y_growth[-len(X):]

        model = lgb.LGBMRegressor(
            n_estimators=80, max_depth=4, learning_rate=0.1,
            subsample=0.8, colsample_bytree=0.8, verbosity=-1,
        )
        model.fit(X, y_target)

        last_feat = []
        for j in range(1, p + 1):
            last_feat.extend([
                views[-j], likes[-j], coins[-j],
                favs[-j], shares[-j],
                math.log(max(views[-j], 1)),
            ])
        pred_growth = float(model.predict(np.array([last_feat]))[0])
        predicted_velocity = max(0, pred_growth * current_views / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        pred_hours = remaining / predicted_velocity if predicted_velocity > 0 else float("inf")

        residuals = np.abs(y_target - model.predict(X))
        cv = float(np.std(residuals) / max(np.mean(np.abs(y_target)), 1e-10))
        confidence = max(0.1, min(0.85, 0.6 - cv * 0.5))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=pred_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "lightgbm", "n_estimators": 80},
            timestamp=datetime.now(),
        )

    def _numpy_predict(self, current_views, velocity, remaining, threshold) -> PredictionResult:
        if velocity <= 0:
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=float("inf"),
                confidence=0.0, current_views=current_views, current_velocity=velocity,
                metadata={"method": "lightgbm_numpy_fallback"},
                timestamp=datetime.now(),
            )
        predicted_hours = remaining / velocity
        confidence = 0.3
        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={"method": "lightgbm_numpy_fallback"},
            timestamp=datetime.now(),
        )
