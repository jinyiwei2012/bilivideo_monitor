"""
Huber鲁棒回归
结合MSE和MAE的损失函数，对异常值不敏感
"""

import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime
import logging

from algorithms.base import BaseAlgorithm

logger = logging.getLogger(__name__)


class HuberRegressionAlgorithm(BaseAlgorithm):
    """
    Huber Robust Regression

    使用 Huber 损失函数 (MSE + MAE 混合) 的线性回归。
    当残差小于 epsilon 时使用平方损失 (高效)，
    大于 epsilon 时使用绝对损失 (鲁棒)。

    适合存在离群值或不规则播放量突增的数据。
    """

    name = "Huber回归"
    description = "Huber鲁棒回归，对异常值不敏感"
    category = "统计模型"

    def __init__(self):
        super().__init__()
        self.epsilon = 1.35
        self.max_iter = 100
        self.tol = 1e-4

    def predict(
        self, current_views: int, target_views: int, history_data: List[Dict[str, Any]], video_info: Dict[str, Any]
    ) -> Optional[Tuple[int, float]]:
        """预测到达目标播放量所需时间"""
        if not history_data or len(history_data) < 8:
            return None

        try:
            X, y, X_last = self._prepare_features(history_data)
            if len(X) < 6:
                return None

            coef, intercept = self._fit_huber(X, y)

            if current_views >= target_views:
                return (0, 1.0)

            predicted_growth = np.dot(coef, X_last) + intercept

            if predicted_growth <= 0:
                views = [d["view"] for d in history_data]
                predicted_growth = max(1, np.mean([views[i] - views[i - 1] for i in range(1, len(views))]))

            remaining = target_views - current_views
            days_needed = remaining / predicted_growth

            if days_needed < 0 or days_needed > 3650:
                return None

            seconds_needed = int(days_needed * 86400)
            confidence = self._calculate_confidence(X, y, coef, intercept)

            return (seconds_needed, confidence)

        except Exception as e:
            logger.warning(f"Huber回归预测失败: {e}")
            return None

    def _prepare_features(self, history_data: List[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """准备特征"""
        X, y = [], []
        for i in range(len(history_data) - 1):
            cur = history_data[i]
            nxt = history_data[i + 1]
            ts = cur.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(str(ts)[:19].replace("T"," "))
                hour = dt.hour / 24.0
                day_week = dt.weekday() / 7.0
            except Exception:
                hour, day_week = 0.5, 0.5

            features = [
                cur.get("view", 0) / 10000,
                cur.get("like", 0) / 1000,
                cur.get("coin", 0) / 100,
                cur.get("share", 0) / 100,
                cur.get("reply", 0) / 100,
                cur.get("follower", 1000) / 10000,
                hour,
                day_week,
            ]
            growth = nxt.get("view", 0) - cur.get("view", 0)
            X.append(features)
            y.append(growth)

        X = np.array(X, dtype=float)
        y = np.array(y, dtype=float)

        # 标准化
        self._X_mean = np.mean(X, axis=0)
        self._X_std = np.std(X, axis=0) + 1e-8
        X_norm = (X - self._X_mean) / self._X_std

        y_mean = np.mean(y)
        y_std = np.std(y) + 1e-8
        y_norm = (y - y_mean) / y_std
        self._y_mean = y_mean
        self._y_std = y_std

        # 最后一个样本的特征（用于预测未来）
        X_last = X_norm[-1]

        return X_norm, y_norm, X_last

    def _huber_loss_gradient(self, r: np.ndarray) -> np.ndarray:
        """Huber损失梯度"""
        return np.where(np.abs(r) <= self.epsilon, r, self.epsilon * np.sign(r))

    def _huber_weights(self, r: np.ndarray) -> np.ndarray:
        """Huber损失权重 (IRLS)"""
        return np.where(np.abs(r) <= self.epsilon, 1.0, self.epsilon / np.abs(r))

    def _fit_huber(self, X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, float]:
        """IRLS (Iteratively Reweighted Least Squares) 拟合Huber回归"""
        n_samples, n_features = X.shape

        # 初始OLS估计
        X_aug = np.column_stack([np.ones(n_samples), X])
        try:
            beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
        except np.linalg.LinAlgError:
            beta = np.zeros(n_features + 1)

        for iteration in range(self.max_iter):
            beta_old = beta.copy()

            # 预测和残差
            pred = X_aug @ beta
            residuals = y - pred
            scale = np.median(np.abs(residuals)) / 0.6745 + 1e-8
            standardized_res = residuals / scale

            # IRLS权重
            w = self._huber_weights(standardized_res)

            # 加权最小二乘
            W = np.diag(w)
            try:
                beta = np.linalg.solve(X_aug.T @ W @ X_aug, X_aug.T @ W @ y)
            except np.linalg.LinAlgError:
                break

            if np.max(np.abs(beta - beta_old)) < self.tol:
                break

        intercept = beta[0]
        coef = beta[1:]

        return coef, intercept

    def _calculate_confidence(self, X: np.ndarray, y: np.ndarray, coef: np.ndarray, intercept: float) -> float:
        """计算置信度"""
        n = len(X)
        base_conf = min(0.85, 0.3 + n * 0.02)
        if n >= 5:
            predictions = X @ coef + intercept
            mape = np.mean(np.abs((y - predictions) / (np.abs(y) + 1)))
            fit_quality = max(0, 1 - mape)
            base_conf = 0.5 * base_conf + 0.5 * fit_quality
        return min(0.9, base_conf)
