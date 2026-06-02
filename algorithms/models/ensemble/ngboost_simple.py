"""
NGBoost (Natural Gradient Boosting) 预测算法模块
================================================

本模块实现了基于自然梯度提升的 B 站视频播放量概率分布预测算法。
NGBoost 与传统梯度提升的关键区别：输出完整概率分布（正常分布），
而非单一标量预测值，因此能够量化预测的不确定性。

核心原理：
    1. 对每个样本拟合一个正态分布 N(μ, σ²)
    2. 使用自然梯度（而非普通梯度）更新分布参数
    3. 自然梯度是 Fisher 信息矩阵下的最速下降方向，对参数变换不变
    4. 最终输出 μ（预测均值）+ σ（预测标准差）→ 完整置信区间

优点：
    - 自带不确定性量化（不需要额外步骤）
    - sigma 越大 → 预测越不确定 → 置信度越低
    - 自然梯度收敛更快，对学习率不那么敏感

适用场景：
    - 需要预测区间的场景（不只一个值，而有分布）
    - 不确定性高的视频（波动大的播放趋势）
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

_HAS_NGBOOST = False
try:
    from ngboost import NGBRegressor
    from ngboost.distns import Normal  # 正态分布族

    _HAS_NGBOOST = True
except ImportError:
    pass


class NgboostAlgorithm(BaseAlgorithm):
    """
    NGBoost 自然梯度提升预测算法

    输出完整正态分布参数的梯度提升。与传统 GBDT 只输出一个标量不同，
    NGBoost 输出均值 μ 和标准差 σ，直接量化预测的不确定性。

    类属性：
        name (str): 算法名称 "NGBoost"
        algorithm_id (str): 算法唯一标识 "ngboost"
        description (str): 算法简述
        category (str): 所属类别 "集成学习"
        default_weight (float): 默认集成权重 1.2（中）
    """

    name = "NGBoost"
    algorithm_id = "ngboost"
    description = "自然梯度提升，输出完整概率分布"
    category = "集成学习"
    default_weight = 1.2

    _model = None  # 类级别模型缓存

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行 NGBoost 概率分布预测。

        流程：
            1. 构造 4 步滑动窗口特征（播放量 + 点赞 + 投币）
            2. 目标：预测播放量增长率
            3. NGBoost 输出 Normal(μ, σ²) 分布
            4. μ → 预测速度，σ → 不确定性 → 置信度

        NGBoost 参数：
            - Dist=Normal: 预测正态分布
            - n_estimators=50: 50 轮提升
            - learning_rate=0.1: 自然梯度学习率

        Args:
            video_data (Dict): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        Returns:
            PredictionResult: 包含预测值 + 不确定性的结果对象
                - metadata.mu: 预测均值
                - metadata.sigma: 预测标准差
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足或无增长 → 回退
        if len(history) < 10 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        # NGBoost 库不可用 → 回退
        if not _HAS_NGBOOST:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            likes = np.array([h.get("like", 0) for h in history], dtype=np.float64)
            coins = np.array([h.get("coin", 0) for h in history], dtype=np.float64)

            p = 4  # 滑动窗口大小
            X, y = [], []
            # 构造特征：播放量 + 点赞 + 投币 的 4 步滞后值
            for i in range(p, len(views)):
                X.append(
                    [views[i - j] for j in range(1, p + 1)]
                    + [likes[i - j] for j in range(1, p + 1)]
                    + [coins[i - j] for j in range(1, p + 1)]
                )
                y.append(views[i])

            if len(X) < 5:
                return self._fallback(velocity, current_views, threshold)

            X, y = np.array(X), np.array(y)

            # 目标：播放量增长率（百分比差值），更稳定
            y_pct = np.diff(views[-len(X) - 1 :]) / np.maximum(views[-len(X) - 1 : -1], 1)
            y_target = y_pct[-len(X) :]

            # NGBoost 训练：拟合正态分布参数
            model = NGBRegressor(Dist=Normal, n_estimators=50, learning_rate=0.1, verbose=False)
            model.fit(X, y_target)

            # 构造最新特征
            last_X = np.array(
                [
                    [views[-j] for j in range(1, p + 1)]
                    + [likes[-j] for j in range(1, p + 1)]
                    + [coins[-j] for j in range(1, p + 1)]
                ]
            )

            # 预测分布的均值和方差
            pred_dist = model.pred_dist(last_X)
            mu = float(pred_dist.mean())      # 预测的增长率均值
            sigma = float(np.sqrt(pred_dist.var))  # 预测的增长率标准差

            # 将增长率转换为绝对速度（每小时播放量）
            predicted_velocity = max(0, mu * views[-1] / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                # 置信度：sigma/|mu| 越小（相对不确定性越小）→ 置信度越高
                cv = sigma / max(abs(mu), 1e-10)
                confidence = max(0.05, min(0.8, 0.6 - cv * 3))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "ngboost", "mu": float(mu), "sigma": float(sigma)},
                timestamp=datetime.now(),
            )
        except Exception:
            # 训练或预测异常 → 回退
            return self._fallback(velocity, current_views, threshold)

    def _fallback(self, velocity, current_views, threshold):
        """
        回退预测方案：匀速外推。

        当 NGBoost 不可用或数据不足时使用。

        Args:
            velocity (float): 当前播放速度
            current_views (int): 当前播放量
            threshold (int): 目标阈值

        Returns:
            PredictionResult: 基于匀速外推的预测结果
        """
        if velocity <= 0:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=float("inf"),  # 无增长
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "ngboost", "reason": "fallback"},
                timestamp=datetime.now(),
            )
        remaining = max(0, threshold - current_views)
        predicted_hours = remaining / velocity if remaining > 0 else 0
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=0.3,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "ngboost", "reason": "fallback"},
            timestamp=datetime.now(),
        )
