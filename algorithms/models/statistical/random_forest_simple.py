"""
随机森林预测算法 — Random Forest Simple
========================================

基于特征工程的随机森林回归预测，带有 sklearn / numpy 双后端。

核心原理：
  1. sklearn 版本：使用 RandomForestRegressor 做特征工程 + 树模型预测
     - 构建时序特征：过去 p=5 个时间点的播放量/点赞/投币/收藏 + 对数变换
     - 目标变量改为增长率（增长率更适合树模型）
     - 100 棵树，max_depth=6 防止过拟合
  2. numpy 简化版（回退）：基于速度和互动率的启发式预测
     - 使用当前速度、互动率和质量分做线性调整

适用场景：历史数据 >= 5 条（numpy 版），>= 10 条推荐使用 sklearn 版
"""

import logging
from datetime import datetime
from typing import Dict, Any

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

# sklearn 可用性标记
_HAS_SKLEARN = False
try:
    from sklearn.ensemble import RandomForestRegressor as _RF

    _HAS_SKLEARN = True
except ImportError:
    pass


class RandomForestSimpleAlgorithm(BaseAlgorithm):
    """
    随机森林预测算法

    支持 sklearn 特征工程版本和 numpy 启发式版本的双后端架构。
    sklearn 版本构建时序上下文特征，预测增长率后转换为播放速度。

    属性:
        default_weight (float): 默认集成权重 1.4，随机森林集成通常表现优异
    """

    name = "随机森林简化"
    algorithm_id = "random_forest_simple"
    description = "基于特征工程的随机森林预测（sklearn 优先，numpy 回退）"
    category = "机器学习"
    default_weight = 1.4

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行随机森林预测

        策略:
          1. sklearn 可用且数据 >= 10 条 → 使用 sklearn RandomForestRegressor
          2. 否则 → 使用 numpy 启发式简化版本

        参数:
            video_data (Dict): 视频数据
            threshold (int): 目标播放量阈值

        返回:
            PredictionResult: 预测结果
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        # 优先使用 sklearn RandomForestRegressor 做特征工程预测
        if _HAS_SKLEARN and len(history) >= 10:
            try:
                result = self._sklearn_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("RandomForest sklearn 失败，回退 numpy: %s", e)

        return self._numpy_predict(video_data, threshold)

    def _sklearn_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        """
        使用 sklearn RandomForestRegressor 做特征工程 + 树模型预测

        特征构建:
          对过去 p=5 个时间点，每个点提取 5 维特征:
            [播放量, 点赞数, 投币数, 收藏数, log(播放量)]
          总共 5×5 = 25 维特征

        目标变量:
          增长率 = diff(views) / max(views[:-1], 1)
          （使用增长率而非绝对播放量，更适合树模型）

        模型配置:
          n_estimators=100: 100 棵树
          max_depth=6: 限制深度防过拟合
          n_jobs=-1: 并行加速

        参数:
            video_data (Dict): 视频数据
            threshold (int): 目标阈值

        返回:
            PredictionResult 或 None
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 提取时序数据
        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        likes = np.array([h.get("like_count", 0) for h in history], dtype=np.float64)
        coins = np.array([h.get("coin_count", 0) for h in history], dtype=np.float64)
        favs = np.array([h.get("favorite_count", 0) for h in history], dtype=np.float64)

        # 构建时序特征：过去 p=5 个点
        p = 5
        X, y = [], []
        for i in range(p, len(views)):
            feat = []
            for j in range(1, p + 1):  # 从最近到最远
                feat.extend(
                    [
                        views[i - j],  # 播放量
                        likes[i - j],  # 点赞数
                        coins[i - j],  # 投币数
                        favs[i - j],  # 收藏数
                        np.log(max(views[i - j], 1)),  # 对数播放量（特征变换）
                    ]
                )
            X.append(feat)
            y.append(views[i])  # 目标：当前播放量

        X, y = np.array(X), np.array(y)
        if len(X) < 8:
            return None

        # 目标变量改为增长率（比绝对播放量更适合树模型）
        # 增长率 = 相邻点之差 / 前一点值
        y_target = np.diff(views[-len(X) - 1:]) / np.maximum(views[-len(X) - 1 : -1], 1)
        y_target = y_target[-len(X):]  # 对齐长度

        # RandomForest: 100 棵树，max_depth=6 防止过拟合，n_jobs=-1 并行加速
        model = _RF(n_estimators=100, max_depth=6, random_state=42, n_jobs=-1)
        model.fit(X, y_target)

        # 构造最新数据点的特征用于预测
        last_feat = []
        for j in range(1, p + 1):
            last_feat.extend(
                [
                    views[-j],
                    likes[-j],
                    coins[-j],
                    favs[-j],
                    np.log(max(views[-j], 1)),
                ]
            )
        # 预测增长率
        pred_growth = float(model.predict(np.array([last_feat]))[0])
        # 增长率转换为每秒增量: pred_growth × current_views / 3600
        predicted_velocity = max(0, pred_growth * current_views / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity  # 速度过低回退

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity if predicted_velocity > 0 else float("inf")
            # 置信度基于残差的变异系数（CV）
            residuals = np.abs(y_target - model.predict(X))
            cv = float(np.std(residuals) / max(np.mean(np.abs(y_target)), 1e-10))  # CV = std/mean
            confidence = max(0.1, min(0.85, 0.6 - cv * 0.5))

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "random_forest_sklearn", "n_estimators": 100},
            timestamp=datetime.now(),
        )

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        """
        使用 numpy 启发式简化版进行预测（sklearn 不可用时的回退）

        基于三个特征做速度调整:
          - view_velocity: 当前播放速度
          - engagement_rate: 互动率（点赞/播放量等）
          - quality_score: 视频质量评分

        调整公式:
          engagement_boost = 1 + engagement_rate × 2
          quality_boost = 0.8 + quality_score × 0.4
          adjustment = (engagement_boost + quality_boost) / 2
          predicted_hours = base_prediction / adjustment

        参数:
            video_data (Dict): 视频数据
            threshold (int): 目标阈值

        返回:
            PredictionResult
        """
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)

        # 提取特征（来自 base class 方法）
        features = {
            "view_velocity": velocity,  # 当前播放速度
            "engagement_rate": self.get_engagement_rate(video_data),  # 互动率
            "quality_score": self.get_quality_score(video_data),  # 质量评分
        }

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        elif velocity <= 0:
            predicted_hours, confidence = float("inf"), 0.0
        else:
            # 基础预测：剩余播放量 / 当前速度
            base_prediction = remaining / velocity
            # 互动率和质量分作为加速/减速因子
            engagement_boost = 1 + features["engagement_rate"] * 2  # 互动率最高可提 2 倍速
            quality_boost = 0.8 + features["quality_score"] * 0.4  # 质量分范围 [0.8, 1.2]
            adjustment = (engagement_boost + quality_boost) / 2  # 综合调整
            predicted_hours = base_prediction / adjustment  # 调整后的预测时间
            # 置信度随互动率和质量分提高
            confidence = min(1.0, 0.5 + features["engagement_rate"] * 3 + features["quality_score"] * 0.3)

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "random_forest_numpy", "features": features},
            timestamp=datetime.now(),
        )
