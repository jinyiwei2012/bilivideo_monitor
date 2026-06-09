"""
分位数集成预测算法模块
======================

本模块实现了分位数回归集成预测算法，为集成学习模型增加分位数回归能力，
输出多分位数预测值和置信区间。

核心思路：
    1. 对每组特征同时预测多个分位数（10%/25%/50%/75%/90%）
    2. 50% 分位数 = 点预测（中位数），其他分位数 = 置信区间
    3. 使用 Pinball Loss 训练分位数回归（GBR 内置支持）
    4. 区间宽度反映预测不确定性：区间越窄 → 预测越确定 → 置信度越高

分位数回归 vs 普通回归：
    - 普通回归：预测条件均值 E[y|X]
    - 分位数回归：预测条件分位数 Q_τ(y|X)，能捕获分布的不对称性

适用场景：需要预测区间（上下界）的集成预测，波动性评估。
"""

import logging
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_SKLEARN = False
try:
    from sklearn.ensemble import GradientBoostingRegressor as _GBR

    _HAS_SKLEARN = True
except ImportError:
    pass

_DEFAULT_QUANTILES = [0.1, 0.25, 0.5, 0.75, 0.9]


def pinball_loss(y_true, y_pred, tau):
    """
    Pinball loss (分位数损失函数) 用于分位数回归。

    定义：
        L(y, ŷ) = max(τ*(y-ŷ), (τ-1)*(y-ŷ))

    当 τ=0.5 时退化为 MAE 的一半。
    τ>0.5 时惩罚低估更多（上限预测），τ<0.5 时惩罚高估更多（下限预测）。

    Args:
        y_true (np.ndarray): 真实值
        y_pred (np.ndarray): 预测值
        tau (float): 目标分位数 [0, 1]

    Returns:
        float: 平均 Pinball 损失
    """
    diff = y_true - y_pred
    return np.mean(np.maximum(tau * diff, (tau - 1) * diff))


class QuantileEnsembleAlgorithm(BaseAlgorithm):
    """
    分位数集成预测算法 — 输出置信区间。

    同时训练 5 个分位数回归模型（0.1/0.25/0.5/0.75/0.9），
    以 0.5 分位数（中位数）作为点预测，以 0.25-0.75 区间宽度衡量不确定性。

    类属性：
        name (str): 算法名称 "分位数集成"
        algorithm_id (str): 算法唯一标识 "quantile_ensemble"
        description (str): 算法简述
        category (str): 所属类别 "集成学习"
        default_weight (float): 默认集成权重 1.5（高）
        quantiles (List[float]): 分位数列表 [0.1, 0.25, 0.5, 0.75, 0.9]
        models (Dict[float, object]): 训练好的分位数模型字典
    """

    name = "分位数集成"
    algorithm_id = "quantile_ensemble"
    description = "多分位数回归集成预测，输出点预测+上下界"
    category = "集成学习"
    default_weight = 1.5

    def __init__(self):
        """初始化分位数集成算法，设置 5 个分位数 [0.1, 0.25, 0.5, 0.75, 0.9]。"""
        super().__init__()
        self.quantiles = [0.1, 0.25, 0.5, 0.75, 0.9]  # 5 个分位数
        self.models: Dict[float, object] = {}  # 分位数 → 模型映射

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行分位数集成预测。

        策略：
            - sklearn 可用：训练 5 个分位数 GBR 模型
            - 否则：使用 numpy bootstrap 模拟分位数

        Args:
            video_data (Dict): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        Returns:
            PredictionResult: 包含点预测 + 分位数区间的预测结果
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 10:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "quantile_fallback"},
                timestamp=datetime.now(),
            )

        if _HAS_SKLEARN:
            try:
                return self._sklearn_predict(video_data, threshold)
            except Exception as e:
                logger.debug("分位数集成 sklearn 失败: %s", e)

        return self._numpy_predict(video_data, threshold)

    def _sklearn_predict(self, video_data, threshold):
        """
        使用 sklearn GBR + pinball loss 训练多分位数模型。

        对每个分位数 τ ∈ [0.1, 0.25, 0.5, 0.75, 0.9]：
            - 训练一个独立的 GBR 模型，loss="quantile", alpha=τ
            - 各模型在最新特征上的预测值构成多分位数结果

        特征构造（p=5 滑动窗口，每步 4 维）：
            views[i-j], likes[i-j], coins[i-j], log(views[i-j])

        Args:
            video_data (Dict): 视频数据字典
            threshold (int): 目标阈值

        Returns:
            PredictionResult 或 None
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        likes = np.array([h.get("like_count", 0) for h in history], dtype=np.float64)
        coins = np.array([h.get("coin_count", 0) for h in history], dtype=np.float64)

        p = 5  # 滑动窗口大小
        X, y = [], []
        for i in range(p, len(views)):
            feat = []
            for j in range(1, p + 1):
                feat.extend([views[i - j], likes[i - j], coins[i - j], np.log(max(views[i - j], 1))])
            X.append(feat)
            y.append(views[i])

        X, y = np.array(X), np.array(y)
        if len(X) < 8:
            return None

        y_target = np.diff(views[-len(X) - 1:]) / np.maximum(views[-len(X) - 1 : -1], 1)
        y_target = y_target[-len(X):]

        # 构造最新特征
        last_feat = []
        for j in range(1, p + 1):
            last_feat.extend([views[-j], likes[-j], coins[-j], np.log(max(views[-j], 1))])

        # 对每个分位数分别训练 GBR 模型
        quantile_preds = {}
        for tau in self.quantiles:
            model = _GBR(
                n_estimators=80, max_depth=3, learning_rate=0.1,
                loss="quantile", alpha=tau,  # 使用 Pinball loss
                random_state=42,
            )
            model.fit(X, y_target)
            pred = float(model.predict(np.array([last_feat]))[0])
            quantile_preds[tau] = pred  # 存储该分位数的预测值

        # 中位数 (q50) 作为点预测
        median_growth = quantile_preds.get(0.5, 0)
        lower_growth = quantile_preds.get(0.25, median_growth)   # 下四分位
        upper_growth = quantile_preds.get(0.75, median_growth)   # 上四分位

        predicted_velocity = max(0, median_growth * current_views / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity if predicted_velocity > 0 else float("inf")
            # 区间宽度倒数为置信度：区间越窄 → 置信度越高
            # 区间宽度 = upper_growth - lower_growth
            interval_width = max(upper_growth - lower_growth, 1e-10)
            confidence = max(0.1, min(0.9, 0.5 / (1 + interval_width * 5)))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={
                "method": "quantile_sklearn",
                "q10": round(float(quantile_preds.get(0.1, 0)), 4),  # 10% 下界
                "q50": round(float(median_growth), 4),                # 中位数
                "q90": round(float(quantile_preds.get(0.9, 0)), 4),  # 90% 上界
            },
            timestamp=datetime.now(),
        )

    def _numpy_predict(self, video_data, threshold):
        """
        使用 numpy bootstrap 模拟分位数预测。

        当 sklearn 不可用时，用 bootstrap 抽样估计播放量增量的分布分位数：
            1. 对增量序列有放回抽样 200 次
            2. 每次取均值得到一个 bootstrap 样本
            3. 对 200 个 bootstrap 均值排序后取对应分位数
            4. q50（中位数）作为点预测

        Args:
            video_data (Dict): 视频数据字典
            threshold (int): 目标阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        views = np.array([h.get("view_count", 0) for h in history[-20:]], dtype=np.float64)
        n = len(views)

        if n < 5:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "quantile_fallback"},
                timestamp=datetime.now(),
            )

        # 用 bootstrap 模拟分位数预测
        diffs = np.diff(views)  # 增量序列
        n_boot = 200  # bootstrap 抽样次数
        bootstraps = []
        rng = np.random.RandomState(42)  # 固定种子保证可复现
        for _ in range(n_boot):
            sample = rng.choice(diffs, size=len(diffs), replace=True)  # 有放回抽样
            bootstraps.append(np.mean(sample))  # 每次取均值

        # 排序后取分位数
        bootstraps = np.sort(bootstraps)
        q10 = bootstraps[int(n_boot * 0.1)]   # 10% 分位数
        q25 = bootstraps[int(n_boot * 0.25)]  # 25% 分位数
        q50 = bootstraps[int(n_boot * 0.5)]   # 50% 分位数（中位数）
        q75 = bootstraps[int(n_boot * 0.75)]  # 75% 分位数
        q90 = bootstraps[int(n_boot * 0.9)]   # 90% 分位数

        predicted_velocity = max(0, q50 / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity
            # 区间宽度倒数为置信度
            interval_width = max(q75 - q25, 1e-10)
            confidence = max(0.1, min(0.85, 0.5 / (1 + interval_width * 3)))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={
                "method": "quantile_numpy",
                "q10": round(float(q10), 2),
                "q50": round(float(q50), 2),
                "q90": round(float(q90), 2),
            },
            timestamp=datetime.now(),
        )
