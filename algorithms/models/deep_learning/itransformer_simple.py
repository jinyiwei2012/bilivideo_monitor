"""
iTransformer (倒置Transformer / Inverted Transformer)
将标准 Transformer 反转：每个变量的整个时间序列作为一个 token（而非每个时间步作为一个token），
注意力机制用于捕捉不同变量（指标）之间的相关性。

核心思路（与标准 Transformer 的对比）：
- 标准 Transformer：时间步 = token，注意力在时间步之间
- iTransformer：变量 = token，注意力在不同指标（播放量、点赞、硬币、收藏）之间
- 对于多变量时序预测，不同指标之间的相关性比时间步之间的相关性更有信息量

论文：iTransformer: Inverted Transformers Are Effective for Time Series Forecasting
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import ITransformerTorchModel, try_torch_predict


class ITransformerSimpleAlgorithm(BaseAlgorithm):
    """iTransformer 倒置Transformer 预测算法。

    核心机制（numpy 简化版）：
    - 多变量差分矩阵：views, likes, coins, favs 四个指标的一阶差分
    - 变量间注意力：metrics @ metrics.T 计算指标间关联
    - 上下文向量：注意力加权后的变量信号
    - 门控激活：tanh 门控过滤信号 → 调整基础速度

    降级链：torch checkpoint → numpy 变量注意力 → velocity 兜底
    """

    name = "iTransformer倒置"
    algorithm_id = "itransformer_simple"
    description = "倒置Transformer，变量作为token捕捉跨指标相关性"
    category = "深度学习"
    default_weight = 1.2

    training_window = 10
    """训练窗口长度（时间步数）"""
    training_horizon = 3
    """预测步数"""

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """预测到达目标播放量所需时间。

        优先使用 torch 模型推理，失败降级到 numpy。

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值，默认 100000

        Returns:
            PredictionResult 预测结果对象
        """
        return try_torch_predict(
            self,
            video_data,
            threshold,
            ITransformerTorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建训练用的 PyTorch 模型。

        Returns:
            ITransformerTorchModel 实例
        """
        return ITransformerTorchModel(in_features=getattr(self, '_training_n_features', 5), window=10, d_model=32, n_heads=4, horizon=self.training_horizon)

    def get_training_features(self) -> List[str]:
        """获取训练使用的特征列表。

        Returns:
            特征名称列表
        """
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """numpy 降级预测 - 简化版 iTransformer。

        变量间注意力 + 门控速度调整。

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
            return self._fallback(velocity, current_views, threshold)

        try:
            # 四个核心指标的差分（度量变化率）
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            likes = np.array([h.get("like", 0) for h in history], dtype=np.float64)
            coins = np.array([h.get("coin", 0) for h in history], dtype=np.float64)
            favs = np.array([h.get("favorite", 0) for h in history], dtype=np.float64)

            # 各指标差分，归一化为变化率 [4, L]
            metrics = np.column_stack([views, likes, coins, favs]).T
            metrics = np.diff(metrics) / np.maximum(metrics[:, :-1], 1)  # 相对变化率
            metrics = np.nan_to_num(metrics)  # 处理 NaN

            n_vars = metrics.shape[0]  # 变量数（4）
            # 变量间注意力：metrics @ metrics.T 是各变量时间序列的交叉相关
            Q = metrics @ metrics.T / np.sqrt(n_vars)  # 缩放
            attn = np.maximum(Q, 0)  # ReLU 激活（仅保留正相关）
            attn = attn / (np.sum(attn, axis=-1, keepdims=True) + 1e-10)  # 行归一化

            # 值投影 + 注意力汇聚
            W_v = np.random.RandomState(42).randn(metrics.shape[1], 1) * 0.01  # 随机投影
            values = metrics @ W_v  # 变量的投影值
            context = attn @ values  # 注意力加权汇聚
            gate = np.tanh(context)  # 门控激活 [-1, 1]
            trends = gate.flatten()

            # view_trend 反映播放量相关变量的综合趋势
            view_trend = float(trends[0]) if len(trends) > 0 else 0
            predicted_velocity = max(0, velocity * (1 + view_trend))  # 速度调整
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                confidence = max(0.1, min(0.8, 0.5))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "itransformer", "n_vars": n_vars},
                timestamp=datetime.now(),
            )
        except Exception:
            return self._fallback(velocity, current_views, threshold)

    def _fallback(self, velocity, current_views, threshold):
        """兜底预测：速度 ≤ 0 时返回无限时间。

        Args:
            velocity: 当前速度（每小时播放量）
            current_views: 当前播放量
            threshold: 目标播放量阈值

        Returns:
            PredictionResult 兜底预测结果
        """
        if velocity <= 0:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=float("inf"),
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "itransformer", "reason": "fallback"},
                timestamp=datetime.now(),
            )
        remaining = max(0, threshold - current_views)
        predicted_hours = remaining / velocity if remaining > 0 else 0
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=0.3,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "itransformer", "reason": "fallback"},
            timestamp=datetime.now(),
        )
