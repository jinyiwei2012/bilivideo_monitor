"""
Theta预测方法
M3预测竞赛获胜方法，通过两条Theta线组合进行预测
"""
import numpy as np
from typing import List, Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class ThetaForecastAlgorithm(BaseAlgorithm):
    """Theta预测算法

    Theta方法通过改变时间序列的曲率生成两条不同的外推线，
    然后组合它们得到最终预测。对趋势型数据表现优异。

    参考: Assimakopoulos & Nikolopoulos (2000), International Journal of Forecasting
    """

    name = "Theta预测"
    algorithm_id = "theta_forecast"
    description = "M3预测竞赛获胜方法，双线组合预测"
    category = "时间序列"
    default_weight = 1.2

    def predict(self, video_data: Dict[str, Any],
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        history = video_data.get('history_data', [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=0, confidence=1.0,
                current_views=current_views, current_velocity=velocity,
                metadata={'method': 'theta'}, timestamp=datetime.now()
            )

        if len(history) < 4 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float('inf')
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views,
                current_velocity=velocity,
                metadata={'method': 'theta', 'notes': 'insufficient_data'},
                timestamp=datetime.now()
            )

        # 按时间排序提取播放量序列
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

        if len(views_vals) < 4:
            predicted_hours = remaining / velocity
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views,
                current_velocity=velocity,
                metadata={'method': 'theta_fallback'}, timestamp=datetime.now()
            )

        try:
            order = np.argsort(timestamps)
            views_sorted = np.array(views_vals)[order]
            n = len(views_sorted)
            x = np.arange(n, dtype=float)

            # 1. 线性趋势拟合
            coeffs = np.polyfit(x, views_sorted, 1)
            trend_vals = np.polyval(coeffs, x)

            # 2. Theta=2 线: 双倍曲率
            theta_2 = 2 * views_sorted - trend_vals

            # 3. 简单指数平滑 (Theta=2 线)
            alpha = 0.3
            smoothed = np.zeros(n)
            smoothed[0] = theta_2[0]
            for i in range(1, n):
                smoothed[i] = alpha * theta_2[i] + (1 - alpha) * smoothed[i - 1]

            # 4. 外推
            growth_per_day = np.mean(np.diff(views_sorted)) if n > 1 else velocity * 24
            n_future = min(365, max(10, int((threshold - current_views) / max(growth_per_day, 1)) + 5))
            future_x = np.arange(n, n + n_future)

            # Theta=0 线: 线性趋势继续
            forecast_0 = np.polyval(coeffs, future_x)

            # Theta=2 线: SES + 逐渐回归趋势
            ses_last = smoothed[-1]
            forecast_2 = np.empty(n_future)
            for i in range(n_future):
                w = min(1.0, i / max(n_future // 2, 1))
                forecast_2[i] = (1 - w) * ses_last + w * forecast_0[i]

            # 5. 组合两条线 (等权重)
            combined = 0.5 * forecast_0 + 0.5 * forecast_2

            # 6. 找达标时间
            target_days = None
            for i in range(n_future):
                if combined[i] >= threshold:
                    target_days = i + 1
                    break

            if target_days is None or target_days > 3650:
                predicted_hours = remaining / velocity
                confidence = 0.4
            else:
                predicted_hours = target_days * 24
                # 置信度: 基于拟合优度
                residuals = views_sorted - trend_vals
                scale = np.std(views_sorted)
                fit_quality = max(0.0, 1.0 - np.std(residuals) / max(scale, 1))
                confidence = min(0.9, 0.4 + 0.3 * fit_quality + 0.2 * min(1.0, n / 20))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views,
                current_velocity=velocity,
                metadata={
                    'method': 'theta',
                    'trend_slope': coeffs[0],
                    'ses_last': float(ses_last),
                    'forecast_horizon': n_future,
                    'data_points': n,
                },
                timestamp=datetime.now()
            )
        except Exception as e:
            print(f"Theta预测失败: {e}")
            predicted_hours = remaining / velocity if velocity > 0 else float('inf')
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.0, current_views=current_views,
                current_velocity=velocity,
                metadata={'error': str(e)}, timestamp=datetime.now()
            )
