"""
卡尔曼滤波器
最优状态估计算法，可以处理噪声数据
适用于播放量数据的平滑和预测
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
import logging
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)


class KalmanFilterAlgorithm(BaseAlgorithm):
    """
    Kalman Filter for View Count Prediction

    状态空间模型:
    - 状态: [播放量, 增长率]
    - 观测: 实际播放量
    """

    name = "卡尔曼滤波器"
    description = "最优状态估计，处理噪声数据"
    category = "时间序列"
    algorithm_id = "kalman_filter"

    def __init__(self):
        super().__init__()
        # 状态转移矩阵
        self.F = np.array([[1, 1], [0, 1]])
        # 观测矩阵
        self.H = np.array([[1, 0]])
        # 过程噪声协方差
        self.Q = np.array([[0.01, 0], [0, 0.001]])
        # 观测噪声协方差
        self.R = np.array([[10000]])

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        target_views = threshold
        history_data = video_data.get("history_data", [])

        if not history_data or len(history_data) < 5:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=-1,
                confidence=0.0,
                current_views=current_views,
                current_velocity=self.calculate_velocity(video_data),
                metadata={},
                timestamp=datetime.now(),
            )

        try:
            views = [d.get("view_count", d.get("view", 0)) for d in history_data]

            x, P = self._kalman_filter(views)

            if current_views >= target_views:
                return PredictionResult(
                    algorithm_name=self.name,
                    algorithm_id=self.algorithm_id,
                    target_threshold=threshold,
                    predicted_hours=0,
                    confidence=1.0,
                    current_views=current_views,
                    current_velocity=self.calculate_velocity(video_data),
                    metadata={},
                    timestamp=datetime.now(),
                )

            growth_rate = x[1, 0]

            if growth_rate <= 0:
                if len(views) >= 2:
                    recent_growth = (views[-1] - views[-5]) / 4 if len(views) >= 5 else views[-1] - views[-2]
                    growth_rate = max(1, recent_growth)
                else:
                    return PredictionResult(
                        algorithm_name=self.name,
                        algorithm_id=self.algorithm_id,
                        target_threshold=threshold,
                        predicted_hours=-1,
                        confidence=0.0,
                        current_views=current_views,
                        current_velocity=self.calculate_velocity(video_data),
                        metadata={},
                        timestamp=datetime.now(),
                    )

            remaining = target_views - current_views

            days_needed = remaining / growth_rate

            if days_needed < 0 or days_needed > 3650:
                return PredictionResult(
                    algorithm_name=self.name,
                    algorithm_id=self.algorithm_id,
                    target_threshold=threshold,
                    predicted_hours=-1,
                    confidence=0.0,
                    current_views=current_views,
                    current_velocity=self.calculate_velocity(video_data),
                    metadata={},
                    timestamp=datetime.now(),
                )

            predicted_hours = days_needed * 24
            confidence = self._calculate_confidence(P, growth_rate)

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=self.calculate_velocity(video_data),
                metadata={},
                timestamp=datetime.now(),
            )

        except Exception as e:
            logger.warning(f"卡尔曼滤波预测失败: {e}")
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=-1,
                confidence=0.0,
                current_views=current_views,
                current_velocity=self.calculate_velocity(video_data),
                metadata={},
                timestamp=datetime.now(),
            )

    def _kalman_filter(self, measurements: List[float]) -> Tuple[np.ndarray, np.ndarray]:
        """
        执行卡尔曼滤波

        Args:
            measurements: 观测值列表

        Returns:
            (最终状态估计, 最终协方差矩阵)
        """
        # 初始化状态 [播放量, 增长率]
        if len(measurements) >= 2:
            x = np.array([[measurements[0]], [measurements[1] - measurements[0]]])
        else:
            x = np.array([[measurements[0]], [0]])

        # 初始化协方差
        P = np.array([[1000000, 0], [0, 10000]])

        for z in measurements[1:]:
            # 预测步骤
            x = self.F @ x
            P = self.F @ P @ self.F.T + self.Q

            # 更新步骤
            y = z - (self.H @ x)[0, 0]  # 残差
            S = self.H @ P @ self.H.T + self.R
            K = P @ self.H.T @ np.linalg.inv(S)  # 卡尔曼增益

            x = x + K * y
            P = (np.eye(2) - K @ self.H) @ P

        return x, P

    def _calculate_confidence(self, P: np.ndarray, growth_rate: float) -> float:
        """计算置信度"""
        # 协方差越小，置信度越高
        position_variance = P[0, 0]
        velocity_variance = P[1, 1]

        # 归一化方差
        pos_conf = max(0, 1 - position_variance / 100000000)
        vel_conf = max(0, 1 - velocity_variance / 10000)

        # 增长率必须为正
        if growth_rate <= 0:
            vel_conf *= 0.5

        confidence = 0.6 * pos_conf + 0.4 * vel_conf
        return min(0.95, max(0.3, confidence))
