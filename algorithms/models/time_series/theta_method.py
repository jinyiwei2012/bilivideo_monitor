"""
Theta方法预测算法 (Theta Method Prediction Algorithm)

Theta方法是M3预测竞赛的亚军方法，通过构造Theta线
（对时间序列做二阶差分变换）来提取趋势信号，
结合季节调整进行预测。

核心原理：
    1. 对原始时序做二阶差分，得到Theta线（theta=2时）
    2. Theta线代表去除季节波动后的长期趋势
    3. 用原始时序减去Theta线得到季节分量
    4. 对Theta线做线性外推，加上季节调整得到最终预测

数学公式：
    Theta_line = cumsum(cumsum(diff²(views)))
    seasonal = views - Theta_line
    forecast = Theta_line_extrapolation + seasonal_adjustment

参考:
    Assimakopoulos & Nikolopoulos (2000)
    "The theta model: a decomposition approach to forecasting"
    International Journal of Forecasting

适用场景：
    - 有明显趋势和季节性波动的视频
    - 需要简单但有效的序列分解场景
    - 作为复杂模型的轻量替代
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class ThetaMethodAlgorithm(BaseAlgorithm):
    """Theta方法预测算法

    通过对时间序列做二阶差分变换构造Theta线提取趋势，
    将序列分解为趋势+季节分量，分别外推后合成预测。

    属性:
        name (str): 算法显示名称 "Theta方法"
        algorithm_id (str): 算法唯一标识 "theta_method"
        description (str): 算法描述
        category (str): 算法分类 "时间序列"
        default_weight (float): 集成预测中的默认权重 1.2
    """

    name = "Theta方法"
    algorithm_id = "theta_method"
    description = "经典Theta线趋势外推，M3竞赛亚军"
    category = "时间序列"
    default_weight = 1.2

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """执行Theta方法预测

        对播放量序列做二阶差分构造Theta线，提取趋势和季节分量，
        外推趋势并加上季节调整后预测达标时间。

        参数:
            video_data (Dict): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 预测结果对象

        算法步骤:
            1. 取最近30个播放量数据点
            2. 计算二阶差分 diff²(views)
            3. 构造Theta线: cumsum(cumsum(diff²))
            4. 提取季节分量: views - Theta_line
            5. 对Theta线做线性回归外推
            6. 加上季节调整得到最终预测速度
            7. 计算达标时间
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足或速度为零时的回退
        if len(history) < 5 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "theta_fallback"}, timestamp=datetime.now(),
            )

        try:
            # 使用最近30个数据点（避免太久远的数据干扰）
            views = np.array([h.get("view_count", 0) for h in history[-30:]], dtype=np.float64)
            n = len(views)

            # Theta=2: 对时序做二阶差分得到Theta线
            theta = 2.0
            x = np.arange(n)
            diff2 = np.diff(views, 2)  # 二阶差分（相当于计算序列的"加速度"变化）
            if len(diff2) >= 3:
                # 通过两次累积和重构Theta线
                theta_line = np.cumsum(np.cumsum(np.insert(diff2, 0, [diff2[0], diff2[0]])))
                if len(theta_line) < n:
                    theta_line = np.pad(theta_line, (0, n - len(theta_line)), 'edge')
                theta_line = theta_line[:n]
                # 季节分量 = 原始序列 - Theta线
                seasonal = views - theta_line
            else:
                # 数据不足以做二阶差分，使用线性拟合作为趋势
                theta_line = np.polyval(np.polyfit(x, views, 1), x)
                seasonal = views - theta_line

            # 季节调整：用最后半个周期的平均值作为未来季节效应
            half_period = max(2, n // 4)
            season_mean = np.mean(seasonal[-half_period:])

            # 趋势外推：对Theta线做线性回归，沿趋势外推10步
            trend_slope = np.polyfit(x, theta_line, 1)[0]
            future = theta_line[-1] + trend_slope * np.arange(1, 11)  # 外推10个点
            future_adjusted = future + season_mean  # 加上季节调整

            # 计算预测速度（外推序列的平均差分除以3600秒/小时）
            growth = np.mean(np.diff(future_adjusted))
            predicted_velocity = max(0, growth / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity  # 速度过小时保持原速度

            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 and predicted_velocity > 0 else float("inf")
            # 置信度随数据量增加而提高
            confidence = min(0.85, 0.35 + 0.02 * min(n, 25))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={"method": "theta_method", "theta": theta, "data_points": n},
                timestamp=datetime.now(),
            )
        except Exception:
            # 计算异常时回退到速度估计
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "theta_error"}, timestamp=datetime.now(),
            )
