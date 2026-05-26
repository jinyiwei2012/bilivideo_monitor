"""
NARX (Nonlinear AutoRegressive with eXogenous inputs)
带外生输入的非线性自回归模型，引入互动数据（点赞、投币、分享）作为外生变量
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


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
