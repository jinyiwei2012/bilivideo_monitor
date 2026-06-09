"""
互动率预测算法 (Engagement Rate Prediction)
=========================================

基于视频互动率（点赞、投币、收藏等交互行为与播放量的比值）
预测视频的传播潜力和播放量增长速度。

核心原理：
    1. 互动率 = 点赞数 / 播放量，反映视频内容质量和观众参与度
    2. 高互动率意味着观众对视频内容高度认可，更可能被分享传播
    3. 互动因子 = 1 + 互动率 * 2，用于加速基础预测速度
    4. 置信度基于互动率水平：互动率越高，预测越可信

适用场景：
    - 需要用一个简洁指标快速估算传播速度
    - 适用于有互动数据（点赞数）的视频
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class EngagementRateAlgorithm(BaseAlgorithm):
    """
    互动率预测算法

    主要功能：
        - 基于视频的互动率（点赞/播放比）计算传播加速因子
        - 高互动率视频获得更快的预测增长速度
        - 置信度与互动率正相关

    计算公式：
        engagement_rate = likes / views
        engagement_factor = 1 + engagement_rate * 2
        adjusted_velocity = base_velocity * engagement_factor
        confidence = min(1.0, 0.5 + engagement_rate * 5)

    类属性：
        name (str)            : "互动率模型"
        algorithm_id (str)    : "engagement_rate"
        category (str)        : "互动率"
        default_weight (float): 1.1
    """

    name = "互动率模型"
    algorithm_id = "engagement_rate"
    description = "基于点赞、投币、收藏等互动率预测"
    category = "互动率"
    default_weight = 1.1

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行互动率预测

        算法流程：
            1. 获取当前播放量、基础速度和互动率
            2. 如果速度 <= 0 或已达标，直接返回相应结果
            3. 计算互动加速因子（engagement_factor = 1 + engagement_rate * 2）
            4. 调整速度 = 基础速度 * 互动因子
            5. 计算到达目标所需时间 = 剩余播放量 / 调整速度
            6. 置信度 = min(1.0, 0.5 + engagement_rate * 5)

        Args:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)
        engagement_rate = self.get_engagement_rate(video_data)

        if velocity <= 0:
            # 速度为非正值，无法有效预测
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                # 已达标
                predicted_hours = 0
                confidence = 1.0
            else:
                # 根据互动率调整传播速度
                # 高互动率 = 更快传播（被分享、被推送的概率更高）
                engagement_factor = 1 + engagement_rate * 2  # 互动因子
                adjusted_velocity = velocity * engagement_factor  # 调整后的速度

                predicted_hours = remaining / adjusted_velocity  # 预测时间

                # 置信度基于互动率稳定性
                confidence = min(1.0, 0.5 + engagement_rate * 5)

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={
                "method": "engagement_rate",
                "engagement_rate": engagement_rate,  # 原始互动率
                "engagement_factor": 1 + engagement_rate * 2,  # 加速因子
            },
            timestamp=datetime.now(),
        )
