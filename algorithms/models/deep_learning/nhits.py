"""
N-HiTS (Neural Hierarchical Interpolation for Time Series)
===========================================================

AAAI 2023论文的B站视频播放量预测实现——通过多尺度层次化插值架构进行时序建模。

核心原理:
    1. 层次化残差架构:
       堆叠多个Block，每个Block包含一个MLP，接收下采样后的输入，
       同时输出backcast（对输入的拟合）和forecast（对未来预测）。
       Block之间通过残差连接级联：每个Block处理上一个Block的
       backcast残差，forecast则累加到最终预测中。

    2. 多尺度下采样（MaxPool）:
       每个Block对输入做不同步长的MaxPool下采样（如kernel=2,4,8），
       实现对不同时间尺度的关注——浅层关注短期波动，深层关注长期趋势。

    3. 分层插值（Interpolation）:
       下采样后的低分辨率预测通过线性插值恢复到原始分辨率，保证不同
       层次输出维度的统一。

优势:
    - 参数效率极高（相比N-BEATS大幅减少参数量）
    - 多尺度结构天然适应不同预测步长的需求

降级链：torch checkpoint（NHiTSTorchModel） → numpy多尺度均值池化 + 加权融合

参考论文：
    "N-HiTS: Neural Hierarchical Interpolation for Time Series Forecasting"
    (Challu et al., AAAI 2023)
    https://arxiv.org/abs/2201.12886
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import NHiTSTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class NHitsAlgorithm(BaseAlgorithm):
    """
    N-HiTS 算法适配器
    ==================
    通过多尺度下采样 + 残差累加模拟 N-HiTS 的层次化预测架构。

    核心流程 (NumPy 回退):
        1. 对播放量序列做不同步长 (1,2,4) 的下采样
        2. 计算每个尺度的平均增长
        3. 加权融合多尺度增长估计
        4. 残差修正: 0.6 * 多尺度增长 + 0.4 * 最近增长

    Torch 模式: 使用 NHiTSTorchModel (3 Block 堆叠残差网络)
    NumPy 模式: 多尺度均值下采样 + 加权融合
    """

    name = "N-HiTS多尺度"
    algorithm_id = "nhits"
    description = "多尺度分层插值预测，堆叠残差块"
    category = "深度学习"
    default_weight = 1.5

    training_window = 12     # 训练窗口长度
    training_horizon = 3     # 预测步数

    def predict(self, video_data, threshold=100000):
        """
        执行 N-HiTS 预测

        Args:
            video_data: dict, 视频数据字典
            threshold: int, 目标播放量阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        return try_torch_predict(
            self, video_data, threshold, NHiTSTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        """
        构建 N-HiTS PyTorch 模型

        Returns:
            NHiTSTorchModel: 包含 3 个 Block 的层次化残差网络
                - n_blocks=3:    三个层次捕捉不同尺度
                - n_pool_kernel=2: 每层下采样倍率
                - hidden=64:      MLP 隐藏层维度
        """
        return NHiTSTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon,
            n_blocks=3, n_pool_kernel=2, hidden=64,
        )

    def get_training_features(self) -> List[str]:
        """返回训练使用的多维特征"""
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """
        N-HiTS 的纯 NumPy 实现

        模拟论文中的多尺度 MaxPool 下采样 + 残差融合机制。
        使用三个不同步长 [1, 2, 4] 对播放量序列做均值下采样，
        在每个尺度上计算平均增长，最后加权融合。

        Args:
            video_data: dict, 视频数据
            threshold: int, 目标阈值

        Returns:
            PredictionResult: 预测结果
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足时回退到简单线性
        if len(history) < 6 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "nhits_fallback"},
                timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-15:]], dtype=np.float64)

        # === 多尺度下采样 (模拟 MaxPool 层次结构) ===
        # 对原始序列用不同步长 k 做均值下采样，捕捉不同时间尺度的趋势
        scales = []
        scale_views = views.copy()
        for k in [1, 2, 4]:                       # 三层尺度: 原始/2x/4x 下采样
            if len(scale_views) >= k:
                # 非重叠窗口均值池化（模拟MaxPool）
                pooled = np.array([np.mean(scale_views[i:i+k]) for i in range(0, len(scale_views) - k + 1, k)])
                if len(pooled) >= 2:
                    growth = np.mean(np.diff(pooled))  # 该尺度下的平均增长
                    scales.append(growth / k)           # 归一化到原始尺度（每步增长）

        if scales:
            growth = np.mean(scales)    # 各尺度均值融合
        else:
            growth = velocity * 3600    # 无有效尺度时回退到当前速度

        # === 残差修正 (模拟 backcast 残差传递) ===
        # 最近观察值与多尺度估计的加权融合
        recent_growth = views[-1] - views[-2] if len(views) >= 2 else growth
        predicted_growth = 0.6 * growth + 0.4 * recent_growth  # 残差修正权重 6:4

        predicted_velocity = max(0, predicted_growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity  # 预测速度过低时使用当前速度兜底

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0  # 已达到阈值
        else:
            predicted_hours = remaining / predicted_velocity
            n_scales = len(scales)
            # 置信度：尺度越多、数据点越多，置信度越高
            confidence = min(0.85, 0.4 + 0.1 * n_scales + 0.05 * min(len(views), 20) * 0.05)

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "nhits_numpy", "scales": len(scales), "data_points": len(views)},
            timestamp=datetime.now(),
        )
