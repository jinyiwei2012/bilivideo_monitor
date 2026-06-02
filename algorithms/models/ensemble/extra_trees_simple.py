"""
极端随机树 (Extra Trees) 预测
优先使用 sklearn.ensemble.ExtraTreesRegressor 真实实现，不可用时回退 numpy 简化版
"""

import math
import logging
import random
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_SKLEARN = False
try:
    from sklearn.ensemble import ExtraTreesRegressor as _ETR

    _HAS_SKLEARN = True
except ImportError:
    pass


class ExtraTreesSimpleAlgorithm(BaseAlgorithm):
    """极端随机树 (Extremely Randomized Trees) 回归

    与随机森林的区别：
    1. 不 bootstrap 采样，使用全部训练数据
    2. 分裂时随机选择分割点（而非最优分割点）

    这些随机化进一步降低方差，在某些数据集上表现优于随机森林。
    """

    name = "ExtraTrees极端树"
    algorithm_id = "extra_trees_simple"
    description = "极端随机树回归，极限随机化降低过拟合"
    category = "集成学习"
    default_weight = 1.2

    def __init__(self):
        super().__init__()
        self.n_trees = 20
        self.max_depth = 6
        self.min_samples_split = 3
        self.trees: List[dict] = []

    class _Node:
        def __init__(self):
            self.feature_idx: Optional[int] = None
            self.threshold: float = 0.0
            self.left: Optional["ExtraTreesSimpleAlgorithm._Node"] = None
            self.right: Optional["ExtraTreesSimpleAlgorithm._Node"] = None
            self.value: float = 0.0
            self.is_leaf: bool = False

    def _build_tree(self, X: np.ndarray, y: np.ndarray, depth: int = 0) -> _Node:
        """构建极端随机树节点"""
        node = self._Node()

        # 终止条件
        if depth >= self.max_depth or len(y) < self.min_samples_split or np.std(y) < 1e-6:
            node.is_leaf = True
            node.value = np.mean(y)
            return node

        n_samples, n_features = X.shape

        # 随机选择特征子集 (Extra Trees: 全部特征)
        n_candidates = max(1, int(math.sqrt(n_features)))
        feature_candidates = random.sample(range(n_features), min(n_candidates, n_features))

        best_var_reduction = -1
        best_feature = None
        best_threshold = None

        for feature_idx in feature_candidates:
            f_min, f_max = float(X[:, feature_idx].min()), float(X[:, feature_idx].max())
            if f_max - f_min < 1e-8:
                continue

            # Extra Trees: 随机选择分割点（而非最优分割点）
            threshold = random.uniform(f_min, f_max)

            left_mask = X[:, feature_idx] <= threshold
            right_mask = ~left_mask

            if np.sum(left_mask) < self.min_samples_split or np.sum(right_mask) < self.min_samples_split:
                continue

            # 方差减少
            y_var = np.var(y)
            left_var = np.var(y[left_mask]) if np.sum(left_mask) > 0 else 0
            right_var = np.var(y[right_mask]) if np.sum(right_mask) > 0 else 0
            n_left = np.sum(left_mask)
            n_right = np.sum(right_mask)
            var_reduction = y_var - (n_left * left_var + n_right * right_var) / len(y)

            if var_reduction > best_var_reduction:
                best_var_reduction = var_reduction
                best_feature = feature_idx
                best_threshold = threshold

        if best_feature is None or best_var_reduction < 0:
            node.is_leaf = True
            node.value = np.mean(y)
            return node

        left_mask = X[:, best_feature] <= best_threshold
        right_mask = ~left_mask

        node.feature_idx = best_feature
        node.threshold = best_threshold
        node.left = self._build_tree(X[left_mask], y[left_mask], depth + 1)
        node.right = self._build_tree(X[right_mask], y[right_mask], depth + 1)
        return node

    def _predict_tree(self, node: _Node, x: np.ndarray) -> float:
        """单棵树预测"""
        if node.is_leaf:
            return node.value
        if x[node.feature_idx] <= node.threshold:
            return self._predict_tree(node.left, x)
        return self._predict_tree(node.right, x)

    def _prepare_features(
        self, views_seq: np.ndarray, features_dict: Dict[str, float]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """准备训练特征和目标"""
        n = len(views_seq)
        if n < 5:
            return np.array([]), np.array([])

        X, y = [], []
        for i in range(4, n):
            features = [
                views_seq[i - 1] / max(views_seq[i - 2], 1) - 1,  # 近期增长率
                views_seq[i - 2] / max(views_seq[i - 3], 1) - 1,  # 中期增长率
                views_seq[i - 1] - views_seq[i - 2],  # 绝对增量
                np.mean(views_seq[max(0, i - 7) : i]),  # 7日平均
                np.std(views_seq[max(0, i - 7) : i]) / max(np.mean(views_seq[max(0, i - 7) : i]), 1),  # 变异系数
            ]
            X.append(features)
            y.append(views_seq[i] - views_seq[i - 1])  # 预测增量

        return np.array(X), np.array(y)

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return self._make_result(0, 1.0, current_views, velocity, {"method": "extra_trees"}, threshold)

        if _HAS_SKLEARN and len(history) >= 10:
            try:
                result = self._sklearn_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("ExtraTrees sklearn 失败，回退 numpy: %s", e)

        # ── numpy 回退 ───────────────────────────
        if len(history) < 6 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return self._make_result(
                predicted_hours, 0.3, current_views, velocity,
                {"method": "extra_trees", "notes": "insufficient_data"}, threshold,
            )

        views_sorted = self._extract_views(history)
        if views_sorted is None or len(views_sorted) < 6:
            return self._make_result(
                remaining / velocity, 0.3, current_views, velocity,
                {"method": "extra_trees_fallback"}, threshold,
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

        model = _ETR(n_estimators=100, max_depth=6, random_state=42, n_jobs=-1)
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
            metadata={"method": "extra_trees_sklearn", "n_estimators": 100},
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
        """执行Extra Trees核心预测"""
        n = len(views_sorted)

        quality = self.get_quality_score(video_data)
        engagement = self.get_engagement_rate(video_data)

        # ── 训练Extra Trees ───────────────────────
        X_train, y_train = self._prepare_features(views_sorted, {"quality": quality, "engagement": engagement})

        if len(X_train) < 5:
            return self._make_result(
                remaining / velocity,
                0.3,
                current_views,
                velocity,
                {"method": "extra_trees_insufficient"},
                threshold,
            )

        # 训练森林
        self.trees = []
        _ = random.random()
        for _ in range(self.n_trees):
            tree = self._build_tree(X_train, y_train)
            self.trees.append(tree)

        # ── 预测 ─────────────────────────────────
        last_features = np.array(
            [
                views_sorted[-1] / max(views_sorted[-2], 1) - 1,
                views_sorted[-2] / max(views_sorted[-3], 1) - 1,
                views_sorted[-1] - views_sorted[-2],
                np.mean(views_sorted[-7:]) if len(views_sorted) >= 7 else np.mean(views_sorted),
                np.std(views_sorted[-7:]) / max(np.mean(views_sorted[-7:]), 1) if len(views_sorted) >= 7 else 0.1,
            ]
        )

        # 所有树预测均值
        tree_preds = [self._predict_tree(t, last_features) for t in self.trees]
        predicted_daily_growth = np.mean(tree_preds)
        pred_std = np.std(tree_preds)

        # 用质量评分调整
        predicted_daily_growth *= 0.8 + 0.4 * quality

        if predicted_daily_growth <= 0:
            predicted_daily_growth = velocity * 24

        forecast_days = min(365, max(10, int((threshold - current_views) / max(predicted_daily_growth, 1)) + 5))

        pred_views = float(current_views)
        target_day = None
        for day in range(1, forecast_days + 1):
            decay = math.exp(-day / (28.0 + 14.0 * engagement))
            growth = predicted_daily_growth * (decay * 0.7 + 0.3)
            pred_views += max(0, growth)
            if pred_views >= threshold:
                target_day = day
                break

        if target_day is not None and target_day <= 365:
            predicted_hours = target_day * 24
            # 置信度: 树间一致性 + 数据量
            consistency = max(0.0, 1.0 - pred_std / max(abs(np.mean(tree_preds)), 1))
            conf = min(0.9, 0.3 + 0.25 * min(1.0, n / 20) + 0.2 * consistency + 0.15 * quality)
        else:
            predicted_hours = remaining / velocity
            conf = 0.35

        return self._make_result(
            predicted_hours,
            conf,
            current_views,
            velocity,
            {
                "method": "extra_trees",
                "n_trees": self.n_trees,
                "predicted_daily_growth": round(float(predicted_daily_growth), 2),
                "tree_std": round(float(pred_std), 2),
                "tree_consistency": round(float(consistency), 3),
                "data_points": n,
            },
            threshold,
        )

    def _make_result(self, predicted_hours, confidence, current_views, velocity, metadata, threshold):
        """构造 PredictionResult"""
        metadata.setdefault("method", "extra_trees")
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
