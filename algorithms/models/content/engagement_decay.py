"""
互动衰减建模 (Engagement Decay Model)
建模视频互动率（点赞/播放、弹幕/播放）随时间的衰减曲线

核心：互动率指数衰减拟合 → 推断视频所处生命周期阶段 → 调整预测
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class EngagementDecayAlgorithm(BaseAlgorithm):
    """互动衰减"""

    name = "互动衰减"
    algorithm_id = "engagement_decay"
    description = "互动率衰减曲线拟合，推断视频生命周期阶段"
    category = "内容感知"
    default_weight = 1.1

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 10 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "decay_fallback"}, timestamp=datetime.now(),
            )

        try:
            views = np.array([h.get("view_count", 0) for h in history[-40:]], dtype=np.float64)
            likes = np.array([h.get("like_count", 0) for h in history[-40:]], dtype=np.float64)
            n = len(views)

            # 计算互动率序列
            engagement = likes / np.maximum(views, 1)
            x = np.arange(n)

            # 指数衰减拟合: eng = a * exp(-lambda * t) + c
            try:
                valid = engagement > 0
                if np.sum(valid) >= 5:
                    log_eng = np.log(engagement[valid] - np.min(engagement[valid]) + 1e-10)
                    coeff = np.polyfit(x[valid], log_eng, 1)
                    decay_rate = -coeff[0]
                else:
                    decay_rate = 0.01
            except Exception:
                decay_rate = 0.01

            # 生命周期阶段判定
            if decay_rate < -0.02:
                stage = "growth"  # 互动率上升
                stage_factor = 1.3
            elif decay_rate < 0.005:
                stage = "mature"  # 稳定
                stage_factor = 1.0
            elif decay_rate < 0.02:
                stage = "decline_slow"  # 缓慢衰减
                stage_factor = 0.7
            else:
                stage = "decline_fast"  # 快速衰减
                stage_factor = 0.4

            growth = velocity * 3600 * stage_factor
            predicted_velocity = max(0, growth / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
            confidence = max(0.1, min(0.85, 0.3 + 0.1 * min(stage_factor, 3) + 0.02 * min(n, 25)))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={
                    "method": "engagement_decay",
                    "decay_rate": round(float(decay_rate), 4),
                    "stage": stage,
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
                metadata={"method": "decay_error"}, timestamp=datetime.now(),
            )
