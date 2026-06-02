"""
投票集成预测算法模块
====================

本模块实现了基于中位数投票的集成预测算法。
通过对多个预测结果取中位数（而非平均值），
有效抵抗个别极端预测值的影响。

核心原理：
    1. 生成 7 个基础预测（不同系数放大/缩小 + 互动率调整 + 质量调整）
    2. 取中位数作为最终预测（抗异常值）
    3. 置信度基于四分位距 (IQR)：IQR 越小，预测越集中，置信度越高

与平均集成的区别：
    - 平均集成受极端值影响较大（一个异常值会拉偏均值）
    - 中位数投票天然忽略极端值，更稳健

适用场景：
    - 存在潜在异常预测的场景
    - 作为稳健集成策略的一部分
"""

from datetime import datetime
from typing import Dict, Any
import statistics
from algorithms.base import BaseAlgorithm, PredictionResult


class EnsembleVotingAlgorithm(BaseAlgorithm):
    """
    投票集成预测算法

    基于统计学的稳健估计思想，使用中位数替代平均值来融合多个预测。
    中位数是非参数估计量，对异常值（outlier）具有天生的抵抗力。

    类属性：
        name (str): 算法名称 "投票集成"
        algorithm_id (str): 算法唯一标识 "ensemble_voting"
        description (str): 算法简述
        category (str): 所属类别 "集成模型"
        default_weight (float): 默认集成权重 1.2（中高）
    """

    name = "投票集成"
    algorithm_id = "ensemble_voting"
    description = "基于中位数投票的集成预测"
    category = "集成模型"
    default_weight = 1.2

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行基于中位数投票的集成预测。

        生成 7 个预测值：
            1. base * 0.7（极度乐观：增速提升 30%）
            2. base * 0.85（乐观）
            3. base（中性）
            4. base * 1.15（悲观）
            5. base * 1.3（极度悲观）
            6. base * (1 - 互动率 * 0.5)（互动率调整）
            7. base / (0.8 + 质量评分 * 0.4)（质量调整）

        取中位数作为最终预测（抗异常值），
        用四分位距 (IQR = Q3 - Q1) 衡量预测一致性。

        Args:
            video_data (Dict): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        Returns:
            PredictionResult: 包含预测到达时间、置信度、元数据的结果对象
        """
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            # 已达标
            predicted_hours = 0
            confidence = 1.0
        elif velocity <= 0:
            # 无增长
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            base = remaining / velocity  # 基准匀速预测

            # 生成 7 个不同视角的预测
            predictions = [
                base * 0.7,   # 极度乐观
                base * 0.85,  # 乐观
                base,         # 中性
                base * 1.15,  # 悲观
                base * 1.3,   # 极度悲观
                base * (1 - self.get_engagement_rate(video_data) * 0.5),  # 互动率调整
                base / (0.8 + self.get_quality_score(video_data) * 0.4),  # 质量评分调整
            ]

            # 使用中位数：天然抵抗异常值，稳健性优于平均值
            predicted_hours = statistics.median(predictions)

            # 置信度基于四分位距 (IQR)：IQR 越小预测越集中
            q1 = sorted(predictions)[len(predictions) // 4]   # 第 1 四分位数
            q3 = sorted(predictions)[3 * len(predictions) // 4]  # 第 3 四分位数
            iqr = q3 - q1  # 四分位距
            confidence = max(0.3, 1 - iqr / (predicted_hours + 1))

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "ensemble_voting", "predictions_count": 7},
            timestamp=datetime.now(),
        )
