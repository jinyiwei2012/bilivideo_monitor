"""
Koopa (Koopman Predictors for Non-stationary Time Series)
基于 Koopman 算子理论的非平稳时序预测，NeurIPS 2023

核心思路：
1. 编码器将时序映射到 Koopman 空间
2. 用线性 Koopman 算子 K 驱动系统演化
3. 解码器将演化结果映射回预测值
4. 多个 Koopman 分量捕捉不同时间尺度
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import KoopaTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class KoopaAlgorithm(BaseAlgorithm):
    """Koopa Koopman算子预测"""

    name = "Koopa算子"
    algorithm_id = "koopa"
    description = "Koopman算子理论驱动的非平稳时序预测"
    category = "深度学习"
    default_weight = 1.4

    training_window = 12
    training_horizon = 3

    def predict(self, video_data, threshold=100000):
        return try_torch_predict(
            self, video_data, threshold, KoopaTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        return KoopaTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon,
            d_model=32, n_components=4,
        )

    def get_training_features(self) -> List[str]:
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 8 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "koopa_fallback"},
                timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-20:]], dtype=np.float64)
        n = len(views)

        # 构造 Hankel 矩阵（时延嵌入）
        L = min(8, n // 2)
        if L >= 3 and n >= 2 * L:
            H = np.array([views[i:i+L] for i in range(n - L + 1)])
            H = H - np.mean(H, axis=0)

            # SVD 分解得到 Koopman 分量
            try:
                U, s, Vt = np.linalg.svd(H, full_matrices=False)
                components = []
                for i in range(min(3, len(s))):
                    comp = s[i] * U[:, i]
                    components.append(np.mean(np.diff(comp)) if len(comp) >= 2 else 0)

                if components:
                    growth = np.mean(components) * L
                else:
                    growth = velocity * 3600
            except np.linalg.LinAlgError:
                growth = velocity * 3600
        else:
            growth = velocity * 3600

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity
            n_comp = min(3, L // 2) if n >= 6 else 1
            confidence = min(0.85, 0.3 + 0.1 * n_comp + 0.02 * min(n, 20))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "koopa_numpy", "components": min(3, L // 2), "data_points": n},
            timestamp=datetime.now(),
        )
