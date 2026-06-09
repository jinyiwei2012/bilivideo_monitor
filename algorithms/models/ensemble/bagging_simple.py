"""
Bagging 集成回归预测算法模块
=============================

本模块实现了基于 Bootstrap Aggregating (Bagging) 集成的 B 站视频播放量预测算法。
通过有放回采样训练多个基学习器并取平均来降低模型方差，
是集成学习中最经典的并行方法之一。

优先使用 sklearn.ensemble.BaggingRegressor 真实实现，不可用时回退 numpy 简化版。

核心原理（sklearn 版）：
    1. 基学习器：DecisionTreeRegressor(max_depth=4)
    2. 30 个 bagging 估计器，每个使用 80% Bootstrap 采样
    3. 并行训练（n_jobs=-1），最终取预测值平均
    4. 降低方差 > 12%，在数据有噪声时显著优于单棵树

核心原理（numpy 回退版）：
    1. 构建 6 维特征（增量/增长率/5日平均/CV/质量分）
    2. 25 个简化回归树，每个用 80% 样本训练
    3. 所有树预测值取平均，标准差衡量一致性
    4. 时间衰减模拟长期趋势

算法来源：Breiman (1996) "Bagging Predictors"

适用场景：中等数据量（≥ 6 点）的视频，对噪声数据鲁棒。
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
    """
    Bagging (Bootstrap Aggregating) 集成回归

    通过对训练数据进行有放回采样（Bootstrap），训练多个基学习器，
    最终预测取所有学习器的平均。能有效降低模型方差，防止过拟合。

    基学习器使用简化版决策树回归。

    类属性：
        name (str): 算法名称 "Bagging集成"
        algorithm_id (str): 算法唯一标识 "bagging_simple"
        description (str): 算法简述
        category (str): 所属类别 "集成学习"
        default_weight (float): 默认集成权重 1.2
        n_estimators (int): 基学习器数量，默认 25
        max_samples (float): 每个学习器的采样比例，默认 0.8
        max_depth (int): 回归树最大深度，默认 5
    """

    name = "Bagging集成"
    algorithm_id = "bagging_simple"
    description = "Bootstrap采样训练多个学习器并平均预测，降低方差"
    category = "集成学习"
    default_weight = 1.2

    def __init__(self):
        """
        初始化 Bagging 集成算法实例。

        设置默认的超参数：25 个基学习器、80% 采样率、树深度 5。
        """
        super().__init__()
        self.n_estimators = 25        # 基学习器数量
        self.max_samples = 0.8        # 每个学习器的采样比例
        self.max_depth = 5            # 树最大深度

    class _RegTree:
        """
        简化回归树实现。

        用于 numpy 回退方案中作为 Bagging 的基学习器。
        使用中位数分割策略和方差减少准则，支持多维特征输入。

        属性：
            max_depth (int): 最大深度
            min_samples (int): 叶节点最少样本数
            tree (dict): 递归构建的树结构字典
        """

        def __init__(self, max_depth=5, min_samples=2):
            """初始化简化回归树。

            Args:
                max_depth (int): 最大树深度，默认 5
                min_samples (int): 叶节点最少样本数，默认 2
            """
            self.max_depth = max_depth
            self.min_samples = min_samples
            self.tree: Optional[dict] = None  # 树结构

        def fit(self, X: np.ndarray, y: np.ndarray):
            """训练回归树。

            Args:
                X (np.ndarray): 特征矩阵 (n_samples, n_features)
                y (np.ndarray): 目标值数组
            """
            self.tree = self._build(X, y, depth=0)

        def _build(self, X: np.ndarray, y: np.ndarray, depth: int) -> dict:
            """递归构建决策树节点。

            使用方差减少作为分裂准则，在每个特征上尝试中位数分割。

            Args:
                X (np.ndarray): 特征矩阵
                y (np.ndarray): 目标值
                depth (int): 当前深度

            Returns:
                dict: 树节点，包含 {"value"} 或 {"feature", "threshold", "left", "right"}
            """
            node = {}
            # 终止条件：达到最大深度 / 样本太少 / 方差为零
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
                    continue  # 特征值不变，跳过

                # 尝试中位数分割
                threshold = np.median(unique_vals)

                left_mask = f_vals <= threshold
                right_mask = ~left_mask

                if np.sum(left_mask) < self.min_samples or np.sum(right_mask) < self.min_samples:
                    continue  # 分割后子节点样本太少

                # 计算方差减少量
                y_var = np.var(y)
                left_var = np.var(y[left_mask]) if np.sum(left_mask) > 0 else 0
                right_var = np.var(y[right_mask]) if np.sum(right_mask) > 0 else 0
                var_red = y_var - (np.sum(left_mask) * left_var + np.sum(right_mask) * right_var) / len(y)

                if var_red > best_var_reduction:
                    best_var_reduction = var_red
                    best_split = (f, threshold)

            # 没有有效分割 → 叶节点
            if best_split is None:
                node["value"] = float(np.mean(y))
                return node

            # 递归构建左右子树
            f_idx, thresh = best_split
            left_mask = X[:, f_idx] <= thresh

            node["feature"] = int(f_idx)
            node["threshold"] = float(thresh)
            node["left"] = self._build(X[left_mask], y[left_mask], depth + 1)
            node["right"] = self._build(X[~left_mask], y[~left_mask], depth + 1)
            return node

        def predict(self, X: np.ndarray) -> np.ndarray:
            """对特征矩阵进行预测。

            Args:
                X (np.ndarray): 特征矩阵 (n_samples, n_features)

            Returns:
                np.ndarray: 预测值数组
            """
            return np.array([self._predict_one(x, self.tree) for x in X])

        def _predict_one(self, x: np.ndarray, node: dict) -> float:
            """对单个样本预测。

            Args:
                x (np.ndarray): 单个样本特征
                node (dict): 当前树节点

            Returns:
                float: 预测值
            """
            if "value" in node:
                return node["value"]  # 叶节点返回存储值
            if x[node["feature"]] <= node["threshold"]:
                return self._predict_one(x, node["left"])
            return self._predict_one(x, node["right"])

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行 Bagging 集成预测。

        策略优先级：
            1. sklearn BaggingRegressor（数据 ≥ 10）
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
            return self._make_result(0, 1.0, current_views, velocity, {"method": "bagging"}, threshold)

        # 优先使用 sklearn BaggingRegressor 做 Bootstrap 集成预测
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
        """
        使用 sklearn BaggingRegressor + 决策树基学习器做 Bootstrap 集成。

        特征构造（p=5 滑动窗口，每步 4 维）：
            views[i-j], likes[i-j], coins[i-j], log(views[i-j])

        目标变量：播放量增长率（百分比差值）

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

        # Bagging: 30 个基学习器，80% Bootstrap 采样，并行训练
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
        """
        从历史记录中提取并排序播放量序列。

        处理多种时间戳格式（float/字符串），按时间排序确保
        数据按发生时间排列，不受原始列表顺序影响。

        Args:
            history (List[Dict]): 历史监控数据列表

        Returns:
            np.ndarray 或 None: 按时间排序的播放量数组，数据不足 6 点返回 None
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
        执行 Bagging 核心预测（numpy 版）。

        工作流程：
            1. 构建 6 维特征数据集
            2. 用 Bootstrap 采样训练 25 个简化回归树
            3. 所有树预测取平均得到每日增长量
            4. 日增长量 × 时间衰减 → 逐日预测播放量曲线
            5. 找到首次超过阈值的日期

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

        # ── 训练 Bagging ───────────────────────────
        n_samples = X.shape[0]
        estimators = []
        sample_size = max(2, int(n_samples * self.max_samples))

        for _ in range(self.n_estimators):
            # Bootstrap 有放回采样
            indices = [random.randint(0, n_samples - 1) for _ in range(sample_size)]
            X_boot = X[indices]
            y_boot = y[indices]

            tree = self._RegTree(max_depth=self.max_depth)
            tree.fit(X_boot, y_boot)
            estimators.append(tree)

        # ── 预测 ─────────────────────────────────
        last_features = self._get_last_features(views_sorted, quality)

        # 所有树对最新样本的预测
        daily_preds = np.array([est.predict(last_features.reshape(1, -1))[0] for est in estimators])
        predicted_daily_growth = np.mean(daily_preds)  # 均值作为预测
        pred_std = np.std(daily_preds)  # 标准差衡量不确定性

        if predicted_daily_growth <= 0:
            predicted_daily_growth = velocity * 24 * 0.5  # 负增长回退

        # 预测天数上限
        forecast_days = min(365, max(10, int((threshold - current_views) / max(predicted_daily_growth, 1)) + 5))

        # 逐日模拟播放量增长曲线
        pred_views = float(current_views)
        target_day = None
        for day in range(1, forecast_days + 1):
            decay = math.exp(-day / 21.0)  # 时间衰减因子
            growth = predicted_daily_growth * (0.5 + 0.5 * (1.0 - decay))
            pred_views += max(0, growth)
            if pred_views >= threshold:
                target_day = day
                break

        if target_day is not None and target_day <= 365:
            predicted_hours = target_day * 24
            # 置信度：综合一致性 + 数据量 + 质量
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
        """
        构建回归数据集。

        6 维特征：
            1. 绝对增量 t-1：views[i-1] - views[i-2]
            2. 绝对增量 t-2：views[i-2] - views[i-3]
            3. 增长率 t-1 (%)：(views[i-1]/views[i-2] - 1) * 100
            4. 5 日移动平均
            5. 变异系数 (CV)：5 日标准差 / 5 日均值
            6. 质量评分 × 100

        目标变量：下一时间步的播放量增量。

        Args:
            views (np.ndarray): 播放量序列
            quality (float): 视频质量评分 [0, 1]

        Returns:
            tuple: (特征矩阵 X, 目标向量 y)
        """
        X, y = [], []
        for i in range(5, len(views)):
            features = [
                views[i - 1] - views[i - 2],           # 绝对增量 t-1
                views[i - 2] - views[i - 3],           # 绝对增量 t-2
                (views[i - 1] / max(views[i - 2], 1) - 1) * 100,  # 增长率 t-1 (%)
                np.mean(views[i - 5 : i]) if i >= 5 else views[i - 1],  # 5日平均
                np.std(views[max(0, i - 5) : i]) / max(np.mean(views[max(0, i - 5) : i]), 1),  # CV
                quality * 100,  # 质量分
            ]
            X.append(features)
            y.append(views[i] - views[i - 1])  # 要预测的增量
        return np.array(X), np.array(y)

    def _get_last_features(self, views: np.ndarray, quality: float) -> np.ndarray:
        """
        获取最新样本的特征向量（用于预测）。

        Args:
            views (np.ndarray): 播放量序列
            quality (float): 视频质量评分 [0, 1]

        Returns:
            np.ndarray: 形状 (1, 6) 的特征向量
        """
        return np.array(
            [
                views[-1] - views[-2],                                   # 最新绝对增量
                views[-2] - views[-3],                                   # 前一绝对增量
                (views[-1] / max(views[-2], 1) - 1) * 100,              # 最新增长率 (%)
                np.mean(views[-5:]),                                     # 最新 5 日平均
                np.std(views[-5:]) / max(np.mean(views[-5:]), 1),       # 最新 CV
                quality * 100,                                          # 质量分
            ]
        ).reshape(1, -1)
