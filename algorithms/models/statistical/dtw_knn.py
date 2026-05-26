"""
DTW-kNN (Dynamic Time Warping k-Nearest Neighbors)
用DTW距离从历史数据中检索增长模式相似的视频，加权平均预测
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

try:
    from scipy.spatial.distance import euclidean
    from scipy.spatial.distance import cdist
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


def _dtw_distance(s1, s2):
    """动态时间规整距离"""
    n, m = len(s1), len(s2)
    dtw = np.full((n + 1, m + 1), np.inf)
    dtw[0, 0] = 0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = abs(s1[i - 1] - s2[j - 1])
            dtw[i, j] = cost + min(dtw[i - 1, j], dtw[i, j - 1], dtw[i - 1, j - 1])
    return dtw[n, m] / max(n, m)


class DtwKnnAlgorithm(BaseAlgorithm):
    """DTW-kNN 动态时间规整类比预测"""

    name = "DTW-kNN类比"
    algorithm_id = "dtw_knn"
    description = "用DTW距离检索相似增长模式，加权平均预测"
    category = "统计模型"
    default_weight = 1.2

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if not _HAS_SCIPY or len(history) < 5 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            likes = np.array([h.get("like", 0) for h in history], dtype=np.float64)
            coins = np.array([h.get("coin", 0) for h in history], dtype=np.float64)

            profile = np.column_stack([
                np.gradient(views),
                np.gradient(likes),
                np.gradient(coins),
            ])

            segments = []
            n = min(6, len(profile) // 2)
            if n < 2:
                n = 2
            for i in range(0, len(profile) - n, n // 2):
                seg = profile[i:i + n]
                if len(seg) == n:
                    segments.append((i, seg))

            if len(segments) < 2:
                return self._fallback(velocity, current_views, threshold)

            query = segments[-1][1]
            distances = []
            for start, seg in segments[:-1]:
                d = _dtw_distance(query.flatten(), seg.flatten())
                distances.append((d, start, seg))

            distances.sort(key=lambda x: x[0])
            k = min(3, len(distances))

            if k == 0 or distances[0][0] < 1e-10:
                return self._fallback(velocity, current_views, threshold)

            weights = np.array([1.0 / max(d[0], 1e-10) for d in distances[:k]])
            weights /= weights.sum()

            future_velocities = []
            for idx, (d, start, seg) in enumerate(distances[:k]):
                end_idx = start + n
                if end_idx + 3 <= len(views):
                    future = views[end_idx:end_idx + 3]
                    if len(future) >= 2:
                        fv = np.mean(np.diff(future))
                        future_velocities.append(fv)

            predicted_velocity = velocity
            if future_velocities:
                predicted_velocity = max(0, np.average(future_velocities, weights=weights[:len(future_velocities)]))

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / max(predicted_velocity, 1)
                confidence = min(0.9, 0.5 + 0.1 * k)

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "dtw_knn", "k": k, "min_dist": float(distances[0][0])},
                timestamp=datetime.now(),
            )
        except Exception as e:
            return self._fallback(velocity, current_views, threshold)

    def _fallback(self, velocity, current_views, threshold):
        if velocity <= 0:
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=float("inf"),
                confidence=0.0, current_views=current_views, current_velocity=velocity,
                metadata={"method": "dtw_knn", "reason": "fallback"},
                timestamp=datetime.now(),
            )
        remaining = threshold - current_views
        predicted_hours = remaining / velocity if remaining > 0 else 0
        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=0.3, current_views=current_views, current_velocity=velocity,
            metadata={"method": "dtw_knn", "reason": "fallback"},
            timestamp=datetime.now(),
        )
