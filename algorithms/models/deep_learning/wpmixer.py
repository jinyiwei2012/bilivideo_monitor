"""
WPMixer (Wavelet Packet Mixer) — 高效多分辨率混合器
=====================================================

AAAI 2025论文的B站视频播放量预测实现——通过多分辨率分支并行处理不同时间尺度的信息，
再进行跨分辨率融合输出。

核心原理:
    1. 多分辨率分支：原始分辨率 / 2×下采样 / 4×下采样（3个并行分支）
    2. 独立分支处理：每个分辨率分支独立的MLP Mixer处理
    3. 跨分辨率融合：加权融合不同分辨率分支的输出：
       - 高分辨率（原始）：捕捉短期波动，权重最高0.5
       - 中分辨率（2×）：捕捉中期趋势，权重0.3
       - 低分辨率（4×）：捕捉长期趋势，权重0.2

优势：
    - 类似小波包分解的多分辨率分析，同时捕捉短期和长期模式
    - 相比单分辨率模型，对非平稳时序数据更具鲁棒性

降级链：torch checkpoint（WPMixerTorchModel） → numpy多分辨率差异 + 加权融合

参考论文：
    "WPMixer: Wavelet Packet Mixer for Efficient Multi-Resolution Time Series Forecasting"
    (AAAI 2025)
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import WPMixerTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class WPMixerAlgorithm(BaseAlgorithm):
    """WPMixer 小波包混合器

    通过多分辨率分支（1×/2×/4×下采样）的并行处理，
    分别捕捉不同时间尺度的增长模式，最终加权融合输出。
    """

    name = "WPMixer多分辨率"
    algorithm_id = "wpmixer"
    description = "多分辨率小波包混合预测，高效轻量级"
    category = "深度学习"
    default_weight = 1.4

    training_window = 12     # 训练时使用的历史窗口长度
    training_horizon = 3     # 训练时预测的未来步数

    def predict(self, video_data, threshold=100000):
        """执行预测

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult: 预测结果
        """
        return try_torch_predict(
            self, video_data, threshold, WPMixerTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        """构建WPMixer PyTorch模型实例

        Returns:
            WPMixerTorchModel: d_model=32的多分辨率混合模型
        """
        return WPMixerTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon, d_model=32,
        )

    def get_training_features(self) -> List[str]:
        """返回训练时使用的多维特征列表"""
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """执行numpy版本的WPMixer预测

        多分辨率分析流程：
        1. 取最近24个数据点的播放量
        2. 对步长 [1, 2, 4] 做下采样，计算各分辨率的增长率
        3. 加权融合：原始分辨率权重0.5、2×权重0.3、4×权重0.2
        4. 转换为小时速度并计算到达时间

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

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
                metadata={"method": "wpmixer_fallback"},
                timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-24:]], dtype=np.float64)
        n = len(views)

        # ===== 多分辨率分析 =====
        # 步长r=1: 原始分辨率（捕捉短期波动）
        # 步长r=2: 2×下采样（捕捉中期趋势）
        # 步长r=4: 4×下采样（捕捉长期趋势）
        resolutions = []
        for r in [1, 2, 4]:
            if n >= r * 2:
                sampled = views[::r]           # 隔r点取一次（下采样）
                diffs = np.diff(sampled)       # 一阶差分
                if len(diffs) > 0:
                    resolutions.append(np.mean(diffs) / r)  # 归一化到每步增长

        if not resolutions:
            growth = velocity * 3600  # 无有效分辨率时回退
        else:
            # 加权融合：低分辨率权重低（只给大趋势方向），高分辨率权重高（精确短期预测）
            weights = [0.5, 0.3, 0.2][:len(resolutions)]
            growth = sum(w * r for w, r in zip(weights, resolutions)) / sum(weights)

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity  # 预测过低时使用当前速度兜底

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0  # 已达到阈值
        else:
            predicted_hours = remaining / predicted_velocity
            n_res = len(resolutions)
            # 置信度：有效分辨率越多、数据点越多，置信度越高
            confidence = min(0.85, 0.35 + 0.1 * n_res + 0.02 * min(n, 25))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "wpmixer_numpy", "resolutions": n_res, "data_points": n},
            timestamp=datetime.now(),
        )
