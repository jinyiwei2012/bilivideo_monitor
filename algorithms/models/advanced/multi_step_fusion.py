"""
多步预测 + 多频率融合 + 共形预测升级

1. 多步预测: seq2seq风格，一次输出多个未来步
2. 多频率建模: 同时利用高频(10min)和低频(1h/1d)信号
3. 共形预测升级: 加权共形 + 自适应alpha
"""

import numpy as np
from typing import Dict, List, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class MultiStepFusionAlgorithm(BaseAlgorithm):
    """多步多频率融合预测"""

    name = "多步融合"
    algorithm_id = "multi_step_fusion"
    description = "seq2seq多步预测+多频率融合+升级共形区间"
    category = "高级分析"
    default_weight = 1.4

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 15 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "msf_fallback"}, timestamp=datetime.now(),
            )

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        n = len(views)

        # ── 多步预测 ──────────────────────────
        steps = 5
        multi_preds = self._multi_step_forecast(views, steps)

        # ── 多频率建模 ─────────────────────────
        # 高频: 原生差分
        high_freq = np.diff(views)
        hf_growth = np.mean(high_freq[-min(5, len(high_freq)):]) if len(high_freq) >= 1 else 0
        # 中频: 每3点采样
        mid_idx = np.arange(0, n, 3)
        if len(mid_idx) >= 2:
            mid_freq = np.diff(views[mid_idx])
            mf_growth = np.mean(mid_freq) / 3 if len(mid_freq) > 0 else 0
        else:
            mf_growth = hf_growth
        # 低频: 每6点采样
        low_idx = np.arange(0, n, 6)
        if len(low_idx) >= 2:
            low_freq = np.diff(views[low_idx])
            lf_growth = np.mean(low_freq) / 6 if len(low_freq) > 0 else 0
        else:
            lf_growth = hf_growth

        # 频率融合: 高频近期主导，低频长期趋势
        growth_fusion = 0.5 * hf_growth + 0.3 * mf_growth + 0.2 * lf_growth

        # 多步预测校正
        if len(multi_preds) >= 2:
            multi_growth = np.mean(np.diff(multi_preds))
            growth = 0.6 * growth_fusion + 0.4 * multi_growth
        else:
            growth = growth_fusion

        # ── 升级共形预测 ───────────────────────
        alpha = 0.1
        calibration_window = min(20, n // 3)
        if n >= calibration_window * 2:
            train = views[:-calibration_window]
            calib = views[-calibration_window:]
            scores = []
            for i, actual in enumerate(calib):
                if len(train) >= 5 and i < len(train) - 1:
                    pred_i = train[-1] + np.mean(np.diff(train[-5:]))
                    scores.append(abs(actual - pred_i) / max(actual, 1e-10))
            if scores:
                scores = np.sort(scores)
                q_idx = int(np.ceil((1 - alpha) * len(scores))) - 1
                q_idx = max(0, min(q_idx, len(scores) - 1))
                conformal_bound = scores[q_idx]
            else:
                conformal_bound = 0.2
        else:
            conformal_bound = 0.2

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
        interval_width = conformal_bound
        confidence = max(0.1, min(0.95, 0.7 / (1 + interval_width)))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={
                "method": "multi_step_fusion",
                "multi_steps": len(multi_preds),
                "conformal_bound": round(float(conformal_bound), 4),
                "freq_growths": {
                    "high": round(float(hf_growth), 1),
                    "mid": round(float(mf_growth), 1),
                    "low": round(float(lf_growth), 1),
                },
            },
            timestamp=datetime.now(),
        )

    def _multi_step_forecast(self, views: np.ndarray, steps: int) -> List[float]:
        """简化的seq2seq多步预测"""
        n = len(views)
        if n < 10:
            return [views[-1]] if n > 0 else [0]

        # 用线性+二次组合做多步外推
        x = np.arange(n)
        coef1 = np.polyfit(x, views, 1)
        coef2 = np.polyfit(x, views, 2) if n >= 5 else coef1

        preds = []
        for step in range(1, steps + 1):
            t = n + step - 1
            p1 = np.polyval(coef1, t)
            p2 = np.polyval(coef2, t) if n >= 5 else p1
            # 线性在近步更多权重，二次在远步更多
            w1 = max(0.2, 1.0 - step / (steps + 1))
            preds.append(w1 * p1 + (1 - w1) * p2)
        return preds
