"""
投币加速预测算法模块
====================

本模块实现了基于投币率（coin/view）的播放量加速预测算法。
投币是 B 站中比点赞更能体现视频质量的互动行为，
高投币率通常意味着视频内容质量高、传播潜力大。

核心原理：
    1. 计算投币率 = 投币数 / 当前播放量
    2. 投币率越高，加速因子越大（boost_factor = 1 + coin_rate * 30）
    3. 用加速因子调整当前播放速度（adjusted_velocity = velocity * boost_factor）
    4. 根据调整后的速度计算到达目标播放量所需时间

适用场景：
    - 投币率高的高质量视频（如教程、深度分析）
    - 作为 ensemble 中的一个子模型，提供基于互动质量的视角
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class CoinBoostAlgorithm(BaseAlgorithm):
    """
    投币加速预测算法

    利用投币率（投币/播放量比）来预测视频的潜在传播速度。
    投币是 B 站最昂贵的互动行为（消耗用户硬币），
    因此高投币率是视频高质量的最强信号之一。

    类属性：
        name (str): 算法名称 "投币加速"
        algorithm_id (str): 算法唯一标识 "coin_boost"
        description (str): 算法简述
        category (str): 所属类别 "互动率"
        default_weight (float): 默认集成权重 1.3（中等偏高）
    """

    name = "投币加速"
    algorithm_id = "coin_boost"
    description = "基于投币率预测高质量视频传播"
    category = "互动率"
    default_weight = 1.3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        基于投币率执行播放量预测。

        算法步骤：
            1. 提取当前播放量、投币数、当前速度
            2. 计算投币率 = 投币数 / 播放量
            3. 计算加速因子 = 1 + 投币率 * 30（投币权重是点赞的 3 倍）
            4. 调整速度 = 当前速度 * 加速因子
            5. 计算到达阈值所需小时数 = 剩余播放量 / 调整速度
            6. 置信度 = min(1.0, 0.5 + 投币率 * 50)

        Args:
            video_data (Dict): 视频数据字典，需包含：
                - view_count (int): 当前播放量
                - coin_count (int): 当前投币数
                - 其他基础字段（用于计算 velocity）
            threshold (int): 目标播放量阈值，默认 100000

        Returns:
            PredictionResult: 包含预测到达时间、置信度、元数据的结果对象
                - predicted_hours (float): 预测到达阈值所需小时数
                - confidence (float): 置信度 [0, 1]
                - metadata.coin_rate (float): 当前投币率
        """
        current_views = video_data.get("view_count", 0)
        coins = video_data.get("coin_count", 0)
        velocity = self.calculate_velocity(video_data)

        if current_views == 0 or velocity <= 0:
            # 无效数据：无法计算投币率或速度
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                # 已达标
                predicted_hours = 0
                confidence = 1.0
            else:
                # 投币率 = 投币数 / 播放量（投币比点赞更能体现视频质量）
                coin_rate = coins / current_views

                # 投币加速因子：投币权重是点赞的 3 倍（30 vs 10）
                # 例如 5% 投币率 → 加速因子 2.5 倍
                boost_factor = 1 + coin_rate * 30
                adjusted_velocity = velocity * boost_factor

                # 用加速后的速度计算到达时间
                predicted_hours = remaining / adjusted_velocity

                # 置信度：投币率越高越确定
                # 例如 1% 投币率 → 置信度 1.0（上限）
                confidence = min(1.0, 0.5 + coin_rate * 50)

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "coin_boost", "coin_rate": coins / current_views if current_views > 0 else 0},
            timestamp=datetime.now(),
        )
