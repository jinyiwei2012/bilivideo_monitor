"""
泊松回归预测
基于计数分布的回归模型，适合非负整数的播放增量预测
"""

import math
import numpy as np
from typing import Dict, Any, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class PoissonRegressionAlgorithm(BaseAlgorithm):
    """泊松回归 (Poisson Regression)

    播放量增量为非负整数，使用泊松分布或负二项分布建模更合理。
    - 泊松分布: 均值=方差（适合常规情况）
    - 负二项分布: 方差>均值（适合过度离散的数据，如病毒式传播）

    使用广义线性模型 (GLM) 框架，连接函数为 log link。
    """

    name = "泊松回归"
    algorithm_id = "poisson_regression"
    description = "基于计数分布的广义线性模型，适合非负整数预测"
    category = "统计模型"
    default_weight = 1.1

    def __init__(self):
        super().__init__()
        self.coef = None
        self.intercept = 0.0
        self.alpha = 0.01  # L2正则化强度
        self.use_negative_binomial = False  # 是否使用负二项

    def _fit_poisson(
        self, X: np.ndarray, y: np.ndarray, max_iter: int = 200, tol: float = 1e-6
    ) -> Tuple[np.ndarray, float]:
        """IRLS (迭代加权最小二乘) 拟合泊松回归"""
        n, p = X.shape
        coef = np.zeros(p)
        intercept = math.log(max(np.mean(y), 0.1))

        for _ in range(max_iter):
            eta = X @ coef + intercept
            mu = np.exp(eta)  # 连接函数反函数
            mu = np.clip(mu, 1e-10, None)

            # 工作变量
            z = eta + (y - mu) / mu

            # 权重
            w = mu

            # 加权最小二乘 (带L2正则化)
            W = np.diag(w)
            X_aug = np.column_stack([np.ones(n), X])
            penalty = self.alpha * np.eye(p + 1)
            penalty[0, 0] = 0  # 不惩罚截距

            try:
                beta_new = np.linalg.solve(X_aug.T @ W @ X_aug + penalty, X_aug.T @ W @ z)
            except np.linalg.LinAlgError:
                break

            intercept_new = beta_new[0]
            coef_new = beta_new[1:]

            if np.max(np.abs(np.concatenate([[intercept_new - intercept], coef_new - coef]))) < tol:
                coef = coef_new
                intercept = intercept_new
                break

            coef = coef_new
            intercept = intercept_new

        return coef, intercept

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=0,
                confidence=1.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "poisson"},
                timestamp=datetime.now(),
            )

        if len(history) < 6 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.3,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "poisson", "notes": "insufficient_data"},
                timestamp=datetime.now(),
            )

        # 提取时序
        timestamps = []
        views_vals = []
        for h in history:
            ts = h.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))

        if len(views_vals) < 6:
            predicted_hours = remaining / velocity
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.3,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "poisson_fallback"},
                timestamp=datetime.now(),
            )

        try:
            order = np.argsort(timestamps)
            views_arr = np.array(views_vals, dtype=float)[order]
            n = len(views_arr)

            quality = self.get_quality_score(video_data)
            age_hours = self.get_video_age_hours(video_data)
            engagement = self.get_engagement_rate(video_data)

            # ── 构建特征 (预测日增量) ────────────────
            X_list, y_list = [], []
            for i in range(4, n):
                features = [
                    1.0,
                    math.log(max(views_arr[i - 1], 1)) / 10.0,  # 对数播放量
                    math.log(max(views_arr[i - 1] - views_arr[i - 2] + 1, 1)),  # 对数上期增量
                    min(age_hours / 720.0, 1.0),  # 视频年龄(月)
                    quality,  # 质量评分
                    engagement,  # 互动率
                ]
                X_list.append(features)
                y_list.append(max(0, int(views_arr[i] - views_arr[i - 1])))  # 非负整数增量

            X = np.array(X_list)
            y = np.array(y_list, dtype=float)

            if len(X) < 3:
                predicted_hours = remaining / velocity
                return PredictionResult(
                    algorithm_name=self.name,
                    algorithm_id=self.algorithm_id,
                    target_threshold=threshold,
                    predicted_hours=predicted_hours,
                    confidence=0.3,
                    current_views=current_views,
                    current_velocity=velocity,
                    metadata={"method": "poisson_insufficient"},
                    timestamp=datetime.now(),
                )

            # ── 拟合泊松回归 ────────────────────────
            self.coef, self.intercept = self._fit_poisson(X, y)

            # ── 预测 ─────────────────────────────────
            last_features = np.array(
                [
                    1.0,
                    math.log(max(views_arr[-1], 1)) / 10.0,
                    math.log(max(views_arr[-1] - views_arr[-2] + 1, 1)),
                    min(age_hours / 720.0, 1.0),
                    quality,
                    engagement,
                ]
            )

            eta = float(last_features @ self.coef + self.intercept)
            predicted_daily_increment = max(0, math.exp(eta))

            if predicted_daily_increment <= 0:
                predicted_daily_increment = max(1, velocity * 24)

            # 置信度: 基于预测均值和实际增量的偏差
            if len(X) >= 5:
                predictions = np.exp(X @ self.coef + self.intercept)
                deviance = 2 * np.sum(
                    y * np.log(np.maximum(y, 1e-10) / np.maximum(predictions, 1e-10)) - (y - predictions)
                )
                null_pred = np.mean(y)
                null_dev = 2 * np.sum(y * np.log(np.maximum(y, 1e-10) / max(null_pred, 1e-10)) - (y - null_pred))
                pseudo_r2 = max(0, 1 - deviance / max(null_dev, 1e-10))
            else:
                pseudo_r2 = 0.3

            forecast_days = min(365, max(10, int((threshold - current_views) / max(predicted_daily_increment, 1)) + 5))

            pred_views = float(current_views)
            target_day = None
            for day in range(1, forecast_days + 1):
                decay = math.exp(-day / 30.0)
                increment = predicted_daily_increment * (0.5 + 0.5 * (1.0 - decay))
                pred_views += increment
                if pred_views >= threshold:
                    target_day = day
                    break

            if target_day is not None and target_day <= 365:
                predicted_hours = target_day * 24
                data_qual = min(1.0, n / 20)
                conf = min(0.85, 0.3 + 0.25 * data_qual + 0.25 * pseudo_r2 + 0.1 * quality)
            else:
                predicted_hours = remaining / velocity
                conf = 0.35

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=conf,
                current_views=current_views,
                current_velocity=velocity,
                metadata={
                    "method": "poisson",
                    "daily_increment": round(float(predicted_daily_increment), 2),
                    "pseudo_r2": round(float(pseudo_r2), 3),
                    "model_type": "poisson",
                    "data_points": n,
                },
                timestamp=datetime.now(),
            )
        except Exception as e:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"error": str(e)},
                timestamp=datetime.now(),
            )
