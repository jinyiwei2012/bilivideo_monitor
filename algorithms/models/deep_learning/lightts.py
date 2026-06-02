"""
LightTS (轻量采样导向MLP结构 / Light Sampling-oriented MLP Structures)
轻量采样MLP，arXiv 2022

核心思想：
1. 对输入时间序列做步长采样降维——每隔 stride 步取一个点
2. 用轻量 MLP 在降维后的序列上直接预测
3. 思想简单但效率高：牺牲少量精度换取大幅计算加速

适用场景：数据量大、需要快速输出的实时预测任务
"""

import logging
from typing import Dict, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import LightTSTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class LightTSAlgorithm(BaseAlgorithm):
    """LightTS 轻量采样算法。

    核心机制：
    - 步长采样 (stride=2)：将原始序列降采样一半
    - 差分分析：在降采样序列上计算差分
    - 增长估算：平均差分 × 采样步长 = 原始尺度增长（补偿降采样损失）

    这是最轻量的深度学习算法之一，复杂度 O(W)，
    适合在计算资源受限环境下快速得到预测。
    """

    name = "LightTS轻量"
    algorithm_id = "lightts"
    description = "步长采样降维+轻量MLP预测"
    category = "深度学习"
    default_weight = 1.3

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
            self, video_data, threshold, LightTSTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        """构建训练用的 PyTorch 模型。

        Returns:
            LightTSTorchModel 实例
        """
        return LightTSTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon, d_model=32, stride=2,
        )

    def get_training_features(self) -> List[str]:
        """获取训练使用的特征列表。

        Returns:
            特征名称列表
        """
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """numpy 降级预测 - 简化版 LightTS。

        步长采样 → 差分 → 平均增长。

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 6 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "lightts_fallback"}, timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-18:]], dtype=np.float64)
        n = len(views)

        # 步长采样（每隔 stride=2 取一个点，相当于降采样一半）
        stride = 2
        sampled = views[::stride]
        # 差分 × stride 以补偿降采样导致的"跳跃"
        diffs = np.diff(sampled) if len(sampled) >= 2 else np.diff(views)
        growth = np.mean(diffs) * stride  # × stride 还原到原始步长尺度

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 and predicted_velocity > 0 else float("inf")
        confidence = min(0.85, 0.3 + 0.02 * min(n, 20))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={"method": "lightts_numpy", "data_points": n}, timestamp=datetime.now(),
        )
