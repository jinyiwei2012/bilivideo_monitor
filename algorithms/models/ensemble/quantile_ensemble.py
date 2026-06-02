"""
概率预测包装器 (Probabilistic Prediction Wrapper)
为集成学习模型增加分位数回归能力，输出预测区间

核心思路：
1. 对每个阈值同时预测多个分位数（10%/25%/50%/75%/90%）
2. 50% 分位数 = 点预测，其他分位数 = 置信区间
3. 使用 Pinball Loss 训练分位数回归
4. 区间宽度反映预测不确定性
"""

import logging
from typing import Dict, List, Tuple, Optional
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
    """Pinball loss for quantile regression."""
    diff = y_true - y_pred
    return np.mean(np.maximum(tau * diff, (tau - 1) * diff))


class QuantileEnsembleAlgorithm(BaseAlgorithm):
    """分位数集成预测 — 输出置信区间"""

    name = "分位数集成"
    algorithm_id = "quantile_ensemble"
    description = "多分位数回归集成预测，输出点预测+上下界"
    category = "集成学习"
    default_weight = 1.5

    def __init__(self):
        super().__init__()
        self.quantiles = [0.1, 0.25, 0.5, 0.75, 0.9]
        self.models: Dict[float, object] = {}

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
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
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        likes = np.array([h.get("like_count", 0) for h in history], dtype=np.float64)
        coins = np.array([h.get("coin_count", 0) for h in history], dtype=np.float64)

        p = 5
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

        last_feat = []
        for j in range(1, p + 1):
            last_feat.extend([views[-j], likes[-j], coins[-j], np.log(max(views[-j], 1))])

        quantile_preds = {}
        for tau in self.quantiles:
            model = _GBR(
                n_estimators=80, max_depth=3, learning_rate=0.1,
                loss="quantile", alpha=tau, random_state=42,
            )
            model.fit(X, y_target)
            pred = float(model.predict(np.array([last_feat]))[0])
            quantile_preds[tau] = pred

        median_growth = quantile_preds.get(0.5, 0)
        lower_growth = quantile_preds.get(0.25, median_growth)
        upper_growth = quantile_preds.get(0.75, median_growth)

        predicted_velocity = max(0, median_growth * current_views / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity if predicted_velocity > 0 else float("inf")
            # 区间宽度倒数为置信度
            interval_width = max(upper_growth - lower_growth, 1e-10)
            confidence = max(0.1, min(0.9, 0.5 / (1 + interval_width * 5)))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={
                "method": "quantile_sklearn",
                "q10": round(float(quantile_preds.get(0.1, 0)), 4),
                "q50": round(float(median_growth), 4),
                "q90": round(float(quantile_preds.get(0.9, 0)), 4),
            },
            timestamp=datetime.now(),
        )

    def _numpy_predict(self, video_data, threshold):
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
        diffs = np.diff(views)
        n_boot = 200
        bootstraps = []
        rng = np.random.RandomState(42)
        for _ in range(n_boot):
            sample = rng.choice(diffs, size=len(diffs), replace=True)
            bootstraps.append(np.mean(sample))

        bootstraps = np.sort(bootstraps)
        q10 = bootstraps[int(n_boot * 0.1)]
        q25 = bootstraps[int(n_boot * 0.25)]
        q50 = bootstraps[int(n_boot * 0.5)]
        q75 = bootstraps[int(n_boot * 0.75)]
        q90 = bootstraps[int(n_boot * 0.9)]

        predicted_velocity = max(0, q50 / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity
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
