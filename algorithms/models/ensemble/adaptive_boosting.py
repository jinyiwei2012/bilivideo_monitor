"""
自适应提升 (AdaBoost) 算法模块
===============================

本模块实现了基于 AdaBoost 集成学习的 B 站视频播放量预测算法。
通过组合多个弱学习器（决策树桩）并重点关注难预测样本，
逐步提升整体预测精度。

核心原理：
    1. 初始化所有样本权重相等
    2. 每轮训练一个弱学习器（决策树桩），计算其加权误差
    3. 根据误差计算该学习器的权重 alpha（误差越小，权重越大）
    4. 更新样本权重：预测错误的样本获得更高权重，下一轮重点学习
    5. 最终预测 = Σ(alpha * 弱学习器预测) / Σ(alpha)

算法来源：Freund & Schapire (1997) "A Decision-Theoretic Generalization of
    On-Line Learning and an Application to Boosting"

适用场景：历史数据点 ≥ 10 的视频，可捕捉非线性增长模式。
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
import logging

from algorithms.base import BaseAlgorithm

logger = logging.getLogger(__name__)


class AdaBoostAlgorithm(BaseAlgorithm):
    """
    自适应提升 (AdaBoost) 播放量预测算法

    通过组合多个弱学习器（决策树桩）来预测视频播放量增长。
    每次迭代会重点关注上一轮预测误差较大的样本，
    从而逐步提升在困难数据点上的预测精度。

    类属性：
        name (str): 算法中文名称 "自适应提升"
        description (str): 算法简述
        category (str): 所属类别 "集成学习"
        n_estimators (int): 弱学习器数量，默认 15
        estimators (list): 存储训练好的决策树桩列表
        estimator_weights (list): 每个树桩对应的投票权重 (alpha)
    """

    name = "自适应提升"
    description = "AdaBoost集成学习，提高预测精度"
    category = "集成学习"

    def __init__(self):
        """初始化 AdaBoost 算法实例。

        设置默认弱学习器数量为 15，并初始化空的估计器和权重列表。
        """
        super().__init__()
        self.n_estimators = 15  # 弱学习器数量
        self.estimators = []  # 存储决策树桩（弱学习器）
        self.estimator_weights = []  # 每个树桩的投票权重

    def predict(
        self, current_views: int, target_views: int, history_data: List[Dict[str, Any]], video_info: Dict[str, Any]
    ) -> Optional[Tuple[int, float]]:
        """
        预测到达目标播放量所需的时间（秒）。

        Args:
            current_views (int): 当前播放量
            target_views (int): 目标播放量阈值
            history_data (List[Dict]): 历史监控数据列表，每条记录包含 view/like/coin/share/reply
            video_info (Dict): 视频基本信息字典

        Returns:
            Optional[Tuple[int, float]]:
                - 成功时返回 (所需秒数, 置信度)
                - 数据不足时返回 None
                - 置信度范围 [0, 1]，越接近 1 预测越可靠

        工作流程：
            1. 从历史数据中提取特征（播放量/点赞/投币/分享/评论 + 时间索引）
            2. 训练 AdaBoost 模型（15 轮迭代）
            3. 用最后一组特征预测平均每日增长量
            4. 根据剩余播放量计算所需天数，转换为秒
            5. 计算综合置信度
        """
        # 数据不足时直接返回 None
        if not history_data or len(history_data) < 10:
            return None

        try:
            # 准备训练数据：从历史记录中提取特征矩阵 X 和目标值 y
            X, y = self._prepare_data(history_data)

            if len(X) < 8:
                return None

            # 训练 AdaBoost 集成模型
            self._train(X, y)

            # 已达标直接返回
            if current_views >= target_views:
                return (0, 1.0)

            # 用最新特征预测每日播放量增长
            last_features = X[-1]  # 最后一组特征对应最新状态
            predicted_growth = self._predict_single(last_features)

            # 预测增长为负时回退到历史平均速度
            if predicted_growth <= 0:
                views = [d["view"] for d in history_data]
                predicted_growth = max(1, np.mean([views[i] - views[i - 1] for i in range(1, len(views))]))

            # 计算到达目标所需天数
            remaining = target_views - current_views
            days_needed = remaining / predicted_growth

            # 极端情况过滤
            if days_needed < 0 or days_needed > 3650:
                return None

            # 转换为秒并计算置信度
            seconds_needed = int(days_needed * 86400)
            confidence = self._calculate_confidence(X, y)

            return (seconds_needed, confidence)

        except Exception as e:
            logger.warning(f"AdaBoost预测失败: {e}")
            return None

    def _prepare_data(self, history_data: List[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray]:
        """
        从历史数据中提取特征矩阵和目标值。

        Args:
            history_data (List[Dict]): 历史监控数据列表

        Returns:
            Tuple[np.ndarray, np.ndarray]:
                - X: 特征矩阵，每行 6 个特征（view/like/coin/share/reply + 时间索引）
                - y: 目标值数组，每项为下一时间点的播放量增量

        特征说明：
            1. 播放量 / 10000（归一化）
            2. 点赞数 / 1000（归一化）
            3. 投币数 / 100（归一化）
            4. 分享数 / 100（归一化）
            5. 评论数 / 100（归一化）
            6. 时间索引 / 10（归一化）
        """
        X = []
        y = []

        for i in range(len(history_data) - 1):
            current = history_data[i]
            next_data = history_data[i + 1]

            # 构造 6 维特征向量，所有值做归一化处理
            features = [
                current.get("view", 0) / 10000,
                current.get("like", 0) / 1000,
                current.get("coin", 0) / 100,
                current.get("share", 0) / 100,
                current.get("reply", 0) / 100,
                i / 10,  # 时间索引归一化
            ]

            growth = next_data.get("view", 0) - current.get("view", 0)

            X.append(features)
            y.append(growth)

        return np.array(X), np.array(y)

    def _build_stump(self, X: np.ndarray, y: np.ndarray, weights: np.ndarray) -> Tuple[Dict, float]:
        """
        构建决策树桩（单层决策树）作为弱学习器。

        决策树桩只在一个特征上做一次分割，分为左右两个叶节点，
        每个叶节点的预测值为该节点内样本的均值。

        Args:
            X (np.ndarray): 特征矩阵 (n_samples, n_features)
            y (np.ndarray): 目标值数组
            weights (np.ndarray): 样本权重数组，用于计算加权误差

        Returns:
            Tuple[Dict, float]:
                - stump (Dict): 树桩信息，包含特征索引、阈值、极性、左右预测值
                - error (float): 该树桩的最小加权误差

        树桩结构：
            {
                "feature": int,          # 分割特征索引
                "threshold": float,      # 分割阈值
                "polarity": int,         # 极性（1 或 -1），控制分割方向
                "prediction_left": float, # 左子节点预测值
                "prediction_right": float # 右子节点预测值
            }
        """
        n_samples, n_features = X.shape

        best_error = float("inf")
        best_stump = {}

        # 遍历每个特征寻找最佳分割
        for feature in range(n_features):
            values = X[:, feature]
            thresholds = np.percentile(values, [30, 50, 70])  # 使用 3 个分位数作为候选阈值

            for threshold in thresholds:
                for polarity in [1, -1]:  # 尝试两种分割方向
                    # 初始预测为全局均值
                    predictions = np.ones(n_samples) * np.mean(y)
                    mask = values <= threshold

                    # 根据极性选择左/右子节点的均值作为预测
                    if polarity == 1:
                        predictions[mask] = np.mean(y[mask]) if np.sum(mask) > 0 else np.mean(y)
                    else:
                        predictions[~mask] = np.mean(y[~mask]) if np.sum(~mask) > 0 else np.mean(y)

                    # 计算加权绝对误差
                    error = np.sum(weights * np.abs(y - predictions))

                    if error < best_error:
                        best_error = error
                        best_stump = {
                            "feature": feature,
                            "threshold": threshold,
                            "polarity": polarity,
                            "prediction_left": np.mean(y[mask]) if np.sum(mask) > 0 else np.mean(y),
                            "prediction_right": np.mean(y[~mask]) if np.sum(~mask) > 0 else np.mean(y),
                        }

        return best_stump, best_error

    def _train(self, X: np.ndarray, y: np.ndarray):
        """
        训练 AdaBoost 集成模型。

        核心算法流程：
            1. 初始化所有样本权重为 1/n
            2. 迭代 n_estimators 轮：
               a. 构建加权误差最小的决策树桩
               b. 计算该树桩的投票权重 alpha（误差越小权重越大）
               c. 更新样本权重（预测误差大的样本获得更高权重）
               d. 归一化样本权重
            3. 存储所有树桩及其权重

        Args:
            X (np.ndarray): 特征矩阵
            y (np.ndarray): 目标值数组
        """
        n_samples = len(X)

        # 初始化样本权重：所有样本等权
        weights = np.ones(n_samples) / n_samples

        self.estimators = []
        self.estimator_weights = []

        for _ in range(self.n_estimators):
            # 构建当前加权条件下的最优树桩
            stump, error = self._build_stump(X, y, weights)

            # 误差 >= 0.5 说明不比随机猜测好，停止训练
            # 误差 == 0 说明完全拟合，继续训练无意义
            if error >= 0.5 or error == 0:
                break

            # 计算学习器权重 alpha：log((1-error)/error)
            # 误差越小 alpha 越大，该学习器在最终投票中权重越高
            alpha = 0.5 * np.log((1 - error) / (error + 1e-10))

            # 更新样本权重：预测不准的样本权重增大
            predictions = self._stump_predict(stump, X)
            weights *= np.exp(-alpha * np.sign(y - predictions) * np.abs(y - predictions) / 1000)
            weights /= np.sum(weights)  # 归一化确保和为 1

            self.estimators.append(stump)
            self.estimator_weights.append(alpha)

    def _stump_predict(self, stump: Dict, X: np.ndarray) -> np.ndarray:
        """
        使用决策树桩对多个样本进行预测。

        Args:
            stump (Dict): 决策树桩字典，包含 feature/threshold/prediction_left/prediction_right
            X (np.ndarray): 特征矩阵 (n_samples, n_features)

        Returns:
            np.ndarray: 预测值数组，形状 (n_samples,)
        """
        values = X[:, stump["feature"]]
        mask = values <= stump["threshold"]

        predictions = np.zeros(len(X))
        predictions[mask] = stump["prediction_left"]   # 小于等于阈值的样本
        predictions[~mask] = stump["prediction_right"]  # 大于阈值的样本

        return predictions

    def _predict_single(self, x: np.ndarray) -> float:
        """
        对单个样本进行加权预测。

        将所有弱学习器的预测值按其权重 alpha 加权平均。

        Args:
            x (np.ndarray): 单个样本的特征向量，形状 (n_features,)

        Returns:
            float: 加权预测值（日播放量增量）
        """
        prediction = 0
        total_weight = 0

        for stump, weight in zip(self.estimators, self.estimator_weights):
            value = x[stump["feature"]]
            if value <= stump["threshold"]:
                pred = stump["prediction_left"]
            else:
                pred = stump["prediction_right"]

            prediction += weight * pred  # 加权累加预测值
            total_weight += weight

        return prediction / total_weight if total_weight > 0 else 0

    def _calculate_confidence(self, X: np.ndarray, y: np.ndarray) -> float:
        """
        计算预测置信度。

        综合以下因素：
            - 数据量 n：越多越可靠
            - 拟合质量 MAPE：预测值与真实值的平均绝对百分比误差

        Args:
            X (np.ndarray): 特征矩阵
            y (np.ndarray): 真实目标值

        Returns:
            float: 置信度 [0, 0.9]
        """
        n = len(X)
        # 基础置信度：随数据量增加而提高
        base_conf = min(0.85, 0.3 + n * 0.02)

        # 结合拟合质量调整置信度
        if n >= 5 and len(self.estimators) > 0:
            predictions = np.array([self._predict_single(X[i]) for i in range(n)])
            mape = np.mean(np.abs((y - predictions) / (np.abs(y) + 1)))  # 平均绝对百分比误差
            fit_quality = max(0, 1 - mape)  # 拟合质量 = 1 - MAPE
            base_conf = 0.5 * base_conf + 0.5 * fit_quality

        return min(0.9, base_conf)
