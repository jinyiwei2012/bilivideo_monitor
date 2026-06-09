"""
加权集成预测算法模块
====================

本模块实现了加权平均集成预测算法。与简单平均不同，
加权集成为每个基础预测分配不同的信任权重，
更信任"更可靠"的预测来源。

核心原理：
    1. 生成 5 个加权预测对 (预测值, 权重)
    2. 对速度/互动/质量/时间各维度分别预测
    3. 互动模型和质量模型获得更高权重（0.25），因为它们使用了额外信号
    4. 最终预测 = Σ(预测值 * 权重) / Σ(权重)

适用场景：
    - 互动率和质量评分可靠的视频
    - 作为 ensemble 中的一个中等复杂度集成算法
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class EnsembleWeightedAlgorithm(BaseAlgorithm):
    """
    加权集成预测算法

    通过对不同预测来源赋予不同的信任权重来提升预测精度。
    互动模型和质量模型因为使用了视频内在信号（而不仅仅是播放速度），
    在集成中获得更高权重（0.25），而简单的乐观/悲观调整权重较低（0.15）。

    类属性：
        name (str): 算法名称 "加权集成"
        algorithm_id (str): 算法唯一标识 "ensemble_weighted"
        description (str): 算法简述
        category (str): 所属类别 "集成模型"
        default_weight (float): 默认集成权重 1.3（中高）
    """

    name = "加权集成"
    algorithm_id = "ensemble_weighted"
    description = "加权平均多个基础预测结果"
    category = "集成模型"
    default_weight = 1.3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行加权集成预测。

        5 个预测源及其权重：
            1. 乐观预测 (base * 0.9)：权重 0.15
            2. 悲观预测 (base * 1.1)：权重 0.15
            3. 互动率调整 (base * (1 - engagement * 0.3))：权重 0.25
            4. 质量调整 (base / (1 + quality * 0.3))：权重 0.25
            5. 时间调整 (base * (1 + min(age_hours, 72) / 72 * 0.2))：权重 0.20

        Args:
            video_data (Dict): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        Returns:
            PredictionResult: 包含预测到达时间、置信度、元数据的结果对象
        """
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)
        age_hours = self.get_video_age_hours(video_data)

        remaining = threshold - current_views
        weighted_predictions = []
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

            # 不同权重的预测：(预测值, 权重)
            weighted_predictions = [
                (base * 0.9, 0.15),  # 乐观预测：较低权重
                (base * 1.1, 0.15),  # 悲观预测：较低权重
                (base * (1 - self.get_engagement_rate(video_data) * 0.3), 0.25),  # 互动率模型：高权重
                (base / (1 + self.get_quality_score(video_data) * 0.3), 0.25),  # 质量模型：高权重
                (base * (1 + min(age_hours, 72) / 72 * 0.2), 0.20),  # 时间模型：中权重
            ]

            # 加权平均
            total_weight = sum(w for _, w in weighted_predictions)
            weighted_sum = sum(p * w for p, w in weighted_predictions)
            predicted_hours = weighted_sum / total_weight

            # 置信度：多个信号源参与，固定置信度较高
            confidence = 0.7

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "ensemble_weighted", "weights": [w for _, w in weighted_predictions]},
            timestamp=datetime.now(),
        )
