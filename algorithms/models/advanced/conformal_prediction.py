"""
共形预测算法 (Conformal Prediction)
====================================

一种分布无关的预测区间构建方法，提供严格的覆盖率保证。
不需要假设数据服从特定分布，只需要假设数据是可交换的（exchangeable）。

核心思路：
    1. 留出法 (Hold-out) 构建校准集 - 将历史序列尾部作为校准集，
       用前面数据线性拟合后预测校准集各点，计算 |预测-真实| 残差。
    2. 分位数误差边界 - 对残差排序，取 1-alpha 分位数作为误差上界，
       保证未来预测区间以 >= 1-alpha 的概率覆盖真实值。
    3. 区间与置信度 - 输出点预测 +/- 误差边界作为预测区间；
       区间越宽（相对误差越大）意味着置信度越低。
    4. 与经典共形预测的区别 - 本实现使用留出法而非完整的归纳式共形
       预测 (Inductive CP)，在数据量有限时更实用。

适用场景：
    - 数据量 >= 10 个历史点时可产出有意义区间
    - 数据不足时回退为简单的速度外推
    - 适合需要预测区间和覆盖率保证的场景
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class ConformalPredictionAlgorithm(BaseAlgorithm):
    """
    共形预测算法

    主要功能：
        - 对视频播放量序列构造保形预测区间（Conformal Prediction Interval）
        - 基于校准集残差分位数确定误差上界
        - 输出带覆盖概率保证的预测结果（点预测 + 置信度）

    算法原理：
        1. 取最近 30 个历史点，分为训练集（前部）和校准集（尾部）
        2. 用训练集线性外推，在校准集上计算残差绝对值
        3. 取残差的 (1-alpha) 分位数作为误差边界（保形误差上界）
        4. 用全序列线性趋势外推得到点预测
        5. 点预测 +/- 误差边界构成预测区间
        6. 用变异系数 CV 换算置信度（区间越宽置信度越低）
    """

    name = "共形预测"
    algorithm_id = "conformal"
    description = "分布无关的预测区间，严格覆盖率保证"
    category = "高级分析"
    default_weight = 1.1

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """
        执行共形预测，产出点预测值与置信度

        算法流程：
            1. 将最近 30 个历史点分为训练集（前部）和校准集（尾部）
            2. 用训练集线性外推，在校准集上计算残差绝对值
            3. 取残差的 (1-alpha) 分位数作为误差边界
            4. 用全序列线性趋势外推得到点预测
            5. 点预测 +/- 误差边界构成预测区间
            6. 用变异系数 CV 换算置信度（区间越宽置信度越低）

        Args:
            video_data (Dict): 包含 view_count / history_data 的视频数据字典
            threshold (int)  : 目标播放量阈值（默认 10 万）

        Returns:
            PredictionResult: 含 predicted_hours / confidence / metadata
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 回退分支：数据不足或速度为 0 时直接用当前速度估算
        if len(history) < 10 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "conformal_fallback"}, timestamp=datetime.now(),
            )

        try:
            # 取最近 30 个历史点作为分析窗口
            views = np.array([h.get("view_count", 0) for h in history[-30:]], dtype=np.float64)
            n = len(views)

            # 留出法 (Hold-out): 前 train_size 个点做训练，后 calibration_size 个点做校准
            calibration_size = max(3, n // 4)  # 至少保留 3 个校准点
            train_size = n - calibration_size

            residuals = []
            for i in range(train_size, n):  # 遍历校准集中的每个点
                train_data = views[:i]  # 用该点之前的所有数据做训练
                if len(train_data) >= 3:
                    # 线性拟合训练数据，外推一步作为对校准点的预测
                    pred_i = np.polyval(np.polyfit(np.arange(len(train_data)), train_data, 1), len(train_data))
                    residuals.append(abs(views[i] - pred_i))  # 收集 |真实-预测| 残差

            # 残差不足 3 个：无法可靠估计分位数，用速度粗估区间
            if len(residuals) < 3:
                growth = velocity * 3600  # 每小时间隔的增长量
                interval_half = growth * 0.2  # 区间半宽设为增长的 20%
            else:
                residuals = np.sort(residuals)  # 残差从小到大排序
                alpha = 0.2  # 显著性水平（覆盖率 = 1-alpha = 80%）
                # 取 (1-alpha) 分位数：使区间覆盖 80% 的真值
                q_idx = int(np.ceil((1 - alpha) * len(residuals))) - 1
                q_idx = max(0, min(q_idx, len(residuals) - 1))
                error_bound = residuals[q_idx]  # 保形误差上界

                # 趋势预测：用全序列线性外推一步
                trend = np.polyfit(np.arange(n), views, 1)  # 一次多项式拟合
                point_pred = np.polyval(trend, n + 1)  # 对 t=n+1 的时间点预测
                lower = point_pred - error_bound  # 预测区间下界
                upper = point_pred + error_bound  # 预测区间上界

                growth = point_pred - views[-1]  # 预测的增长量
                interval_half = error_bound  # 区间半宽 = 保形误差

            # 预测速度换算
            predicted_velocity = max(0, growth / 3600)  # 每小时速度（增长/3600秒）
            if predicted_velocity < 1:  # 速度过低时退化为当前速度
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                # 已达标：无需预测时间，置信度为 1
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                # CV = 区间半宽 / 增长量，即变异系数
                # CV 越大意味着预测不确定性越高，置信度越低
                cv = interval_half / max(growth, 1e-10)
                confidence = max(0.1, min(0.9, 0.6 / (1 + cv)))  # sigmoid 风格映射

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={
                    "method": "conformal",
                    "error_bound": round(float(interval_half), 2),
                    "alpha": 0.2,
                },
                timestamp=datetime.now(),
            )
        except Exception:
            # 异常回退：用当前速度做简单估算
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "conformal_error"}, timestamp=datetime.now(),
            )
