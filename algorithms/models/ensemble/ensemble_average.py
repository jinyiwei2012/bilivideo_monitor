"""
平均集成预测算法模块
====================

本模块实现了简单平均集成预测算法，通过对多个基础预测结果
取算术平均来获得最终预测值。虽然方法简单，但在预测器之间
误差互补的情况下，平均集成可以有效降低方差。

核心原理：
    1. 生成 5 个基础预测变体（线性/乐观/悲观/互动调整/质量调整）
    2. 对所有预测取算术平均作为最终预测
    3. 置信度基于预测方差：方差越小，一致性越高，置信度越大

适用场景：
    - 作为集成基准（baseline）算法
    - 数据较少时的稳健选择
    - 与其他复杂集成算法对比参考
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class EnsembleAverageAlgorithm(BaseAlgorithm):
    """
    平均集成预测算法

    通过生成多个基础预测变体并取算术平均来预测视频播放量。
    实现最简单但有效的集成策略——Bagging 理论指出，
    对多个不完美相关估计量的平均可以降低整体方差。

    类属性：
        name (str): 算法名称 "平均集成"
        algorithm_id (str): 算法唯一标识 "ensemble_average"
        description (str): 算法简述
        category (str): 所属类别 "集成模型"
        default_weight (float): 默认集成权重 1.0（基准水平）
    """

    name = "平均集成"
    algorithm_id = "ensemble_average"
    description = "简单平均多个基础预测结果"
    category = "集成模型"
    default_weight = 1.0

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行平均集成预测。

        生成 5 种基础预测变体并取算术平均：
            1. 线性预测：直接匀速外推
            2. 乐观预测：线性 * 0.8（加速因素）
            3. 悲观预测：线性 * 1.2（减速因素）
            4. 互动调整：线性 * (1 + 互动率)，高互动 → 更快到达
            5. 质量调整：线性 / (1 + 质量评分 * 0.5)，高质量 → 更快到达

        置信度计算：
            基于 5 个预测值的方差，方差越小 → 预测越一致 → 置信度越高。

        Args:
            video_data (Dict): 视频数据字典，需包含 view_count 等基础字段
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
            # 基础预测：匀速到达目标的时间
            base = remaining / velocity

            # 生成 5 种预测变体
            predictions = [
                base,  # 线性：基准预测
                base * 0.8,  # 乐观：假设增速提升 20%
                base * 1.2,  # 悲观：假设增速下降 20%
                base * (1 + self.get_engagement_rate(video_data)),  # 互动率调整
                base / (1 + self.get_quality_score(video_data) * 0.5),  # 质量评分调整
            ]

            # 简单算术平均
            predicted_hours = sum(predictions) / len(predictions)

            # 置信度基于方差：方差越小预测越一致
            variance = sum((p - predicted_hours) ** 2 for p in predictions) / len(predictions)
            confidence = max(0.3, 1 - variance / (predicted_hours**2 + 1))

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "ensemble_average", "ensemble_size": 5},
            timestamp=datetime.now(),
        )
