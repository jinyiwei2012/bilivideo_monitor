"""
指数增长预测模型模块

该模块实现基于指数增长（Exponential Growth）的播放量预测算法。
指数增长模型假设视频播放量的增长速度与当前播放量成正比，即"越火越火"的复合增长效应。

核心公式：
    dV/dt = r * V
    解：V(t) = V₀ * exp(r * t)

其中：
    - V(t): 时间t时的播放量
    - V₀:    初始播放量
    - r:     增长率参数（通过对数线性回归从历史数据估计）

模型特点：
    1. 适合视频发布初期的快速增长阶段（通常前几周）
    2. 此时推荐算法带来的曝光与播放量形成正反馈循环
    3. 指数增长不能长期持续，模型内置了衰减机制（半衰期3-5天）
    4. 通过随时间衰减的增长率来模拟热度自然消退

算法流程：
    1. 提取历史时序数据，用最近数据做对数线性回归估计增长率r
    2. 根据视频质量分计算衰减半衰期（3-5天）
    3. 数值迭代模拟：每天增长率按指数衰减，累计播放量
    4. 找到首次达到目标阈值的模拟时间点
    5. 早期视频置信度有加成，随时间递减

适用场景：发布初期、播放量正在快速增长的新视频
局限性：对已过增长期的视频预测过于乐观

所属分类：增长模型类（category = "增长模型"）
"""

import math
import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class ExponentialGrowthAlgorithm(BaseAlgorithm):
    """指数增长模型 (Exponential Growth) 预测算法

    假设播放量增长速度与当前播放量成正比：
        dV/dt = r * V

    解为 V(t) = V₀ * exp(r * t)

    适合视频发布初期的快速增长阶段（前几周），
    此时推荐算法带来的曝光与播放量正相关。

    注意：指数增长不能长期持续，模型内置了衰减机制，
    增长率随时间指数衰减来模拟热度的自然消退。

    类属性：
        name: 算法中文名称
        algorithm_id: 算法唯一标识符
        description: 算法简要描述
        category: 算法分类标签
        default_weight: 集成预测中的默认权重
    """

    name = "指数增长"
    algorithm_id = "exponential_growth"
    description = "早期快速增长模型，增速与播放量成正比"
    category = "增长模型"
    default_weight = 1.1

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行指数增长预测

        使用指数增长模型预测视频播放量达到目标阈值所需的时间。
        模型通过历史数据的对数线性回归估计增长率r，
        并内置衰减机制模拟热度的自然消退。

        Args:
            video_data: 视频数据字典，必须包含以下字段：
                - view_count (int): 当前播放量
                - history_data (list): 历史数据列表，每条包含：
                    - view_count (int): 该时刻的播放量
                    - timestamp (str/datetime/timestamp): 时间戳
            threshold: 目标播放量阈值，默认为 100000（10万播放）

        Returns:
            PredictionResult: 预测结果对象，包含：
                - predicted_hours: 预测到达阈值所需的小时数
                - confidence: 置信度 (0.0 ~ 0.9)，
                  基于数据质量、增长率大小、视频质量和早期加成
                - metadata: 包含增长率r、半衰期、24小时后有效增长率等诊断信息
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            # 已达到目标阈值，预测时间0，完全置信
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

        # 数据不足时的回退方案：使用速度法
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

        # 提取时序数据：时间戳和播放量
        timestamps = []
        views_vals = []
        for h in history:
            ts = h.get("timestamp", 0)
            # 处理多种时间戳格式：datetime对象、字符串、数值
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(str(ts)[:19].replace("T", " ")).timestamp()
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
            # 按时间戳排序，确保时序正确
            order = np.argsort(timestamps)
            views_arr = np.array(views_vals, dtype=float)[order]
            n = len(views_arr)

            quality = self.get_quality_score(video_data)
            age_hours = self.get_video_age_hours(video_data)

            # ── 估计增长率 r ─────────────────────────
            # V(t) = V₀ * exp(r * t)
            # 取对数：ln(V(t)) = ln(V₀) + r * t
            # 对ln(V)进行线性回归来估计r
            log_v = np.log(np.maximum(views_arr, 1))  # 防止log(0)
            t = np.arange(n, dtype=float)

            # 只使用最近一半数据进行回归，使估计对近期变化更敏感
            recent_n = max(3, n // 2)
            recent_log_v = log_v[-recent_n:]
            recent_t = t[-recent_n:] - t[-recent_n]  # 从0开始重新编号

            # 线性最小二乘拟合 ln(V) = intercept + slope * t
            slope, intercept = np.polyfit(recent_t, recent_log_v, 1)
            r = max(0.0, slope)  # 增长率（确保非负）

            # 如果回归得到的增长率极小或为负，使用速度法估计一个正向增长率
            if r < 0.001:
                r = velocity / max(current_views, 1)
                r = max(0.001, r)  # 确保最小增长率为0.001

            # ── 预测衰减 ─────────────────────────────
            # 指数增长不能长期持续，增长率随时间指数衰减
            # 半衰期与质量分和视频年龄相关，质量越高衰减越慢
            quality = max(0.1, min(1.0, quality))
            half_life_hours = 72 + 48 * quality  # 3-5天的半衰期范围

            # 衰减系数：λ = ln(2) / 半衰期
            decay_rate = math.log(2) / half_life_hours

            # ── 数值预测 ─────────────────────────────
            # 使用数值迭代模拟，每步1小时
            # dV/dt = r * V * exp(-decay_rate * t)
            # 因为增长率指数衰减，无简单解析解，采用数值积分
            pred_views = float(current_views)
            target_hour = None
            max_hours = min(8760, max(24, int(remaining / max(velocity, 0.1) * 2)))

            dt = 1.0  # 模拟时间步长：1小时

            for hour in range(1, int(max_hours) + 1):
                # 当前时刻的有效增长率 = 初始增长率 * 指数衰减因子
                effective_r = r * math.exp(-decay_rate * hour)

                # 指数增长步进：ΔV = r * V * Δt
                delta = effective_r * pred_views * dt
                pred_views += max(0, delta)

                if pred_views >= threshold:
                    target_hour = hour
                    break

            if target_hour is not None and target_hour <= max_hours:
                predicted_hours = target_hour
                # 数据质量分：数据点越多越好（12条以上满分）
                data_qual = min(1.0, n / 12)
                # 增长率质量分：r越大说明增长越明显
                r_qual = min(1.0, r * 100)

                # 早期视频（<1周）指数模型置信度有加成
                # 因为指数增长模型最适合早期快速增长阶段
                early_bonus = max(0.0, 0.2 * (1.0 - min(age_hours / 168.0, 1.0)))

                # 综合置信度 = 基础分 + 数据质量分 + 增长率分 + 质量分 + 早期加成
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
            # 异常处理：回退到速度法
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
