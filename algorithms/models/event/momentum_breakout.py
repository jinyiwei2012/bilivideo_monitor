"""
动量突破检测 (Momentum Breakout Detection)
借鉴金融技术分析，检测播放量增速的动量突破信号

核心：双均线交叉 + RSI + MACD 型信号合成
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class MomentumBreakoutAlgorithm(BaseAlgorithm):
    """动量突破"""

    name = "动量突破"
    algorithm_id = "momentum_breakout"
    description = "双均线交叉+RSI+MACD信号，检测播放量增速突破"
    category = "事件驱动"
    default_weight = 1.0

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 12 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "momentum_fallback"}, timestamp=datetime.now(),
            )

        try:
            views = np.array([h.get("view_count", 0) for h in history[-40:]], dtype=np.float64)
            n = len(views)

            # 平滑播放量
            diffs = np.diff(views)
            if len(diffs) < 6:
                growth = velocity * 3600
            else:
                # 快均线 (5) vs 慢均线 (15)
                fast_ma = np.mean(diffs[-5:]) if len(diffs) >= 5 else np.mean(diffs)
                slow_ma = np.mean(diffs[-min(15, len(diffs)):])

                # MACD: 快-慢 的差分指数平滑
                macd_line = fast_ma - slow_ma
                signal_line = 0.5 * macd_line + 0.5 * (np.mean(diffs[-10:]) - slow_ma) if len(diffs) >= 10 else 0

                # RSI 型信号：正差分比例
                pos_ratio = np.sum(diffs[-8:] > 0) / min(8, len(diffs[-8:])) if len(diffs) >= 8 else 0.5

                # 合成信号
                breakout_signal = macd_line - signal_line
                momentum = pos_ratio - 0.5

                growth = np.mean(diffs) * (1 + 0.3 * breakout_signal + 0.2 * momentum)
                growth = max(0, growth)

            predicted_velocity = max(0, growth / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
            confidence = max(0.1, min(0.85, 0.35 + 0.02 * min(n, 25)))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={
                    "method": "momentum_breakout",
                    "macd": round(float(macd_line), 4) if "macd_line" in dir() else 0,
                    "pos_ratio": round(float(pos_ratio), 3),
                },
                timestamp=datetime.now(),
            )
        except Exception:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "momentum_error"}, timestamp=datetime.now(),
            )
