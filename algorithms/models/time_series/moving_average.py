"""
移动平均预测算法 (Moving Average Prediction Algorithm)

使用简单移动平均（SMA）对历史播放量数据进行平滑，
消除短期波动，提取趋势信号进行预测。

核心原理：
    移动平均是最基本的时间序列平滑方法，
    对最近 N 个数据点取算术平均值作为下一期的预测值。
    N 越大，平滑效果越强，但对变化的响应越慢。

公式:
    MA_t = (y_{t-N+1} + y_{t-N+2} + ... + y_t) / N

适用场景：
    - 波动较大但无明显趋势的平稳序列
    - 作为其他更复杂算法的基线对比
    - 快速计算场景

注意事项：
    - 移动平均存在滞后性（延迟 N/2 个周期）
    - 本算法同时考虑近期趋势和远期趋势的差异来调整预测
"""

from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class MovingAverageAlgorithm(BaseAlgorithm):
    """简单移动平均预测算法

    对最近 window_size 个历史播放量取平均作为预测基础，
    并结合近期趋势和远期趋势的差异进行调整。

    属性:
        name (str): 算法显示名称 "移动平均"
        algorithm_id (str): 算法唯一标识 "moving_average"
        description (str): 算法描述
        category (str): 算法分类 "时间序列"
        window_size (int): 移动平均窗口大小，默认 5
    """

    name = "移动平均"
    algorithm_id = "moving_average"
    description = "使用历史数据的简单移动平均预测"
    category = "时间序列"

    def __init__(self):
        """初始化移动平均算法，设置窗口大小为 5"""
        super().__init__()
        self.window_size = 5

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行移动平均预测

        计算历史播放量的滑动窗口平均值，并结合趋势调整后，
        预估达到目标播放量所需的时间。

        参数:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 预测结果对象

        算法步骤:
            1. 取最近 window_size 个数据点计算简单移动平均
            2. 若有 ≥3 个数据点，计算近期趋势 vs 远期趋势的差异
            3. 用移动平均值 + 趋势调整作为预测值
            4. 根据预测值和当前速度估计达标时间
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 2:
            prediction = current_views
            confidence = 0.3
        else:
            views = [h.get("view_count", 0) for h in history]
            # 窗口大小不超过已有数据点数
            window = min(self.window_size, len(views))

            # 计算简单移动平均: MA = sum(最近window个值) / window
            ma = sum(views[-window:]) / window

            # 考虑趋势：近期平均值 vs 远期平均值之差
            if len(views) >= 3:
                recent_avg = sum(views[-3:]) / 3  # 最近3点平均值
                old_avg = sum(views[:3]) / 3  # 最早3点平均值
                trend = (recent_avg - old_avg) / 3  # 趋势斜率（除以数据跨度）
                prediction = ma + trend * 0.3  # 趋势外推30%
            else:
                prediction = ma

            prediction = max(0, prediction)
            confidence = min(0.75, 0.2 + len(history) * 0.08)

        # 计算预测达到阈值的时间
        growth = prediction - current_views
        predicted_hours = float("inf")

        if growth > 0 and current_views < threshold:
            remaining = threshold - current_views
            if velocity > 0:
                predicted_hours = remaining / velocity
            else:
                predicted_hours = float("inf")
        elif current_views >= threshold:
            predicted_hours = 0
            confidence = 1.0

        metadata = {
            "ma_value": prediction,
            "window_size": min(self.window_size, len(history)),
            "trend": "上涨" if growth > 0 else "下跌",
        }

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
