"""
TimeMixer (Decomposable Multiscale Mixing) — 可分解多尺度混合
=============================================================

ICLR 2024论文的B站视频播放量预测实现——通过多尺度时间下采样+MLP Mixer混合机制
进行时序预测。

核心原理:
    1. 多尺度时间下采样:
       对输入时序用不同步长做取样，生成多个不同时间分辨率的序列视图
       (如原始步长1、步长3下采样、步长7下采样)。

    2. 尺度内混合（Past Decomposable Mixing）:
       每个尺度内部使用MLP Mixer结构，分别沿着时间维度和特征维度
       做MLP混合，实现时间依赖和特征交互的分离建模。

    3. 跨尺度融合（Future Multipredictor Mixing）:
       不同尺度的特征通过可学习的权重融合，最终经过预测头(MLP)输出。
       浅层高分辨率捕捉短期波动，深层低分辨率捕捉长期趋势。

关键创新:
    - 将传统的单尺度MLP Mixer扩展到多尺度，首次在时间维度上实现
      可分解的多尺度混合
    - 在ETT, Weather, Exchange等多个基准上超越DLinear, PatchTST

降级链：torch checkpoint（TimeMixerTorchModel） → numpy多尺度下采样 + 加权融合

参考论文：
    "TimeMixer: Decomposable Multiscale Mixing for Time Series Forecasting"
    (Wang et al., ICLR 2024)
    https://arxiv.org/abs/2405.14616
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import TimeMixerTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class TimeMixerAlgorithm(BaseAlgorithm):
    """
    TimeMixer 算法适配器
    =====================
    通过多尺度下采样 + 加权融合模拟 TimeMixer 的多尺度混合机制。

    核心流程 (NumPy 回退):
        1. 对播放量序列用步长 [1, 3, 7] 做时间下采样
        2. 计算每个尺度的平均增长量级
        3. 按权重 [0.5, 0.3, 0.2] 加权融合各尺度增长
           (短期权重高，长期权重低)

    Torch 模式: TimeMixerTorchModel (3 尺度 MLP Mixer)
    NumPy 模式: 步长采样 + 加权均值融合
    """

    name = "TimeMixer混合"
    algorithm_id = "time_mixer"
    description = "多尺度下采样+MLP Mixer混合预测"
    category = "深度学习"
    default_weight = 1.5

    training_window = 12     # 训练窗口长度
    training_horizon = 3     # 预测步数

    def predict(self, video_data, threshold=100000):
        """执行 TimeMixer 预测

        Args:
            video_data: dict, 视频数据
            threshold: int, 目标播放量阈值

        Returns:
            PredictionResult: 预测结果
        """
        return try_torch_predict(
            self, video_data, threshold, TimeMixerTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        """构建 TimeMixer PyTorch 模型

        Returns:
            TimeMixerTorchModel:
                - d_model=32: 特征嵌入维度
                - scales=3:   3 个时间尺度 (原始/3x/7x 下采样)
        """
        return TimeMixerTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon,
            d_model=32, scales=3,
        )

    def get_training_features(self) -> List[str]:
        """返回训练使用的多维特征"""
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """执行numpy版本的TimeMixer预测

        多尺度融合流程：
        1. 提取最近20个数据点的播放量
        2. 用步长 [1, 3, 7] 做下采样，计算每个尺度的增长
        3. 加权融合：短期权重0.5、中期0.3、长期0.2
        4. 转换为小时速度并计算到达时间

        Args:
            video_data: dict, 视频数据
            threshold: int, 目标阈值

        Returns:
            PredictionResult: 预测结果
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足时回退
        if len(history) < 8 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "time_mixer_fallback"},
                timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-20:]], dtype=np.float64)

        # ===== 多尺度增长分析 =====
        # 不同步长对应不同时间尺度：步长1=短期，步长3=中期，步长7=长期趋势
        scale_growths = []
        for scale in [1, 3, 7]:
            if len(views) >= scale * 2:
                sampled = views[::scale]  # 隔scale取点做下采样
                if len(sampled) >= 2:
                    diffs = np.diff(sampled)
                    scale_growths.append(np.mean(diffs) / scale)  # 归一化到每步增长
                elif scale == 1 and len(views) >= 2:
                    scale_growths.append(np.mean(np.diff(views)))

        if not scale_growths:
            growth = velocity * 3600  # 无有效尺度时回退
        else:
            # 加权融合：短期权重最高（0.5），长期最低（0.2）
            weights = [0.5, 0.3, 0.2]
            growth = sum(w * g for w, g in zip(weights[:len(scale_growths)], scale_growths))
            growth /= sum(weights[:len(scale_growths)])  # 归一化权重

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity  # 预测速度过低时使用当前速度

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0  # 已达到阈值
        else:
            predicted_hours = remaining / predicted_velocity
            n_scales = len(scale_growths)
            # 置信度：有效尺度越多、数据点越多，置信度越高
            confidence = min(0.85, 0.35 + 0.12 * n_scales + 0.02 * min(len(views), 25))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "time_mixer_numpy", "scales": n_scales, "data_points": len(views)},
            timestamp=datetime.now(),
        )
