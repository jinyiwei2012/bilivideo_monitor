"""
趋势回归预测算法 (Trend Regression Prediction Algorithm)

使用多项式回归（最高2次）对历史播放量数据进行拟合，
通过求解多项式方程来计算达到目标播放量所需的时间。

核心原理：
    将播放量视作时间的多项式函数 y = f(t)，
    使用 np.polyfit 拟合多项式系数，然后求解方程 f(t) = threshold
    得到预计达标时间。最高使用2次多项式以平衡拟合精度和泛化能力。

数学基础：
    - 1次多项式（线性）: y = a₁t + a₀
    - 2次多项式（二次）: y = a₂t² + a₁t + a₀
    - 求根：使用 np.roots 求解多项式方程 a₂t² + a₁t + (a₀-threshold) = 0

适用场景：
    - 播放量呈加速增长（二次系数 > 0）或减速增长（二次系数 < 0）的视频
    - 需要同时考虑线性和非线性趋势的场景

局限性：
    - 多项式阶数过高容易过拟合
    - 长期外推可能大幅偏离实际
"""

from datetime import datetime
from typing import Dict, Any
import numpy as np
from algorithms.base import BaseAlgorithm, PredictionResult


class TrendRegressionAlgorithm(BaseAlgorithm):
    """趋势回归预测算法

    使用多项式回归（最高2次）拟合历史播放量随时间的变化趋势，
    通过求解多项式方程的根来计算达到目标播放量的时间点。

    属性:
        name (str): 算法显示名称 "趋势回归"
        algorithm_id (str): 算法唯一标识 "trend_regression"
        description (str): 算法描述
        category (str): 算法分类 "机器学习"
        default_weight (float): 集成预测中的默认权重 1.2
    """

    name = "趋势回归"
    algorithm_id = "trend_regression"
    description = "基于历史数据的多项式回归预测"
    category = "机器学习"
    default_weight = 1.2

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行趋势回归预测

        使用多项式回归拟合历史播放量，求解多项式方程计算达标时间。

        参数:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 预测结果对象

        算法步骤:
            1. 将历史数据的时间转换为相对于起始时间的小时数
            2. 使用 np.polyfit 进行多项式拟合（次数 = min(2, n-1)）
            3. 构造目标方程: poly(t) - threshold = 0
            4. 使用 np.roots 求解方程的正实数根
            5. 取最小的正实数根作为预计达标时间
            6. 若无正实数根，使用当前速度作为回退
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        if len(history) < 3:
            # 数据不足，使用当前速度的线性估算
            velocity = self.calculate_velocity(video_data)
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
            elif velocity <= 0:
                predicted_hours = float("inf")
            else:
                predicted_hours = remaining / velocity
            confidence = 0.4
        else:
            try:
                # 准备数据：以第一个数据点的时间为基准，转换为相对小时数
                base_time = history[0].get("timestamp", 0)
                X = np.array([(h.get("timestamp", 0) - base_time) / 3600 for h in history])
                y = np.array([h.get("view_count", 0) for h in history])

                # 多项式回归：次数不超过数据点数-1，最高为2次
                degree = min(2, len(history) - 1)
                coeffs = np.polyfit(X, y, degree)
                np.poly1d(coeffs)

                # 求解达到阈值的时间: poly(t) = threshold
                # 等价于求解 poly(t) - threshold = 0
                coeffs_target = coeffs.copy()
                coeffs_target[-1] -= threshold  # 常数项减去阈值
                roots = np.roots(coeffs_target)  # 求多项式方程的根

                # 筛选实数正根（时间必须大于当前最后时间点）
                real_roots = [r.real for r in roots if np.isreal(r) and r.real > X[-1]]

                if real_roots:
                    # 取最小的正实数根作为达标时间，减去已过去的时间
                    predicted_hours = min(real_roots) - (history[-1].get("timestamp", 0) - base_time) / 3600
                    if predicted_hours < 0:
                        predicted_hours = 0
                    confidence = 0.7
                else:
                    # 无实数解（在当前模型下永远无法达标），使用当前速度估算
                    velocity = (y[-1] - y[-2]) / (X[-1] - X[-2]) if len(X) > 1 and X[-1] != X[-2] else 0
                    remaining = threshold - current_views
                    predicted_hours = remaining / velocity if velocity > 0 else float("inf")
                    confidence = 0.5

            except Exception:
                # 回归计算异常，回退到速度估计
                velocity = self.calculate_velocity(video_data)
                remaining = threshold - current_views
                if remaining <= 0:
                    predicted_hours = 0
                elif velocity <= 0:
                    predicted_hours = float("inf")
                else:
                    predicted_hours = remaining / velocity
                confidence = 0.4

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=self.calculate_velocity(video_data),
            metadata={"method": "trend_regression", "history_points": len(history)},
            timestamp=datetime.now(),
        )
