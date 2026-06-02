"""
指数衰减预测算法 (Exponential Decay Prediction Algorithm)

考虑播放量增长速度随时间呈指数衰减的物理特性。

核心原理：
    B站视频的播放量增长并非匀速。发布初期由于推荐流量集中，
    增长速度最快；随着时间推移，推荐流量减少，增长速度呈指数下降。
    本算法将当前速度反向推算至初始速度（发布时刻的速度），
    然后积分求解达到目标播放量所需的时间。

数学模型：
    - 衰减系数: λ = ln(2) / 24（24小时半衰期，即每24小时速度减半）
    - 当前速度 v(t) = v₀ × e^(-λt)，其中 v₀ 为初始速度
    - 反向推算: v₀ = v(t) × e^(λt)
    - 积分求解: T = -ln(1 - λ × remaining / v₀) / λ

适用场景：
    - 发布超过24小时、增长速度明显放缓的视频
    - 自然流量为主的视频（非爆发型热门视频）
    - 需要保守估计的长期预测

参考：
    基于B站推荐算法的时效性衰减特征
"""

from datetime import datetime
import math
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class ExponentialDecayAlgorithm(BaseAlgorithm):
    """指数衰减预测算法

    假设播放量增长速度随时间指数衰减（24小时半衰期），
    通过积分求解达到目标播放量所需的时间。

    核心假设:
        - 播放量增长速度遵循指数衰减规律
        - 24小时后速度下降为原来的一半（半衰期=24h）
        - 剩余播放量可通过对速度函数积分得到

    属性:
        name (str): 算法显示名称 "指数衰减"
        algorithm_id (str): 算法唯一标识 "exponential_decay"
        description (str): 算法描述
        category (str): 算法分类 "时间衰减"
        default_weight (float): 集成预测中的默认权重 1.3
    """

    name = "指数衰减"
    algorithm_id = "exponential_decay"
    description = "考虑播放量增长速度随时间指数衰减"
    category = "时间衰减"
    default_weight = 1.3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行指数衰减预测

        基于当前速度和视频年龄，反向推算初始速度，然后积分计算达到目标播放量所需时间。

        参数:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 预测结果对象

        算法步骤:
            1. 计算衰减系数 λ = ln(2)/24（每24小时速度减半）
            2. 反向推算初始速度: v₀ = v_current × e^(λ × age_hours)
            3. 积分求解: 若 λ × remaining / v₀ ≥ 1，则永远无法达标
              否则 T = -ln(1 - λ × remaining / v₀) / λ
        """
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)
        age_hours = self.get_video_age_hours(video_data)

        # 边界情况：无法计算有效预测
        if velocity <= 0 or age_hours <= 0:
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            # 已达标情况
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                # 衰减系数 λ = ln(2)/24，表示每24小时速度衰减为原来的一半
                decay_rate = 0.693 / 24  # ln(2) / 24

                # 反向推算初始速度（假设发布时的速度）
                # v₀ = v(t) × e^(λt)
                v0 = velocity * math.exp(decay_rate * age_hours)

                # 积分求解: ∫ v₀ × e^(-λt) dt = remaining
                # 解得: t = -ln(1 - λ × remaining / v₀) / λ
                # 其中 v₀ × e^(-λt) 是t时刻的速度，remaining = ∫₀^T v₀e^(-λt) dt

                numerator = decay_rate * remaining / v0
                # 若 numerator ≥ 1，表示在当前衰减模型下永远无法达到目标
                if numerator >= 1:
                    predicted_hours = float("inf")
                    confidence = 0.3
                else:
                    predicted_hours = -math.log(1 - numerator) / decay_rate
                    # 置信度基于模型拟合程度
                    confidence = 0.7

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "exponential_decay", "decay_rate": 0.693 / 24},
            timestamp=datetime.now(),
        )
