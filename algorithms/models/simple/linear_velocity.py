"""
线性速度预测算法模块

该模块实现基于当前播放速度的线性预测算法。核心思想是假设视频的播放量增长速度保持恒定，
即"匀速增长"假设。通过计算当前播放速度（播放量/小时），直接外推到达目标阈值所需的时间。

算法流程：
1. 获取当前播放量和播放速度
2. 计算剩余所需播放量 = 阈值 - 当前播放量
3. 预测时间 = 剩余播放量 / 当前速度
4. 根据视频年龄动态调整置信度（越新的视频置信度越高，一周后逐渐降低）

适用场景：播放量增长相对稳定的视频，增长模式未发生明显变化。
局限性：忽略了增长加速/减速趋势，对于处于爆发期或衰退期的视频预测偏差较大。

所属分类：基础速度类（category = "基础速度"）
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class LinearVelocityAlgorithm(BaseAlgorithm):
    """线性速度预测算法

    基于视频当前的播放速度（播放量增量/小时）进行线性外推预测。
    假设播放量增长速度保持恒定，直接计算达到目标阈值所需的时间。

    类属性：
        name: 算法中文名称
        algorithm_id: 算法唯一标识符
        description: 算法简要描述
        category: 算法分类标签
        default_weight: 集成预测中的默认权重
    """

    name = "线性速度"
    algorithm_id = "linear_velocity"
    description = "基于当前播放速度进行线性预测"
    category = "基础速度"
    default_weight = 1.0

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行线性速度预测

        基于当前播放速度进行线性外推，计算达到目标阈值所需的小时数。

        Args:
            video_data: 视频数据字典，必须包含以下字段：
                - view_count (int): 当前播放量
                - 其他由基类 calculate_velocity 和 get_video_age_hours 所需的字段
            threshold: 目标播放量阈值，默认为 100000（10万播放）

        Returns:
            PredictionResult: 预测结果对象，包含：
                - predicted_hours: 预测到达阈值所需的小时数，
                  无穷大(float("inf"))表示永远无法到达
                - confidence: 置信度 (0.0 ~ 1.0)，
                  基于视频年龄衰减（一周内置信度较高，之后递减）
                - current_views: 当前播放量
                - current_velocity: 当前播放速度（播放量/小时）
                - metadata: 包含预测方法标识
        """
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)

        if velocity <= 0:
            # 速度为0或负，无法预测，置信度为0
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                # 已经达到或超过阈值，预测时间为0，完全置信
                predicted_hours = 0
                confidence = 1.0
            else:
                # 线性外推：时间 = 剩余量 / 速度
                predicted_hours = remaining / velocity
                # 置信度随时间递减，越老的视频线性预测越不可靠
                # 视频年龄超过一周(168小时)后，置信度最低降至0.3
                age_hours = self.get_video_age_hours(video_data)
                confidence = min(1.0, max(0.3, 1 - age_hours / 168))

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "linear_velocity"},
            timestamp=datetime.now(),
        )
