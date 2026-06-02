"""
BiTCN (双向时序卷积网络 / Bidirectional Temporal Convolutional Network)
在传统 TCN 基础上增加反向卷积通道，同时捕捉历史和未来的时序依赖。

核心思路：
1. 前向 TCN：因果卷积捕捉历史→当前的趋势关系
2. 反向 TCN：反向卷积捕捉远期依赖和对称模式
3. 双向特征拼接后经预测头输出最终预测值

论文：BiTCN — 结合双向 LSTM 思路与 TCN 膨胀卷积的混合架构
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import BiTCNTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class BiTCNAlgorithm(BaseAlgorithm):
    """BiTCN 双向时序卷积算法。

    核心机制：
    - 前向 EMA（指数移动平均）：从远期到近期平滑，捕捉长期增长趋势
    - 反向 EMA：从近期到远期平滑，识别增长拐点
    - 卷积差分分析：5 点加权卷积核提取局部模式
    - 三路信号（前向增长 + 反向修正 + 卷积信号）加权融合

    降级链：torch checkpoint → numpy EMA+卷积 → velocity 兜底
    """

    name = "BiTCN双向卷积"
    algorithm_id = "bitcn"
    description = "双向时序卷积网络，前向+反向捕捉时序特征"
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
            self, video_data, threshold, BiTCNTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        """构建训练用的 PyTorch 模型。

        Returns:
            BiTCNTorchModel 实例
        """
        return BiTCNTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon,
            channels=32, kernel_size=3, layers=3,
        )

    def get_training_features(self) -> List[str]:
        """获取训练使用的特征列表。

        Returns:
            特征名称列表
        """
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """numpy 降级预测 - 简化版 BiTCN。

        用前向/反向 EMA + 卷积差分模拟双向 TCN。

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
                metadata={"method": "bitcn_fallback"},
                timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-20:]], dtype=np.float64)
        n = len(views)

        # 前向 EMA（从最早的记录向最新平滑，捕捉长期趋势）
        fwd_ema = views[-1]
        fwd_alpha = 0.3  # 平滑系数
        for v in views[::-1]:  # 反向遍历（从新到旧）
            fwd_ema = fwd_alpha * v + (1 - fwd_alpha) * fwd_ema

        # 反向 EMA（从最新的记录向最旧平滑，识别拐点）
        bwd_ema = views[0]
        bwd_alpha = 0.3
        for v in views:  # 正向遍历
            bwd_ema = bwd_alpha * v + (1 - bwd_alpha) * bwd_ema

        # 卷积式差分分析（5 点加权核）
        if n >= 5:
            kernel = np.array([0.1, 0.2, 0.4, 0.2, 0.1])  # 中间权重最高
            if n >= len(kernel):
                diffs = np.diff(views)
                conv_signal = np.convolve(diffs[-len(kernel):], kernel, mode='valid')
                conv_growth = np.mean(conv_signal) if len(conv_signal) > 0 else 0
            else:
                conv_growth = np.mean(np.diff(views))
        else:
            conv_growth = velocity * 3600

        # 融合双向 + 卷积三路信号
        forward_growth = max(0, fwd_ema - views[-1]) + np.mean(np.diff(views[-3:])) if n >= 3 else 0
        backward_growth = max(0, views[-1] - bwd_ema) * 0.3  # 反向修正 (权重较低)
        growth = 0.5 * forward_growth + 0.2 * backward_growth + 0.3 * conv_growth

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity
            confidence = min(0.85, 0.35 + 0.02 * min(n, 25) + 0.1)

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "bitcn_numpy", "data_points": n},
            timestamp=datetime.now(),
        )
