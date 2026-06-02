"""
热搜趋势检测 (Hot Trend Detection)
检测播放量是否处于"热搜加速"状态，识别正向趋势拐点

核心：二阶导数符号变化 + 加速度持续性 + 加速比
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class HotTrendAlgorithm(BaseAlgorithm):
    """热搜趋势"""

    name = "热搜趋势"
    algorithm_id = "hot_trend"
    description = "二阶导数拐点检测+加速度持续判断，识别趋势加速"
    category = "事件驱动"
    default_weight = 1.1

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 12 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "hot_trend_fallback"}, timestamp=datetime.now(),
            )

        try:
            views = np.array([h.get("view_count", 0) for h in history[-40:]], dtype=np.float64)
            n = len(views)

            diffs = np.diff(views)
            if len(diffs) < 8:
                growth = velocity * 3600
            else:
                # 一阶差分（速度）
                v1 = diffs
                # 二阶差分（加速度）
                v2 = np.diff(v1)
                # 三阶差分（加加速度/急动度）
                v3 = np.diff(v2) if len(v2) >= 2 else np.zeros(len(v2))

                # 加速度持续性检测
                recent_v2 = v2[-min(5, len(v2)):]
                accel_positive = np.sum(recent_v2 > 0)
                accel_persistent = accel_positive / max(len(recent_v2), 1)

                # 趋势强度
                current_vel = np.mean(v1[-3:]) if len(v1) >= 3 else np.mean(v1)
                recent_accel = np.mean(recent_v2)
                jerk = np.mean(v3[-2:]) if len(v3) >= 2 else 0

                # 趋势判定
                if accel_persistent > 0.6 and recent_accel > 0:
                    # 加速中: 二次外推
                    trend_factor = 1.0 + 0.3 * accel_persistent + 0.1 * min(jerk, 5)
                    growth = max(0, current_vel * trend_factor)
                elif accel_persistent < 0.3:
                    # 减速中: 保守估计
                    growth = max(0, current_vel * 0.7)
                else:
                    growth = current_vel

            predicted_velocity = max(0, growth / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
            confidence = max(0.1, min(0.85, 0.3 + 0.3 * accel_persistent + 0.02 * min(n, 25)))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={
                    "method": "hot_trend",
                    "accel_persist": round(float(accel_persistent), 3),
                    "jerk": round(float(jerk), 3),
                },
                timestamp=datetime.now(),
            )
        except Exception:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "hot_trend_error"}, timestamp=datetime.now(),
            )
