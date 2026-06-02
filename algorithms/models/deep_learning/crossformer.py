"""
Crossformer (跨维度依赖Transformer / Cross-Dimension Dependency Transformer)
跨维度依赖Transformer，ICLR 2023

核心思想：
1. 将时间序列按定长分段（segment），每段压缩为一个 token
2. 段间用交叉注意力（Cross-Attention）捕捉多维度依赖关系
3. 不同段可能对应不同的增长阶段，段间交互能发现阶段变化

与标准 Transformer 的区别：
- 标准 Transformer：每个时间步为一个 token
- Crossformer：每个段为一个 token，段内信息先压缩再交互

论文：Crossformer: Transformer Utilizing Cross-Dimension Dependency for Multivariate Time Series Forecasting
"""

import logging
from typing import Dict, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import CrossformerTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class CrossformerAlgorithm(BaseAlgorithm):
    """Crossformer 跨维Transformer 算法。

    核心机制：
    - 序列分段：将播放量历史切分为等长段（seg_len=4）
    - 段内差分：计算每段的一阶差分的平均值
    - 段间相关加权：用相关系数衡量每段与最近段的相似度，作为加权权重
    - 加权平均得到综合增长率

    适用于播放量有阶段性变化的视频（如多个推荐爆发期）。
    """

    name = "Crossformer跨维"
    algorithm_id = "crossformer"
    description = "分段编码+段间交叉注意力捕捉多维依赖"
    category = "深度学习"
    default_weight = 1.4

    training_window = 12
    """训练窗口长度（时间步数）"""
    training_horizon = 3
    """预测步数"""

    def predict(self, video_data, threshold=100000):
        """预测到达目标播放量所需时间。

        优先使用 torch 模型推理，失败降级到 numpy。

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值，默认 100000

        Returns:
            PredictionResult 预测结果对象
        """
        return try_torch_predict(
            self, video_data, threshold, CrossformerTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        """构建训练用的 PyTorch 模型。

        Returns:
            CrossformerTorchModel 实例
        """
        return CrossformerTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon, d_model=32, seg_len=4,
        )

    def get_training_features(self) -> List[str]:
        """获取训练使用的特征列表。

        Returns:
            特征名称列表
        """
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """numpy 降级预测 - 简化版 Crossformer。

        分段计算差分 → 段间相关系数加权 → 预测速度。

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult 预测结果对象
        """
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
        n_segs = max(1, n // seg_len)  # 分段数量
        seg_diffs = []
        for i in range(n_segs):
            seg = views[i * seg_len: (i + 1) * seg_len]
            if len(seg) >= 2:
                seg_diffs.append(np.mean(np.diff(seg)))  # 每段的平均差分

        if seg_diffs:
            # 段间交叉：用相关系数加权（衡量每段与最近段的相似度）
            seg_arr = np.array(seg_diffs)
            weights = np.ones(len(seg_arr))
            if len(seg_arr) >= 2:
                for i in range(len(seg_arr)):
                    corr = np.corrcoef(views[i*seg_len:(i+1)*seg_len], views[-seg_len:])[0, 1] if n >= seg_len else 0.5
                    weights[i] = max(0.1, corr)  # 相关系数不能为负
            growth = np.average(seg_arr, weights=weights)  # 加权平均
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
