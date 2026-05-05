"""
ElasticNet回归
结合L1(Lasso)和L2(Ridge)正则化的线性回归，适合处理相关特征
"""
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime
from algorithms.base import BaseAlgorithm


class ElasticNetRegressionAlgorithm(BaseAlgorithm):
    """
    Elastic Net Regression

    结合 L1 (Lasso) 和 L2 (Ridge) 正则化，兼具特征选择和系数收缩能力。
    使用坐标下降法优化，适合特征间存在相关性的场景。
    """

    name = "ElasticNet回归"
    description = "L1+L2正则化线性回归，坐标下降优化"
    category = "统计模型"

    def __init__(self):
        super().__init__()
        self.alpha = 0.01
        self.l1_ratio = 0.5
        self.max_iter = 1000
        self.tol = 1e-4
        self.coef_ = None
        self.intercept_ = 0.0

    def predict(
        self,
        current_views: int,
        target_views: int,
        history_data: List[Dict[str, Any]],
        video_info: Dict[str, Any]
    ) -> Optional[Tuple[int, float]]:
        """预测到达目标播放量所需时间"""
        if not history_data or len(history_data) < 8:
            return None

        try:
            X, y = self._prepare_features(history_data)
            if len(X) < 6:
                return None

            self._fit(X, y)

            if current_views >= target_views:
                return (0, 1.0)

            last_features = X[-1]
            predicted_growth = np.dot(self.coef_, last_features) + self.intercept_

            if predicted_growth <= 0:
                views = [d['view'] for d in history_data]
                predicted_growth = max(1, np.mean([views[i] - views[i-1]
                                                   for i in range(1, len(views))]))

            remaining = target_views - current_views
            days_needed = remaining / predicted_growth

            if days_needed < 0 or days_needed > 3650:
                return None

            seconds_needed = int(days_needed * 86400)
            confidence = self._calculate_confidence(X, y)

            return (seconds_needed, confidence)

        except Exception as e:
            print(f"ElasticNet预测失败: {e}")
            return None

    def _prepare_features(self, history_data: List[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray]:
        """准备特征：播放量、互动指标、时间特征"""
        X, y = [], []
        for i in range(len(history_data) - 1):
            cur = history_data[i]
            nxt = history_data[i + 1]
            ts = cur.get('timestamp', '')
            try:
                dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
                hour = dt.hour / 24.0
                day_week = dt.weekday() / 7.0
            except Exception:
                hour, day_week = 0.5, 0.5

            features = [
                1.0,
                cur.get('view', 0) / 10000,
                cur.get('like', 0) / 1000,
                cur.get('coin', 0) / 100,
                cur.get('share', 0) / 100,
                cur.get('reply', 0) / 100,
                cur.get('follower', 1000) / 10000,
                hour,
                day_week,
            ]
            growth = nxt.get('view', 0) - cur.get('view', 0)
            X.append(features)
            y.append(growth)

        X = np.array(X, dtype=float)
        y = np.array(y, dtype=float)

        # 标准化
        self._X_mean = np.mean(X, axis=0)
        self._X_std = np.std(X, axis=0) + 1e-8
        X = (X - self._X_mean) / self._X_std

        # 标准化 y
        self._y_mean = np.mean(y)
        self._y_std = np.std(y) + 1e-8
        y = (y - self._y_mean) / self._y_std

        return X, y

    def _soft_threshold(self, x: float, thresh: float) -> float:
        """软阈值函数"""
        if x > thresh:
            return x - thresh
        elif x < -thresh:
            return x + thresh
        return 0.0

    def _fit(self, X: np.ndarray, y: np.ndarray):
        """使用坐标下降拟合ElasticNet"""
        n_samples, n_features = X.shape
        self.coef_ = np.zeros(n_features)
        self.intercept_ = 0.0

        l1_penalty = self.alpha * self.l1_ratio
        l2_penalty = self.alpha * (1 - self.l1_ratio)

        residuals = y.copy()

        for _ in range(self.max_iter):
            max_change = 0.0

            # 更新截距
            old_intercept = self.intercept_
            self.intercept_ = np.mean(residuals + self.intercept_)
            residuals += old_intercept - self.intercept_
            max_change = max(max_change, abs(old_intercept - self.intercept_))

            # 更新每个特征系数
            for j in range(n_features):
                old_coef = self.coef_[j]
                X_j = X[:, j]

                # 偏残差: 移除当前特征贡献
                residuals += X_j * old_coef

                # 计算 rho = <X_j, residuals>
                rho = np.dot(X_j, residuals) / n_samples

                # ElasticNet更新
                if l2_penalty > 0:
                    self.coef_[j] = self._soft_threshold(rho, l1_penalty) / (1 + l2_penalty)
                else:
                    self.coef_[j] = self._soft_threshold(rho, l1_penalty)

                # 更新残差
                residuals -= X_j * self.coef_[j]
                max_change = max(max_change, abs(old_coef - self.coef_[j]))

            if max_change < self.tol:
                break

        # 还原缩放
        self.coef_ = self.coef_ * self._y_std / self._X_std
        self.intercept_ = self._y_mean - np.dot(self._X_mean, self.coef_)

    def _calculate_confidence(self, X: np.ndarray, y: np.ndarray) -> float:
        """计算置信度（使用拟合后的原始尺度）"""
        n = len(X)
        base_conf = min(0.85, 0.3 + n * 0.02)
        if n >= 5:
            predictions = X @ self.coef_ + self.intercept_
            mape = np.mean(np.abs((y - predictions) / (np.abs(y) + 1)))
            fit_quality = max(0, 1 - mape)
            base_conf = 0.5 * base_conf + 0.5 * fit_quality
        return min(0.9, base_conf)
