"""
指数平滑预测算法 (Exponential Smoothing Prediction Algorithm)

使用指数加权移动平均（EWMA）对播放量历史数据进行平滑处理，
消除短期波动干扰，提取长期趋势进行预测。

核心原理：
    指数平滑是一种时间序列预测方法，通过对历史数据赋予指数递减的权重，
    使得近期数据对预测结果影响更大，远期数据影响逐渐衰减。
    平滑系数 α 控制着对新数据的敏感程度：
    - α → 1: 更敏感，更关注近期变化
    - α → 0: 更平滑，更关注长期趋势

公式:
    S₁ = y₁
    S_t = α × y_t + (1-α) × S_{t-1}

适用场景：
    - 波动较大但无明显趋势的视频
    - 需要平滑短期噪声的场景
    - 作为时间序列预测的基线算法

参考:
    Holt, C. C. (1957) "Forecasting seasonals and trends by exponentially weighted moving averages"
"""

from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class ExponentialSmoothingAlgorithm(BaseAlgorithm):
    """指数平滑预测算法

    对历史播放量序列进行指数加权移动平均，提取平滑趋势值，
    并结合近期趋势调整来预测未来增长。

    属性:
        name (str): 算法显示名称 "指数平滑"
        algorithm_id (str): 算法唯一标识 "exponential_smoothing"
        description (str): 算法描述
        category (str): 算法分类 "时间序列"
        alpha (float): 平滑系数，默认 0.3，控制对新数据的权重
    """

    name = "指数平滑"
    algorithm_id = "exponential_smoothing"
    description = "使用指数加权移动平均预测"
    category = "时间序列"

    def __init__(self):
        """初始化指数平滑算法，设置平滑系数 alpha = 0.3"""
        super().__init__()
        self.alpha = 0.3  # 平滑系数：0.3 表示新数据权重30%，历史平滑值权重70%

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行指数平滑预测

        对历史播放量进行指数加权平滑，然后基于平滑值计算达到目标播放量所需的时间。

        参数:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 预测结果对象

        算法步骤:
            1. 如果历史数据不足2条，使用当前播放量作为平滑值
            2. 对历史播放量序列进行指数平滑: S_t = αy_t + (1-α)S_{t-1}
            3. 如果数据足够（≥3条），考虑近期趋势调整
            4. 基于平滑值和当前速度计算达标时间
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足时使用保守估计
        if len(history) < 2:
            smoothed = current_views
            confidence = 0.3
        else:
            views = [h.get("view_count", 0) for h in history]

            # 指数平滑迭代: S_t = α × y_t + (1-α) × S_{t-1}
            smoothed = views[0]  # 初始值 = 第一个观测值
            for v in views[1:]:
                smoothed = self.alpha * v + (1 - self.alpha) * smoothed

            # 使用平滑值趋势调整预测
            # 当有≥3个数据点时，计算近期趋势并进行外推
            if len(views) >= 3:
                recent_trend = (views[-1] - views[-3]) / 2  # 最近3点趋势（除以2是点数差）
                prediction = smoothed + recent_trend * 0.5  # 趋势外推一半步长
            else:
                prediction = smoothed

            # 确保预测值非负
            smoothed = max(0, prediction)
            # 置信度随数据量增加而提高
            confidence = min(0.85, 0.25 + len(history) * 0.1)

        # 计算预测达到阈值的时间
        growth = smoothed - current_views
        predicted_hours = float("inf")

        if growth > 0 and current_views < threshold:
            remaining = threshold - current_views
            # 使用当前速度估计每小时增长
            if velocity > 0:
                predicted_hours = remaining / velocity
            else:
                predicted_hours = float("inf")
        elif current_views >= threshold:
            predicted_hours = 0
            confidence = 1.0

        metadata = {"smoothed_value": smoothed, "alpha": self.alpha, "trend": growth}

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=max(0, predicted_hours),
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata=metadata,
            timestamp=datetime.now(),
        )
