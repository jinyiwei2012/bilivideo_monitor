"""
Blending 集成 (Blending Ensemble)
用留出验证集训练元学习器，防 Stacking 过拟合

区别于 Stacking：
- Stacking: K-fold 交叉验证产生元特征
- Blending: 固定 holdout 验证集，更简单、更防过拟合
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

_HAS_SKLEARN = False
try:
    from sklearn.linear_model import Ridge
    from sklearn.ensemble import GradientBoostingRegressor
    _HAS_SKLEARN = True
except ImportError:
    pass


class BlendingEnsembleAlgorithm(BaseAlgorithm):
    """Blending 集成"""

    name = "Blending集成"
    algorithm_id = "blending_ensemble"
    description = "留出验证集训练元学习器，防过拟合"
    category = "集成学习"
    default_weight = 1.6

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 25 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "blending_fallback"}, timestamp=datetime.now(),
            )

        if _HAS_SKLEARN and len(history) >= 30:
            try:
                return self._sklearn_blend(video_data, threshold)
            except Exception:
                pass

        return self._numpy_blend(video_data, threshold)

    def _sklearn_blend(self, video_data, threshold):
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)
        history = video_data.get("history_data", [])

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        likes = np.array([h.get("like_count", 0) for h in history], dtype=np.float64)
        coins = np.array([h.get("coin_count", 0) for h in history], dtype=np.float64)
        n = len(views)

        p = 6
        X_all, y_all = [], []
        for i in range(p, n - 1):
            feat = [
                np.polyfit(np.arange(p), views[i - p: i], 1)[0],
                np.mean(np.diff(views[i - p: i])),
                np.mean(likes[i - p: i]) / max(np.mean(views[i - p: i]), 1),
                np.mean(coins[i - p: i]) / max(np.mean(views[i - p: i]), 1),
                np.std(views[i - p: i]) / max(np.mean(views[i - p: i]), 1),
                max(views[i - 1] / max(views[i - 2], 1) - 1, 0),
            ]
            X_all.append(feat)
            y_all.append(views[i] - views[i - 1])

        if len(X_all) < 15:
            return None

        X_all, y_all = np.array(X_all), np.array(y_all)
        # Blending: 固定 split (80% train, 20% holdout)
        split = int(len(X_all) * 0.8)
        X_train, X_hold = X_all[:split], X_all[split:]
        y_train, y_hold = y_all[:split], y_all[split:]

        if len(X_hold) < 3:
            X_train, X_hold = X_all, X_all
            y_train, y_hold = y_all, y_all

        models = [
            Ridge(alpha=1.0),
            GradientBoostingRegressor(n_estimators=60, max_depth=3, random_state=42),
            Ridge(alpha=0.1),
        ]
        meta_X_hold = []
        for m in models:
            m.fit(X_train, y_train)
            meta_X_hold.append(m.predict(X_hold))
        meta_X_hold = np.column_stack(meta_X_hold)

        meta = Ridge(alpha=0.5).fit(meta_X_hold, y_hold)

        last_feat = np.array([
            np.polyfit(np.arange(p), views[-p:], 1)[0],
            np.mean(np.diff(views[-p:])),
            np.mean(likes[-p:]) / max(np.mean(views[-p:]), 1),
            np.mean(coins[-p:]) / max(np.mean(views[-p:]), 1),
            np.std(views[-p:]) / max(np.mean(views[-p:]), 1),
            max(views[-1] / max(views[-2], 1) - 1, 0),
        ]).reshape(1, -1)

        base_preds = [float(m.predict(last_feat)[0]) for m in models]
        growth = float(meta.predict(np.array([base_preds]))[0])

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
        confidence = max(0.1, min(0.9, 0.5 + 0.1 * abs(meta.coef_[1] - meta.coef_[0])))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={
                "method": "blending_sklearn",
                "meta_coef": [round(float(c), 3) for c in meta.coef_],
                "holdout_size": len(X_hold),
            },
            timestamp=datetime.now(),
        )

    def _numpy_blend(self, video_data, threshold):
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)
        history = video_data.get("history_data", [])

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        n = len(views)
        diffs = np.diff(views)
        split = int(n * 0.8)

        if split >= 5 and n - split >= 3:
            train_diffs = diffs[:split]
            hold_diffs = diffs[split:]
            train_mean = np.mean(train_diffs)
            train_median = np.median(train_diffs)
            hold_mean = np.mean(hold_diffs)

            biases = [abs(train_mean - hold_mean), abs(train_median - hold_mean)]
            total_bias = sum(biases)
            if total_bias > 1e-10:
                w = [1 - b / (total_bias + 1e-10) for b in biases]
                w = [x / sum(w) for x in w]
                growth = w[0] * train_mean + w[1] * train_median
            else:
                growth = train_mean
        else:
            growth = np.mean(diffs) if len(diffs) > 0 else velocity * 3600

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
        confidence = min(0.85, 0.35 + 0.02 * min(n, 25))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={"method": "blending_numpy"}, timestamp=datetime.now(),
        )
