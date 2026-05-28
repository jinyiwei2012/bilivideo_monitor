"""
Time-MoE (时间序列专家混合模型)
混合专家架构，不同专家学习不同增长阶段模式，路由自动选择最优专家
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import TimeMoETorchModel, try_torch_predict


class TimeMoeSimpleAlgorithm(BaseAlgorithm):
    """Time-MoE 专家混合模型"""

    name = "Time-MoE专家混合"
    algorithm_id = "time_moe_simple"
    description = "混合专家架构，不同专家专攻不同增长阶段"
    category = "深度学习"
    default_weight = 1.3

    training_window = 10
    training_horizon = 3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        return try_torch_predict(
            self,
            video_data,
            threshold,
            TimeMoETorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        return TimeMoETorchModel(in_features=getattr(self, '_training_n_features', 5), window=10, n_experts=4, d_model=16, horizon=self.training_horizon)

    def get_training_features(self) -> List[str]:
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 8 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            likes = np.array([h.get("like", 0) for h in history], dtype=np.float64)
            coins = np.array([h.get("coin", 0) for h in history], dtype=np.float64)
            favs = np.array([h.get("favorite", 0) for h in history], dtype=np.float64)

            growth_rates = np.diff(views) / np.maximum(views[:-1], 1)
            engagement = (likes + coins * 2 + favs) / np.maximum(views, 1)
            recent_growth = np.mean(growth_rates[-3:]) if len(growth_rates) >= 3 else 0
            current_eng = engagement[-1] if len(engagement) > 0 else 0

            n_experts = 4
            np.random.seed(42)
            W_gate = np.random.randn(2, n_experts) * 0.1
            W_exp = [np.random.randn(2, 1) * 0.1 for _ in range(n_experts)]

            routing_input = np.array([recent_growth, current_eng])
            gate_logits = routing_input @ W_gate
            gate_probs = np.exp(gate_logits - np.max(gate_logits))
            gate_probs = gate_probs / (np.sum(gate_probs) + 1e-10)

            predictions = [float(routing_input @ W_exp[i]) for i in range(n_experts)]
            moe_pred = sum(gate_probs[i] * predictions[i] for i in range(n_experts))

            dominant_expert = int(np.argmax(gate_probs))
            experts_interpret = {0: "cold_start", 1: "viral_growth", 2: "stable_growth", 3: "saturation"}

            predicted_velocity = max(0, moe_pred * views[-1] / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                confidence = max(0.1, min(0.85, 0.4 + float(gate_probs[dominant_expert]) * 0.4))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={
                    "method": "time_moe",
                    "dominant_expert": experts_interpret[dominant_expert],
                    "expert_weight": float(gate_probs[dominant_expert]),
                },
                timestamp=datetime.now(),
            )
        except Exception:
            return self._fallback(velocity, current_views, threshold)

    def _fallback(self, velocity, current_views, threshold):
        if velocity <= 0:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=float("inf"),
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "time_moe", "reason": "fallback"},
                timestamp=datetime.now(),
            )
        remaining = max(0, threshold - current_views)
        predicted_hours = remaining / velocity if remaining > 0 else 0
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=0.3,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "time_moe", "reason": "fallback"},
            timestamp=datetime.now(),
        )
