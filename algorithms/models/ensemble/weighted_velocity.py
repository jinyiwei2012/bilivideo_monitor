"""
加权速度预测算法模块
====================

本模块实现了基于时间衰减加权的播放速度预测算法。
核心思想是：距离当前越近的数据点对预测未来越有参考价值，
因此赋予更高的权重。

核心原理：
    1. 遍历历史数据，计算每对相邻数据点之间的播放速度
    2. 按照时间顺序分配线性递增的权重（越新的数据对权重越大）
    3. 加权平均得到最终预测速度
    4. 如果无历史数据，回退到基础速度（BaseAlgorithm.calculate_velocity）

权重策略：
    - 权重 = (i + 1) / len(history)
    - 第 1 个数据点权重 ≈ 1/n
    - 最后 1 个数据点权重 ≈ 1.0
    - 实现：线性递增，最近的数据点权重最高

适用场景：
    - 播放趋势持续加速或减速的视频
    - 作为基础速度类的算法
    - 在 ensemble 中提供近期偏重的视角
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class WeightedVelocityAlgorithm(BaseAlgorithm):
    """
    加权速度预测算法

    通过对历史速度数据按时间远近加权，更重视近期播放趋势。
    相比简单匀速外推，能更快响应视频播放量的加速或减速变化。

    类属性：
        name (str): 算法名称 "加权速度"
        algorithm_id (str): 算法唯一标识 "weighted_velocity"
        description (str): 算法简述
        category (str): 所属类别 "基础速度"
        default_weight (float): 默认集成权重 1.2（中）
    """

    name = "加权速度"
    algorithm_id = "weighted_velocity"
    description = "近期播放速度权重更高"
    category = "基础速度"
    default_weight = 1.2

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行加权速度预测。

        如果有足够历史数据：
            1. 遍历每对相邻数据点
            2. 计算两点间播放速度 (小时播放量)
            3. 按时间远近分配权重（越新权重越高）
            4. 加权平均得到最终速度
        否则回退到基础速度。

        Args:
            video_data (Dict): 视频数据字典，需包含：
                - view_count (int): 当前播放量
                - history_data (List[Dict]): 历史监控数据
                - 其他基础字段（用于计算 velocity）
            threshold (int): 目标播放量阈值，默认 100000

        Returns:
            PredictionResult: 包含预测到达时间、置信度、元数据的结果对象
                - metadata.history_points (int): 使用的历史数据点数量
        """
        current_views = video_data.get("view_count", 0)
        base_velocity = self.calculate_velocity(video_data)

        # 获取历史数据用于加权计算
        history = video_data.get("history_data", [])

        if len(history) >= 2:
            # 有足够历史数据：按时间远近加权计算速度
            total_weight = 0
            weighted_velocity = 0

            for i, record in enumerate(history):
                # 线性递增权重：越新权重越高
                # i=0 时 weight ≈ 1/n，i=n-1 时 weight ≈ 1.0
                weight = (i + 1) / len(history)  # 越新权重越高
                if i > 0:
                    # 计算相邻点之间的播放增量
                    views_diff = record.get("view_count", 0) - history[i - 1].get("view_count", 0)
                    time_diff = record.get("timestamp", 0) - history[i - 1].get("timestamp", 0)
                    if time_diff > 0:
                        # 转换为每小时播放量速度
                        velocity = views_diff / (time_diff / 3600)
                        weighted_velocity += velocity * weight
                        total_weight += weight

            if total_weight > 0:
                final_velocity = weighted_velocity / total_weight
            else:
                final_velocity = base_velocity  # 回退到基础速度
        else:
            final_velocity = base_velocity  # 数据不足，使用基础速度

        if final_velocity <= 0:
            # 无有效速度
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                # 已达标
                predicted_hours = 0
                confidence = 1.0
            else:
                predicted_hours = remaining / final_velocity
                # 有历史数据时置信度更高，每增加一个数据点 +0.1
                confidence = min(1.0, 0.5 + len(history) * 0.1)

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=final_velocity,
            metadata={"method": "weighted_velocity", "history_points": len(history)},
            timestamp=datetime.now(),
        )
