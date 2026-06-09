"""
Bass扩散模型 (Bass Diffusion Model) 预测算法模块

Bass扩散模型是Frank Bass于1969年提出的经典创新扩散理论模型，用于描述新产品、新技术或内容
在社会网络中的传播与采纳过程。在B站视频播放量预测场景中，该模型将播放量增长视为视频在观众
网络中"扩散"的结果。

核心公式：
    dN(t)/dt = (p + q * N(t)/M) * (M - N(t))

其中：
    - N(t): 时间t时的累计播放量（累计采纳者数量）
    - M:    市场容量（视频的潜在最大播放量）
    - p:    创新系数 (coefficient of innovation)，表示观众自发发现视频的速率
    - q:    模仿系数 (coefficient of imitation)，表示观众受他人影响而观看的速率

模型特点：
    1. 将增长分解为"创新者"驱动（参数p）和"模仿者"驱动（参数q）
    2. p/q比值反映传播模式：p>>q为纯创新驱动，q>>p为病毒式传播
    3. 典型的S型曲线：初期缓慢、中期加速、后期饱和

实现流程：
    1. 检查历史数据是否充足（>=5条），不足则回退到速度法
    2. 用差分近似dN/dt，通过最小二乘法估计参数p和q
    3. 市场容量M估计为当前播放量的5倍或阈值的1.2倍
    4. 用拟合的p、q模拟预测曲线，找到达到阈值的时间点
    5. 置信度基于q/p比值和数据量

参考：Bass, F.M. (1969) "A New Product Growth for Model Consumer Durables"

所属分类：扩散模型类（category = "扩散模型"）
"""

import logging
import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)


class BassDiffusionAlgorithm(BaseAlgorithm):
    """Bass扩散模型预测算法

    基于Bass创新扩散理论，将视频播放量增长建模为社会网络中的信息传播过程。
    通过历史数据拟合创新系数p和模仿系数q，预测达到目标播放量所需时间。

    适用场景：
        - 播放量受社交传播影响较大的视频
        - 存在明显"跟风"效应的热点内容
        - 需要区分自发发现和社交影响贡献的场景

    类属性：
        name: 算法中文名称
        algorithm_id: 算法唯一标识符
        description: 算法简要描述
        category: 算法分类标签
        default_weight: 集成预测中的默认权重（略高于基准1.0）
    """

    name = "Bass扩散"
    algorithm_id = "bass_diffusion"
    description = "创新扩散理论建模视频传播曲线"
    category = "扩散模型"
    default_weight = 1.2

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """执行Bass扩散模型预测

        通过历史数据拟合Bass扩散模型的参数（p和q），然后模拟预测曲线
        来估计达到目标播放量阈值所需的时间。

        Args:
            video_data: 视频数据字典，必须包含以下字段：
                - view_count (int): 当前播放量
                - history_data (list): 历史数据列表，每条包含view_count和时间戳
            threshold: 目标播放量阈值，默认为 100000（10万播放）

        Returns:
            PredictionResult: 预测结果对象，包含：
                - predicted_hours: 预测到达阈值所需的小时数
                - confidence: 置信度 (0.3 ~ 0.85)
                - metadata: 包含预测方法、拟合参数p和q、市场容量M

                如果历史数据不足（<5条），使用速度法回退方案，
                置信度降为0.3。
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足时回退到简单的速度法预测
        if len(history) < 5 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "bass_fallback"}, timestamp=datetime.now(),
            )

        try:
            # 提取最近30条历史数据的播放量，转为numpy数组进行数值计算
            views = np.array([h.get("view_count", 0) for h in history[-30:]], dtype=np.float64)
            n = len(views)
            cum_views = views

            # 市场容量估计：当前播放量的5倍或阈值的1.2倍，取较大值
            M = max(current_views * 5, threshold * 1.2)

            # 用差分近似 dN/dt（播放量的逐时间段增量）
            dN = np.diff(cum_views)
            N = cum_views[:-1]  # 对应时间点的当前播放量
            mask = dN > 0  # 只考虑播放量增长的数据点

            if np.sum(mask) < 3:
                return self._fallback(velocity, current_views, threshold)

            # 最小二乘法估计参数p和q
            # 将 Bass 微分方程改写为线性形式：dN/(M-N) = p + q*(N/M)
            # y = dN/(M-N), X = [1, N/M]，回归系数即为 [p, q]
            y = dN[mask] / (M - N[mask])
            X = np.column_stack([np.ones(len(y)), N[mask] / M])
            try:
                coeffs = np.linalg.lstsq(X, y, rcond=None)[0]
                p, q = max(0.001, coeffs[0]), max(0.001, coeffs[1])  # 确保p、q为正
            except np.linalg.LinAlgError:
                p, q = 0.01, 0.05  # 矩阵不可逆时的默认参数

            # 用估计的p、q参数模拟预测曲线
            # Bass模型的解析解：F(t) = (1 - exp(-(p+q)*t)) / (1 + (q/p)*exp(-(p+q)*t))
            # N(t) = M * F(t)
            t = np.arange(0, 365 * 24, 1)  # 模拟一年内每小时
            F = (1 - np.exp(-(p + q) * t)) / (1 + q / p * np.exp(-(p + q) * t))
            N_pred = M * F + current_views * (1 - F)  # 预测播放量曲线
            target_idx = np.where(N_pred >= threshold)[0]  # 找到首次达到阈值的时间索引
            predicted_hours = target_idx[0] if len(target_idx) > 0 else remaining / velocity
            # 置信度：基于q/p比值（模仿/创新比值越大，置信度越高）
            # 和数据量（数据越多，拟合越可靠）
            confidence = min(0.85, 0.4 + 0.15 * min(q / p, 3) + 0.02 * min(n, 20))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={"method": "bass_diffusion", "p": round(p, 4), "q": round(q, 4), "M": M},
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.debug("Bass diffusion failed: %s", e)
            return self._fallback(velocity, current_views, threshold)

    def _fallback(self, velocity, current_views, threshold):
        """Bass模型拟合失败时的回退方案

        当历史数据不足或模型拟合失败时，回退到简单的速度法进行线性预测。

        Args:
            velocity: 当前播放速度（播放量/小时）
            current_views: 当前播放量
            threshold: 目标阈值播放量

        Returns:
            PredictionResult: 使用速度法的降级预测结果，置信度固定为0.3
        """
        remaining = threshold - current_views
        predicted_hours = remaining / velocity if velocity > 0 else float("inf")
        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=0.3, current_views=current_views, current_velocity=velocity,
            metadata={"method": "bass_fallback"}, timestamp=datetime.now(),
        )
