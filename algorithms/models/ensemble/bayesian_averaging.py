"""
贝叶斯模型平均 (Bayesian Model Averaging)
用 BIC/AIC 对多模型输出做贝叶斯加权，替代固定权重

核心原理：
1. 对每个算法计算 BIC (Bayesian Information Criterion)
2. BIC = n * log(MSE) + k * log(n)，k=参数复杂度惩罚
3. 后验概率 w_i ∝ exp(-0.5 * ΔBIC_i)
4. 最终预测 = Σ w_i * pred_i
"""

import numpy as np
from typing import Dict, List, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class BayesianModelAveragingAlgorithm(BaseAlgorithm):
    """贝叶斯模型平均"""

    name = "贝叶斯平均"
    algorithm_id = "bayesian_averaging"
    description = "BIC后验加权，替代固定权重，信息论最优"
    category = "集成学习"
    default_weight = 1.5

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
                metadata={"method": "bma_fallback"}, timestamp=datetime.now(),
            )

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        n = len(views)

        # 基模型：多个不同复杂度的预测器
        methods = []
        names = []

        # M1: 线性 (k=2)
        if n >= 3:
            methods.append(np.polyfit(np.arange(min(10, n)), views[-min(10, n):], 1)[0])
            names.append("linear")

        # M2: 二次 (k=3)
        if n >= 5:
            methods.append(np.polyfit(np.arange(min(10, n)), views[-min(10, n):], 2)[0])
            names.append("quadratic")

        # M3: 移动平均 (k=1)
        methods.append(np.mean(np.diff(views[-min(8, n):])))
        names.append("moving_avg")

        # M4: 指数 (k=2)
        if n >= 5:
            try:
                log_v = np.log(np.maximum(views[-min(10, n):], 1))
                methods.append(np.polyfit(np.arange(len(log_v)), log_v, 1)[0] * views[-1])
                names.append("exponential")
            except Exception:
                pass

        # M5: 三阶 (k=4)
        if n >= 8:
            methods.append(np.polyfit(np.arange(min(10, n)), views[-min(10, n):], 3)[0])
            names.append("cubic")

        if len(methods) < 2:
            growth = velocity * 3600
        else:
            # 用最后 30% 的数据做验证，计算 BIC
            val_start = max(1, int(n * 0.7))
            actual = np.diff(views[val_start - 1:])

            bics = []
            valid_methods = []
            valid_names = []
            for i, method_growth in enumerate(methods):
                if i >= len(actual):
                    continue
                pred_diffs = np.full(len(actual), method_growth)
                mse = np.mean((actual - pred_diffs) ** 2)
                if mse < 1e-10:
                    mse = 1e-10

                k_map = {"linear": 2, "quadratic": 3, "moving_avg": 1, "exponential": 2, "cubic": 4}
                k = k_map.get(names[i], 2)
                bic = len(actual) * np.log(mse) + k * np.log(len(actual))
                bics.append(bic)
                valid_methods.append(method_growth)
                valid_names.append(names[i])

            if not bics:
                growth = methods[0]
            else:
                # ΔBIC + softmax 后验
                bics = np.array(bics)
                delta_bic = bics - bics.min()
                weights = np.exp(-0.5 * delta_bic)
                weights /= weights.sum()
                growth = np.dot(weights, valid_methods)

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
        n_models = len(bics) if "bics" in dir() else len(methods)
        top_weight = weights.max() if "weights" in dir() else 1.0
        confidence = max(0.1, min(0.9, 0.3 + 0.3 * top_weight + 0.02 * min(n_models, 5)))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={
                "method": "bma",
                "n_models": n_models,
                "top_weight": round(float(top_weight), 3),
                "delta_bic": round(float(delta_bic.max() - delta_bic.min()), 1) if "delta_bic" in dir() else 0,
            },
            timestamp=datetime.now(),
        )
