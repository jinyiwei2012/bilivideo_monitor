"""
病毒传播潜力算法 (Viral Potential Detection)
============================================

检测视频是否具有病毒式传播的特征，并据此调整预测。
病毒式传播的特征包括：早期的超高互动率、大量的分享转发、
以及短时间内快速的播放量增长。

核心原理：
    1. 病毒评分计算：viralscore = (分享率 × 10 + 点赞率 × 5) × (24 / min(age_hours, 1))
    2. 早期因子：视频越新，同样的互动率对应的病毒潜力越高
    3. 病毒加速因子：virusscore > 1 时，加速因子 = 1 + virusscore；否则 = 1
    4. 置信度 = min(1.0, virusscore / 3)

特点：
    - 早期高互动率是病毒传播的最强信号
    - 视频年龄因子确保"新视频高互动"比"老视频高互动"更有价值
    - 病毒评分 > 1 触发加速，评分 < 1 忽略（保持原速度）
    - 适合在视频发布早期快速识别潜在爆款

变量说明：
    - share_rate = 分享数 / 播放量
    - like_rate = 点赞数 / 播放量
    - age_hours = 视频发布以来的时间（小时）
    - 早期因子 = 24 / max(age_hours, 1)（越新越高）
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class ViralPotentialAlgorithm(BaseAlgorithm):
    """
    病毒传播潜力检测算法

    主要功能：
        - 计算视频的病毒潜力评分（基于分享率、点赞率和视频年龄）
        - 检测视频是否处于病毒式传播状态
        - 病毒传播视频获得显著的速度加速
        - 置信度基于病毒评分水平

    计算公式：
       病毒评分 = (分享率 * 10 + 点赞率 * 5) * (24 / max(age_hours, 1))
       病毒因子 = 1 + 病毒评分 (当评分 > 1) 否则 = 1
       调整速度 = 基础速度 * 病毒因子
       置信度 = min(1.0, 病毒评分 / 3)

    类属性：
        name (str)            : "病毒潜力"
        algorithm_id (str)    : "viral_potential"
        category (str)        : "互动率"
        default_weight (float): 1.4（较高权重）
    """

    name = "病毒潜力"
    algorithm_id = "viral_potential"
    description = "检测视频是否具有病毒式传播特征"
    category = "互动率"
    default_weight = 1.4

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行病毒传播潜力预测

        算法流程：
            1. 获取当前播放量、点赞数、分享数和基础速度
            2. 计算视频年龄（小时）
            3. 如果播放量为 0 / 年龄 <= 0 / 速度 <= 0：无法预测
            4. 计算分享率和点赞率
            5. 计算病毒评分：viralscore = (分享率*10 + 点赞率*5) * 早期因子
            6. 如果病毒评分 > 1：加速因子 = 1 + viralscore
               否则：加速因子 = 1（不加速）
            7. 调整速度 = 基础速度 * 加速因子
            8. 置信度 = min(1.0, viralscore / 3)

        Args:
            video_data (Dict[str, Any]): 视频数据字典
                - view_count (int)  : 当前播放量
                - like_count (int)  : 总点赞数
                - share_count (int) : 总分享数
            threshold (int): 目标播放量阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)
        viral_score = 0.0
        age_hours = self.get_video_age_hours(video_data)

        # 获取互动数据
        views = video_data.get("view_count", 0)
        likes = video_data.get("like_count", 0)
        shares = video_data.get("share_count", 0)

        if views == 0 or age_hours <= 0 or velocity <= 0:
            # 无播放量或速度为 0 或年龄无效：无法预测
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                # 已达标
                predicted_hours = 0
                confidence = 1.0
            else:
                # 计算病毒指标
                share_rate = shares / views  # 分享率
                like_rate = likes / views  # 点赞率

                # 早期高互动 = 病毒潜力：互动率乘以早期因子
                # 早期因子 (24 / max(age_hours, 1)) 确保越新的视频权重越高
                viral_score = (share_rate * 10 + like_rate * 5) * (24 / max(age_hours, 1))

                # 病毒加速因子：仅当病毒评分 > 1 时触发加速
                if viral_score > 1:
                    viral_factor = 1 + viral_score  # 强加速
                else:
                    viral_factor = 1  # 不加速

                adjusted_velocity = velocity * viral_factor  # 调整后的速度
                predicted_hours = remaining / adjusted_velocity  # 预测时间

                # 置信度基于病毒评分水平
                confidence = min(1.0, viral_score / 3)

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={
                "method": "viral_potential",
                "viral_score": viral_score,  # 病毒潜力评分
            },
            timestamp=datetime.now(),
        )
