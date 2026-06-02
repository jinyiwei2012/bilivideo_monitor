"""
点赞动量预测算法 (Like Momentum Prediction)
===========================================

基于视频点赞的增长动量来预测播放量增长趋势。
点赞是观众对视频内容认可的最直接信号，高点赞率通常意味着
视频质量较高，更容易被平台推荐和用户分享。

核心原理：
    1. 点赞率 = 总点赞数 / 总播放量
    2. 动量因子 = 1 + 点赞率 * 10（点赞率每增加 1%，速度提升 10%）
    3. 置信度 = min(1.0, 0.5 + 点赞率 * 20)

特点：
    - 简洁直观，仅需点赞数和播放量两个指标
    - 高点赞率意味着高质量内容，传播潜力更大
    - 可作为其他复杂算法的补充参考
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class LikeMomentumAlgorithm(BaseAlgorithm):
    """
    点赞动量预测算法

    主要功能：
        - 基于点赞率计算播放量的动量加速因子
        - 高点赞率视频获得更高的预测增长速度
        - 置信度随点赞率线性增长

    计算公式：
        like_rate = likes / views
        momentum_factor = 1 + like_rate * 10
        adjusted_velocity = base_velocity * momentum_factor
        confidence = min(1.0, 0.5 + like_rate * 20)

    类属性：
        name (str)            : "点赞动量"
        algorithm_id (str)    : "like_momentum"
        category (str)        : "互动率"
        default_weight (float): 1.0
    """

    name = "点赞动量"
    algorithm_id = "like_momentum"
    description = "基于点赞增长动量预测播放量"
    category = "互动率"
    default_weight = 1.0

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行点赞动量预测

        算法流程：
            1. 获取当前播放量、点赞数和基础速度
            2. 如果点赞数为 0 或速度 <= 0，无法有效预测
            3. 计算点赞率（likes / views）
            4. 计算动量因子（1 + like_rate * 10）
            5. 调整速度 = 基础速度 * 动量因子
            6. 计算到达目标所需时间
            7. 置信度 = min(1.0, 0.5 + like_rate * 20)

        Args:
            video_data (Dict[str, Any]): 视频数据字典
                - view_count (int)  : 当前播放量
                - like_count (int)  : 总点赞数
            threshold (int): 目标播放量阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        likes = video_data.get("like_count", 0)
        velocity = self.calculate_velocity(video_data)

        if likes == 0 or velocity <= 0:
            # 无点赞数据或速度为非正：无法有效预测
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                # 已达标
                predicted_hours = 0
                confidence = 1.0
            else:
                # 计算点赞率（点赞数 / 播放量）
                like_rate = likes / current_views if current_views > 0 else 0

                # 高点赞率 = 高质量内容 = 更快的传播速度
                # 点赞率每增加 1%，速度提升 10%
                momentum_factor = 1 + like_rate * 10
                adjusted_velocity = velocity * momentum_factor  # 调整后的速度

                predicted_hours = remaining / adjusted_velocity  # 预测时间

                # 置信度：点赞率越高，预测越可信
                confidence = min(1.0, 0.5 + like_rate * 20)

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={
                "method": "like_momentum",
                "like_rate": likes / current_views if current_views > 0 else 0,  # 点赞率
            },
            timestamp=datetime.now(),
        )
