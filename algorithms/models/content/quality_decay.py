"""
质量衰减模型 (Quality-Adjusted Decay)
融合内容质量评分与时间衰减的复合预测模型

核心：quality_score × 指数时间衰减 + 近期速度趋势
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class QualityDecayAlgorithm(BaseAlgorithm):
    """质量衰减"""

    name = "质量衰减"
    algorithm_id = "quality_decay"
    description = "内容质量分+时间衰减复合预测"
    category = "内容感知"
    default_weight = 1.0

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 8 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "quality_decay_fallback"}, timestamp=datetime.now(),
            )

        try:
            views = np.array([h.get("view_count", 0) for h in history[-40:]], dtype=np.float64)
            n = len(views)

            quality = self.get_quality_score(video_data)
            engagement = self.get_engagement_rate(video_data)
            age_hours = self.get_video_age_hours(video_data)

            # 质量加权的指数衰减
            base_decay_rate = 1.0 / max(age_hours, 1) if age_hours > 0 else 0.01
            quality_decay_rate = base_decay_rate / (0.3 + 0.7 * quality)

            # 质量折扣因子: 高质量视频衰减缓
            quality_factor = 0.4 + 0.6 * quality

            # 近期速度趋势
            if n >= 5:
                recent_diffs = np.diff(views[-min(10, n):])
                recent_growth = np.mean(recent_diffs)
                trend_accel = recent_diffs[-1] - recent_diffs[-2] if len(recent_diffs) >= 2 else 0
            else:
                recent_growth = velocity * 3600
                trend_accel = 0

            # 复合预测: 质量×衰减 + 速度趋势
            time_factor = np.exp(-quality_decay_rate * 24)  # 24小时后衰减倍率
            base_growth = velocity * 3600 * quality_factor * time_factor
            trend_growth = recent_growth * (1 + 0.2 * np.tanh(trend_accel / max(recent_growth, 1)))
            growth = 0.6 * base_growth + 0.4 * trend_growth

            predicted_velocity = max(0, growth / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
            confidence = max(0.1, min(0.85, 0.3 + 0.3 * quality + 0.02 * min(n, 25)))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={
                    "method": "quality_decay",
                    "quality": round(float(quality), 3),
                    "decay_rate": round(float(quality_decay_rate), 5),
                    "age_hours": round(float(age_hours), 1),
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
                metadata={"method": "quality_decay_error"}, timestamp=datetime.now(),
            )
