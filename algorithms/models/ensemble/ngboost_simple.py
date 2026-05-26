"""
NGBoost (Natural Gradient Boosting)
输出完整概率分布的梯度提升，用自然梯度优化分布参数
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

_HAS_NGBOOST = False
try:
    from ngboost import NGBRegressor
    from ngboost.distns import Normal

    _HAS_NGBOOST = True
except ImportError:
    pass


class NgboostAlgorithm(BaseAlgorithm):
    """NGBoost 自然梯度提升"""

    name = "NGBoost"
    algorithm_id = "ngboost"
    description = "自然梯度提升，输出完整概率分布"
    category = "集成学习"
    default_weight = 1.2

    _model = None

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 10 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        if not _HAS_NGBOOST:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            likes = np.array([h.get("like", 0) for h in history], dtype=np.float64)
            coins = np.array([h.get("coin", 0) for h in history], dtype=np.float64)

            p = 4
            X, y = [], []
            for i in range(p, len(views)):
                X.append(
                    [views[i - j] for j in range(1, p + 1)]
                    + [likes[i - j] for j in range(1, p + 1)]
                    + [coins[i - j] for j in range(1, p + 1)]
                )
                y.append(views[i])

            if len(X) < 5:
                return self._fallback(velocity, current_views, threshold)

            X, y = np.array(X), np.array(y)
            y_pct = np.diff(views[-len(X) - 1 :]) / np.maximum(views[-len(X) - 1 : -1], 1)
            y_target = y_pct[-len(X) :]

            model = NGBRegressor(Dist=Normal, n_estimators=50, learning_rate=0.1, verbose=False)
            model.fit(X, y_target)

            last_X = np.array(
                [
                    [views[-j] for j in range(1, p + 1)]
                    + [likes[-j] for j in range(1, p + 1)]
                    + [coins[-j] for j in range(1, p + 1)]
                ]
            )

            pred_dist = model.pred_dist(last_X)
            mu = float(pred_dist.mean())
            sigma = float(np.sqrt(pred_dist.var))

            predicted_velocity = max(0, mu * views[-1] / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                cv = sigma / max(abs(mu), 1e-10)
                confidence = max(0.05, min(0.8, 0.6 - cv * 3))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "ngboost", "mu": float(mu), "sigma": float(sigma)},
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
                metadata={"method": "ngboost", "reason": "fallback"},
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
            metadata={"method": "ngboost", "reason": "fallback"},
            timestamp=datetime.now(),
        )
