"""
级联集成 (Cascade Ensemble) 预测
多个预测器按顺序级联，每个预测器的输出作为下一个的输入
"""

import math
import numpy as np
from typing import Dict, Any, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class CascadeEnsembleAlgorithm(BaseAlgorithm):
    """级联集成 (Cascade Generalization / Regressor Cascading)

    与传统并行集成不同，级联集成将预测器按顺序排列，
    每个预测器的输出作为额外特征输入下一个预测器。
    能捕获不同模型间的互补信息，通常优于简单的投票/平均集成。

    参考: Linardatos et al. (2024), "Regressor cascading for
          time series forecasting", Intelligent Decision Technologies
    """

    name = "Cascade级联集成"
    algorithm_id = "cascade_ensemble"
    description = "预测器逐级级联，每个输出作为下一级输入"
    category = "集成学习"
    default_weight = 1.25

    def __init__(self):
        super().__init__()
        self.cascade_levels = 3

    def _level1_prediction(self, views: np.ndarray) -> float:
        """第一级: 简单线性趋势预测"""
        n = len(views)
        if n < 2:
            return 0.0
        np.arange(n)
        slope = (views[-1] - views[0]) / max(n - 1, 1)
        return slope

    def _level2_prediction(self, views: np.ndarray, l1_output: float) -> Tuple[float, float]:
        """第二级: 指数平滑 + 第一级输出"""
        n = len(views)
        if n < 2:
            return 0.0, 0.0

        # 简单指数平滑
        alpha = 0.3
        smoothed = views[0]
        for i in range(1, n):
            smoothed = alpha * views[i] + (1 - alpha) * smoothed

        growth = smoothed - views[-1]

        # 用第一级输出修正
        adjusted = growth * 0.6 + l1_output * 0.4
        return adjusted, smoothed

    def _level3_prediction(self, views: np.ndarray, l2_output: float, l2_smoothed: float) -> float:
        """第三级: 考虑季节性 + 前两级输出"""
        n = len(views)
        if n < 7:
            return l2_output

        # 周季节性
        weekly_cycle = []
        for i in range(1, 8):
            if n >= i + 7:
                cycle_growth = (views[-i] - views[-i - 7]) / 7.0
                weekly_cycle.append(cycle_growth)

        seasonal_effect = np.mean(weekly_cycle) if weekly_cycle else 0

        # 最终: 组合三级信息
        final = l2_output * 0.5 + seasonal_effect * 0.3 + (l2_smoothed - views[-1]) * 0.2
        return final

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
                metadata={"method": "cascade"},
                timestamp=datetime.now(),
            )

        if len(history) < 5 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.3,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "cascade", "notes": "insufficient_data"},
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
                    ts = datetime.fromisoformat(str(ts)[:19].replace("T"," ")).timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))

        if len(views_vals) < 5:
            predicted_hours = remaining / velocity
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.3,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "cascade_fallback"},
                timestamp=datetime.now(),
            )

        try:
            order = np.argsort(timestamps)
            views_arr = np.array(views_vals, dtype=float)[order]
            n = len(views_arr)

            quality = self.get_quality_score(video_data)
            engagement = self.get_engagement_rate(video_data)

            # ── 级联预测流程 ──────────────────────────
            # Level 1: 线性趋势
            l1_slope = self._level1_prediction(views_arr)
            l1_daily = l1_slope * 24  # 转换为日增长

            # Level 2: 指数平滑 + L1 修正
            l2_daily, l2_smoothed = self._level2_prediction(views_arr, l1_daily)

            # Level 3: 季节性 + L2 修正
            l3_daily = self._level3_prediction(views_arr, l2_daily, l2_smoothed)

            if l3_daily <= 0:
                l3_daily = l1_daily if l1_daily > 0 else velocity * 24

            daily_growth = l3_daily

            # ── 评估级间一致性作为置信度权重 ──────────
            predictions = [l1_daily, l2_daily, l3_daily]
            pred_mean = np.mean(predictions)
            pred_std = np.std(predictions)
            consistency = max(0.0, 1.0 - pred_std / max(abs(pred_mean), 1))

            # ── 预测 ─────────────────────────────────
            forecast_days = min(365, max(10, int((threshold - current_views) / max(daily_growth, 1)) + 5))

            pred_views = float(current_views)
            target_day = None
            for day in range(1, forecast_days + 1):
                # 级联预测：用各层级的融合结果，随时间衰减
                decay = math.exp(-day / 30.0)
                growth = daily_growth * (0.6 + 0.4 * (1.0 - decay))
                pred_views += max(0, growth)
                if pred_views >= threshold:
                    target_day = day
                    break

            if target_day is not None and target_day <= 365:
                predicted_hours = target_day * 24
                data_qual = min(1.0, n / 15)
                conf = min(0.9, 0.35 + 0.2 * data_qual + 0.2 * consistency + 0.1 * quality + 0.05 * engagement)
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
                    "method": "cascade",
                    "level1_l1": round(float(l1_daily), 2),
                    "level2_exp_smooth": round(float(l2_daily), 2),
                    "level3_cascade": round(float(l3_daily), 2),
                    "consistency": round(float(consistency), 3),
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
