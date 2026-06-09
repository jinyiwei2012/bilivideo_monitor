"""
质量分数预测算法 (Quality Score Prediction)
===========================================

基于视频质量分数预测视频的传播速度。视频质量分数是一个
综合多个维度（内容质量、制作水平、互动反馈等）的评分指标，
用于衡量视频内容的整体品质。

核心原理：
    1. 质量因子 = 0.5 + quality_score（范围 0.5 ~ 1.5）
    2. 质量越高，传播越快（好内容更容易被推荐和分享）
    3. 调整速度 = 基础速度 * 质量因子
    4. 置信度 = 0.4 + quality_score * 0.5（范围 0.4 ~ 0.9）

特点：
    - 基于外部质量评分（由其他算法或人工标注产生）
    - 质量因子映射到 [0.5, 1.5]，质量低的视频速度被降级
    - 适合作为其他预测算法的"质量锚点"补充
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class QualityScoreAlgorithm(BaseAlgorithm):
    """
    质量分数预测算法

    主要功能：
        - 利用视频质量分数计算速度调整因子
        - 高质量视频获得更高的预测速度
        - 置信度与质量分数正相关

    计算公式：
        quality_factor = 0.5 + quality_score  (范围 0.5 ~ 1.5)
        adjusted_velocity = base_velocity * quality_factor
        confidence = 0.4 + quality_score * 0.5  (范围 0.4 ~ 0.9)

    类属性：
        name (str)            : "质量分数"
        algorithm_id (str)    : "quality_score"
        category (str)        : "互动率"
        default_weight (float): 1.0
    """

    name = "质量分数"
    algorithm_id = "quality_score"
    description = "基于视频质量评分预测传播速度"
    category = "互动率"
    default_weight = 1.0

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行质量分数预测

        算法流程：
            1. 获取当前播放量、基础速度和质量分数
            2. 如果速度 <= 0 或已达标，直接返回对应结果
            3. 计算质量加速因子（0.5 + quality_score）
            4. 调整速度 = 基础速度 * 质量因子
            5. 计算到达目标所需时间
            6. 置信度 = 0.4 + quality_score * 0.5

        Args:
            video_data (Dict[str, Any]): 视频数据字典
                - view_count (int)       : 当前播放量
                - quality_score (float)  : 视频质量分数 [0, 1]
            threshold (int): 目标播放量阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)
        quality_score = self.get_quality_score(video_data)

        if velocity <= 0:
            # 速度为非正，无法有效预测
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                # 已达标
                predicted_hours = 0
                confidence = 1.0
            else:
                # 质量越高，传播越快
                # 质量因子映射：0 分 -> 0.5x（减速），1 分 -> 1.5x（加速）
                quality_factor = 0.5 + quality_score  # 范围 [0.5, 1.5]
                adjusted_velocity = velocity * quality_factor  # 调整后的速度

                predicted_hours = remaining / adjusted_velocity  # 预测时间

                # 置信度基于质量分数：质量越高 -> 预测越可信
                confidence = 0.4 + quality_score * 0.5  # 范围 [0.4, 0.9]

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={
                "method": "quality_score",
                "quality_score": quality_score,  # 原始质量分数
                "quality_factor": 0.5 + quality_score,  # 质量加速因子
            },
            timestamp=datetime.now(),
        )
