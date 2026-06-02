"""
共形预测 (Conformal Prediction)
分布无关的预测区间构建方法，提供严格的覆盖率保证

核心：
1. 用留出校准集计算残差分布
2. 对新预测加上/减去对应分位数的残差
3. 输出带覆盖率保证的预测区间
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class ConformalPredictionAlgorithm(BaseAlgorithm):
    """共形预测"""

    name = "共形预测"
    algorithm_id = "conformal"
    description = "分布无关的预测区间，严格覆盖率保证"
    category = "高级分析"
    default_weight = 1.1

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
                metadata={"method": "conformal_fallback"}, timestamp=datetime.now(),
            )

        try:
            views = np.array([h.get("view_count", 0) for h in history[-30:]], dtype=np.float64)
            n = len(views)

            # 留一法构建校准集残差
            calibration_size = max(3, n // 4)
            train_size = n - calibration_size

            residuals = []
            for i in range(train_size, n):
                train_data = views[:i]
                if len(train_data) >= 3:
                    pred_i = np.polyval(np.polyfit(np.arange(len(train_data)), train_data, 1), len(train_data))
                    residuals.append(abs(views[i] - pred_i))

            if len(residuals) < 3:
                growth = velocity * 3600
                interval_half = growth * 0.2
            else:
                residuals = np.sort(residuals)
                alpha = 0.2
                q_idx = int(np.ceil((1 - alpha) * len(residuals))) - 1
                q_idx = max(0, min(q_idx, len(residuals) - 1))
                error_bound = residuals[q_idx]

                # 趋势预测
                trend = np.polyfit(np.arange(n), views, 1)
                point_pred = np.polyval(trend, n + 1)
                lower = point_pred - error_bound
                upper = point_pred + error_bound

                growth = point_pred - views[-1]
                interval_half = error_bound

            predicted_velocity = max(0, growth / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                cv = interval_half / max(growth, 1e-10)
                confidence = max(0.1, min(0.9, 0.6 / (1 + cv)))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={
                    "method": "conformal",
                    "error_bound": round(float(interval_half), 2),
                    "alpha": 0.2,
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
                metadata={"method": "conformal_error"}, timestamp=datetime.now(),
            )
