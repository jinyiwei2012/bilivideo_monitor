"""
XGBoost 预测算法模块
====================

本模块实现了基于 XGBoost 梯度提升的 B 站视频播放量预测算法。
XGBoost (eXtreme Gradient Boosting) 是目前最流行的梯度提升框架之一，
在 Kaggle 竞赛和工业界广泛应用。

优先使用 xgboost.XGBRegressor 构建梯度提升模型；
若库不可用或训练失败，回退到同算法的 numpy 简化版。

核心原理（XGBoost 版）：
    1. 构造 5 步滑动窗口特征（播放量/点赞/投币/收藏 + log 变换）
    2. 目标变量为播放量增长率（百分比差值）
    3. 二阶泰勒展开近似损失函数（牛顿法），比普通 GBDT 更精确
    4. 正则化目标函数：惩罚树复杂度 + L1/L2 正则化
    5. 列采样（colsample_bytree=0.8）+ 行采样（subsample=0.8）

核心原理（numpy 回退版）：
    匀速外推，使用基础播放速度预测。

算法来源：Chen & Guestrin (2016) "XGBoost: A Scalable Tree Boosting System"

适用场景：历史数据 ≥ 10 点的视频，精度和速度平衡良好。
"""

import math
import logging
from datetime import datetime
from typing import Dict, Any

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_XGBOOST = False
try:
    import xgboost as xgb

    _HAS_XGBOOST = True
except ImportError:
    pass


class XGBoostSimpleAlgorithm(BaseAlgorithm):
    """
    XGBoost 预测算法

    使用 XGBoost 梯度提升进行播放量预测。核心优势：
        1. 正则化目标函数：防止过拟合
        2. 近似分位数算法 (Weighted Quantile Sketch)：高效处理大规模数据
        3. 缓存感知访问 + 数据压缩：内存效率高
        4. 并行化特征列块：训练速度快

    类属性：
        name (str): 算法名称 "XGBoost"
        algorithm_id (str): 算法唯一标识 "xgboost"
        description (str): 算法简述
        category (str): 所属类别 "集成学习"
        default_weight (float): 默认集成权重 1.6（高）
    """

    name = "XGBoost"
    algorithm_id = "xgboost"
    description = "基于 XGBoost 梯度提升的播放量预测"
    category = "集成学习"
    default_weight = 1.6

    def __init__(self):
        """初始化 XGBoost 算法实例。"""
        super().__init__()
        self._model = None  # 训练好的模型缓存

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行 XGBoost 预测，优先真实实现，失败回退 numpy。

        Args:
            video_data (Dict): 视频数据字典
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
                metadata={"method": "xgboost", "note": "already_reached"},
                timestamp=datetime.now(),
            )

        # 数据不足或速度为零 → numpy 回退
        if len(history) < 10 or velocity <= 0:
            return self._numpy_predict(current_views, velocity, remaining, threshold)

        # 尝试真实 XGBoost
        if _HAS_XGBOOST:
            try:
                result = self._xgboost_predict(history, current_views, velocity, remaining, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("XGBoost 训练失败，回退 numpy: %s", e)

        return self._numpy_predict(current_views, velocity, remaining, threshold)

    def _xgboost_predict(self, history, current_views, velocity, remaining, threshold) -> PredictionResult:
        """
        XGBoost 真实实现预测。

        特征构造（5 步滑动窗口，每步 5 维特征）：
            - views[i-j]: 播放量
            - likes[i-j]: 点赞数
            - coins[i-j]: 投币数
            - favs[i-j]: 收藏数
            - log(views[i-j]): 对数播放量

        XGBoost 参数：
            - n_estimators=80: 树的数量
            - max_depth=4: 最大深度
            - learning_rate=0.1: 学习率
            - subsample=0.8: 行采样率
            - colsample_bytree=0.8: 列采样率

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
                        math.log(max(views[i - j], 1)),  # 对数变换
                    ]
                )
            X.append(feat)
            y.append(views[i])

        X, y = np.array(X), np.array(y)
        if len(X) < 8:
            return None

        # 目标：预测下一个周期的增速比
        y_growth = np.diff(views[-len(X) - 1 :]) / np.maximum(views[-len(X) - 1 : -1], 1)
        y_target = y_growth[-len(X) :]

        # XGBoost 训练：带行/列采样 + 正则化
        model = xgb.XGBRegressor(
            n_estimators=80,          # 树的数量
            max_depth=4,              # 最大深度
            learning_rate=0.1,        # 学习率
            subsample=0.8,            # 行采样率（每棵树用 80% 数据）
            colsample_bytree=0.8,     # 列采样率（每棵树用 80% 特征）
            verbosity=0,              # 静默训练
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
                    math.log(max(views[-j], 1)),
                ]
            )
        pred_growth = float(model.predict(np.array([last_feat]))[0])

        # 增长率转换为绝对速度（每小时播放量）
        predicted_velocity = max(0, pred_growth * current_views / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

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
            metadata={"method": "xgboost", "n_estimators": 80},
            timestamp=datetime.now(),
        )

    def _numpy_predict(self, current_views, velocity, remaining, threshold) -> PredictionResult:
        """
        numpy 简化版回退预测。

        当 XGBoost 库不可用或训练失败时使用。
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
                metadata={"method": "xgboost_numpy_fallback"},
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
            metadata={"method": "xgboost_numpy_fallback"},
            timestamp=datetime.now(),
        )
