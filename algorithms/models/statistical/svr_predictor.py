"""
支持向量回归 — Support Vector Regression (SVR)
================================================

基于支持向量机的回归方法，适用于非线性播放量预测。

核心原理：
  1. SVR 目标：在 ε-不敏感管道 ±ε 内拟合数据，管道外的点被惩罚
  2. 损失函数：ε-不敏感损失 = max(0, |r| - ε)
     即残差在 [-ε, ε] 内的不计算损失，大于 ε 的损失为 |r| - ε
  3. 使用梯度下降训练简化版 SVR：
     - 对每个样本，若 |error| > ε 则更新参数
     - 正则化项 (C) 控制模型复杂度
     - 带早停机制：loss 连续 patience 轮不降则停止
  4. 特征包括时间步、播放量、点赞、投币、分享数

适用场景：历史数据 >= 10 条，播放量增长具有非线性特征
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
import logging
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)


class SVRPredictorAlgorithm(BaseAlgorithm):
    """
    支持向量回归预测算法

    使用 SVR 进行播放量预测，适合处理非线性关系和异常值。
    实现简化版 SVR（无核技巧），使用梯度下降 + 早停训练。

    属性:
        epsilon (float): ε-不敏感管道的宽度，默认 0.1
        C (float): 正则化参数，控制模型复杂度，默认 1.0
        gamma (float): 核宽度参数（简化版中未使用），默认 0.1
    """

    name = "支持向量回归"
    description = "基于SVM的非线性回归预测"
    category = "统计模型"
    algorithm_id = "svr_predictor"

    def __init__(self):
        """初始化 SVR 模型参数"""
        super().__init__()
        self.epsilon = 0.1  # ε-不敏感管道宽度
        self.C = 1.0  # 正则化强度
        self.gamma = 0.1  # 核参数（预留）

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行 SVR 预测

        流程:
          1. 检查历史数据是否充足（>= 10 条）
          2. 构建特征矩阵和标签向量
          3. 用梯度下降 + 早停训练 SVR
          4. 用训练后的权重预测当前增量
          5. 计算到达目标所需天数和置信度

        参数:
            video_data (Dict): 视频数据，包含 view_count、history_data 等
            threshold (int): 目标播放量阈值

        返回:
            PredictionResult: 预测结果
        """
        current_views = video_data.get("view_count", 0)
        target_views = threshold
        history_data = video_data.get("history_data", [])
        video_info = video_data

        # 数据不足，返回无效预测
        if not history_data or len(history_data) < 10:
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
            # 构建特征和标签
            X, y = self._prepare_features(history_data)

            # 有效样本数不足
            if len(X) < 5:
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

            # 训练 SVR 模型
            weights, bias = self._train_svr(X, y)

            # 已达目标
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

            # 用最新特征预测当前增量
            last_features = X[-1]
            current_growth = np.dot(weights, last_features) + bias

            # 增量为负时的回退策略
            if current_growth <= 0:
                views = [d.get("view_count", d.get("view", 0)) for d in history_data]
                current_growth = max(1, (views[-1] - views[0]) / len(views))  # 使用平均增速

            remaining = target_views - current_views
            days_needed = remaining / current_growth

            # 预测不合理
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

            predicted_hours = days_needed * 24  # 转换为小时
            confidence = self._calculate_confidence(X, y, weights, bias)

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
            logger.warning(f"SVR预测失败: {e}")
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

    def _prepare_features(self, history_data: List[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray]:
        """
        准备特征矩阵和标签向量

        特征 (5 维):
          [时间步索引, 当前播放量, 点赞数, 投币数, 分享数]

        标签:
          下一条记录的播放量 - 当前播放量（单期增量）

        所有特征做 Z-score 标准化。

        参数:
            history_data (List[Dict]): 历史数据列表

        返回:
            Tuple[np.ndarray, np.ndarray]: (标准化特征矩阵, 标签向量)
        """
        X = []
        y = []

        for i in range(len(history_data) - 1):
            current = history_data[i]
            next_data = history_data[i + 1]

            # 特征：时间步 + 4 维互动指标
            features = [
                i,  # 时间步（序列位置，隐含时间趋势）
                current.get("view", 0),  # 当前播放量
                current.get("like", 0),  # 点赞数
                current.get("coin", 0),  # 投币数
                current.get("share", 0),  # 分享数
            ]

            # 标签：相邻两点播放量之差
            growth = next_data.get("view", 0) - current.get("view", 0)

            X.append(features)
            y.append(growth)

        # Z-score 标准化（保存均值/标准差以便预测时标准化新数据）
        X = np.array(X, dtype=float)
        y = np.array(y, dtype=float)

        if len(X) > 0:
            self.X_mean = np.mean(X, axis=0)
            self.X_std = np.std(X, axis=0) + 1e-8  # +1e-8 防止除零
            X = (X - self.X_mean) / self.X_std

        return X, y

    def _train_svr(self, X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        训练简化版 SVR 模型（含早停机制）

        算法流程:
          1. 零初始化权重和偏置
          2. 对每个 epoch:
             a. 遍历所有样本计算预测和误差
             b. 若 |error| > ε 则更新参数（ε-不敏感损失梯度下降）
             c. 正则化项: C·w/n_samples
             d. 早停检查: 连续 patience 轮无改善则停止

        参数:
            X (np.ndarray): 标准化特征矩阵 (n_samples, n_features)
            y (np.ndarray): 标签向量 (n_samples,)

        返回:
            Tuple[np.ndarray, float]: (权重向量, 偏置)
        """
        n_samples, n_features = X.shape

        # 初始化参数为零
        weights = np.zeros(n_features)
        bias = 0.0

        # 梯度下降超参数
        lr = 0.01  # 学习率
        max_epochs = 100  # 最大 epoch 数
        patience = 5  # 早停耐心轮数
        best_loss = float("inf")  # 最佳损失（用于早停）
        no_improve = 0  # 连续未改善计数

        for epoch in range(max_epochs):
            epoch_loss = 0.0
            for i in range(n_samples):
                prediction = np.dot(weights, X[i]) + bias  # wᵀx + b
                error = y[i] - prediction  # 残差

                # ε-不敏感损失: L = max(0, |error| - ε)
                if abs(error) > self.epsilon:
                    epoch_loss += abs(error) - self.epsilon  # 累积 ε-不敏感损失
                    if error > 0:  # 正误差 → 沿梯度下降方向更新
                        grad_w = -X[i] + self.C * weights / n_samples  # 梯度：-x + λw/N
                        grad_b = -1  # 偏置梯度
                    else:  # 负误差
                        grad_w = X[i] + self.C * weights / n_samples
                        grad_b = 1

                    # 参数更新
                    weights -= lr * grad_w
                    bias -= lr * grad_b

            # ── 早停检查 ───────────────────────
            if epoch_loss < 1e-6:  # 损失已极小
                break
            if epoch_loss < best_loss:  # 改善
                best_loss = epoch_loss
                no_improve = 0
            else:  # 未改善
                no_improve += 1
                if no_improve >= patience:  # 连续 patience 轮无改善
                    break

        return weights, bias

    def _calculate_confidence(self, X: np.ndarray, y: np.ndarray, weights: np.ndarray, bias: float) -> float:
        """
        计算预测置信度

        基于样本数量和拟合质量（MAPE）综合评估。

        参数:
            X (np.ndarray): 特征矩阵
            y (np.ndarray): 标签向量
            weights (np.ndarray): SVR 权重
            bias (float): SVR 偏置

        返回:
            float: 置信度，范围 [0, 0.9]
        """
        n = len(X)

        # 基础置信度：样本越多越可信（上限 0.85）
        base_conf = min(0.85, 0.3 + n * 0.03)

        # 拟合质量：MAPE 越低质量越高
        if n >= 5:
            predictions = X @ weights + bias
            mape = np.mean(np.abs((y - predictions) / (np.abs(y) + 1)))  # 平均绝对百分比误差
            fit_quality = max(0, 1 - mape)  # 拟合质量 = 1 - MAPE
            # 综合基础置信度和拟合质量
            base_conf = 0.5 * base_conf + 0.5 * fit_quality

        return min(0.9, base_conf)
