"""
Bagging集成回归预测
优先使用 sklearn.ensemble.BaggingRegressor 真实实现，不可用时回退 numpy 简化版
"""

import math
import logging
import random
import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_SKLEARN = False
try:
    from sklearn.ensemble import BaggingRegressor
    from sklearn.tree import DecisionTreeRegressor

    _HAS_SKLEARN = True
except ImportError:
    pass


class BaggingSimpleAlgorithm(BaseAlgorithm):
    """Bagging (Bootstrap Aggregating) 集成回归

    通过对训练数据进行有放回采样（Bootstrap），训练多个基学习器，
    最终预测取所有学习器的平均。能有效降低模型方差，防止过拟合。

    基学习器使用简化版决策树回归。
    """

    name = "Bagging集成"
    algorithm_id = "bagging_simple"
    description = "Bootstrap采样训练多个学习器并平均预测，降低方差"
    category = "集成学习"
    default_weight = 1.2

    def __init__(self):
        super().__init__()
        self.n_estimators = 25
        self.max_samples = 0.8  # 每个学习器的采样比例
        self.max_depth = 5

    class _RegTree:
        """简化回归树"""

        def __init__(self, max_depth=5, min_samples=2):
            self.max_depth = max_depth
            self.min_samples = min_samples
            self.tree: Optional[dict] = None

        def fit(self, X: np.ndarray, y: np.ndarray):
            self.tree = self._build(X, y, depth=0)

        def _build(self, X: np.ndarray, y: np.ndarray, depth: int) -> dict:
            node = {}
            if depth >= self.max_depth or len(y) < self.min_samples or np.std(y) < 1e-8:
                node["value"] = float(np.mean(y))
                return node

            n_features = X.shape[1]
            best_var_reduction = -1
            best_split = None

            for f in range(n_features):
                f_vals = X[:, f]
                unique_vals = np.unique(f_vals)
                if len(unique_vals) < 2:
                    continue

                # 尝试中位数分割
                threshold = np.median(unique_vals)

                left_mask = f_vals <= threshold
                right_mask = ~left_mask

                if np.sum(left_mask) < self.min_samples or np.sum(right_mask) < self.min_samples:
                    continue

                y_var = np.var(y)
                left_var = np.var(y[left_mask]) if np.sum(left_mask) > 0 else 0
                right_var = np.var(y[right_mask]) if np.sum(right_mask) > 0 else 0
                var_red = y_var - (np.sum(left_mask) * left_var + np.sum(right_mask) * right_var) / len(y)

                if var_red > best_var_reduction:
                    best_var_reduction = var_red
                    best_split = (f, threshold)

            if best_split is None:
                node["value"] = float(np.mean(y))
                return node

            f_idx, thresh = best_split
            left_mask = X[:, f_idx] <= thresh

            node["feature"] = int(f_idx)
            node["threshold"] = float(thresh)
            node["left"] = self._build(X[left_mask], y[left_mask], depth + 1)
            node["right"] = self._build(X[~left_mask], y[~left_mask], depth + 1)
            return node

        def predict(self, X: np.ndarray) -> np.ndarray:
            return np.array([self._predict_one(x, self.tree) for x in X])

        def _predict_one(self, x: np.ndarray, node: dict) -> float:
            if "value" in node:
                return node["value"]
            if x[node["feature"]] <= node["threshold"]:
                return self._predict_one(x, node["left"])
            return self._predict_one(x, node["right"])

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return self._make_result(0, 1.0, current_views, velocity, {"method": "bagging"}, threshold)

        if _HAS_SKLEARN and len(history) >= 10:
            try:
                result = self._sklearn_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("Bagging sklearn 失败，回退 numpy: %s", e)

        # ── numpy 回退 ───────────────────────────
        if len(history) < 6 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return self._make_result(
                predicted_hours, 0.3, current_views, velocity,
                {"method": "bagging", "notes": "insufficient_data"}, threshold,
            )

        views_sorted = self._extract_views(history)
        if views_sorted is None or len(views_sorted) < 6:
            return self._make_result(
                remaining / velocity, 0.3, current_views, velocity,
                {"method": "bagging_fallback"}, threshold,
            )

        try:
            return self._predict_impl(views_sorted, current_views, velocity, remaining, threshold, video_data)
        except Exception as e:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return self._make_result(predicted_hours, 0.0, current_views, velocity, {"error": str(e)}, threshold)

    def _sklearn_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
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

        base = DecisionTreeRegressor(max_depth=4, random_state=42)
        model = BaggingRegressor(
            estimator=base, n_estimators=30, max_samples=0.8, random_state=42, n_jobs=-1,
        )
        model.fit(X, y_target)

        last_feat = []
        for j in range(1, p + 1):
            last_feat.extend([views[-j], likes[-j], coins[-j], np.log(max(views[-j], 1))])
        pred_growth = float(model.predict(np.array([last_feat]))[0])
        predicted_velocity = max(0, pred_growth * current_views / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity if predicted_velocity > 0 else float("inf")
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
            metadata={"method": "bagging_sklearn", "n_estimators": 30},
            timestamp=datetime.now(),
        )

    def _extract_views(self, history):
        """从历史记录中提取并排序播放量序列"""
        timestamps, views_vals = [], []
        for h in history:
            ts = h.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(str(ts)[:19].replace("T", " ")).timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))
        if len(views_vals) < 6:
            return None
        order = np.argsort(timestamps)
        return np.array(views_vals, dtype=float)[order]

    def _predict_impl(self, views_sorted, current_views, velocity, remaining, threshold, video_data):
        """执行Bagging核心预测"""
        n = len(views_sorted)

        quality = self.get_quality_score(video_data)

        # ── 构建特征 ──────────────────────────────
        X, y = self._build_dataset(views_sorted, quality)

        if len(X) < 5:
            return self._make_result(
                remaining / velocity,
                0.3,
                current_views,
                velocity,
                {"method": "bagging_insufficient"},
                threshold,
            )

        # ── 训练Bagging ───────────────────────────
        n_samples = X.shape[0]
        estimators = []
        sample_size = max(2, int(n_samples * self.max_samples))

        for _ in range(self.n_estimators):
            # Bootstrap采样
            indices = [random.randint(0, n_samples - 1) for _ in range(sample_size)]
            X_boot = X[indices]
            y_boot = y[indices]

            tree = self._RegTree(max_depth=self.max_depth)
            tree.fit(X_boot, y_boot)
            estimators.append(tree)

        # ── 预测 ─────────────────────────────────
        last_features = self._get_last_features(views_sorted, quality)

        daily_preds = np.array([est.predict(last_features.reshape(1, -1))[0] for est in estimators])
        predicted_daily_growth = np.mean(daily_preds)
        pred_std = np.std(daily_preds)

        if predicted_daily_growth <= 0:
            predicted_daily_growth = velocity * 24 * 0.5

        forecast_days = min(365, max(10, int((threshold - current_views) / max(predicted_daily_growth, 1)) + 5))

        pred_views = float(current_views)
        target_day = None
        for day in range(1, forecast_days + 1):
            decay = math.exp(-day / 21.0)
            growth = predicted_daily_growth * (0.5 + 0.5 * (1.0 - decay))
            pred_views += max(0, growth)
            if pred_views >= threshold:
                target_day = day
                break

        if target_day is not None and target_day <= 365:
            predicted_hours = target_day * 24
            cv = pred_std / max(abs(np.mean(daily_preds)), 1)
            consistency = max(0.0, 1.0 - min(cv, 2.0) * 0.5)
            conf = min(0.9, 0.3 + 0.25 * min(1.0, n / 20) + 0.25 * consistency + 0.1 * quality)
        else:
            predicted_hours = remaining / velocity
            conf = 0.35

        return self._make_result(
            predicted_hours,
            conf,
            current_views,
            velocity,
            {
                "method": "bagging",
                "n_estimators": self.n_estimators,
                "daily_growth": round(float(predicted_daily_growth), 2),
                "pred_std": round(float(pred_std), 2),
                "consistency": round(float(consistency), 3),
                "data_points": n,
            },
            threshold,
        )

    def _make_result(self, predicted_hours, confidence, current_views, velocity, metadata, threshold):
        """构造 PredictionResult"""
        metadata.setdefault("method", "bagging")
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata=metadata,
            timestamp=datetime.now(),
        )

    def _build_dataset(self, views: np.ndarray, quality: float) -> tuple:
        """构建回归数据集"""
        X, y = [], []
        for i in range(5, len(views)):
            features = [
                views[i - 1] - views[i - 2],  # 绝对增量 t-1
                views[i - 2] - views[i - 3],  # 绝对增量 t-2
                (views[i - 1] / max(views[i - 2], 1) - 1) * 100,  # 增长率 t-1 (%)
                np.mean(views[i - 5 : i]) if i >= 5 else views[i - 1],  # 5日平均
                np.std(views[max(0, i - 5) : i]) / max(np.mean(views[max(0, i - 5) : i]), 1),  # CV
                quality * 100,  # 质量分
            ]
            X.append(features)
            y.append(views[i] - views[i - 1])  # 要预测的增量
        return np.array(X), np.array(y)

    def _get_last_features(self, views: np.ndarray, quality: float) -> np.ndarray:
        """获取最后一个样本的特征"""
        return np.array(
            [
                views[-1] - views[-2],
                views[-2] - views[-3],
                (views[-1] / max(views[-2], 1) - 1) * 100,
                np.mean(views[-5:]),
                np.std(views[-5:]) / max(np.mean(views[-5:]), 1),
                quality * 100,
            ]
        ).reshape(1, -1)
