"""
LightGBM风格梯度提升
基于直方图的梯度提升，比CatBoost的穷举分裂更高效
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import logging

from algorithms.base import BaseAlgorithm

logger = logging.getLogger(__name__)


class LightGBMSimpleAlgorithm(BaseAlgorithm):
    """
    Simplified LightGBM-style Gradient Boosting

    使用直方图分裂策略，速度快于穷举搜索。
    主要特点:
    - 特征分桶 (binning)
    - 直方图统计计算最佳分裂
    - 叶子节点优先生长 (leaf-wise)
    """

    name = "LightGBM风格"
    description = "基于直方图的梯度提升，高效分裂策略"
    category = "机器学习"

    def __init__(self):
        super().__init__()
        self.n_trees = 12
        self.learning_rate = 0.1
        self.max_leaves = 8
        self.num_bins = 32
        self.trees = []

    def predict(
        self, current_views: int, target_views: int, history_data: List[Dict[str, Any]], video_info: Dict[str, Any]
    ) -> Optional[Tuple[int, float]]:
        """预测到达目标播放量所需时间"""
        if not history_data or len(history_data) < 8:
            return None

        try:
            X, y = self._prepare_data(history_data)
            if len(X) < 6:
                return None

            self._train(X, y)

            if current_views >= target_views:
                return (0, 1.0)

            last_features = X[-1].reshape(1, -1)
            predicted_growth = self._predict_single(last_features[0])

            if predicted_growth <= 0:
                views = [d["view"] for d in history_data]
                predicted_growth = max(1, np.mean([views[i] - views[i - 1] for i in range(1, len(views))]))

            remaining = target_views - current_views
            days_needed = remaining / predicted_growth

            if days_needed < 0 or days_needed > 3650:
                return None

            seconds_needed = int(days_needed * 86400)
            confidence = self._calculate_confidence(X, y)

            return (seconds_needed, confidence)

        except Exception as e:
            logger.warning(f"LightGBM预测失败: {e}")
            return None

    def _prepare_data(self, history_data: List[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray]:
        """准备数据：同CatBoost的特征工程"""
        X, y = [], []
        for i in range(len(history_data) - 1):
            current = history_data[i]
            next_data = history_data[i + 1]

            ts = current.get("timestamp", "")
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                day_of_week = dt.weekday() / 7.0
            except Exception:
                day_of_week = 0.5

            features = [
                current.get("view", 0) / 10000,
                current.get("like", 0) / 1000,
                current.get("coin", 0) / 100,
                current.get("share", 0) / 100,
                current.get("reply", 0) / 100,
                current.get("follower", 1000) / 10000,
                day_of_week,
            ]
            growth = next_data.get("view", 0) - current.get("view", 0)
            X.append(features)
            y.append(growth)

        return np.array(X), np.array(y)

    def _train(self, X: np.ndarray, y: np.ndarray):
        """训练直方图基梯度提升（leaf-wise生长）"""
        n_samples = len(X)
        self.base_prediction = np.mean(y)
        predictions = np.full(n_samples, self.base_prediction)
        self.trees = []

        for _ in range(self.n_trees):
            residuals = y - predictions
            # 直方图构建 + leaf-wise树生长
            tree = self._build_histogram_tree(X, residuals)
            self.trees.append(tree)

            # 更新预测
            for i in range(n_samples):
                predictions[i] += self.learning_rate * self._tree_predict(tree, X[i])

            # 早停
            loss = np.mean(residuals**2)
            if loss < 1e-8:
                break

    def _build_histogram_tree(self, X: np.ndarray, y: np.ndarray) -> Dict:
        """构建直方图基决策树（leaf-wise生长）"""
        n_samples, n_features = X.shape

        binned_X, bin_boundaries = self._bin_features(X, n_features)

        # Leaf-wise 生长: 用节点列表，每次找到增益最大的叶子分裂
        nodes = [
            {
                "indices": np.arange(n_samples),
                "depth": 0,
                "value": np.mean(y),
                "left": None,
                "right": None,
                "leaf": True,
            }
        ]

        while True:
            # 找增益最大的叶子
            best_leaf_idx, best_gain, best_split = self._find_best_split(nodes, y, binned_X, n_features, bin_boundaries)

            if best_gain <= 0 or best_leaf_idx < 0:
                break

            # 执行分裂
            if not self._execute_split(nodes, best_leaf_idx, best_split, y, binned_X):
                break

            if self._should_stop_splitting(nodes):
                break

        # 转换为决策树结构
        return self._node_to_tree(nodes[0])

    def _bin_features(self, X, n_features):
        """对每个特征构建直方图分桶，返回分桶矩阵和边界列表"""
        binned_X = np.empty_like(X)
        bin_boundaries = []
        for f in range(n_features):
            col = X[:, f]
            if np.max(col) == np.min(col):
                binned_X[:, f] = 0
                bin_boundaries.append(np.array([0.0]))
                continue
            bins = np.linspace(np.min(col), np.max(col), self.num_bins + 1)
            binned_X[:, f] = np.digitize(col, bins[:-1]) - 1
            bin_boundaries.append(bins)
        return binned_X, bin_boundaries

    def _find_best_split(self, nodes, y, binned_X, n_features, bin_boundaries):
        """在所有叶子节点上扫描所有特征找最佳分裂"""
        best_leaf_idx = -1
        best_gain = 0
        best_split = None

        for idx, node in enumerate(nodes):
            if not node.get("leaf", False):
                continue
            if len(node["indices"]) < 3:
                continue

            indices = node["indices"]
            node_y = y[indices]
            var_y = np.var(node_y)
            if var_y <= 0:
                continue
            n_node = len(indices)

            for f in range(n_features):
                hist_grad = np.zeros(self.num_bins)
                hist_count = np.zeros(self.num_bins, dtype=int)

                for i in indices:
                    bin_id = int(binned_X[i, f])
                    hist_grad[bin_id] += y[i]
                    hist_count[bin_id] += 1

                cum_sum = 0.0
                cum_count = 0
                for b in range(self.num_bins - 1):
                    cum_sum += hist_grad[b]
                    cum_count += hist_count[b]
                    if cum_count < 2 or (n_node - cum_count) < 2:
                        continue

                    left_var = np.var(node_y[:cum_count]) if cum_count > 0 else 0
                    gain = var_y - (cum_count * left_var + (n_node - cum_count) * np.var(node_y[cum_count:])) / n_node

                    if gain > best_gain:
                        best_gain = gain
                        best_leaf_idx = idx
                        best_split = (f, b, bin_boundaries[f][b + 1])

        return best_leaf_idx, best_gain, best_split

    def _execute_split(self, nodes, best_leaf_idx, best_split, y, binned_X):
        """执行分裂操作，成功返回True，失败返回False"""
        leaf = nodes[best_leaf_idx]
        f, bin_thresh, threshold_val = best_split
        indices = leaf["indices"]
        left_mask = binned_X[indices, f] <= bin_thresh
        left_idx = indices[left_mask]
        right_idx = indices[~left_mask]

        if len(left_idx) < 2 or len(right_idx) < 2:
            return False

        leaf["leaf"] = False
        leaf["feature"] = f
        leaf["threshold"] = threshold_val
        leaf["left"] = {
            "indices": left_idx,
            "depth": leaf["depth"] + 1,
            "value": np.mean(y[left_idx]),
            "leaf": True,
            "left": None,
            "right": None,
        }
        leaf["right"] = {
            "indices": right_idx,
            "depth": leaf["depth"] + 1,
            "value": np.mean(y[right_idx]),
            "leaf": True,
            "left": None,
            "right": None,
        }
        nodes.append(leaf["left"])
        nodes.append(leaf["right"])
        return True

    def _should_stop_splitting(self, nodes):
        """检查是否应停止分裂（无可用叶子或达到最大深度）"""
        leaves_viable = [n for n in nodes if n.get("leaf") and len(n["indices"]) >= 3]
        if not leaves_viable:
            return True
        if max(n["depth"] for n in nodes if n.get("leaf")) >= 6:
            return True
        return False

    def _node_to_tree(self, node: Dict) -> Dict:
        """将节点表示转换为树结构"""
        if node.get("leaf", False):
            return {"leaf": True, "value": node["value"]}
        return {
            "leaf": False,
            "feature": node["feature"],
            "threshold": node["threshold"],
            "left": self._node_to_tree(node["left"]),
            "right": self._node_to_tree(node["right"]),
        }

    def _tree_predict(self, tree: Dict, x: np.ndarray) -> float:
        """使用树进行预测（迭代实现）"""
        node = tree
        while not node["leaf"]:
            if x[node["feature"]] <= node["threshold"]:
                node = node["left"]
            else:
                node = node["right"]
        return node["value"]

    def _predict_single(self, x: np.ndarray) -> float:
        """预测单个样本"""
        pred = self.base_prediction
        for tree in self.trees:
            pred += self.learning_rate * self._tree_predict(tree, x)
        return pred

    def _calculate_confidence(self, X: np.ndarray, y: np.ndarray) -> float:
        """计算置信度（采样评估）"""
        n = len(X)
        base_conf = min(0.85, 0.3 + n * 0.02)
        if n >= 5:
            step = max(1, n // 5)
            errors = []
            for i in range(0, n, step):
                pred = self._predict_single(X[i])
                errors.append(abs(y[i] - pred) / (abs(y[i]) + 1))
            fit_quality = max(0, 1 - np.mean(errors))
            base_conf = 0.5 * base_conf + 0.5 * fit_quality
        return min(0.9, base_conf)
