"""
分位数回归预测
通过不同分位点估计完整预测分布，提供乐观/中位/悲观多情景
"""
import math
import numpy as np
from typing import Dict, Any, List, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class QuantileRegressionAlgorithm(BaseAlgorithm):
    """分位数回归 (Quantile Regression)

    相比普通最小二乘只预测均值，分位数回归能估计完整条件分布。
    对于播放量预测，可同时给出：
    - τ=0.5: 中位数预测（最稳健）
    - τ=0.25: 悲观情景
    - τ=0.75: 乐观情景

    参考: Koenker & Hallock (2001), "Quantile Regression"
    """

    name = "分位数回归"
    algorithm_id = "quantile_regression"
    description = "多分位点预测，提供乐观/中位/悲观情景"
    category = "统计模型"
    default_weight = 1.15

    def __init__(self):
        super().__init__()
        self.tau = 0.5  # 默认使用中位数
        self.learning_rate = 0.01
        self.max_iter = 200

    def _quantile_loss(self, y_true: np.ndarray, y_pred: np.ndarray,
                       tau: float) -> float:
        """分位数损失函数: ρ_τ(y, ŷ) = max(τ(y-ŷ), (τ-1)(y-ŷ))"""
        diff = y_true - y_pred
        loss = np.where(diff > 0, tau * diff, (tau - 1) * diff)
        return float(np.mean(loss))

    def _fit_quantile(self, X: np.ndarray, y: np.ndarray,
                      tau: float) -> Tuple[np.ndarray, float]:
        """使用梯度下降拟合分位数回归"""
        n, p = X.shape
        coef = np.zeros(p)
        intercept = float(np.median(y))

        for _ in range(self.max_iter):
            pred = X @ coef + intercept
            diff = y - pred

            # 分位数梯度
            grad_coef = np.zeros(p)
            grad_intercept = 0.0
            for i in range(n):
                if diff[i] > 0:
                    weight = tau
                elif diff[i] < 0:
                    weight = tau - 1
                else:
                    weight = 0
                grad_coef += weight * X[i] / n
                grad_intercept += weight / n

            coef += self.learning_rate * grad_coef
            intercept += self.learning_rate * grad_intercept

            # 学习率衰减
            self.learning_rate *= 0.99

        return coef, intercept

    def predict(self, video_data: Dict[str, Any],
                threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get('view_count', 0)
        history = video_data.get('history_data', [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=0, confidence=1.0,
                current_views=current_views, current_velocity=velocity,
                metadata={'method': 'quantile'}, timestamp=datetime.now()
            )

        if len(history) < 5 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float('inf')
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views,
                current_velocity=velocity,
                metadata={'method': 'quantile', 'notes': 'insufficient_data'},
                timestamp=datetime.now()
            )

        # 提取时序
        timestamps = []
        views_vals = []
        for h in history:
            ts = h.get('timestamp', 0)
            if hasattr(ts, 'timestamp'):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S').timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get('view_count', 0)))

        if len(views_vals) < 5:
            predicted_hours = remaining / velocity
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views,
                current_velocity=velocity,
                metadata={'method': 'quantile_fallback'}, timestamp=datetime.now()
            )

        try:
            order = np.argsort(timestamps)
            views_arr = np.array(views_vals, dtype=float)[order]
            n = len(views_arr)

            quality = self.get_quality_score(video_data)
            age_hours = self.get_video_age_hours(video_data)

            # ── 构建特征 ──────────────────────────────
            X_list, y_list = [], []
            for i in range(3, n):
                features = [
                    1.0,
                    views_arr[i-1] / 10000,                  # 归一化播放量
                    (views_arr[i-1] - views_arr[i-2]) / 100,  # 近期增量
                    np.mean(views_arr[max(0, i-7):i]) / 10000,  # 7日均值
                    min(age_hours / 168.0, 1.0),               # 视频年龄(周)
                    quality,                                     # 质量分
                ]
                X_list.append(features)
                y_list.append(views_arr[i] - views_arr[i-1])  # 预测增量

            X = np.array(X_list)
            y = np.array(y_list)

            if len(X) < 3:
                predicted_hours = remaining / velocity
                return PredictionResult(
                    algorithm_name=self.name, algorithm_id=self.algorithm_id,
                    target_threshold=threshold, predicted_hours=predicted_hours,
                    confidence=0.3, current_views=current_views,
                    current_velocity=velocity,
                    metadata={'method': 'quantile_insufficient'}, timestamp=datetime.now()
                )

            # ── 拟合多个分位数 ────────────────────────
            quantiles = {
                'pessimistic': 0.25,
                'median': 0.50,
                'optimistic': 0.75,
            }

            results = {}
            for label, tau in quantiles.items():
                coef, intercept = self._fit_quantile(X, y, tau)
                results[label] = {'coef': coef, 'intercept': intercept}

            # ── 预测 ─────────────────────────────────
            last_X = np.array([[
                1.0,
                views_arr[-1] / 10000,
                (views_arr[-1] - views_arr[-2]) / 100,
                np.mean(views_arr[-7:]) / 10000 if len(views_arr) >= 7 else views_arr[-1] / 10000,
                min(age_hours / 168.0, 1.0),
                quality,
            ]])

            # 三个分位数的日增长预测
            median_pred = float(last_X @ results['median']['coef'] + results['median']['intercept'])
            optimistic_pred = float(last_X @ results['optimistic']['coef'] + results['optimistic']['intercept'])
            pessimistic_pred = float(last_X @ results['pessimistic']['coef'] + results['pessimistic']['intercept'])

            # 使用中位数作为主预测
            daily_growth = max(0, median_pred)

            if daily_growth <= 0:
                daily_growth = max(0, velocity * 24)

            # 预测区间宽度反映不确定性
            prediction_spread = max(1, optimistic_pred - pessimistic_pred)
            relative_spread = prediction_spread / max(daily_growth, 1)

            forecast_days = min(365, max(10, int((threshold - current_views) / max(daily_growth, 1)) + 5))

            pred_views = float(current_views)
            target_day = None
            for day in range(1, forecast_days + 1):
                decay = math.exp(-day / 28.0)
                growth = daily_growth * (0.6 + 0.4 * (1.0 - decay))
                pred_views += max(0, growth)
                if pred_views >= threshold:
                    target_day = day
                    break

            if target_day is not None and target_day <= 365:
                predicted_hours = target_day * 24
                data_qual = min(1.0, n / 20)
                stability = max(0.0, 1.0 - min(relative_spread * 0.1, 0.5))
                conf = min(0.9, 0.3 + 0.25 * data_qual + 0.2 * stability + 0.1 * quality)
            else:
                predicted_hours = remaining / velocity
                conf = 0.35

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=conf, current_views=current_views,
                current_velocity=velocity,
                metadata={
                    'method': 'quantile',
                    'daily_growth_median': round(float(median_pred), 2),
                    'daily_growth_optimistic': round(float(optimistic_pred), 2),
                    'daily_growth_pessimistic': round(float(pessimistic_pred), 2),
                    'prediction_spread': round(float(prediction_spread), 2),
                    'data_points': n,
                },
                timestamp=datetime.now()
            )
        except Exception as e:
            predicted_hours = remaining / velocity if velocity > 0 else float('inf')
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.0, current_views=current_views,
                current_velocity=velocity,
                metadata={'error': str(e)}, timestamp=datetime.now()
            )
