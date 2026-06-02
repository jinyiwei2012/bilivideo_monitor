"""
病毒传播评分 (Virality Score)
基于播放量增速+互动率+分享比率计算病毒传播潜力评分

核心：多维度加权评分 → 映射到预测加速因子
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class ViralityScoreAlgorithm(BaseAlgorithm):
    """病毒传播评分"""

    name = "病毒传播"
    algorithm_id = "virality_score"
    description = "多维传播潜力评分，预测病毒式增长概率"
    category = "内容感知"
    default_weight = 1.1

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
                metadata={"method": "viral_fallback"}, timestamp=datetime.now(),
            )

        try:
            views = np.array([h.get("view_count", 0) for h in history[-30:]], dtype=np.float64)
            likes = np.array([h.get("like_count", 0) for h in history[-30:]], dtype=np.float64)
            coins = np.array([h.get("coin_count", 0) for h in history[-30:]], dtype=np.float64)
            shares = np.array([h.get("share_count", 0) for h in history[-30:]], dtype=np.float64)
            favs = np.array([h.get("favorite_count", 0) for h in history[-30:]], dtype=np.float64)

            n = len(views)

            # 维度1: 播放量增速
            recent_views = views[-min(8, n):]
            view_growth = np.mean(np.diff(recent_views)) / max(np.mean(recent_views[:-1]), 1) if len(recent_views) >= 2 else 0
            view_score = min(1.0, max(0, view_growth * 20))

            # 维度2: 互动率
            engagement = (likes + coins * 2 + favs * 3) / np.maximum(views, 1)
            recent_eng = engagement[-min(5, n):]
            eng_score = min(1.0, np.mean(recent_eng) * 20)

            # 维度3: 分享率
            share_rate = shares / np.maximum(views, 1)
            share_score = min(1.0, np.mean(share_rate[-min(5, n):]) * 50)

            # 维度4: 加速度
            if n >= 6:
                vel = np.diff(views)
                accel = np.diff(vel[-min(6, len(vel)):])
                accel_score = min(1.0, max(0, np.mean(accel) / max(abs(np.mean(accel)), 1e-10)) * 0.5 + 0.5)
            else:
                accel_score = 0.5

            # 综合病毒传播评分
            w_view, w_eng, w_share, w_accel = 0.3, 0.35, 0.15, 0.2
            virality = w_view * view_score + w_eng * eng_score + w_share * share_score + w_accel * accel_score

            # 映射到加速因子 [0.5, 2.5]
            boost = 0.5 + 2.0 * virality
            growth = velocity * 3600 * boost

            predicted_velocity = max(0, growth / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
            confidence = max(0.1, min(0.85, 0.3 + 0.4 * virality + 0.02 * min(n, 25)))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={
                    "method": "virality_score",
                    "virality": round(float(virality), 3),
                    "boost": round(float(boost), 2),
                    "scores": {
                        "view": round(float(view_score), 2),
                        "engagement": round(float(eng_score), 2),
                        "share": round(float(share_score), 2),
                        "accel": round(float(accel_score), 2),
                    },
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
                metadata={"method": "viral_error"}, timestamp=datetime.now(),
            )
