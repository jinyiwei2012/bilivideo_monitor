"""
Autoformer (自相关Transformer / Auto-Correlation Transformer)
自相关机制替代自注意力，NeurIPS 2021

核心思路：
1. 用 FFT 计算序列自相关代替点积注意力（Wiener-Khinchin 定理）
2. 时序分解：移动平均提取趋势分量 + 自相关提取季节分量
3. 渐进式分解架构，逐层提取不同时间尺度的模式

论文：Autoformer: Decomposition Transformers with Auto-Correlation for Long-Term Series Forecasting
"""

import logging
from typing import Dict, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import AutoformerTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class AutoformerAlgorithm(BaseAlgorithm):
    """Autoformer 自相关Transformer 算法。

    核心机制：
    - 自相关注意力：用 FFT 高效计算序列自身的周期性依赖关系
    - 趋势-季节分解：移动平均提取趋势、自相关提取季节，两者互补
    - 预测时优先使用 torch checkpoint 推理，失败则降级到 numpy 简化版

    时序依赖捕获方式：
    1. 季节性分量通过自相关系数加权 V，捕捉周期模式
    2. 趋势分量通过移动平均提取低频趋势
    3. 趋势 + 季节叠加得到最终表示
    """

    name = "Autoformer自相关"
    algorithm_id = "autoformer"
    description = "自相关机制替代注意力，趋势-季节渐进分解"
    category = "深度学习"
    default_weight = 1.5

    training_window = 12
    """训练窗口长度（时间步数）"""
    training_horizon = 3
    """预测步数"""

    def predict(self, video_data, threshold=100000):
        """预测到达目标播放量所需时间。

        优先使用 torch 模型推理，失败则降级到 _numpy_predict。

        Args:
            video_data: 视频数据字典，含 view_count, history_data, bvid 等字段
            threshold: 目标播放量阈值，默认 100000

        Returns:
            PredictionResult 预测结果对象
        """
        return try_torch_predict(
            self, video_data, threshold, AutoformerTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        """构建训练用的 PyTorch 模型。

        Returns:
            AutoformerTorchModel 实例
        """
        return AutoformerTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon, d_model=32, n_heads=2,
        )

    def get_training_features(self) -> List[str]:
        """获取训练使用的特征列表。

        Returns:
            特征名称列表
        """
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """numpy 降级预测 - 简化版 Autoformer。

        当 torch checkpoint 不可用或推理失败时使用。
        用移动平均 + 自相关分析模拟 Autoformer 的趋势-季节分解。

        处理流程：
        1. 移动平均提取趋势分量
        2. 残差作为季节分量
        3. 自相关分析找出主导周期（peak_lag）
        4. 趋势增长 + 季节增长加权求和
        5. 预测速度 → 时间

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
                metadata={"method": "autoformer_fallback"}, timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-24:]], dtype=np.float64)
        n = len(views)

        # 移动平均趋势（核大小=3）
        ma_kernel = 3
        if n >= ma_kernel * 2:
            trend = np.convolve(views, np.ones(ma_kernel) / ma_kernel, mode='valid')
        else:
            trend = views

        # 季节性 = 原始 - 趋势（高频残差）
        seasonal = views[-len(trend):] - trend if len(trend) > 0 else views - np.mean(views)

        # 自相关分析：找出最强周期
        if len(seasonal) >= 4:
            ac = np.correlate(seasonal - np.mean(seasonal), seasonal - np.mean(seasonal), mode='full')
            ac = ac[len(ac) // 2:]  # 仅保留正滞后
            ac = ac / (ac[0] + 1e-8)  # 归一化
            peak_lag = np.argmax(ac[1:min(8, len(ac))]) + 1 if len(ac) > 1 else 1
        else:
            peak_lag = 1

        # 趋势增长 + 季节增长加权
        trend_growth = np.mean(np.diff(trend)) if len(trend) >= 2 else velocity * 3600
        seasonal_growth = np.mean(np.diff(seasonal)) if len(seasonal) >= 2 else 0
        growth = 0.6 * trend_growth + 0.4 * seasonal_growth  # 趋势占主导

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = (remaining / predicted_velocity) if remaining > 0 and predicted_velocity > 0 else (remaining / velocity if velocity > 0 else float("inf"))
        confidence = min(0.85, 0.35 + 0.02 * min(n, 20))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={"method": "autoformer_numpy", "peak_lag": peak_lag, "data_points": n},
            timestamp=datetime.now(),
        )
