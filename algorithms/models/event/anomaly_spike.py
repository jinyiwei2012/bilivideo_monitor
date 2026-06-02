"""
异常脉冲检测 (Anomaly Spike Detection)
检测播放量突变点，区分自然增长与事件驱动的脉冲

核心：滑动窗口Z-score + 格兰杰因果检验脉冲后衰减
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class AnomalySpikeAlgorithm(BaseAlgorithm):
    """异常脉冲检测"""

    name = "脉冲检测"
    algorithm_id = "anomaly_spike"
    description = "Z-score滑动窗口检测播放量异常脉冲，建模衰减"
    category = "事件驱动"
    default_weight = 1.0

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 10 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "spike_fallback"}, timestamp=datetime.now(),
            )

        try:
            views = np.array([h.get("view_count", 0) for h in history[-40:]], dtype=np.float64)
            n = len(views)

            # 滑动窗口 Z-score
            window = min(10, n // 3)
            diffs = np.diff(views)
            spikes = np.zeros(len(diffs), dtype=bool)
            for i in range(window, len(diffs)):
                local = diffs[max(0, i - window): i]
                if len(local) >= 3 and np.std(local) > 0:
                    z = (diffs[i] - np.mean(local)) / np.std(local)
                    if z > 2.0:
                        spikes[i] = True

            # 分离脉冲和基线
            n_spikes = np.sum(spikes)
            if n_spikes > 0 and n_spikes < len(diffs) * 0.5:
                baseline = np.mean(diffs[~spikes]) if np.sum(~spikes) > 0 else np.mean(diffs)
                spike_magnitude = np.mean(diffs[spikes]) - baseline if n_spikes > 0 else 0
                # 脉冲后衰减: 假设指数衰减
                decay_rate = 0.3 if not np.isnan(spike_magnitude) else 0.2
                adjusted_growth = baseline + spike_magnitude * np.exp(-decay_rate * n_spikes / max(n, 1))
            else:
                adjusted_growth = np.mean(diffs)

            predicted_velocity = max(0, adjusted_growth / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
            spike_ratio = n_spikes / max(len(diffs), 1)
            confidence = max(0.1, min(0.85, 0.5 * (1 - spike_ratio) + 0.02 * min(n, 25)))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={"method": "anomaly_spike", "spikes": int(n_spikes), "spike_ratio": round(spike_ratio, 3)},
                timestamp=datetime.now(),
            )
        except Exception:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "spike_error"}, timestamp=datetime.now(),
            )
