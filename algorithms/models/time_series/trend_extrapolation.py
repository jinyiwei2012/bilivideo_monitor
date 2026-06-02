"""
趋势外推预测算法 (Trend Extrapolation Prediction Algorithm)

使用最小二乘线性回归对历史播放量数据进行拟合，
然后沿回归线外推到未来，预测达到目标播放量所需的时间。

核心原理：
    将播放量随时间的变化视为线性关系，使用最小二乘法
    拟合一条直线 y = slope × x + intercept，然后沿此直线外推，
    计算播放量达到目标阈值时的 x 值（时间点）。

公式:
    斜率 = Σ((x_i - x̄)(y_i - ȳ)) / Σ(x_i - x̄)²
    截距 = ȳ - slope × x̄
    预测值 = slope × 未来x + 截距

适用场景：
    - 播放量呈近似线性增长的视频
    - 需要简单快速预测的场景
    - 作为其他复杂算法的基线对比

局限性：
    - 忽略非线性趋势和季节性波动
    - 长期外推可能偏离实际（播放量增长通常非线性）
"""

from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class TrendExtrapolationAlgorithm(BaseAlgorithm):
    """趋势外推预测算法（基于线性回归）

    使用最小二乘线性回归拟合历史播放量趋势，沿回归线外推预测。

    属性:
        name (str): 算法显示名称 "趋势外推"
        algorithm_id (str): 算法唯一标识 "trend_extrapolation"
        description (str): 算法描述
        category (str): 算法分类 "时间序列"
    """

    name = "趋势外推"
    algorithm_id = "trend_extrapolation"
    description = "使用线性回归外推未来趋势"
    category = "时间序列"

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行趋势外推预测

        使用最小二乘线性回归拟合历史播放量，外推至未来，
        预估达到目标播放量所需的时间。

        参数:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 预测结果对象

        算法步骤:
            1. 提取历史播放量序列
            2. 计算 x 均值 (x̄) 和 y 均值 (ȳ)
            3. 计算斜率: slope = Σ((x_i - x̄)(y_i - ȳ)) / Σ(x_i - x̄)²
            4. 计算截距: intercept = ȳ - slope × x̄
            5. 预测下一期播放量: y_next = slope × n + intercept
            6. 基于当前速度或外推估计达标时间
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 3:
            # 数据不足，使用保守的3%增长估计
            prediction = current_views * 1.03
            confidence = 0.3
            slope = 0
            future_predictions = []
        else:
            views = [h.get("view_count", 0) for h in history]
            n = len(views)

            # 最小二乘线性回归
            # x 的均值（数据点索引的平均值）
            x_mean = (n - 1) / 2
            # y 的均值（播放量的平均值）
            y_mean = sum(views) / n

            # 计算斜率: Σ((x_i - x̄)(y_i - ȳ)) / Σ(x_i - x̄)²
            numerator = sum((i - x_mean) * (views[i] - y_mean) for i in range(n))
            denominator = sum((i - x_mean) ** 2 for i in range(n))

            if denominator > 0:
                slope = numerator / denominator
            else:
                slope = 0  # 无法计算斜率（所有x值相同），默认为0

            # 计算截距: ȳ - slope × x̄
            intercept = y_mean - slope * x_mean

            # 预测下一期（第 n 个点）的播放量
            future_x = n
            prediction = slope * future_x + intercept
            prediction = max(0, prediction)  # 确保预测值非负

            # 生成未来3期的预测列表（供元数据使用）
            future_predictions = []
            for i in range(1, 4):
                fx = n - 1 + i
                fy = max(0, slope * fx + intercept)
                future_predictions.append(fy)

            # 置信度随数据量增加而提高
            confidence = min(0.85, 0.25 + len(history) * 0.1)

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
            "slope": slope if len(history) >= 3 else 0,
            "future_predictions": future_predictions if len(history) >= 3 else [],
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
