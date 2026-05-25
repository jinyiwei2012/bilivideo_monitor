"""
SIRD (Susceptible-Infected-Recovered-Depleted) 传染病传播模型
将视频传播类比传染病模型：粉丝=易感，观看=感染，过气=恢复
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

try:
    from scipy.integrate import odeint
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


class SirdModelAlgorithm(BaseAlgorithm):
    """SIRD 传染病传播模型"""

    name = "SIRD传播模型"
    algorithm_id = "sird_model"
    description = "易感-感染-恢复-消亡微分方程模型"
    category = "高级分析"
    default_weight = 1.3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)
        total_fans = video_data.get("up_fans", max(current_views * 10, 100000))

        if len(history) < 5 or velocity <= 0 or not _HAS_SCIPY:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            t = np.arange(len(views))

            S0 = max(total_fans - views[-1], 1)
            I0 = max(views[-1] - views[-2] if len(views) >= 2 else velocity * 3600, 0)
            R0 = views[-1] - I0
            D0 = 0

            def sird_model(y, t, beta, gamma, delta):
                S, I, R, D = y
                dS = -beta * S * I / max(S + I + R, 1)
                dI = beta * S * I / max(S + I + R, 1) - gamma * I - delta * I
                dR = gamma * I
                dD = delta * I
                return [dS, dI, dR, dD]

            daily_views = np.diff(views) / max(np.mean(np.diff(t)), 1) * 24
            avg_daily = np.mean(daily_views[-min(5, len(daily_views)):])
            beta = max(0.01, avg_daily / max(S0, 1))
            gamma = max(0.01, I0 / max(R0, 1)) if R0 > 0 else 0.1
            delta = gamma * 0.5

            future_t = np.linspace(0, 90, 90)
            sol = odeint(sird_model, [S0, I0, R0, D0], future_t, args=(beta, gamma, delta))
            I_pred = sol[:, 1]
            R_pred = sol[:, 2]
            total_pred = I_pred + R_pred

            remaining = threshold - current_views
            idx = np.where(total_pred >= threshold)[0]

            if len(idx) > 0:
                predicted_days = future_t[idx[0]]
                predicted_hours = predicted_days * 24
                confidence = min(0.8, 0.3 + 0.5 * (1 - predicted_days / 90))
            elif remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                peak_infected = np.max(I_pred)
                peak_time = future_t[np.argmax(I_pred)]
                max_reach = np.max(total_pred)
                if max_reach > current_views:
                    growth_rate = np.mean(np.diff(total_pred[-min(10, len(total_pred)):])) * 24
                    predicted_velocity_est = max(0, growth_rate)
                    predicted_hours = remaining / max(predicted_velocity_est, 1)
                else:
                    predicted_hours = remaining / velocity
                confidence = 0.3

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=min(0.85, confidence), current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "sird", "beta": float(beta), "gamma": float(gamma), "peak_hours": float(peak_time * 24) if 'peak_time' in dir() else 0},
                timestamp=datetime.now(),
            )
        except Exception:
            return self._fallback(velocity, current_views, threshold)

    def _fallback(self, velocity, current_views, threshold):
        if velocity <= 0:
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=float("inf"),
                confidence=0.0, current_views=current_views, current_velocity=velocity,
                metadata={"method": "sird", "reason": "fallback"},
                timestamp=datetime.now(),
            )
        remaining = max(0, threshold - current_views)
        predicted_hours = remaining / velocity if remaining > 0 else 0
        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=0.3, current_views=current_views, current_velocity=velocity,
            metadata={"method": "sird", "reason": "fallback"},
            timestamp=datetime.now(),
        )
