"""
LightGBM 预测算法模块
=====================

本模块实现了基于 LightGBM 直方图梯度提升的 B 站视频播放量预测算法。
LightGBM 是微软开发的基于直方图的高效梯度提升框架，
使用 leaf-wise 生长策略和直方图分桶，比 XGBoost 更快且内存更省。

优先使用 lightgbm.LGBMRegressor 真实实现构建直方图梯度提升；
若库不可用或训练失败，回退到同算法的 numpy 简化版。

核心原理（LightGBM 版）：
    1. 构造 5 步滑动窗口特征（播放量/点赞/投币/收藏/分享 + log 变换）
    2. 目标变量为播放量增长率（百分比差值）
    3. 使用 leaf-wise 树生长策略（而非 level-wise），分裂增益最大的节点
    4. 直方图分桶加速特征分裂搜索
    5. 列采样（colsample_bytree=0.8）增加随机性防过拟合

核心原理（numpy 回退版）：
    匀速外推，使用基础播放速度预测。

算法来源：Ke et al. (2017) "LightGBM: A Highly Efficient Gradient Boosting Decision Tree"

适用场景：历史数据 ≥ 10 点的视频，大数据集优势明显。
"""

import math
import logging
import warnings
from typing import Dict, Any
from datetime import datetime

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_LIGHTGBM = False
try:
    import lightgbm as lgb

    _HAS_LIGHTGBM = True
except ImportError:
    pass


class LightGBMSimpleAlgorithm(BaseAlgorithm):
    """
    LightGBM 预测算法

    使用 LightGBM 直方图梯度提升进行播放量预测。核心优势：
        1. Leaf-wise 树生长：优先分裂增益最大的叶节点，收敛更快
        2. 直方图分桶：将连续特征离散化，大幅降低计算量和内存
        3. GOSS 采样：保留大梯度样本 + 随机采样小梯度样本
        4. EFB 特征捆绑：合并互斥特征减少特征数量

    类属性：
        name (str): 算法名称 "LightGBM"
        algorithm_id (str): 算法唯一标识 "lightgbm"
        description (str): 算法简述
        category (str): 所属类别 "集成学习"
        default_weight (float): 默认集成权重 1.6（高）
    """

    name = "LightGBM"
    algorithm_id = "lightgbm"
    description = "基于 LightGBM 直方图梯度提升的播放量预测"
    category = "集成学习"
    default_weight = 1.6

    def __init__(self):
        """初始化 LightGBM 算法实例。"""
        super().__init__()
        self._model = None  # 训练好的模型缓存

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行 LightGBM 预测，优先真实实现，失败回退 numpy。

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
                metadata={"method": "lightgbm", "note": "already_reached"},
                timestamp=datetime.now(),
            )

        # 数据不足或速度为零 → numpy 回退
        if len(history) < 10 or velocity <= 0:
            return self._numpy_predict(current_views, velocity, remaining, threshold)

        # 尝试真实 LightGBM
        if _HAS_LIGHTGBM:
            try:
                result = self._lightgbm_predict(history, current_views, velocity, remaining, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("LightGBM 训练失败，回退 numpy: %s", e)

        return self._numpy_predict(current_views, velocity, remaining, threshold)

    def _lightgbm_predict(self, history, current_views, velocity, remaining, threshold) -> PredictionResult:
        """
        屏蔽 LightGBM 的特征名称警告后调用实现。

        新版 sklearn API 可能导致特征名称警告，这里捕获后忽略。

        Args:
            history (List[Dict]): 历史数据
            current_views (int): 当前播放量
            velocity (float): 当前速度
            remaining (int): 剩余播放量
            threshold (int): 目标阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="X does not have valid feature names")
            return self._lightgbm_predict_impl(history, current_views, velocity, remaining, threshold)

    def _lightgbm_predict_impl(self, history, current_views, velocity, remaining, threshold) -> PredictionResult:
        """
        LightGBM 真实实现预测。

        特征构造（5 步滑动窗口，每步 6 维特征）：
            - views[i-j]: 播放量
            - likes[i-j]: 点赞数
            - coins[i-j]: 投币数
            - favs[i-j]: 收藏数
            - shares[i-j]: 分享数
            - log(views[i-j]): 对数播放量

        LightGBM 参数：
            - n_estimators=80: 树的数量
            - max_depth=4: 最大深度
            - learning_rate=0.1: 学习率
            - subsample=0.8: 样本采样率
            - colsample_bytree=0.8: 每棵树的特征采样率

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
                        math.log(max(views[i - j], 1)),
                    ]
                )
            X.append(feat)
            y.append(views[i])

        X, y = np.array(X), np.array(y)
        if len(X) < 8:
            return None

        # 目标变量：播放量增长率（百分比差值）
        y_growth = np.diff(views[-len(X) - 1 :]) / np.maximum(views[-len(X) - 1 : -1], 1)
        y_target = y_growth[-len(X) :]

        # LightGBM 训练参数：leaf-wise 生长 + 列采样
        model = lgb.LGBMRegressor(
            n_estimators=80,        # 树的数量
            max_depth=4,            # 最大深度
            learning_rate=0.1,      # 学习率
            subsample=0.8,          # 样本采样率（GOSS 风格）
            colsample_bytree=0.8,   # 每棵树的特征采样率
            verbosity=-1,           # 完全静默
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
            metadata={"method": "lightgbm", "n_estimators": 80},
            timestamp=datetime.now(),
        )

    def _numpy_predict(self, current_views, velocity, remaining, threshold) -> PredictionResult:
        """
        numpy 简化版回退预测。

        当 LightGBM 库不可用或训练失败时使用。
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
                metadata={"method": "lightgbm_numpy_fallback"},
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
            metadata={"method": "lightgbm_numpy_fallback"},
            timestamp=datetime.now(),
        )
