"""
极端随机树 (Extra Trees) 预测算法模块
=====================================

本模块实现了基于极端随机树 (Extremely Randomized Trees) 的 B 站视频播放量预测算法。
Extra Trees 与随机森林类似但引入了更多随机性，进一步降低方差。

优先使用 sklearn.ensemble.ExtraTreesRegressor 真实实现，不可用时回退 numpy 简化版。

核心原理：
    1. 不使用 Bootstrap 采样（使用全部训练数据）
    2. 分裂时不搜索最优分割点，而是随机选择分割点
    3. 更极端的随机化比随机森林更能降低方差
    4. 在特征量少、数据噪声大的情况下表现优于随机森林

与随机森林的关键区别：
    - 随机森林：Bootstrap 采样 + 最优分割点
    - Extra Trees：全数据 + 随机分割点（进一步去相关化）
    代价：偏差可能略高，但方差显著更低。

适用场景：噪声较大的播放量数据，过拟合风险高的场景。
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
    """
    极端随机树 (Extremely Randomized Trees) 回归

    与随机森林的区别：
        1. 不 bootstrap 采样，使用全部训练数据
        2. 分裂时随机选择分割点（而非最优分割点）

    这些随机化进一步降低方差，在某些数据集上表现优于随机森林。

    类属性：
        name (str): 算法名称 "ExtraTrees极端树"
        algorithm_id (str): 算法唯一标识 "extra_trees_simple"
        description (str): 算法简述
        category (str): 所属类别 "集成学习"
        default_weight (float): 默认集成权重 1.2
        n_trees (int): 树的数量，默认 20
        max_depth (int): 最大深度，默认 6
        min_samples_split (int): 分裂最少样本数，默认 3
    """

    name = "ExtraTrees极端树"
    algorithm_id = "extra_trees_simple"
    description = "极端随机树回归，极限随机化降低过拟合"
    category = "集成学习"
    default_weight = 1.2

    def __init__(self):
        """
        初始化 Extra Trees 算法实例。

        设置默认超参数：20 棵树、深度 6、最少分裂样本 3。
        """
        super().__init__()
        self.n_trees = 20             # 树的数量
        self.max_depth = 6            # 最大深度
        self.min_samples_split = 3    # 分裂最少样本数
        self.trees: List[dict] = []   # 训练好的树列表

    class _Node:
        """
        极端随机树节点。

        属性：
            feature_idx (int): 分裂特征索引
            threshold (float): 分裂阈值
            left (_Node): 左子节点
            right (_Node): 右子节点
            value (float): 叶节点预测值
            is_leaf (bool): 是否为叶节点
        """
        def __init__(self):
            self.feature_idx: Optional[int] = None
            self.threshold: float = 0.0
            self.left: Optional["ExtraTreesSimpleAlgorithm._Node"] = None
            self.right: Optional["ExtraTreesSimpleAlgorithm._Node"] = None
            self.value: float = 0.0
            self.is_leaf: bool = False

    def _build_tree(self, X: np.ndarray, y: np.ndarray, depth: int = 0) -> _Node:
        """
        递归构建极端随机树节点。

        Extra Trees 的核心：分裂时随机选择分割点，而非搜索最优值。
        这比寻找最优分割点更快，且进一步去相关化各树，降低集成方差。

        Args:
            X (np.ndarray): 特征矩阵 (n_samples, n_features)
            y (np.ndarray): 目标值数组
            depth (int): 当前深度

        Returns:
            _Node: 构建的树节点
        """
        node = self._Node()

        # 终止条件：深度达到上限 / 样本太少 / 方差为零
        if depth >= self.max_depth or len(y) < self.min_samples_split or np.std(y) < 1e-6:
            node.is_leaf = True
            node.value = np.mean(y)
            return node

        n_samples, n_features = X.shape

        # 随机选择特征子集（默认使用 sqrt(n_features) 个特征）
        n_candidates = max(1, int(math.sqrt(n_features)))
        feature_candidates = random.sample(range(n_features), min(n_candidates, n_features))

        best_var_reduction = -1
        best_feature = None
        best_threshold = None

        for feature_idx in feature_candidates:
            f_min, f_max = float(X[:, feature_idx].min()), float(X[:, feature_idx].max())
            if f_max - f_min < 1e-8:
                continue  # 特征值不变，跳过

            # Extra Trees 核心差异：随机选择分割点（而非搜索最优分割点）
            threshold = random.uniform(f_min, f_max)

            left_mask = X[:, feature_idx] <= threshold
            right_mask = ~left_mask

            if np.sum(left_mask) < self.min_samples_split or np.sum(right_mask) < self.min_samples_split:
                continue  # 分裂后子节点样本太少

            # 计算方差减少量评估分裂质量
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

        # 没有有效分裂 → 叶节点
        if best_feature is None or best_var_reduction < 0:
            node.is_leaf = True
            node.value = np.mean(y)
            return node

        # 递归构建左右子树
        left_mask = X[:, best_feature] <= best_threshold
        right_mask = ~left_mask

        node.feature_idx = best_feature
        node.threshold = best_threshold
        node.left = self._build_tree(X[left_mask], y[left_mask], depth + 1)
        node.right = self._build_tree(X[right_mask], y[right_mask], depth + 1)
        return node

    def _predict_tree(self, node: _Node, x: np.ndarray) -> float:
        """
        单棵树对单个样本的预测。

        递归遍历树直到到达叶节点。

        Args:
            node (_Node): 当前树节点
            x (np.ndarray): 单个样本特征向量

        Returns:
            float: 预测值
        """
        if node.is_leaf:
            return node.value
        if x[node.feature_idx] <= node.threshold:
            return self._predict_tree(node.left, x)
        return self._predict_tree(node.right, x)

    def _prepare_features(
        self, views_seq: np.ndarray, features_dict: Dict[str, float]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        准备训练特征和目标。

        5 维特征：
            1. 近期增长率：views[i-1]/views[i-2] - 1
            2. 中期增长率：views[i-2]/views[i-3] - 1
            3. 绝对增量：views[i-1] - views[i-2]
            4. 7 日移动平均
            5. 变异系数 (CV)：7 日标准差 / 7 日均值

        目标：下一时间步的播放量增量。

        Args:
            views_seq (np.ndarray): 播放量序列
            features_dict (Dict): 额外特征字典（quality, engagement）

        Returns:
            Tuple[np.ndarray, np.ndarray]: (特征矩阵 X, 目标向量 y)
        """
        n = len(views_seq)
        if n < 5:
            return np.array([]), np.array([])

        X, y = [], []
        for i in range(4, n):
            features = [
                views_seq[i - 1] / max(views_seq[i - 2], 1) - 1,  # 近期增长率
                views_seq[i - 2] / max(views_seq[i - 3], 1) - 1,  # 中期增长率
                views_seq[i - 1] - views_seq[i - 2],               # 绝对增量
                np.mean(views_seq[max(0, i - 7) : i]),             # 7日平均
                np.std(views_seq[max(0, i - 7) : i]) / max(np.mean(views_seq[max(0, i - 7) : i]), 1),  # 变异系数
            ]
            X.append(features)
            y.append(views_seq[i] - views_seq[i - 1])  # 预测增量

        return np.array(X), np.array(y)

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行 Extra Trees 预测。

        策略优先级：
            1. sklearn ExtraTreesRegressor（数据 ≥ 10）
            2. numpy 简化版（数据 ≥ 6）
            3. 匀速外推回退

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
            return self._make_result(0, 1.0, current_views, velocity, {"method": "extra_trees"}, threshold)

        # 优先使用 sklearn ExtraTreesRegressor 做极限随机树预测
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
        """
        使用 sklearn ExtraTreesRegressor 做极限随机树回归预测。

        特征构造（p=5 滑动窗口，每步 4 维）：
            views[i-j], likes[i-j], coins[i-j], log(views[i-j])

        Extra Trees 参数：
            - n_estimators=100: 100 棵树
            - max_depth=6: 最大深度
            - 全数据训练（不使用 Bootstrap）

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

        # ExtraTrees: 100 棵树，随机分割点，全数据训练（不 Bootstrap）
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
        """
        从历史记录中提取并排序播放量序列。

        处理多种时间戳格式（float/字符串），按时间排序。

        Args:
            history (List[Dict]): 历史监控数据列表

        Returns:
            np.ndarray 或 None: 按时间排序的播放量数组
        """
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
        order = np.argsort(timestamps)  # 按时间排序
        return np.array(views_vals, dtype=float)[order]

    def _predict_impl(self, views_sorted, current_views, velocity, remaining, threshold, video_data):
        """
        执行 Extra Trees 核心预测（numpy 版）。

        工作流程：
            1. 训练 20 棵极端随机树（随机分割点）
            2. 所有树对最新样本预测取均值
            3. 用质量评分调整日增长量
            4. 时间衰减逐日模拟播放量增长
            5. 树间一致性作为置信度参考

        Args:
            views_sorted (np.ndarray): 按时间排序的播放量数组
            current_views (int): 当前播放量
            velocity (float): 当前速度
            remaining (int): 剩余播放量
            threshold (int): 目标阈值
            video_data (Dict): 视频数据字典

        Returns:
            PredictionResult: 预测结果对象
        """
        n = len(views_sorted)

        quality = self.get_quality_score(video_data)
        engagement = self.get_engagement_rate(video_data)

        # ── 训练 Extra Trees ───────────────────────
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

        # 训练 20 棵极端随机树
        self.trees = []
        _ = random.random()  # 初始化随机数生成器
        for _ in range(self.n_trees):
            tree = self._build_tree(X_train, y_train)
            self.trees.append(tree)

        # ── 构造最新特征用于预测 ─────────────────
        last_features = np.array(
            [
                views_sorted[-1] / max(views_sorted[-2], 1) - 1,  # 近期增长率
                views_sorted[-2] / max(views_sorted[-3], 1) - 1,  # 中期增长率
                views_sorted[-1] - views_sorted[-2],               # 绝对增量
                np.mean(views_sorted[-7:]) if len(views_sorted) >= 7 else np.mean(views_sorted),  # 7日平均
                np.std(views_sorted[-7:]) / max(np.mean(views_sorted[-7:]), 1) if len(views_sorted) >= 7 else 0.1,  # CV
            ]
        )

        # 所有树的预测取均值
        tree_preds = [self._predict_tree(t, last_features) for t in self.trees]
        predicted_daily_growth = np.mean(tree_preds)
        pred_std = np.std(tree_preds)  # 树间预测标准差

        # 用质量评分调整日增长量
        predicted_daily_growth *= 0.8 + 0.4 * quality  # 质量分 0→0.8, 质量分 1→1.2

        if predicted_daily_growth <= 0:
            predicted_daily_growth = velocity * 24  # 负增长回退

        # 预测天数上限
        forecast_days = min(365, max(10, int((threshold - current_views) / max(predicted_daily_growth, 1)) + 5))

        # 逐日模拟播放量增长（带互动率调整的时间衰减）
        pred_views = float(current_views)
        target_day = None
        for day in range(1, forecast_days + 1):
            decay = math.exp(-day / (28.0 + 14.0 * engagement))  # 互动率越高衰减越慢
            growth = predicted_daily_growth * (decay * 0.7 + 0.3)
            pred_views += max(0, growth)
            if pred_views >= threshold:
                target_day = day
                break

        if target_day is not None and target_day <= 365:
            predicted_hours = target_day * 24
            # 置信度: 树间一致性 + 数据量 + 质量
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
        """
        构造统一的 PredictionResult 对象。

        Args:
            predicted_hours (float): 预测到达阈值所需小时数
            confidence (float): 置信度 [0, 1]
            current_views (int): 当前播放量
            velocity (float): 当前速度
            metadata (Dict): 预测元数据
            threshold (int): 目标阈值

        Returns:
            PredictionResult: 标准预测结果对象
        """
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
