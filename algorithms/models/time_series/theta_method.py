"""
Theta方法 (Theta Method)
经典时间序列预测方法，M3竞赛亚军

核心：对时序做二阶差分（Theta线），线性外推趋势
简洁但效果超越许多复杂模型
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class ThetaMethodAlgorithm(BaseAlgorithm):
    """Theta方法"""

    name = "Theta方法"
    algorithm_id = "theta_method"
    description = "经典Theta线趋势外推，M3竞赛亚军"
    category = "时间序列"
    default_weight = 1.2

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 5 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "theta_fallback"}, timestamp=datetime.now(),
            )

        try:
            views = np.array([h.get("view_count", 0) for h in history[-30:]], dtype=np.float64)
            n = len(views)

            # Theta=2: 对时序做二阶差分得到Theta线
            theta = 2.0
            x = np.arange(n)
            diff2 = np.diff(views, 2)
            if len(diff2) >= 3:
                theta_line = np.cumsum(np.cumsum(np.insert(diff2, 0, [diff2[0], diff2[0]])))
                if len(theta_line) < n:
                    theta_line = np.pad(theta_line, (0, n - len(theta_line)), 'edge')
                theta_line = theta_line[:n]
                seasonal = views - theta_line
            else:
                theta_line = np.polyval(np.polyfit(x, views, 1), x)
                seasonal = views - theta_line

            # 季节调整：用最后半个周期的平均值
            half_period = max(2, n // 4)
            season_mean = np.mean(seasonal[-half_period:])

            # 趋势外推
            trend_slope = np.polyfit(x, theta_line, 1)[0]
            future = theta_line[-1] + trend_slope * np.arange(1, 11)
            future_adjusted = future + season_mean

            growth = np.mean(np.diff(future_adjusted))
            predicted_velocity = max(0, growth / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 and predicted_velocity > 0 else float("inf")
            confidence = min(0.85, 0.35 + 0.02 * min(n, 25))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={"method": "theta_method", "theta": theta, "data_points": n},
                timestamp=datetime.now(),
            )
        except Exception:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "theta_error"}, timestamp=datetime.now(),
            )
