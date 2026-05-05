"""
SARIMA季节性预测
在ARIMA基础上加入季节性差分项，处理周/月周期性播放模式
"""
import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class SARIMASimpleAlgorithm(BaseAlgorithm):
    """SARIMA (Seasonal ARIMA) 季节性差分自回归移动平均

    在标准 ARIMA(p,d,q) 基础上引入季节性成分 (P,D,Q,m)，
    捕捉 B 站视频播放量的星期周期性（如周末高峰）。

    参考: Box, Jenkins, Reinsel & Ljung (2015), Time Series Analysis
    """

    name = "SARIMA季节预测"
    algorithm_id = "sarima_simple"
    description = "季节性差分自回归移动平均，处理周/月周期"
    category = "时间序列"
    default_weight = 1.2

    def __init__(self):
        super().__init__()
        self.p, self.d, self.q = 1, 1, 1
        self.P, self.D, self.Q, self.m = 1, 0, 0, 7  # 周周期=7天

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
                metadata={'method': 'sarima'}, timestamp=datetime.now()
            )

        if len(history) < max(4, self.m + 2) or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float('inf')
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views,
                current_velocity=velocity,
                metadata={'method': 'sarima', 'notes': 'insufficient_data'},
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

        if len(views_vals) < 4:
            predicted_hours = remaining / velocity
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views,
                current_velocity=velocity,
                metadata={'method': 'sarima_fallback'}, timestamp=datetime.now()
            )

        try:
            order = np.argsort(timestamps)
            views_sorted = np.array(views_vals)[order]
            n = len(views_sorted)

            # ── 差分 (d) ─────────────────────────────────
            diff_series = views_sorted.copy()
            for _ in range(self.d):
                diff_series = np.diff(diff_series)
                if len(diff_series) == 0:
                    break

            m = self.m
            # ── 季节性差分 (D) ──────────────────────────
            if m > 0 and self.D > 0 and len(diff_series) > m:
                for _ in range(self.D):
                    if len(diff_series) > m:
                        diff_series = diff_series[m:] - diff_series[:-m]

            if len(diff_series) < 2:
                predicted_hours = remaining / velocity
                return PredictionResult(
                    algorithm_name=self.name, algorithm_id=self.algorithm_id,
                    target_threshold=threshold, predicted_hours=predicted_hours,
                    confidence=0.3, current_views=current_views,
                    current_velocity=velocity,
                    metadata={'method': 'sarima_diff_failed'}, timestamp=datetime.now()
                )

            # ── AR 成分 ─────────────────────────────────
            y_centered = diff_series - np.mean(diff_series)
            p = min(self.p, len(y_centered) - 1)
            ar_coeffs = np.zeros(p)
            if p > 0:
                ar_matrix = np.column_stack([y_centered[p-i-1:len(y_centered)-i-1] for i in range(p)])
                if ar_matrix.shape[0] > p and ar_matrix.shape[1] > 0:
                    try:
                        ar_coeffs = np.linalg.lstsq(ar_matrix, y_centered[p:], rcond=None)[0]
                    except np.linalg.LinAlgError:
                        ar_coeffs = np.zeros(p)

            # ── MA 成分 (残差滑动平均) ─────────────────
            q = min(self.q, len(y_centered) - p - 1)
            residuals = y_centered.copy()
            if p > 0 and len(ar_coeffs) == p:
                for i in range(p, len(y_centered)):
                    residuals[i] = y_centered[i] - np.dot(ar_coeffs, y_centered[i-p:i])
            ma_coeffs = np.zeros(q)
            if q > 0:
                ma_matrix = np.column_stack([residuals[q-j-1:len(residuals)-j-1] for j in range(q)])
                if ma_matrix.shape[0] > q and ma_matrix.shape[1] > 0:
                    try:
                        ma_coeffs = np.linalg.lstsq(ma_matrix, y_centered[q:], rcond=None)[0]
                    except np.linalg.LinAlgError:
                        ma_coeffs = np.zeros(q)

            # ── 季节性成分 (逐周期偏移) ─────────────────
            seasonal_pattern = np.zeros(m) if m <= n else np.zeros(n)
            if m > 0 and m < n:
                n_full = n // m
                if n_full >= 1:
                    seasonal_vals = views_sorted[:n_full * m].reshape(n_full, m)
                    seasonal_pattern = np.mean(seasonal_vals, axis=0) - np.mean(views_sorted)
                    # 去趋势的季节性
                    trend = np.mean(views_sorted)
                    seasonal_pattern = np.mean(seasonal_vals, axis=0) - trend

            # ── 预测 ──────────────────────────────────
            growth_rate = np.mean(np.diff(views_sorted)) if n > 1 else velocity * 24
            forecast_days = min(365, max(14, int((threshold - current_views) / max(growth_rate, 1)) + 7))
            pred_values = list(views_sorted)

            last_residual = 0.0
            for i in range(forecast_days):
                idx = len(pred_values)
                # AR成分
                ar_term = 0.0
                if p > 0 and len(ar_coeffs) == p:
                    ar_term = np.dot(ar_coeffs, pred_values[idx-p:idx]) if len(ar_coeffs) <= p else 0

                # MA成分
                ma_term = 0.0
                if q > 0 and len(ma_coeffs) == q:
                    ma_term = np.dot(ma_coeffs, [last_residual] * q) if len(ma_coeffs) <= q else 0

                # 季节性成分
                seas_term = seasonal_pattern[i % m] if m > 0 else 0

                next_val = ar_term + ma_term + seas_term + 0.1 * growth_rate
                if next_val < pred_values[-1]:
                    next_val = pred_values[-1] + max(growth_rate * 0.3, 0)
                pred_values.append(next_val)

                if len(pred_values) > p + q:
                    actual = views_sorted[-1] if i == 0 else pred_values[-2]
                    last_residual = actual - (ar_term + seas_term)

            # 寻找达标点
            combined = np.array(pred_values[n:])
            target_idx = np.where(combined >= threshold)[0]

            if len(target_idx) > 0 and target_idx[0] < 300:
                predicted_hours = (target_idx[0] + 1) * 24
                # 置信度
                seasonal_strength = 0.0
                if m > 0 and len(seasonal_pattern) > 0:
                    seasonal_strength = min(1.0, np.std(seasonal_pattern) / max(np.std(views_sorted), 1))
                n_points_conf = min(1.0, n / 30)
                conf = min(0.9, 0.35 + 0.25 * n_points_conf + 0.2 * seasonal_strength + 0.1 * min(1.0, velocity / 100))
            else:
                predicted_hours = remaining / velocity
                conf = 0.35

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=conf, current_views=current_views,
                current_velocity=velocity,
                metadata={
                    'method': 'sarima',
                    'ar_order': p, 'diff_order': self.d, 'ma_order': q,
                    'seasonal_period': m, 'seasonal_strength': round(seasonal_strength, 3) if m > 0 else 0,
                    'forecast_horizon': forecast_days,
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
