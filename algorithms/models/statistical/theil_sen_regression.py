"""
Theil-Sen鲁棒回归
基于中位数的非参数回归方法，对异常值高度鲁棒
"""

import math
import random
import numpy as np
from typing import Dict, Any, List, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class TheilSenRegressionAlgorithm(BaseAlgorithm):
    """Theil-Sen 鲁棒回归

    计算所有数据点对之间斜率的中位数作为回归斜率，
    对异常值的容忍度高达 29.3%，远优于普通最小二乘。

    对于 B 站播放量数据中的突发高峰（异常值）有很强的鲁棒性，
    能更准确地估计真实趋势。

    参考: Theil (1950), Sen (1968)
    """

    name = "Theil-Sen回归"
    algorithm_id = "theil_sen"
    description = "基于中位数斜率的非参数鲁棒回归"
    category = "统计模型"
    default_weight = 1.15

    def __init__(self):
        super().__init__()
        self.max_subpairs = 2000  # 最大计算点对数

    def _theil_sen_slope(self, x: np.ndarray, y: np.ndarray) -> Tuple[float, float]:
        """计算Theil-Sen斜率和截距"""
        n = len(x)
        if n < 2:
            return 0.0, 0.0

        slopes = []
        n_pairs = n * (n - 1) // 2

        if n_pairs <= self.max_subpairs:
            # 计算所有点对
            for i in range(n):
                for j in range(i + 1, n):
                    if abs(x[j] - x[i]) > 1e-10:
                        slopes.append((y[j] - y[i]) / (x[j] - x[i]))
        else:
            # 随机采样点对
            indices = list(range(n))
            sampled = 0
            while sampled < self.max_subpairs:
                i, j = random.sample(indices, 2)
                if i > j:
                    i, j = j, i
                if i != j and abs(x[j] - x[i]) > 1e-10:
                    slopes.append((y[j] - y[i]) / (x[j] - x[i]))
                    sampled += 1

        if not slopes:
            return 0.0, float(np.median(y))

        slope = float(np.median(slopes))
        # 截距: 所有 (y_i - slope * x_i) 的中位数
        intercept = float(np.median(y - slope * x))

        return slope, intercept

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
                metadata={"method": "theil_sen"},
                timestamp=datetime.now(),
            )

        if len(history) < 4 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.3,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "theil_sen", "notes": "insufficient_data"},
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

        if len(views_vals) < 4:
            predicted_hours = remaining / velocity
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.3,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "theil_sen_fallback"},
                timestamp=datetime.now(),
            )

        try:
            order = np.argsort(timestamps)
            views_arr = np.array(views_vals, dtype=float)[order]
            n = len(views_arr)
            x = np.arange(n, dtype=float)

            # ── Theil-Sen 斜率估计 ────────────────────
            slope, intercept = self._theil_sen_slope(x, views_arr)

            if slope <= 0:
                # 用中位数日增量作为备选
                daily_increments = np.diff(views_arr)
                slope = float(np.median(daily_increments))
                intercept = float(views_arr[0])

            # ── 基于时间序列分解评估趋势稳定性 ────────
            # 分段评估趋势一致性
            n_segments = min(5, n // 3)
            segment_slopes = []
            if n_segments >= 2:
                seg_size = n // n_segments
                for s in range(n_segments):
                    start = s * seg_size
                    end = start + seg_size if s < n_segments - 1 else n
                    if end - start >= 2:
                        xs = np.arange(end - start)
                        ys = views_arr[start:end]
                        s_slope, _ = self._theil_sen_slope(xs, ys)
                        segment_slopes.append(s_slope)

            trend_consistency = 1.0
            if len(segment_slopes) >= 2:
                slope_cv = np.std(segment_slopes) / max(abs(np.mean(segment_slopes)), 1)
                trend_consistency = max(0.0, 1.0 - min(slope_cv, 3.0) * 0.3)

            # ── 预测 ─────────────────────────────────
            # 日增长量 = Theil-Sen slope（每数据点增量）× 每天数据点
            daily_growth = slope * 24  # 假设每小时一个数据点
            if daily_growth <= 0:
                daily_growth = velocity * 24

            forecast_days = min(365, max(10, int((threshold - current_views) / max(daily_growth, 1)) + 5))

            pred_views = float(current_views)
            target_day = None
            for day in range(1, forecast_days + 1):
                decay = math.exp(-day / 35.0)
                pred_views += daily_growth * (0.4 + 0.6 * (1.0 - decay))
                if pred_views >= threshold:
                    target_day = day
                    break

            if target_day is not None and target_day <= 365:
                predicted_hours = target_day * 24
                data_qual = min(1.0, n / 15)
                conf = min(0.9, 0.35 + 0.25 * data_qual + 0.25 * trend_consistency)
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
                    "method": "theil_sen",
                    "theil_slope": round(float(slope), 2),
                    "daily_growth": round(float(daily_growth), 2),
                    "trend_consistency": round(float(trend_consistency), 3),
                    "segment_slopes": len(segment_slopes),
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
