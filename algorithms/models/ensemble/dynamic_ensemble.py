"""
动态集成策略 (Dynamic Ensemble Strategy) 模块
=============================================

本模块实现了动态集成预测算法，根据视频数据量和生命周期阶段自动切换集成策略。
核心思想来自"No Free Lunch"定理——没有单一策略在所有场景下最优。

算法来源：
    启发自"No Free Lunch"定理——没有单一策略在所有场景下最优。
    根据数据量（早期/成长期/成熟期）和阈值大小，动态调整 4 个子模型的
    融合权重。类似 AutoML 中根据数据特征自动选择模型的思想。

核心原理：
    - 数据少 (<20点): 简单平均 + 短期速度类高权重（冷启动友好）
    - 数据中 (20-100点): 加权平均 + 趋势类高权重（捕捉增长模式）
    - 数据多 (>100点): 长期衰减调整权重高（稳定预测）
    - 高阈值（>1000万）→ 增加长期预测权重；低阈值（≤10万）→ 增加短期权重

4 个子模型：
    1. 短期速度：最近 3 点平均增量（对最新变化最敏感）
    2. 中期趋势：最近 15 点线性拟合斜率（捕捉中期增长/衰减）
    3. 长期衰减：速度序列的线性衰减趋势（判断减速还是加速）
    4. 质量感知：基于视频质量分的速度调整（高质量→更高速度）

适用场景：所有数据量的视频，自适应能力强，无需人工调参。
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class DynamicEnsembleAlgorithm(BaseAlgorithm):
    """
    动态集成策略预测器。

    同时运行 4 个预测子模型（短期速度/中期趋势/长期衰减/质量感知），
    根据视频当前所处阶段（早期/成长/成熟）和预测阈值自动调整融合权重。
    核心优势：自适应——无需人工选择模型，算法自动判断最优策略。

    类属性：
        name (str): 算法名称 "动态集成"
        algorithm_id (str): 算法唯一标识 "dynamic_ensemble"
        description (str): 算法简述
        category (str): 所属类别 "集成学习"
        default_weight (float): 默认集成权重 1.6（高，自适应性带来额外价值）
    """

    name = "动态集成"
    algorithm_id = "dynamic_ensemble"
    description = "根据数据量/阶段动态切换集成策略"
    category = "集成学习"
    default_weight = 1.6

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """
        执行动态集成预测。

        Args:
            video_data (Dict): 视频数据字典（需包含 view_count, history_data, quality_score, engagement_rate）。
            threshold (int): 目标播放量阈值，默认 100000。

        Returns:
            PredictionResult: 包含预测到达阈值所需小时数、阶段、权重等元数据。

        流程：
            1. 阶段判定：根据数据量判断 early/growth/mature。
            2. 计算 4 个子模型各自的速度预测。
            3. 根据阶段查表获得初始权重。
            4. 根据阈值大小微调权重（高阈值偏长期，低阈值偏短期）。
            5. 加权融合得到最终预测。
            6. 置信度综合数据量、质量、互动率。
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足 → 回退到匀速外推
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
        diffs = np.diff(views)  # 逐点增量序列
        quality = self.get_quality_score(video_data)      # 视频质量分 (0-1)
        engagement = self.get_engagement_rate(video_data)  # 互动率 (0-1)

        # ========== 阶段判定：根据数据点数量判断视频生命周期阶段 ==========
        if n < 20:
            stage = "early"        # 早期：数据不足，噪声大，需保守
            stage_desc = "早期冷启动"
        elif n < 100:
            stage = "growth"       # 成长期：数据充足，可捕捉趋势
            stage_desc = "成长中"
        else:
            stage = "mature"       # 成熟期：数据丰富，可做更复杂分析
            stage_desc = "成熟期"

        # ========== 4 个子模型 ==========

        # 子模型1: 短期速度 — 最近 3 点平均增量（对最新变化最敏感）
        short_vel = np.mean(diffs[-min(3, len(diffs)):]) if len(diffs) >= 1 else velocity * 3600

        # 子模型2: 中期趋势 — 最近 15 点线性拟合斜率（捕捉中期增长/衰减）
        mid_window = min(15, n)
        mid_trend = np.polyfit(np.arange(mid_window), views[-mid_window:], 1)[0] if mid_window >= 2 else short_vel

        # 子模型3: 长期衰减 — 速度序列本身的线性趋势（判断减速还是加速）
        if n >= 8:
            vel_series = diffs[-min(10, len(diffs)):]  # 最近 10 个速度值
            decay_rate = np.polyfit(np.arange(len(vel_series)), vel_series, 1)[0]  # 速度变化率
            long_adj = np.mean(vel_series) + decay_rate * 2  # 预测 2 步后的速度
        else:
            long_adj = short_vel  # 数据不够时回退

        # 子模型4: 质量感知 — 高质量视频偏向更高速度
        quality_vel = velocity * 3600 * (0.5 + 0.5 * quality)  # 质量 0→0.5x, 质量 1→1.0x

        # ========== 动态权重：不同阶段不同侧重 ==========
        # 阶段权重查表（经验参数，可根据实际效果调整）
        if stage == "early":
            # 早期: 60% 短期速度 + 质量（冷启动友好，不过度依赖不可靠的趋势）
            w_short, w_mid, w_long, w_quality = 0.5, 0.2, 0.1, 0.2
        elif stage == "growth":
            # 成长: 均衡 + 趋势偏重（捕捉增长模式）
            w_short, w_mid, w_long, w_quality = 0.3, 0.35, 0.2, 0.15
        else:
            # 成熟: 偏长期衰减（稳定预测，但不过度依赖）
            w_short, w_mid, w_long, w_quality = 0.2, 0.3, 0.35, 0.15

        # ========== 阈值调整：高阈值偏长期，低阈值偏短期 ==========
        # 预测越远，长期信号越重要；预测越近，短期信号越可靠
        if threshold >= 10000000:       # 千万级阈值：增加长期权重
            w_long += 0.1
            w_short *= 0.8
        elif threshold <= 100000:       # 十万级阈值：增加短期权重
            w_short += 0.1
            w_long *= 0.9

        # 加权融合 4 个子模型
        growth = w_short * short_vel + w_mid * mid_trend + w_long * long_adj + w_quality * quality_vel
        growth = max(0, growth)  # 确保非负

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")

        # 置信度：综合数据量、视频质量、互动率
        # 数据越多 → 置信度越高（上限 0.3）
        # 质量越高 → 置信度越高（上限 0.2）
        # 互动率越高 → 置信度越高（上限 0.2）
        confidence = max(0.1, min(0.9, 0.3 + 0.1 * min(n / 20, 3) + 0.2 * quality + 0.2 * engagement))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={
                "method": "dynamic_ensemble",
                "stage": stage_desc,       # 当前阶段描述（早期冷启动/成长中/成熟期）
                "weights": {               # 实际使用的子模型权重
                    "short": round(w_short, 2), "mid": round(w_mid, 2),
                    "long": round(w_long, 2), "quality": round(w_quality, 2),
                },
            },
            timestamp=datetime.now(),
        )
