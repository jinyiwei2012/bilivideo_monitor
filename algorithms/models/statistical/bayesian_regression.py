"""
贝叶斯回归 — Bayesian Linear Regression
=========================================

基于贝叶斯推断的回归方法，提供播放量预测及其不确定性估计。

核心原理：
  1. 假设回归系数服从先验正态分布
  2. 使用观测数据计算后验分布 p(w | y, X) ~ N(mean, cov)
  3. 后验协方差 = (αI + β XᵀX)⁻¹，后验均值 = β · cov · Xᵀ · y
  4. 利用后验均值预测未来增长量，利用后验协方差计算不确定性
  5. 不确定性越低 → 置信度越高

适用场景：数据量适中（>=6 条历史记录），希望获得预测区间估计
"""

import numpy as np
from typing import List, Dict, Any, Tuple
from datetime import datetime
import logging

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)


class BayesianRegressionAlgorithm(BaseAlgorithm):
    """
    贝叶斯线性回归预测算法

    使用贝叶斯方法进行回归，核心优势是能提供预测的不确定性估计。
    通过先验精度 α 和噪声精度 β 控制模型的复杂度。

    属性:
        alpha (float): 先验精度参数，控制系数收缩强度
        beta (float): 噪声精度参数，控制观测噪声
        mean (np.ndarray): 后验分布的均值向量
        cov (np.ndarray): 后验分布的协方差矩阵
    """

    name = "贝叶斯回归"
    algorithm_id = "bayesian_regression"
    description = "基于贝叶斯推断，提供不确定性估计"
    category = "概率模型"

    def __init__(self):
        """初始化贝叶斯回归模型，设置默认先验参数"""
        super().__init__()
        self.alpha = 1.0  # 先验精度（正则化强度）
        self.beta = 1.0  # 噪声精度（观测噪声的倒数）
        self.mean = None  # 后验均值向量
        self.cov = None  # 后验协方差矩阵

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        预测到达目标播放量所需的小时数

        流程:
          1. 检查历史数据是否充足（>=6 条）
          2. 准备特征矩阵 X 和标签向量 y
          3. 执行贝叶斯推断，获取后验分布
          4. 用后验均值预测当前增量
          5. 用后验协方差计算不确定性 → 置信度

        参数:
            video_data (Dict): 视频数据字典，包含 view_count、history_data 等
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 包含预测小时数、置信度、元数据等
        """
        current_views = video_data.get("view_count", 0)
        history_data = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足时返回无效预测
        if not history_data or len(history_data) < 6:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=float("inf"),
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"error": "Insufficient data"},
                timestamp=datetime.now(),
            )

        try:
            # 准备数据：提取特征和标签
            X, y = self._prepare_data(history_data)

            # 特征数太少，无法有效拟合
            if len(X) < 5:
                return PredictionResult(
                    algorithm_name=self.name,
                    algorithm_id=self.algorithm_id,
                    target_threshold=threshold,
                    predicted_hours=float("inf"),
                    confidence=0.0,
                    current_views=current_views,
                    current_velocity=velocity,
                    metadata={"error": "Insufficient processed data"},
                    timestamp=datetime.now(),
                )

            # 执行贝叶斯推断
            self._bayesian_inference(X, y)

            # 已达阈值，无需预测
            if current_views >= threshold:
                return PredictionResult(
                    algorithm_name=self.name,
                    algorithm_id=self.algorithm_id,
                    target_threshold=threshold,
                    predicted_hours=0,
                    confidence=1.0,
                    current_views=current_views,
                    current_velocity=velocity,
                    metadata={"method": "bayesian_regression", "status": "already_reached"},
                    timestamp=datetime.now(),
                )

            # 使用后验均值预测当前增量
            last_features = X[-1]  # 最新数据点的特征
            predicted_growth = np.dot(self.mean, last_features)  # wᵀx 线性预测

            # 使用后验协方差计算预测不确定性
            uncertainty = np.sqrt(last_features @ self.cov @ last_features)

            # 若预测增量为负或零，使用历史平均增量作为兜底
            if predicted_growth <= 0:
                views = [d.get("view_count", 0) for d in history_data]
                predicted_growth = max(1, np.mean([views[i] - views[i - 1] for i in range(1, len(views))]))

            remaining = threshold - current_views
            days_needed = remaining / predicted_growth

            # 预测时间过长或异常，判定无效
            if days_needed < 0 or days_needed > 3650:
                return PredictionResult(
                    algorithm_name=self.name,
                    algorithm_id=self.algorithm_id,
                    target_threshold=threshold,
                    predicted_hours=float("inf"),
                    confidence=0.0,
                    current_views=current_views,
                    current_velocity=velocity,
                    metadata={"error": "Prediction too far"},
                    timestamp=datetime.now(),
                )

            predicted_hours = days_needed * 24

            # 置信度基于不确定性的相对大小
            confidence = self._calculate_confidence(uncertainty, predicted_growth)

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={
                    "method": "bayesian_regression",
                    "uncertainty": float(uncertainty),
                    "predicted_growth": float(predicted_growth),
                },
                timestamp=datetime.now(),
            )

        except Exception as e:
            logger.warning(f"贝叶斯回归预测失败: {e}")
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=float("inf"),
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"error": str(e)},
                timestamp=datetime.now(),
            )

    def _prepare_data(self, history_data: List[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray]:
        """
        准备特征矩阵和标签向量

        特征 (5 维):
          [1, view/10000, like/1000, coin/100, share/100]
          其中第 0 维为偏置项 (intercept)

        标签:
          下一条记录的 view 减去当前记录的 view（即单期增量）

        参数:
            history_data (List[Dict]): 历史数据列表，每条包含 view, like, coin, share

        返回:
            Tuple[np.ndarray, np.ndarray]: (特征矩阵 X, 标签向量 y)
        """
        X = []
        y = []

        for i in range(len(history_data) - 1):
            current = history_data[i]
            next_data = history_data[i + 1]

            # 特征构造：播放量归一化到万，点赞到千，投币/分享到百
            features = [
                1.0,  # 偏置项
                current.get("view", 0) / 10000,
                current.get("like", 0) / 1000,
                current.get("coin", 0) / 100,
                current.get("share", 0) / 100,
            ]

            # 标签为相邻两点播放量之差
            growth = next_data.get("view", 0) - current.get("view", 0)

            X.append(features)
            y.append(growth)

        return np.array(X), np.array(y)

    def _bayesian_inference(self, X: np.ndarray, y: np.ndarray):
        """
        执行贝叶斯推断，计算后验分布

        先验: p(w) ~ N(0, α⁻¹I)  — 零均值高斯先验
        似然: p(y|X,w) ~ N(Xw, β⁻¹I)  — 高斯噪声模型
        后验: p(w|y,X) ~ N(mean, cov)

        计算公式:
          cov = (αI + βXᵀX)⁻¹
          mean = β · cov · Xᵀy

        参数:
            X (np.ndarray): 特征矩阵 (n_samples, n_features)
            y (np.ndarray): 标签向量 (n_samples,)
        """
        n_features = X.shape[1]

        # 先验协方差 = α⁻¹I（此处仅做类型标注，实际未使用局部变量）
        np.eye(n_features) / self.alpha

        # 后验协方差: (αI + βXᵀX)⁻¹
        # αI 提供正则化，βXᵀX 来自数据
        self.cov = np.linalg.inv(self.alpha * np.eye(n_features) + self.beta * X.T @ X)

        # 后验均值: β · cov · Xᵀ · y
        # 等价于加权最小二乘解的贝叶斯版本
        self.mean = self.beta * self.cov @ X.T @ y

    def _calculate_confidence(self, uncertainty: float, predicted_growth: float) -> float:
        """
        基于不确定性计算置信度

        逻辑:
          - 相对不确定性 = uncertainty / (|growth| + 100)
          - 置信度 = 1 - 相对不确定性 × 0.5
          - 若预测增量为负，置信度减半
          - 最终限制在 [0.3, 0.95]

        参数:
            uncertainty (float): 预测的标准差（后验协方差算出）
            predicted_growth (float): 预测的单期增长量

        返回:
            float: 置信度，范围 [0.3, 0.95]
        """
        # 不确定性越低，置信度越高
        # 归一化不确定性：除以增长量（+100 防止除零）
        relative_uncertainty = uncertainty / (abs(predicted_growth) + 100)

        confidence = max(0, 1 - relative_uncertainty * 0.5)

        # 预测增量为负 → 模型不可靠，折半处理
        if predicted_growth <= 0:
            confidence *= 0.5

        return min(0.95, max(0.3, confidence))
