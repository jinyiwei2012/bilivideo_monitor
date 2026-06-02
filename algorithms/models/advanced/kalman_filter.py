"""
卡尔曼滤波预测算法 (Kalman Filter)
================================

基于卡尔曼滤波器的最优状态估计算法，用于处理有噪声的播放量数据。
卡尔曼滤波器能够从不完美的观测中估计出系统的隐藏状态（播放量及其增长率），
并对未来的状态做出预测。

核心原理：
    1. 状态空间模型 - 用两个隐藏状态描述系统：
        - x[0]: 当前播放量
        - x[1]: 播放量增长率（速度）
    2. 状态转移方程 - 假设播放量线性增长：
        x_{t+1} = F * x_t + noise
        F = [[1, 1], [0, 1]] (播放量 += 增长率，增长率保持不变)
    3. 观测方程 - 观测值等于真实值加噪声：
        z_t = H * x_t + noise
        H = [[1, 0]] (只观测播放量，不直接观测增长率)
    4. 递推更新 - 对每个观测值执行"预测-更新"两步：
        - 预测：基于上一时刻的状态和转移矩阵预测当前状态
        - 更新：利用当前观测值和卡尔曼增益修正预测

参数说明：
    Q (过程噪声): 模型本身的不确定性（播放量噪声 0.01，增长率噪声 0.001）
    R (观测噪声): 观测数据的不确定性（默认 10000）
    K (卡尔曼增益): 自动计算，控制观测值对状态修正的权重

适用场景：
    - 需要平滑有噪声的播放量数据
    - 需要估计隐藏的增长率状态
    - 数据量 >= 5 个历史点
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
import logging
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)


class KalmanFilterAlgorithm(BaseAlgorithm):
    """
    卡尔曼滤波预测算法

    主要功能：
        - 使用卡尔曼滤波器估计视频的"真实"播放量和增长率
        - 从噪声观测中提取平滑的趋势信息
        - 基于估计的增长率进行未来播放量预测

    状态空间模型设定：
        - 状态向量 x = [播放量, 增长率]^T
        - 状态转移矩阵 F = [[1, 1], [0, 1]]
          （每个时间步播放量增加一个增长率，增长率保持不变）
        - 观测矩阵 H = [[1, 0]]
          （只观测到播放量，增长率是隐藏状态）

    类属性：
        name (str)          : "卡尔曼滤波器"
        algorithm_id (str)  : "kalman_filter"
        description (str)   : 算法简要描述
        category (str)      : "时间序列"
    """

    name = "卡尔曼滤波器"
    description = "最优状态估计，处理噪声数据"
    category = "时间序列"
    algorithm_id = "kalman_filter"

    def __init__(self):
        """
        初始化卡尔曼滤波器

        设置四大矩阵参数：
            F (2x2): 状态转移矩阵 [[1, 1], [0, 1]]
            H (1x2): 观测矩阵 [[1, 0]]
            Q (2x2): 过程噪声协方差 [[0.01, 0], [0, 0.001]]
            R (1x1): 观测噪声协方差 [[10000]]
        """
        super().__init__()
        # 状态转移矩阵：每个时间步播放量 = 上一步播放量 + 增长率
        self.F = np.array([[1, 1], [0, 1]])
        # 观测矩阵：仅观测播放量（增长率不可直接观测）
        self.H = np.array([[1, 0]])
        # 过程噪声协方差：模型的不确定性（播放量 0.01，增长率 0.001）
        self.Q = np.array([[0.01, 0], [0, 0.001]])
        # 观测噪声协方差：播放量观测值的噪声方差
        self.R = np.array([[10000]])

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        使用卡尔曼滤波进行预测

        算法流程：
            1. 检查历史数据是否充足（至少 5 个点）
            2. 提取播放量序列
            3. 执行卡尔曼滤波递推，得到最终状态估计和协方差
            4. 提取估计的增长率作为预测基准
            5. 如果增长率为非正，用近期趋势修正
            6. 计算到达目标所需的天数和置信度

        Args:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        target_views = threshold
        history_data = video_data.get("history_data", [])

        # 数据不足（< 5 个点）：无法可靠运行卡尔曼滤波
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
            # 提取播放量时间序列
            views = [d.get("view_count", d.get("view", 0)) for d in history_data]

            # 执行卡尔曼滤波，得到最终状态估计 x 和协方差 P
            x, P = self._kalman_filter(views)

            # 已达标则直接返回
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

            # 提取估计的增长率（第二状态分量）
            growth_rate = x[1, 0]

            # 增长率为非正：尝试用近期趋势修正
            if growth_rate <= 0:
                if len(views) >= 2:
                    # 用最近 5 个点的平均增长量或最近 2 点的差值估算
                    recent_growth = (views[-1] - views[-5]) / 4 if len(views) >= 5 else views[-1] - views[-2]
                    growth_rate = max(1, recent_growth)  # 至少设为 1
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

            # 计算到达目标所需天数 = 剩余播放量 / 日增长率
            days_needed = remaining / growth_rate

            # 预测时间不合理（负数或超过 10 年）视为无效
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

            predicted_hours = days_needed * 24  # 天数转小时
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
        执行卡尔曼滤波递推

        对每个观测值依次执行预测步骤和更新步骤：
            预测步骤：
                x = F @ x           (根据转移矩阵预测下一状态)
                P = F @ P @ F^T + Q (更新协方差，加上过程噪声)
            更新步骤：
                y = z - H @ x       (计算残差 = 观测 - 预测)
                S = H @ P @ H^T + R (计算残差协方差)
                K = P @ H^T @ S^{-1}(计算卡尔曼增益)
                x = x + K * y       (用观测修正状态估计)
                P = (I - K @ H) @ P (更新协方差)

        Args:
            measurements (List[float]): 观测值列表（播放量时间序列）

        Returns:
            Tuple[np.ndarray, np.ndarray]: (最终状态估计向量 [2x1], 最终协方差矩阵 [2x2])
        """
        # 初始化状态 [播放量, 增长率]
        if len(measurements) >= 2:
            # 用前两个观测值初始化状态
            x = np.array([[measurements[0]], [measurements[1] - measurements[0]]])
        else:
            # 只有一个观测值时，设增长率为 0
            x = np.array([[measurements[0]], [0]])

        # 初始化协方差矩阵（较大的初始不确定性）
        P = np.array([[1000000, 0], [0, 10000]])

        # 对每个后续观测执行卡尔曼滤波递推
        for z in measurements[1:]:
            # ── 预测步骤 ──
            x = self.F @ x  # 状态预测：x_{k|k-1} = F * x_{k-1|k-1}
            P = self.F @ P @ self.F.T + self.Q  # 协方差预测：P_{k|k-1} = F * P_{k-1|k-1} * F^T + Q

            # ── 更新步骤 ──
            y = z - (self.H @ x)[0, 0]  # 残差 = 观测值 - 预测观测值
            S = self.H @ P @ self.H.T + self.R  # 残差协方差
            K = P @ self.H.T @ np.linalg.inv(S)  # 卡尔曼增益

            x = x + K * y  # 状态更新：x_{k|k} = x_{k|k-1} + K * y
            P = (np.eye(2) - K @ self.H) @ P  # 协方差更新：P_{k|k} = (I - K * H) * P_{k|k-1}

        return x, P

    def _calculate_confidence(self, P: np.ndarray, growth_rate: float) -> float:
        """
        基于卡尔曼滤波的协方差矩阵计算预测置信度

        置信度来源：
            1. 位置估计的精确度（协方差 P[0,0] 越小越精确）
            2. 增长率估计的精确度（协方差 P[1,1] 越小越精确）
            3. 增长率的符号（增长率必须为正才可信）

        综合公式：
            pos_conf = max(0, 1 - P[0,0] / 100000000)  # 位置置信度
            vel_conf = max(0, 1 - P[1,1] / 10000)      # 速度置信度
            confidence = 0.6 * pos_conf + 0.4 * vel_conf

        Args:
            P (np.ndarray): 协方差矩阵 [2x2]
            growth_rate (float): 估计的增长率

        Returns:
            float: 置信度值 (0.3 ~ 0.95)
        """
        # 协方差越小，置信度越高
        position_variance = P[0, 0]  # 播放量估计的不确定性
        velocity_variance = P[1, 1]  # 增长率估计的不确定性

        # 归一化方差：方差 / 参考值
        pos_conf = max(0, 1 - position_variance / 100000000)  # 位置置信度
        vel_conf = max(0, 1 - velocity_variance / 10000)  # 速度置信度

        # 增长率为非正时，速度置信度打对折
        if growth_rate <= 0:
            vel_conf *= 0.5

        # 综合置信度：位置 60% + 速度 40%
        confidence = 0.6 * pos_conf + 0.4 * vel_conf
        return min(0.95, max(0.3, confidence))  # 钳制在 [0.3, 0.95]
