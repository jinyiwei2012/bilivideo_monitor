"""
对数增长预测算法模块

对数增长模型（Logarithmic Growth Model）假设播放量随时间呈对数函数形式增长：
即增长速度随时间递减，初期快、后期慢。这种模式在内容平台上非常常见——
新发布的内容最初会获得算法推荐的曝光红利，但随着时间推移，推荐流量逐渐减少。

核心公式：
    views(t) = a * ln(t) + b

其中：
    - t:    视频发布以来的时间（小时）
    - a:    增长系数，基于当前播放量拟合
    - b:    初始常数（假设为0）

模型特点：
    1. 增长速度持续递减，符合"收益递减"规律
    2. 适合描述平稳下降的热度轨迹
    3. 参数少、计算开销小
    4. 假设存在明确的饱和趋势

算法流程：
    1. 获取当前播放量和视频年龄（小时数）
    2. 基于当前数据拟合对数增长系数 a = view_count / ln(age_hours + 1)
    3. 反解方程：threshold = a * ln(target_time)，求解目标时间
    4. 预测小时数 = 目标时间 - 当前年龄

适用场景：播放量增长进入平稳减速阶段、热度已过峰值的视频
局限性：忽略了增长中期可能出现的爆发加速现象

所属分类：时间衰减类（category = "时间衰减"）
"""

from datetime import datetime
import math
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class LogarithmicGrowthAlgorithm(BaseAlgorithm):
    """对数增长预测算法

    基于对数增长模型预测视频播放量达到目标阈值所需时间。
    模型假设播放量随时间的对数函数增长，即增长速度持续递减。

    适用于经历过初期增长后进入平稳减速阶段的视频。

    类属性：
        name: 算法中文名称
        algorithm_id: 算法唯一标识符
        description: 算法简要描述
        category: 算法分类标签
        default_weight: 集成预测中的默认权重（略低于基准1.0）
    """

    name = "对数增长"
    algorithm_id = "logarithmic_growth"
    description = "基于对数增长曲线的播放量预测"
    category = "时间衰减"
    default_weight = 0.9

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行对数增长预测

        通过对数增长模型估计视频播放量达到目标阈值所需的时间。

        Args:
            video_data: 视频数据字典，必须包含以下字段：
                - view_count (int): 当前播放量
                - 其他由基类 get_video_age_hours 所需的字段
            threshold: 目标播放量阈值，默认为 100000（10万播放）

        Returns:
            PredictionResult: 预测结果对象，包含：
                - predicted_hours: 预测到达阈值所需的小时数，
                  无穷大或负值表示无法到达
                - confidence: 置信度 (0.0 ~ 0.6)，对数模型置信度相对保守
                - metadata: 包含预测方法标识

        数学原理：
            假设播放量 views = a * ln(t)，其中t为小时数。
            从当前数据拟合出系数 a = current_views / ln(age_hours + 1)。
            然后求解方程 threshold = a * ln(target_time)，得到目标时间，
            预测小时数 = target_time - age_hours。
        """
        current_views = video_data.get("view_count", 0)
        age_hours = self.get_video_age_hours(video_data)

        if age_hours <= 0:
            # 无法确定视频年龄，预测不可行
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                # 已达标，预测时间0，完全置信
                predicted_hours = 0
                confidence = 1.0
            else:
                # 对数增长模型: views(t) = a * ln(t) + b
                # 基于当前数据点拟合系数 a
                # 假设初始偏移b=0（简化处理），则 a = current_views / ln(age_hours + 1)
                # +1 避免 ln(0) 的数学错误
                a = current_views / math.log(max(age_hours, 1) + 1)

                # 预测达到阈值的时间：
                # threshold = a * ln(target_time)
                # target_time = exp(threshold / a)
                # predicted_hours = target_time - age_hours
                try:
                    target_time = math.exp(threshold / a)
                    predicted_hours = target_time - age_hours

                    if predicted_hours < 0:
                        predicted_hours = 0  # 负值修正为0

                    # 对数模型置信度相对保守，固定0.6
                    confidence = 0.6
                except Exception:
                    # 指数过大溢出，预测不可行
                    predicted_hours = float("inf")
                    confidence = 0.2

        velocity = self.calculate_velocity(video_data)

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "logarithmic_growth"},
            timestamp=datetime.now(),
        )
