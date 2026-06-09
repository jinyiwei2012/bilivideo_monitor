"""
评论趋势预测算法 (Comment Trend Prediction Algorithm)

基于视频评论活跃度来预测播放量增长趋势。

核心原理：
    评论数是衡量视频"互动热度"的关键指标。高评论率意味着观众参与度高，
    视频更有可能被算法推荐，从而加速播放量增长。
    本算法通过评论率（评论数/播放量）来调整基础增长速度，
    评论率越高，预测的增长速度越快，达到目标播放量所需的时间越短。

适用场景：
    - 高互动率视频（引发讨论的话题类、争议类视频）
    - 评论区活跃的UP主视频
    - 作为互动率维度预测的参考算法之一

参考：
    基于B站推荐算法机制：互动率（点赞、评论、转发）是影响视频推荐量的重要因子
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class CommentTrendAlgorithm(BaseAlgorithm):
    """评论趋势预测算法

    通过计算视频的评论率（评论数 / 播放量），
    评估观众互动热度，并据此调整播放量增长速度预测。

    核心逻辑：
        评论率越高 → 视频互动热度越高 → 预测增长速度越快 → 达标时间越短

    属性:
        name (str): 算法显示名称 "评论趋势"
        algorithm_id (str): 算法唯一标识 "comment_trend"
        description (str): 算法描述
        category (str): 算法分类 "互动率"
        default_weight (float): 集成预测中的默认权重 0.9
    """

    name = "评论趋势"
    algorithm_id = "comment_trend"
    description = "基于评论活跃度预测视频热度"
    category = "互动率"
    default_weight = 0.9

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行评论趋势预测

        根据评论率（评论数/播放量）计算趋势因子，调整基础增长速度，
        预测视频达到目标播放量阈值所需的时间。

        参数:
            video_data (Dict[str, Any]): 视频数据字典，需包含:
                - view_count (int): 当前播放量
                - reply_count (int): 当前评论数
                - history_data (list): 历史数据列表
                - publish_time: 发布时间
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 预测结果对象，包含:
                - predicted_hours: 预计达到阈值所需的小时数
                - confidence: 预测置信度 (0.0 ~ 1.0)
                - 其他元数据信息

        算法步骤:
            1. 计算评论率 = 评论数 / 播放量
            2. 计算趋势因子 = 1 + 评论率 × 20（评论率越高，趋势越强）
            3. 计算调整速度 = 基础速度 × 趋势因子
            4. 预估时间 = 剩余播放量 / 调整速度
            5. 置信度 = min(1.0, 0.5 + 评论率 × 40)
        """
        current_views = video_data.get("view_count", 0)
        replies = video_data.get("reply_count", 0)
        velocity = self.calculate_velocity(video_data)

        # 边界情况：播放量为0或速度为0时无法预测
        if current_views == 0 or velocity <= 0:
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            # 已达标情况
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                # 计算评论率（评论数 / 播放量）
                comment_rate = replies / current_views

                # 评论活跃 = 讨论热度高，使用趋势因子放大速度
                # 系数20表示评论率每增加1%，速度提升20%
                trend_factor = 1 + comment_rate * 20
                adjusted_velocity = velocity * trend_factor

                # 计算达到阈值所需小时数
                predicted_hours = remaining / adjusted_velocity

                # 置信度随评论率增加而提高
                # 评论率越高，预测越有把握
                confidence = min(1.0, 0.5 + comment_rate * 40)

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "comment_trend", "comment_rate": replies / current_views if current_views > 0 else 0},
            timestamp=datetime.now(),
        )
