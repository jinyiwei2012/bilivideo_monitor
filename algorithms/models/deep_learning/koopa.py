"""
Koopa (基于 Koopman 算子的非平稳时序预测 / Koopman Predictors for Non-stationary Time Series)
NeurIPS 2023

核心思路：
1. 通过延迟嵌入（Hankel 矩阵）将一维时序映射到高维空间
2. 用 SVD 分解提取 Koopman 分量（等同于线性的系统演化模式）
3. 多个 Koopman 分量捕捉不同时间尺度的动力学特征
4. 各分量趋势平均得到综合增长预测

Koopman 理论的核心思想：非线性动力系统可以在高维空间中近似为线性演化
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import KoopaTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class KoopaAlgorithm(BaseAlgorithm):
    """Koopa Koopman算子预测算法。

    核心机制：
    - 延迟嵌入（Hankel 矩阵）：将标量时间序列映射为 L 维轨迹
    - SVD 分解：提取前 k 个奇异向量作为 Koopman 分量
    - 分量趋势分析：计算各分量的一阶差分均值 × 延迟长度

    不同于传统时序方法，Koopman 试图找到系统的"不变子空间"，
    在该空间中时间演化变为线性操作。
    """

    name = "Koopa算子"
    algorithm_id = "koopa"
    description = "Koopman算子理论驱动的非平稳时序预测"
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
            self, video_data, threshold, KoopaTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        """构建训练用的 PyTorch 模型。

        Returns:
            KoopaTorchModel 实例
        """
        return KoopaTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon,
            d_model=32, n_components=4,
        )

    def get_training_features(self) -> List[str]:
        """获取训练使用的特征列表。

        Returns:
            特征名称列表
        """
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """numpy 降级预测 - 简化版 Koopa。

        Hankel 矩阵 → SVD 分解 → 分量趋势分析。

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
                metadata={"method": "koopa_fallback"},
                timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-20:]], dtype=np.float64)
        n = len(views)

        # 构造 Hankel 矩阵（延迟嵌入 / time-delay embedding）
        # 每行是长度为 L 的滑动窗口子序列
        L = min(8, n // 2)  # 嵌入维度
        if L >= 3 and n >= 2 * L:
            H = np.array([views[i:i+L] for i in range(n - L + 1)])  # (n-L+1) × L
            H = H - np.mean(H, axis=0)  # 去均值

            # SVD 分解得到 Koopman 分量
            try:
                U, s, Vt = np.linalg.svd(H, full_matrices=False)
                components = []
                for i in range(min(3, len(s))):
                    comp = s[i] * U[:, i]  # 第 i 个分量
                    components.append(np.mean(np.diff(comp)) if len(comp) >= 2 else 0)

                if components:
                    growth = np.mean(components) * L  # × L 以还原到原始尺度
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
