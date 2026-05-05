"""
指数增长预测模型
适用于早期快速增长的视频，假设增长速度与当前播放量成正比
"""

import math
import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class ExponentialGrowthAlgorithm(BaseAlgorithm):
    """指数增长模型 (Exponential Growth)

    假设播放量增长速度与当前播放量成正比：
    dV/dt = r * V

    解为 V(t) = V₀ * exp(r * t)

    适合视频发布初期的快速增长阶段（前几周），
    此时推荐算法带来的曝光与播放量正相关。

    注意：指数增长不能长期持续，模型内置了衰减机制。
    """

    name = "指数增长"
    algorithm_id = "exponential_growth"
    description = "早期快速增长模型，增速与播放量成正比"
    category = "增长模型"
    default_weight = 1.1

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=0,
                confidence=1.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "exponential"},
                timestamp=datetime.now(),
            )

        if len(history) < 3 or velocity <= 0 or current_views <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.3,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "exponential", "notes": "insufficient_data"},
                timestamp=datetime.now(),
            )

        # 提取时序
        timestamps = []
        views_vals = []
        for h in history:
            ts = h.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))

        if len(views_vals) < 3:
            predicted_hours = remaining / velocity
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.3,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "exponential_fallback"},
                timestamp=datetime.now(),
            )

        try:
            order = np.argsort(timestamps)
            views_arr = np.array(views_vals, dtype=float)[order]
            n = len(views_arr)

            quality = self.get_quality_score(video_data)
            age_hours = self.get_video_age_hours(video_data)

            # ── 估计增长率 r ─────────────────────────
            # V(t) = V₀ * exp(r * t)
            # ln(V(t)) = ln(V₀) + r * t
            log_v = np.log(np.maximum(views_arr, 1))
            t = np.arange(n, dtype=float)

            # 用最近数据估计增长率（更敏感）
            recent_n = max(3, n // 2)
            recent_log_v = log_v[-recent_n:]
            recent_t = t[-recent_n:] - t[-recent_n]

            slope, intercept = np.polyfit(recent_t, recent_log_v, 1)
            r = max(0.0, slope)  # 增长率

            # 如果 r 很小或为负，回退到速度法
            if r < 0.001:
                r = velocity / max(current_views, 1)
                # 使用自然衰减
                r = max(0.001, r)

            # ── 预测衰减 ─────────────────────────────
            # 指数增长不能长期持续，随时间逐渐衰减到线性增长
            # 半衰期: 与质量分和视频年龄相关
            half_life_hours = 72 + 48 * quality  # 3-5天
            decay_rate = math.log(2) / half_life_hours

            # ── 预测 ─────────────────────────────────
            # 使用积分: dV/dt = r * V * exp(-decay * t)
            # 但没有解析解，用数值积分
            pred_views = float(current_views)
            target_hour = None
            max_hours = min(8760, max(24, int(remaining / max(velocity, 0.1) * 2)))

            dt = 1.0  # 1小时间隔

            for hour in range(1, int(max_hours) + 1):
                # 有效增长率（随时间衰减）
                effective_r = r * math.exp(-decay_rate * hour)

                # 指数增长: dV = r * V * dt
                delta = effective_r * pred_views * dt
                pred_views += max(0, delta)

                if pred_views >= threshold:
                    target_hour = hour
                    break

            if target_hour is not None and target_hour <= max_hours:
                predicted_hours = target_hour
                data_qual = min(1.0, n / 12)
                r_qual = min(1.0, r * 100)

                # 早期视频（<1周）指数模型置信度高
                early_bonus = max(0.0, 0.2 * (1.0 - min(age_hours / 168.0, 1.0)))

                conf = min(0.9, 0.3 + 0.2 * data_qual + 0.15 * r_qual + 0.1 * quality + early_bonus)
            else:
                predicted_hours = remaining / velocity
                conf = 0.3

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=conf,
                current_views=current_views,
                current_velocity=velocity,
                metadata={
                    "method": "exponential",
                    "growth_rate_r": round(float(r), 6),
                    "half_life_hours": round(float(half_life_hours), 1),
                    "effective_r_at_24h": round(float(r * math.exp(-decay_rate * 24)), 6),
                    "data_points": n,
                },
                timestamp=datetime.now(),
            )
        except Exception as e:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"error": str(e)},
                timestamp=datetime.now(),
            )
