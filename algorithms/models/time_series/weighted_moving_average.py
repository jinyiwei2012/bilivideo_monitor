"""
加权移动平均预测算法 (Weighted Moving Average Prediction Algorithm)

使用加权移动平均（WMA）对历史播放量数据进行平滑预测，
近期的数据点被赋予更高的权重，远期的数据点权重较低。

核心原理：
    不同于简单移动平均给每个点相同权重，加权移动平均认为
    越近期的数据越能反映当前趋势，因此赋予更大的权重。
    这可以减少简单移动平均的滞后性，对趋势变化的响应更快。

公式:
    WMA_t = Σ(w_i × y_{t-i}) / Σw_i
    其中 w_i 是递减的权重序列

适用场景：
    - 近期有显著变化的视频
    - 需要快速响应趋势变化的预测
    - 作为移动平均类算法的改进版本

权重设计:
    默认权重 [0.1, 0.15, 0.2, 0.25, 0.3]，
    最近的数据点权重最大（0.3），最远的权重最小（0.1）
"""

from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class WeightedMovingAverageAlgorithm(BaseAlgorithm):
    """加权移动平均预测算法

    对最近的历史播放量进行加权平均，越近的数据权重越高，
    并结合近期趋势和远期趋势的差异进行调整。

    属性:
        name (str): 算法显示名称 "加权移动平均"
        algorithm_id (str): 算法唯一标识 "weighted_moving_average"
        description (str): 算法描述
        category (str): 算法分类 "时间序列"
        default_weights (list): 默认权重序列 [0.1, 0.15, 0.2, 0.25, 0.3]
    """

    name = "加权移动平均"
    algorithm_id = "weighted_moving_average"
    description = "使用加权移动平均，近期数据权重更高"
    category = "时间序列"

    def __init__(self):
        """初始化加权移动平均算法，设置递减权重序列"""
        super().__init__()
        # 默认权重：越近权重越高，总和为 1.0（归一化前）
        self.default_weights = [0.1, 0.15, 0.2, 0.25, 0.3]

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行加权移动平均预测

        对最近的历史播放量进行加权平均（近期权重更高），
        结合趋势调整后，预估达到目标播放量所需的时间。

        参数:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 预测结果对象

        算法步骤:
            1. 根据数据点数截取对应长度的权重序列
            2. 对权重进行归一化（总和 = 1.0）
            3. 计算加权移动平均: WMA = Σ w_i × y_i
            4. 结合近期趋势和远期趋势的差异进行调整
            5. 根据预测值和当前速度估计达标时间
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 2:
            prediction = current_views
            confidence = 0.3
            weights = []
        else:
            views = [h.get("view_count", 0) for h in history]
            # 窗口大小不超过数据点数和权重列表长度
            window_size = min(len(self.default_weights), len(views))

            # 截取对应长度的权重（取最后 window_size 个权重）
            weights = self.default_weights[-window_size:]
            # 归一化权重，确保总和为 1.0
            total_weight = sum(weights)
            weights = [w / total_weight for w in weights]

            # 计算加权移动平均: Σ w_i × y_i
            wma = sum(views[-window_size + i] * weights[i] for i in range(window_size))

            # 考虑趋势调整：近期变化 vs 远期变化
            if len(views) >= 3:
                recent = sum(views[-2:]) / 2  # 最近2点的平均值
                older = sum(views[:2]) / 2  # 最早2点的平均值
                trend = (recent - older) / 2  # 趋势差异
                prediction = wma + trend * 0.5  # 加权平均 + 50%趋势调整
            else:
                prediction = wma

            prediction = max(0, prediction)
            confidence = min(0.8, 0.25 + len(history) * 0.08)

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
            "wma_value": prediction,
            "weights": weights if len(history) >= 2 else [],
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
