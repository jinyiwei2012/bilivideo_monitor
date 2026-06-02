"""
Crossformer (Cross-Dimension Dependency Transformer)
跨维度依赖Transformer，ICLR 2023

核心：将序列分段，段间用交叉注意力捕捉多维依赖
"""

import logging
from typing import Dict, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import CrossformerTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class CrossformerAlgorithm(BaseAlgorithm):
    """Crossformer 跨维Transformer"""

    name = "Crossformer跨维"
    algorithm_id = "crossformer"
    description = "分段编码+段间交叉注意力捕捉多维依赖"
    category = "深度学习"
    default_weight = 1.4

    training_window = 12
    training_horizon = 3

    def predict(self, video_data, threshold=100000):
        return try_torch_predict(
            self, video_data, threshold, CrossformerTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        return CrossformerTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon, d_model=32, seg_len=4,
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
                metadata={"method": "crossformer_fallback"}, timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-20:]], dtype=np.float64)
        n, seg_len = len(views), 4
        n_segs = max(1, n // seg_len)
        seg_diffs = []
        for i in range(n_segs):
            seg = views[i * seg_len: (i + 1) * seg_len]
            if len(seg) >= 2:
                seg_diffs.append(np.mean(np.diff(seg)))

        if seg_diffs:
            # 段间交叉：用相关系数加权
            seg_arr = np.array(seg_diffs)
            weights = np.ones(len(seg_arr))
            if len(seg_arr) >= 2:
                for i in range(len(seg_arr)):
                    corr = np.corrcoef(views[i*seg_len:(i+1)*seg_len], views[-seg_len:])[0, 1] if n >= seg_len else 0.5
                    weights[i] = max(0.1, corr)
            growth = np.average(seg_arr, weights=weights)
        else:
            growth = velocity * 3600

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 and predicted_velocity > 0 else float("inf")
        confidence = min(0.85, 0.3 + 0.02 * min(n_segs, 5) + 0.02 * min(n, 20))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={"method": "crossformer_numpy", "segments": n_segs}, timestamp=datetime.now(),
        )
