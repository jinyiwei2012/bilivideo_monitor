"""
分享速度预测算法 (Share Velocity Prediction)
============================================

基于视频的分享率（转发分享次数 / 播放量）预测视频的病毒式传播潜力。
分享是病毒传播的最关键指标，因为每一次分享都意味着视频被传播到
一个新的潜在观众群体中。

核心原理：
    1. 分享率 = 分享次数 / 播放量
    2. 病毒加速因子 = 1 + 分享率 * 50（分享率每增加 1%，速度提升 50%）
    3. 置信度 = min(1.0, 0.5 + 分享率 * 100)

特点：
    - 分享是病毒传播的最强信号（分享率远低于点赞率但影响更大）
    - 加速因子阈值很高（乘 50 vs 点赞的乘 10），反映分享的巨大影响力
    - 适合识别潜在的"爆款"视频
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class ShareVelocityAlgorithm(BaseAlgorithm):
    """
    分享速度预测算法

    主要功能：
        - 基于分享率计算病毒传播加速因子
        - 分享率高的视频获得极高的速度加成
        - 置信度与分享率正相关

    计算公式：
        share_rate = shares / views
        viral_boost = 1 + share_rate * 50
        adjusted_velocity = base_velocity * viral_boost
        confidence = min(1.0, 0.5 + share_rate * 100)

    类属性：
        name (str)            : "分享速度"
        algorithm_id (str)    : "share_velocity"
        category (str)        : "互动率"
        default_weight (float): 1.5（较高权重，因为分享是强信号）
    """

    name = "分享速度"
    algorithm_id = "share_velocity"
    description = "基于分享率预测病毒传播潜力"
    category = "互动率"
    default_weight = 1.5

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行分享速度预测

        算法流程：
            1. 获取当前播放量、分享数和基础速度
            2. 如果播放量为 0 或速度 <= 0，无法预测
            3. 计算分享率（shares / views）
            4. 计算病毒加速因子（1 + share_rate * 50）
            5. 调整速度 = 基础速度 * 病毒因子
            6. 计算到达目标所需时间
            7. 置信度 = min(1.0, 0.5 + share_rate * 100)

        Args:
            video_data (Dict[str, Any]): 视频数据字典
                - view_count (int)  : 当前播放量
                - share_count (int) : 总分享数
            threshold (int): 目标播放量阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        shares = video_data.get("share_count", 0)
        velocity = self.calculate_velocity(video_data)

        if current_views == 0 or velocity <= 0:
            # 无播放量或速度为非正：无法有效预测
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                # 已达标
                predicted_hours = 0
                confidence = 1.0
            else:
                # 计算分享率
                share_rate = shares / current_views

                # 分享是病毒传播的最关键指标
                # 分享率每增加 1%，速度提升 50%（乘 50 而非点赞的乘 10）
                viral_boost = 1 + share_rate * 50
                adjusted_velocity = velocity * viral_boost  # 调整后的速度

                predicted_hours = remaining / adjusted_velocity  # 预测时间

                # 置信度基于分享率水平
                confidence = min(1.0, 0.5 + share_rate * 100)

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={
                "method": "share_velocity",
                "share_rate": shares / current_views if current_views > 0 else 0,  # 分享率
            },
            timestamp=datetime.now(),
        )
