"""
NARX (Nonlinear AutoRegressive with eXogenous inputs)
优先使用 sklearn.linear_model 真实实现，不可用时回退 numpy 简化版
"""

import logging
import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_SKLEARN = False
try:
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import PolynomialFeatures

    _HAS_SKLEARN = True
except ImportError:
    pass


class NarxSimpleAlgorithm(BaseAlgorithm):
    """NARX 带外生输入自回归"""

    name = "NARX外生自回归"
    algorithm_id = "narx_simple"
    description = "带外生输入(点赞/投币/分享)的非线性自回归"
    category = "时间序列"
    default_weight = 1.1

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 6 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        if _HAS_SKLEARN and len(history) >= 10:
            try:
                result = self._sklearn_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("NARX sklearn 失败，回退 numpy: %s", e)

        return self._numpy_predict(video_data, threshold)

    def _sklearn_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        likes = np.array([h.get("like_count", 0) for h in history], dtype=np.float64)
        coins = np.array([h.get("coin_count", 0) for h in history], dtype=np.float64)
        favs = np.array([h.get("favorite_count", 0) for h in history], dtype=np.float64)

        v_diff = np.diff(views)
        l_diff = np.diff(likes)
        c_diff = np.diff(coins)
        f_diff = np.diff(favs)

        p = 4
        X, y = [], []
        for i in range(p, len(v_diff)):
            feat = []
            for j in range(p):
                feat.extend([v_diff[i - j - 1], l_diff[i - j - 1], c_diff[i - j - 1], f_diff[i - j - 1]])
            X.append(feat)
            y.append(v_diff[i])

        if len(X) < 5:
            return None

        X, y = np.array(X), np.array(y)
        poly = PolynomialFeatures(degree=2, include_bias=False)
        X_poly = poly.fit_transform(X)

        model = Ridge(alpha=1.0)
        model.fit(X_poly, y)

        last_feat = []
        for j in range(p):
            idx = len(v_diff) - 1 - j
            if idx >= 0:
                last_feat.extend([v_diff[idx], l_diff[idx], c_diff[idx], f_diff[idx]])
            else:
                last_feat.extend([0, 0, 0, 0])
        last_poly = poly.transform(np.array([last_feat]))
        pred_diff = float(model.predict(last_poly)[0])
        predicted_velocity = max(0, pred_diff / 3600)

        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity if predicted_velocity > 0 else float("inf")
            residuals = y - model.predict(X_poly)
            rmse = np.sqrt(np.mean(residuals**2))
            cv = float(rmse / max(np.mean(np.abs(y)), 1))
            confidence = max(0.1, min(0.85, 0.6 - cv))

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "narx_sklearn", "lag": p, "rmse": float(rmse)},
            timestamp=datetime.now(),
        )

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            likes = np.array([h.get("like", 0) for h in history], dtype=np.float64)
            coins = np.array([h.get("coin", 0) for h in history], dtype=np.float64)
            favorites = np.array([h.get("favorite", 0) for h in history], dtype=np.float64)

            v_diff = np.diff(views)
            l_diff = np.diff(likes)
            c_diff = np.diff(coins)
            f_diff = np.diff(favorites)

            p = 3
            X, y = [], []
            for i in range(p, len(v_diff)):
                feat = []
                for j in range(p):
                    feat.extend([v_diff[i - j], l_diff[i - j], c_diff[i - j], f_diff[i - j]])
                X.append(feat)
                y.append(v_diff[i])

            if len(X) < 3:
                return self._fallback(velocity, current_views, threshold)

            X, y = np.array(X), np.array(y)
            X = np.column_stack([np.ones(len(X)), X])

            try:
                theta = np.linalg.lstsq(X, y, rcond=None)[0]
            except np.linalg.LinAlgError:
                return self._fallback(velocity, current_views, threshold)

            last_feat = []
            for j in range(p):
                idx = len(v_diff) - 1 - j
                if idx >= 0:
                    last_feat.extend([v_diff[idx], l_diff[idx], c_diff[idx], f_diff[idx]])
                else:
                    last_feat.extend([0, 0, 0, 0])

            pred_diff = np.dot(np.array([1] + last_feat), theta)
            predicted_velocity = max(0, pred_diff / 3600)

            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                residuals = y - X @ theta
                rmse = np.sqrt(np.mean(residuals**2)) if len(residuals) > 0 else 1
                cv = rmse / max(np.mean(y), 1)
                confidence = max(0.1, min(0.85, 0.6 - cv))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "narx", "lag": p, "rmse": float(rmse) if "rmse" in dir() else 0},
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
                metadata={"method": "narx", "reason": "fallback"},
                timestamp=datetime.now(),
            )
        remaining = threshold - current_views
        predicted_hours = remaining / velocity if remaining > 0 else 0
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=0.3,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "narx", "reason": "fallback"},
            timestamp=datetime.now(),
        )
