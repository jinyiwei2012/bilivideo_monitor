"""
CatBoost 预测算法模块
====================

本模块实现了基于 CatBoost 有序提升的 B 站视频播放量预测算法。
CatBoost (Categorical Boosting) 是 Yandex 开发的高效梯度提升库，
特别擅长处理类别特征和防止过拟合。

优先使用 catboost.CatBoostRegressor 真实实现构建有序提升模型；
若库不可用或训练失败，回退到 numpy 简化版。

核心原理（CatBoost 版）：
    1. 构造 5 步滑动窗口特征（播放量/点赞/投币/收藏/分享 + log 变换）
    2. 追加星期几作为类别特征（cat_features=[-1]）
    3. 目标变量为播放量增长率（百分比差值）
    4. 有序提升：使用随机排列避免预测偏移，防过拟合效果更优

核心原理（numpy 回退版）：
    匀速外推，使用基础播放速度预测。

算法来源：Prokhorenkova et al. (2018) "CatBoost: unbiased boosting with categorical features"

适用场景：历史数据 ≥ 10 点的视频，CatBoost 比 XGBoost 更少调参需求。
"""

import math
import logging
from typing import Dict, Any
from datetime import datetime

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_CATBOOST = False
try:
    from catboost import CatBoostRegressor

    _HAS_CATBOOST = True
except ImportError:
    pass


class CatBoostSimpleAlgorithm(BaseAlgorithm):
    """
    CatBoost 预测算法

    使用 CatBoost 梯度提升进行播放量预测。CatBoost 的核心优势在于：
        1. 有序提升（Ordered Boosting）：有效防止过拟合
        2. 原生类别特征支持：不需要手动 one-hot 编码
        3. 默认参数即可获得良好效果

    类属性：
        name (str): 算法名称 "CatBoost"
        algorithm_id (str): 算法唯一标识 "catboost"
        description (str): 算法简述
        category (str): 所属类别 "集成学习"
        default_weight (float): 默认集成权重 1.6（高）
    """

    name = "CatBoost"
    algorithm_id = "catboost"
    description = "基于 CatBoost 有序提升的播放量预测"
    category = "集成学习"
    default_weight = 1.6

    def __init__(self):
        """初始化 CatBoost 算法实例。"""
        super().__init__()
        self._model = None  # 训练好的模型缓存

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行 CatBoost 预测，优先真实实现，失败回退 numpy。

        Args:
            video_data (Dict): 视频数据字典，需包含：
                - view_count (int): 当前播放量
                - history_data (List[Dict]): 历史监控数据
            threshold (int): 目标播放量阈值，默认 100000

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            # 已达标
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=0,
                confidence=1.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "catboost", "note": "already_reached"},
                timestamp=datetime.now(),
            )

        # 数据不足或无增长 → 使用 numpy 简化版
        if len(history) < 10 or velocity <= 0:
            return self._numpy_predict(current_views, velocity, remaining, threshold)

        # 尝试真实 CatBoost 实现
        if _HAS_CATBOOST:
            try:
                result = self._catboost_predict(history, current_views, velocity, remaining, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("CatBoost 训练失败，回退 numpy: %s", e)

        return self._numpy_predict(current_views, velocity, remaining, threshold)

    def _catboost_predict(self, history, current_views, velocity, remaining, threshold) -> PredictionResult:
        """
        CatBoost 真实实现预测。

        特征构造（5 步滑动窗口，每步 6 维特征）：
            - views[i-j]: 播放量
            - likes[i-j]: 点赞数
            - coins[i-j]: 投币数
            - favs[i-j]: 收藏数
            - shares[i-j]: 分享数
            - log(views[i-j]): 对数播放量
            + i % 7: 星期几类别特征

        CatBoost 参数：
            - iterations=80: 提升轮数
            - depth=4: 树深度
            - learning_rate=0.1: 学习率
            - subsample=0.8: 样本采样率
            - cat_features=[-1]: 最后一列(星期几)为类别特征

        Args:
            history (List[Dict]): 历史数据
            current_views (int): 当前播放量
            velocity (float): 当前速度
            remaining (int): 剩余播放量
            threshold (int): 目标阈值

        Returns:
            PredictionResult 或 None
        """
        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        likes = np.array([h.get("like_count", 0) for h in history], dtype=np.float64)
        coins = np.array([h.get("coin_count", 0) for h in history], dtype=np.float64)
        favs = np.array([h.get("favorite_count", 0) for h in history], dtype=np.float64)
        shares = np.array([h.get("share_count", 0) for h in history], dtype=np.float64)

        p = 5  # 滑动窗口大小
        X, y = [], []
        for i in range(p, len(views)):
            feat = []
            for j in range(1, p + 1):
                feat.extend(
                    [
                        views[i - j],
                        likes[i - j],
                        coins[i - j],
                        favs[i - j],
                        shares[i - j],
                        math.log(max(views[i - j], 1)),  # 对数变换稳定数值范围
                    ]
                )
            # 星期几作为类别特征（CatBoost 原生支持）
            feat.append((i % 7))
            X.append(feat)
            y.append(views[i])

        X, y = np.array(X), np.array(y)
        if len(X) < 8:
            return None

        # 目标变量：播放量增长率（百分比差值）
        y_growth = np.diff(views[-len(X) - 1 :]) / np.maximum(views[-len(X) - 1 : -1], 1)
        y_target = y_growth[-len(X) :]

        # CatBoost 训练参数
        model = CatBoostRegressor(
            iterations=80,      # 提升轮数
            depth=4,            # 树深度（避免过拟合）
            learning_rate=0.1,  # 学习率
            subsample=0.8,      # 样本采样率
            verbose=False,      # 静默训练
            cat_features=[-1],  # 最后一列为类别特征
        )
        model.fit(X, y_target)

        # 构造最新特征
        last_feat = []
        for j in range(1, p + 1):
            last_feat.extend(
                [
                    views[-j],
                    likes[-j],
                    coins[-j],
                    favs[-j],
                    shares[-j],
                    math.log(max(views[-j], 1)),
                ]
            )
        last_feat.append((len(views) % 7))  # 当前星期几
        pred_growth = float(model.predict(np.array([last_feat]))[0])

        # 增长率转换为绝对速度（每小时播放量）
        predicted_velocity = max(0, pred_growth * current_views / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity  # 速度过慢时使用原速度

        pred_hours = remaining / predicted_velocity if predicted_velocity > 0 else float("inf")

        # 置信度：基于残差变异系数 (CV)
        residuals = np.abs(y_target - model.predict(X))
        cv = float(np.std(residuals) / max(np.mean(np.abs(y_target)), 1e-10))
        confidence = max(0.1, min(0.85, 0.6 - cv * 0.5))

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=pred_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "catboost", "iterations": 80},
            timestamp=datetime.now(),
        )

    def _numpy_predict(self, current_views, velocity, remaining, threshold) -> PredictionResult:
        """
        numpy 简化版回退预测。

        当 CatBoost 库不可用或训练失败时使用。
        简单匀速外推，置信度较低 (0.3)。

        Args:
            current_views (int): 当前播放量
            velocity (float): 当前速度
            remaining (int): 剩余播放量
            threshold (int): 目标阈值

        Returns:
            PredictionResult: 预测结果对象
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
                metadata={"method": "catboost_numpy_fallback"},
                timestamp=datetime.now(),
            )
        # 匀速外推
        predicted_hours = remaining / velocity
        confidence = 0.3
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "catboost_numpy_fallback"},
            timestamp=datetime.now(),
        )
