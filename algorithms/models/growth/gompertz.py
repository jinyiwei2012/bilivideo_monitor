"""
Gompertz增长模型预测算法模块

Gompertz增长模型是Benjamin Gompertz于1825年提出的S型增长曲线，
最初用于描述人口死亡率统计，后来被广泛应用于生物学、经济学和技术扩散领域。

在B站视频播放量预测中，Gompertz模型描述视频热度的增长过程：
    - 初期增长缓慢（观众积累阶段）
    - 中期加速增长（推荐算法爆发阶段）
    - 后期趋于饱和（热度自然消退，接近容量上限）

核心公式：
    V(t) = a * exp(-b * exp(-c * t))

其中：
    - a: 渐近线（理论最大播放量/市场容量）
    - b: 位移参数（控制曲线左右平移）
    - c: 增长率参数（控制增长速度）

本模块的实现是Gompertz模型的简化版本，使用历史数据的相对增长率
来估计模型参数，而非进行完整的曲线拟合。

注意：本模块与 gompertz_growth.py 是独立的两个实现。
      gompertz_growth.py 使用 scipy.curve_fit 进行精确拟合，
      而本模块使用简化的增长率估计方法。

所属分类：增长模型类（category = "增长模型"）
"""

from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class GompertzAlgorithm(BaseAlgorithm):
    """Gompertz增长模型预测算法（简化版）

    基于Gompertz增长曲线的播放量预测。使用历史记录中的相对增长率
    来估计模型参数，然后结合速度法产出最终预测。

    与线性模型相比，该模型考虑了增长率的衰减特性，
    更适合预测到达较高阈值所需的时间。

    类属性：
        name: 算法中文名称
        algorithm_id: 算法唯一标识符
        description: 算法简要描述
        category: 算法分类标签
    """

    name = "Gompertz"
    algorithm_id = "gompertz"
    description = "基于Gompertz增长曲线预测，适用于视频热度增长"
    category = "增长模型"

    def __init__(self):
        """初始化Gompertz预测器

        设置最大容量默认值为1000万播放量。
        该值用于限制预测值的上限，防止无限制的指数增长估计。
        """
        super().__init__()
        self.K = 10000000  # 最大容量默认值（1000万播放）

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行Gompertz增长模型预测

        基于历史数据的相对增长率估计Gompertz模型参数，
        结合当前速度进行目标阈值到达时间预测。

        Args:
            video_data: 视频数据字典，必须包含以下字段：
                - view_count (int): 当前播放量
                - history_data (list): 历史数据列表，每条含view_count
            threshold: 目标播放量阈值，默认为 100000（10万播放）

        Returns:
            PredictionResult: 预测结果对象，包含：
                - predicted_hours: 预测到达阈值所需的小时数
                - confidence: 置信度 (0.2 ~ 0.8)，
                  基于历史数据条数递增
                - metadata: 包含预测方法、最大容量和平均增长率

        数据不足处理：
            当历史数据少于3条时，回退到简单的速度法预测，
            置信度降为0.3。
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 3:
            # 数据不足：回退到简单增长预测（速度法）
            if velocity > 0:
                predicted_hours = (threshold - current_views) / velocity
            else:
                predicted_hours = float("inf")
            confidence = 0.3
            metadata = {"method": "gompertz_simple", "reason": "insufficient_data"}
        else:
            views = [h.get("view_count", 0) for h in history]

            # 计算相对增长率序列：rate[i] = (views[i] - views[i-1]) / views[i-1]
            # 这反映了每个时间段播放量的相对增长幅度
            growth_rates = []
            for i in range(1, len(views)):
                if views[i - 1] > 0:
                    rate = (views[i] - views[i - 1]) / views[i - 1]
                    growth_rates.append(max(0, rate))  # 只保留正向增长

            if growth_rates:
                avg_rate = sum(growth_rates) / len(growth_rates)  # 平均相对增长率
            else:
                avg_rate = 0.01  # 默认1%的增长率

            # Gompertz模型预测：基于增长率的直接外推
            # prediction = current_views * (1 + avg_rate)
            prediction = current_views * (1 + avg_rate)
            # 限制在最大容量的50%以内，防止无限增长
            prediction = min(self.K * 0.5, prediction)

            if velocity > 0:
                predicted_hours = (threshold - current_views) / velocity
            else:
                predicted_hours = float("inf")

            # 置信度：基础0.2 + 每条历史数据增加0.1，上限0.8
            confidence = min(0.8, 0.2 + len(history) * 0.1)
            metadata = {"method": "gompertz", "max_capacity": self.K, "average_growth_rate": avg_rate}

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=max(0, predicted_hours),  # 确保预测时间非负
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata=metadata,
            timestamp=datetime.now(),
        )
