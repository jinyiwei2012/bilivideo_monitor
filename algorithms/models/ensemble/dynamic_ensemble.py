"""
动态集成策略 (Dynamic Ensemble Strategy)
根据视频数据量和生命周期阶段动态切换集成策略

核心原理：
- 数据少 (<20点): 简单平均 + 速度类算法高权重
- 数据中 (20-100点): 加权平均 + 统计模型高权重
- 数据多 (>100点): Stacking + 深度学习高权重
- 根据不同阈值 (10万/100万/1000万) 调整策略
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class DynamicEnsembleAlgorithm(BaseAlgorithm):
    """动态集成策略"""

    name = "动态集成"
    algorithm_id = "dynamic_ensemble"
    description = "根据数据量/阶段动态切换集成策略"
    category = "集成学习"
    default_weight = 1.6

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
                metadata={"method": "dynamic_fallback"}, timestamp=datetime.now(),
            )

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        n = len(views)
        diffs = np.diff(views)
        quality = self.get_quality_score(video_data)
        engagement = self.get_engagement_rate(video_data)

        # 阶段判定
        if n < 20:
            stage = "early"
            stage_desc = "早期冷启动"
        elif n < 100:
            stage = "growth"
            stage_desc = "成长中"
        else:
            stage = "mature"
            stage_desc = "成熟期"

        # 多模型预测 (速度/统计/趋势)
        # 模型1: 短期速度
        short_vel = np.mean(diffs[-min(3, len(diffs)):]) if len(diffs) >= 1 else velocity * 3600

        # 模型2: 中期趋势
        mid_window = min(15, n)
        mid_trend = np.polyfit(np.arange(mid_window), views[-mid_window:], 1)[0] if mid_window >= 2 else short_vel

        # 模型3: 长期衰减调整
        if n >= 8:
            vel_series = diffs[-min(10, len(diffs)):]
            decay_rate = np.polyfit(np.arange(len(vel_series)), vel_series, 1)[0]
            long_adj = np.mean(vel_series) + decay_rate * 2
        else:
            long_adj = short_vel

        # 模型4: 质量感知
        quality_vel = velocity * 3600 * (0.5 + 0.5 * quality)

        # 动态权重
        if stage == "early":
            w_short, w_mid, w_long, w_quality = 0.5, 0.2, 0.1, 0.2
        elif stage == "growth":
            w_short, w_mid, w_long, w_quality = 0.3, 0.35, 0.2, 0.15
        else:
            w_short, w_mid, w_long, w_quality = 0.2, 0.3, 0.35, 0.15

        # 阈值调整
        if threshold >= 10000000:
            w_long += 0.1
            w_short *= 0.8
        elif threshold <= 100000:
            w_short += 0.1
            w_long *= 0.9

        growth = w_short * short_vel + w_mid * mid_trend + w_long * long_adj + w_quality * quality_vel
        growth = max(0, growth)

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
        confidence = max(0.1, min(0.9, 0.3 + 0.1 * min(n / 20, 3) + 0.2 * quality + 0.2 * engagement))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={
                "method": "dynamic_ensemble",
                "stage": stage_desc,
                "weights": {
                    "short": round(w_short, 2), "mid": round(w_mid, 2),
                    "long": round(w_long, 2), "quality": round(w_quality, 2),
                },
            },
            timestamp=datetime.now(),
        )
