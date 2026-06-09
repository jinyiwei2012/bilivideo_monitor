"""
FEDformer (频域增强分解Transformer / Frequency Enhanced Decomposed Transformer)
频域增强分解Transformer，ICML 2022

核心思路：
1. FFT 变换到频域，在频域进行注意力机制（频率增强）
2. 保留 Top-K 个最强的频率分量（稀疏频域表示）
3. 频域幅度+相位增强后聚合输出预测
4. 趋势分解：去趋势后分析周期性频率，再加回趋势

相比 Autoformer 的优势：直接在频域操作，计算更高效
"""

import logging
from typing import Dict, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import FEDformerTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class FEDformerAlgorithm(BaseAlgorithm):
    """FEDformer 频域Transformer 算法。

    核心机制：
    - 趋势分离：一次多项式拟合去趋势
    - FFT 变换：提取频谱
    - Top-K 频率选择：保留 n_modes 个最强频率分量
    - 频域增强：根据相位调整幅度缩放
    - iFFT 还原 + 趋势恢复

    降级链：torch checkpoint → numpy FFT+滤波 → velocity 兜底
    """

    name = "FEDformer频域"
    algorithm_id = "fedformer"
    description = "FFT频域变换+TopK频率增强预测"
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
            self, video_data, threshold, FEDformerTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        """构建训练用的 PyTorch 模型。

        Returns:
            FEDformerTorchModel 实例
        """
        return FEDformerTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon, d_model=32, n_modes=6,
        )

    def get_training_features(self) -> List[str]:
        """获取训练使用的特征列表。

        Returns:
            特征名称列表
        """
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """numpy 降级预测 - 简化版 FEDformer。

        去趋势 → FFT → Top-K 频率滤波 → 频域增强 → iFFT 还原。

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
                metadata={"method": "fedformer_fallback"}, timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-24:]], dtype=np.float64)
        n = len(views)

        # 去趋势（一次多项式拟合）
        detrended = views - np.polyval(np.polyfit(np.arange(n), views, 1), np.arange(n))
        fft = np.fft.rfft(detrended)  # 实 FFT
        freqs = np.abs(fft)
        n_modes = min(6, len(freqs) - 1)  # 最多保留 6 个频率模式
        top_idx = np.argsort(freqs)[-n_modes:]  # 最大的 n_modes 个频率

        # 频域滤波：仅保留 Top-K 频率
        filtered = np.zeros_like(fft, dtype=complex)
        for idx in top_idx:
            filtered[idx] = fft[idx]

        # 频域增强：根据相位调整幅度
        phase_adj = np.angle(filtered[top_idx]).mean() if len(top_idx) > 0 else 0
        amp_scale = 1.0 + 0.2 * np.tanh(phase_adj)  # 相位信息调整幅度
        for idx in top_idx:
            filtered[idx] *= amp_scale

        # iFFT 还原 + 趋势恢复
        reconstructed = np.fft.irfft(filtered, n=n)
        trend = np.polyfit(np.arange(n), views, 1)
        reconstructed += np.polyval(trend, np.arange(n))

        growth = np.mean(np.diff(reconstructed[-5:])) if n >= 5 else velocity * 3600
        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 and predicted_velocity > 0 else float("inf")
        confidence = min(0.85, 0.3 + 0.1 * min(n_modes, 6) + 0.02 * min(n, 20))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={"method": "fedformer_numpy", "n_modes": n_modes}, timestamp=datetime.now(),
        )
