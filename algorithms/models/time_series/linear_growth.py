"""
线性增长预测算法 (Linear Growth Prediction Algorithm)

基于历史播放量数据的增长率，预测未来的线性增长趋势。

核心原理：
    计算历史每期之间的增长率（相对增长和绝对增长），
    取平均值作为未来增长的估计。同时用绝对增长量乘以增长率
    来保证预测的合理性。

适用场景：
    - 播放量稳定增长的视频
    - 数据量较少的初期预测
    - 作为其他复杂算法的基线参考

算法步骤:
    1. 计算每期相对增长率: (y_{i} - y_{i-1}) / y_{i-1}
    2. 计算每期绝对增长量: y_{i+1} - y_i
    3. 取平均增长率作为未来预测
    4. 根据当前速度或日均增长估计达标时间
"""

from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class LinearGrowthAlgorithm(BaseAlgorithm):
    """线性增长预测算法

    基于历史数据的平均增长率和绝对增长量，
    对未来播放量进行线性外推预测。

    属性:
        name (str): 算法显示名称 "线性增长"
        algorithm_id (str): 算法唯一标识 "linear_growth"
        description (str): 算法描述
        category (str): 算法分类 "时间序列"
    """

    name = "线性增长"
    algorithm_id = "linear_growth"
    description = "基于历史平均增长率预测未来值"
    category = "时间序列"

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行线性增长预测

        计算历史播放量的平均增长率和平均绝对增长量，
        预估达到目标播放量所需的时间。

        参数:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 预测结果对象

        算法步骤:
            1. 从历史数据提取播放量序列
            2. 计算每期相对增长率（百分比）
            3. 计算每期绝对增长量
            4. 取平均值作为增长预测
            5. 基于增长量或当前速度估计达标时间
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 2:
            # 数据不足，使用保守的1%增长率
            growth_rate = 0.01
            avg_growth = current_views * growth_rate
            confidence = 0.3
        else:
            views = [h.get("view_count", 0) for h in history]

            # 计算每期相对增长率 (y_{i} - y_{i-1}) / y_{i-1}
            growths = []
            for i in range(1, len(views)):
                if views[i - 1] > 0:
                    growth = (views[i] - views[i - 1]) / views[i - 1]
                    growths.append(max(0, growth))  # 仅保留非负增长

            if growths:
                avg_growth_rate = sum(growths) / len(growths)
            else:
                avg_growth_rate = 0.01  # 默认1%增长率

            # 计算平均绝对增长量
            abs_growths = [max(0, views[i + 1] - views[i]) for i in range(len(views) - 1)]
            avg_growth = sum(abs_growths) / max(1, len(abs_growths))

            # 如果平均增长太小，使用相对增长率修正
            if avg_growth < current_views * 0.001:
                avg_growth = current_views * avg_growth_rate

            # 置信度随历史数据量增加而提高
            confidence = min(0.9, 0.3 + len(history) * 0.1)

        # 预测达到阈值的时间
        predicted_hours = float("inf")
        if avg_growth > 0 and current_views < threshold:
            remaining = threshold - current_views
            if velocity > 0:
                predicted_hours = remaining / velocity
            else:
                # 速度为零时使用日均增长量换算（除以24将天转为小时）
                predicted_hours = remaining / (avg_growth / 24)
        elif current_views >= threshold:
            predicted_hours = 0
            confidence = 1.0

        metadata = {
            "avg_growth": avg_growth,
            "growth_rate": avg_growth / max(1, current_views),
            "data_points": len(history),
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
