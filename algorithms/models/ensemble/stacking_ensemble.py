"""
Stacking 元学习器 (Stacking Ensemble with Meta-Learner)
用二阶元学习器学习基模型的预测权重，超越简单加权平均

核心原理：
1. 训练阶段：各基模型输出预测，元学习器学习最优组合
2. 预测阶段：元学习器综合基模型输出，给出最终预测
3. 相比简单加权，捕捉模型间的非线性互补关系
"""

import logging
import numpy as np
from typing import Dict, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_SKLEARN = False
try:
    from sklearn.linear_model import Ridge, Lasso
    from sklearn.ensemble import GradientBoostingRegressor
    _HAS_SKLEARN = True
except ImportError:
    pass


class StackingEnsembleAlgorithm(BaseAlgorithm):
    """Stacking 元学习器"""

    name = "Stacking元学习"
    algorithm_id = "stacking_ensemble"
    description = "二阶元学习器学习基模型权重，超越简单加权"
    category = "集成学习"
    default_weight = 1.7

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 20 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "stacking_fallback"}, timestamp=datetime.now(),
            )

        if _HAS_SKLEARN:
            try:
                result = self._sklearn_stack(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("Stacking sklearn 失败: %s", e)

        return self._numpy_stack(video_data, threshold)

    def _sklearn_stack(self, video_data, threshold):
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        likes = np.array([h.get("like_count", 0) for h in history], dtype=np.float64)
        coins = np.array([h.get("coin_count", 0) for h in history], dtype=np.float64)
        n = len(views)

        p = 7
        X, y = [], []
        for i in range(p, n - 1):
            feat = []
            # 基模型1: 简单线性
            feat.append(np.polyfit(np.arange(p), views[i - p: i], 1)[0])
            # 基模型2: 指数增长
            log_views = np.log(np.maximum(views[i - p: i], 1))
            feat.append(np.polyfit(np.arange(p), log_views, 1)[0])
            # 基模型3: 加权移动平均速度
            feat.append(np.mean(np.diff(views[i - p: i])))
            # 基模型4: 互动率趋势
            feat.append(np.mean(likes[i - p: i]) / max(np.mean(views[i - p: i]), 1))
            # 基模型5: 投币趋势
            feat.append(np.mean(coins[i - p: i]) / max(np.mean(views[i - p: i]), 1))
            # 基模型6: 加速度
            diffs = np.diff(views[i - p: i + 1])
            feat.append(np.mean(np.diff(diffs)) if len(diffs) >= 2 else 0)
            # 基模型7: 变异系数
            sm = np.mean(views[i - p: i + 1])
            feat.append(np.std(views[i - p: i + 1]) / max(sm, 1))

            X.append(feat)
            y.append(views[i] - views[i - 1])

        if len(X) < 10:
            return None

        X, y = np.array(X), np.array(y)
        # 元学习器：Ridge + GBM 平均
        split = int(len(X) * 0.8)
        X_train, X_val = X[:split], X[split:]
        y_train, y_val = y[:split], y[split:]

        if len(X_val) < 3:
            X_train, X_val = X, X
            y_train, y_val = y, y

        # Level 0: 基模型训练
        ridge = Ridge(alpha=1.0).fit(X_train, y_train)
        gbm = GradientBoostingRegressor(n_estimators=50, max_depth=3, random_state=42).fit(X_train, y_train)

        # Level 1: 元学习器（用验证集训练）
        ridge_preds = ridge.predict(X_val).reshape(-1, 1)
        gbm_preds = gbm.predict(X_val).reshape(-1, 1)
        meta_X = np.column_stack([ridge_preds, gbm_preds])
        meta = Ridge(alpha=0.1).fit(meta_X, y_val)

        # 预测
        last_feat = np.array([
            np.polyfit(np.arange(p), views[-p:], 1)[0],
            np.polyfit(np.arange(p), np.log(np.maximum(views[-p:], 1)), 1)[0],
            np.mean(np.diff(views[-p:])),
            np.mean(likes[-p:]) / max(np.mean(views[-p:]), 1),
            np.mean(coins[-p:]) / max(np.mean(views[-p:]), 1),
            np.mean(np.diff(np.diff(views[-(p + 1):]))) if n >= p + 2 else 0,
            np.std(views[-p:]) / max(np.mean(views[-p:]), 1),
        ]).reshape(1, -1)

        r_pred = float(ridge.predict(last_feat)[0])
        g_pred = float(gbm.predict(last_feat)[0])
        final_growth = float(meta.predict(np.array([[r_pred, g_pred]]))[0])

        predicted_velocity = max(0, final_growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        meta_weights = meta.coef_
        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
        confidence = max(0.1, min(0.9, 0.5 + 0.2 * abs(meta_weights[0] - meta_weights[1])))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={
                "method": "stacking_sklearn",
                "meta_weights": [round(float(w), 3) for w in meta_weights],
                "base_preds": [round(r_pred, 2), round(g_pred, 2)],
            },
            timestamp=datetime.now(),
        )

    def _numpy_stack(self, video_data, threshold):
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)
        history = video_data.get("history_data", [])

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        n = len(views)

        # 三个简单基模型的预测
        methods = []
        methods.append(np.mean(np.diff(views[-5:])) if n >= 5 else velocity * 3600)
        methods.append(np.polyfit(np.arange(min(10, n)), views[-min(10, n):], 1)[0] if n >= 3 else velocity * 3600)
        if n >= 4:
            log_v = np.log(np.maximum(views[-min(8, n):], 1))
            methods.append(np.polyfit(np.arange(len(log_v)), log_v, 1)[0] * views[-1])
        else:
            methods.append(methods[0])

        # 元学习器：用过去的表现加权
        weights = np.ones(3)
        if n >= 15:
            val_size = n // 4
            errors = []
            for m, method_growth in enumerate(methods):
                pred = views[-val_size - 1] + method_growth
                err = abs(pred - views[-val_size]) / max(views[-val_size], 1)
                errors.append(err)
            weights = np.exp(-np.array(errors))
            weights /= weights.sum()

        growth = np.dot(weights, methods)
        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
        confidence = max(0.1, min(0.85, 0.3 + 0.2 * (weights.max() / max(weights.sum(), 1e-10))))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={
                "method": "stacking_numpy",
                "weights": [round(float(w), 3) for w in weights],
            },
            timestamp=datetime.now(),
        )
