"""
梯度提升预测算法模块
====================

本模块实现了基于梯度提升（Gradient Boosting）的 B 站视频播放量预测算法。
优先使用 sklearn.ensemble.GradientBoostingRegressor 真实实现，若库不可用或
训练失败则回退到 numpy 简化版。

核心原理（sklearn 版）：
    1. 构造 5 步滑动窗口特征（播放量/点赞/投币 + log 变换）
    2. 目标变量为播放量增长率（百分比差值）
    3. 使用 GBR 逐步拟合前一轮的残差（100 棵树，深度 4，学习率 0.1）
    4. 残差变异系数 (CV) 作为置信度参考

核心原理（numpy 回退版）：
    1. 使用互动率、质量评分、视频年龄构造修正因子
    2. 逐步调整基准预测：互动率修正 → 质量修正 → 时间因子

算法来源：Friedman (2001) "Greedy Function Approximation: A Gradient Boosting Machine"

适用场景：历史数据 ≥ 10 点的视频，sklearn 版本更优。
"""

import logging
from datetime import datetime
from typing import Dict, Any

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_SKLEARN = False
try:
    from sklearn.ensemble import GradientBoostingRegressor as _GBR

    _HAS_SKLEARN = True
except ImportError:
    pass


class GradientBoostSimpleAlgorithm(BaseAlgorithm):
    """
    梯度提升预测算法

    使用梯度提升回归树（GBRT）预测视频播放量增长。
    GBRT 通过迭代拟合残差来逐步提升预测精度，是 Kaggle 竞赛中最常用的模型之一。

    类属性：
        name (str): 算法名称 "梯度提升简化"
        algorithm_id (str): 算法唯一标识 "gradient_boost_simple"
        description (str): 算法简述
        category (str): 所属类别 "机器学习"
        default_weight (float): 默认集成权重 1.4（中高）
    """

    name = "梯度提升简化"
    algorithm_id = "gradient_boost_simple"
    description = "基于梯度提升的播放量预测（sklearn 优先，numpy 回退）"
    category = "集成学习"
    default_weight = 1.4

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行梯度提升预测。

        策略：
            - sklearn 可用且历史数据 ≥ 10 点：使用真实 GBRT
            - 否则：回退到 numpy 简化版

        Args:
            video_data (Dict): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        # 优先使用 sklearn GradientBoostingRegressor 做梯度提升预测
        if _HAS_SKLEARN and len(history) >= 10:
            try:
                result = self._sklearn_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("GradientBoost sklearn 失败，回退 numpy: %s", e)

        # 回退到 numpy 简化版
        return self._numpy_predict(video_data, threshold)

    def _sklearn_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        """
        使用 sklearn GradientBoostingRegressor 做梯度提升树预测。

        特征工程（p=5 滑动窗口）：
            对每个时间步 j（1 到 5），提取 4 个特征：
                - views[i-j]：播放量
                - likes[i-j]：点赞数
                - coins[i-j]：投币数
                - log(max(views[i-j], 1))：对数播放量

        目标变量：播放量增长率 = (views[t] - views[t-1]) / views[t-1]

        Args:
            video_data (Dict): 视频数据字典
            threshold (int): 目标阈值

        Returns:
            PredictionResult 或 None（训练数据不足时）
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        likes = np.array([h.get("like_count", 0) for h in history], dtype=np.float64)
        coins = np.array([h.get("coin_count", 0) for h in history], dtype=np.float64)

        p = 5  # 滑动窗口大小
        X, y = [], []
        # 构造特征和目标
        for i in range(p, len(views)):
            feat = []
            for j in range(1, p + 1):
                feat.extend([views[i - j], likes[i - j], coins[i - j], np.log(max(views[i - j], 1))])
            X.append(feat)
            y.append(views[i])

        X, y = np.array(X), np.array(y)
        if len(X) < 8:
            return None

        # 目标转换为增长率：t 时刻相对于 t-1 的增长百分比
        y_target = np.diff(views[-len(X) - 1:]) / np.maximum(views[-len(X) - 1 : -1], 1)
        y_target = y_target[-len(X):]

        # GBR: 100 棵树，max_depth=4，学习率 0.1（渐进拟合残差）
        model = _GBR(n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42)
        model.fit(X, y_target)

        # 构造最新特征用于预测
        last_feat = []
        for j in range(1, p + 1):
            last_feat.extend([views[-j], likes[-j], coins[-j], np.log(max(views[-j], 1))])
        pred_growth = float(model.predict(np.array([last_feat]))[0])

        # 增长率转换为绝对速度（每小时播放量）
        predicted_velocity = max(0, pred_growth * current_views / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        # 计算到达阈值所需时间
        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity if predicted_velocity > 0 else float("inf")
            # 置信度：基于残差的变异系数 (CV)
            # CV 越小 → 模型拟合越好 → 置信度越高
            residuals = np.abs(y_target - model.predict(X))
            cv = float(np.std(residuals) / max(np.mean(np.abs(y_target)), 1e-10))
            confidence = max(0.1, min(0.85, 0.6 - cv * 0.5))

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "gradient_boost_sklearn", "n_estimators": 100},
            timestamp=datetime.now(),
        )

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        """
        numpy 简化版梯度提升预测。

        使用互动率、质量评分、视频年龄三个信号逐步修正基准预测：
            r1 = 基准 * (1 - 互动率 * 0.5)：高互动 → 更快到达
            r2 = r1 * (1 - 质量 * 0.3)：高质量 → 更快到达
            最终 = r2 * (2 - 时间因子)：新视频有增长空间

        Args:
            video_data (Dict): 视频数据字典
            threshold (int): 目标阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        elif velocity <= 0:
            predicted_hours, confidence = float("inf"), 0.0
        else:
            # 基准匀速预测
            base_prediction = remaining / velocity
            engagement = self.get_engagement_rate(video_data)
            quality = self.get_quality_score(video_data)
            age_hours = self.get_video_age_hours(video_data)

            # 三步残差修正（模拟梯度提升的逐步改进过程）：
            r1 = base_prediction * (1 - engagement * 0.5)  # 第一轮修正：互动率
            r2 = r1 * (1 - quality * 0.3)  # 第二轮修正：质量评分
            time_factor = min(1.0, 24 / max(age_hours, 1))  # 时间因子：新视频 (age<24h) → factor=1，衰减
            predicted_hours = r2 * (2 - time_factor)  # 第三轮修正：时间
            confidence = min(1.0, 0.5 + engagement * 2 + quality * 0.3)

        residuals_count = 3 if confidence > 0 else 0  # 模拟 3 轮残差修正
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "gradient_boost_numpy", "residuals": residuals_count},
            timestamp=datetime.now(),
        )
