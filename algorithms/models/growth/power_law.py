"""
幂律衰减预测算法模块

幂律衰减模型（Power Law Decay Model）基于幂律分布理论，假设视频播放量的增长速率
随时间的幂函数递减。幂律分布广泛存在于自然和社会现象中，包括网络内容的流行度分布、
社交媒体传播模式等。

核心公式：
    v(t) = v₀ * (t₀ / t)^α

其中：
    - v(t):  时间t时的播放速度（播放量/小时）
    - v₀:    初始速度（在参考时间点t₀的速度）
    - α:     幂律指数（alpha），控制衰减速率（α越大衰减越快）
    - t:     时间（小时）

物理直觉：
    α = 1 时，速度为双曲线衰减（v ∝ 1/t），播放量按对数增长
    α > 1 时，速度衰减更快，播放量趋于有限上限
    α < 1 时，速度衰减较慢，播放量仍可无限增长（但增速递减）

算法流程：
    1. 获取当前播放速度、视频年龄和剩余播放量
    2. 基于当前速度反算初始速度 v₀ = velocity * (age_hours)^α
    3. 通过幂律积分求解到达目标播放量所需时间：
       预测小时数 = [(remaining*(α-1)/v₀) + age^(1-α)]^(1/(1-α)) - age
    4. 检查数值有效性，排除NaN和负值
    5. 置信度基于v₀与当前播放量的比值

适用场景：
    - 热度自然消退中的视频
    - 网络传播现象（幂律衰减是网络的固有特性）
    - 长期预测（比线性模型更符合实际衰减规律）

劣势：幂律指数α固定为1.5，未根据实际数据动态调整

所属分类：时间衰减类（category = "时间衰减"）
"""

from datetime import datetime
import math
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class PowerLawAlgorithm(BaseAlgorithm):
    """幂律衰减预测算法

    基于幂律分布理论，假设视频播放速度随时间呈幂律衰减（v ∝ t^(-α)）。
    通过对速度函数的积分计算到达目标播放量阈值所需的时间。

    适合预测热度正在自然衰退、播放速度持续下降的视频。

    类属性：
        name: 算法中文名称
        algorithm_id: 算法唯一标识符
        description: 算法简要描述
        category: 算法分类标签
        default_weight: 集成预测中的默认权重（略高于基准1.0）
    """

    name = "幂律衰减"
    algorithm_id = "power_law"
    description = "基于幂律分布的播放量衰减模型"
    category = "时间衰减"
    default_weight = 1.2

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行幂律衰减预测

        使用幂律衰减模型预测视频播放量达到目标阈值所需的时间。
        假设播放速度按 v(t) = v₀ * t^(-α) 衰减，通过对速度积分求解时间。

        Args:
            video_data: 视频数据字典，必须包含以下字段：
                - view_count (int): 当前播放量
                - 其他由基类 calculate_velocity 和 get_video_age_hours 所需的字段
            threshold: 目标播放量阈值，默认为 100000（10万播放）

        Returns:
            PredictionResult: 预测结果对象，包含：
                - predicted_hours: 预测到达阈值所需的小时数
                - confidence: 置信度 (0.0 ~ 0.9)
                - metadata: 包含预测方法和幂律指数alpha

        数学推导：
            速度函数: v(t) = v₀ * (t₀/t)^α = v₀ * t₀^α / t^α
            播放量增量: dV = v(t) * dt
            积分: V(t) = ∫ v₀ * t₀^α / t^α dt = v₀ * t₀^α * t^(1-α) / (1-α) + C
            解出达到阈值所需时间的关键方程。
        """
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)
        age_hours = self.get_video_age_hours(video_data)

        if velocity <= 0 or age_hours <= 0:
            # 速度为0或年龄未知，无法预测
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                # 已达标
                predicted_hours = 0
                confidence = 1.0
            else:
                # 幂律指数：固定为1.5，代表中等衰减速率
                # α值越大，衰减越快，预测到达时间越长
                alpha = 1.5

                # 反算初始速度：v₀ = v_current * (t_current)^α
                # 这是幂律关系的核心——知道任意时刻的速度和幂指数，就能反推初始速度
                v0 = velocity * (age_hours**alpha)

                # 预测时间积分求解：
                # 从age到age+predicted_hours的速度积分应等于remaining
                # ∫[age, age+Δ] v₀/t^α dt = remaining
                # 解方程得:
                # Δ = [remaining*(α-1)/v₀ + age^(1-α)]^(1/(1-α)) - age
                predicted_hours = ((remaining * (alpha - 1) / v0) + (age_hours ** (1 - alpha))) ** (
                    1 / (1 - alpha)
                ) - age_hours

                if predicted_hours < 0 or math.isnan(predicted_hours):
                    # 数值异常（如积分导致负值或NaN），预测失败
                    predicted_hours = float("inf")
                    confidence = 0.3
                else:
                    # 置信度：基于v₀与当前播放量的相对大小
                    # v₀/current_views 越小，说明速度已经衰减得很厉害，预测更不确定
                    confidence = min(0.9, max(0.3, 1.0 - abs(v0) / max(current_views, 1)))

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "power_law", "alpha": 1.5},
            timestamp=datetime.now(),
        )
