"""
TSMixer (MLP Mixer) — 纯MLP架构时间序列预测器
================================================

基于MLP Mixer架构的B站视频播放量预测模型，交替在时间维和通道维做MLP混合，
结构轻量化不易过拟合。

核心原理:
    1. 时间混合（Time Mixing）：在时间维度上应用MLP，捕捉时间依赖
    2. 通道混合（Channel Mixing）：在特征维度上应用MLP，捕捉特征间交互
    3. 交替操作：时间混合 → 通道混合交替进行，类似Transformer但全是MLP

简化版实现：
    - 计算多种特征的百分比变化序列
    - 时间混合：随机投影 + ReLU（模拟时间维MLP）
    - 通道混合：随机投影 + ReLU（模拟通道维MLP）
    - 线性输出头

降级链：torch checkpoint（TSMixerTorchModel） → numpy双阶段MLP

参考论文：
    "TSMixer: An All-MLP Architecture for Time Series Forecasting"
    (Chen et al., 2023)
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import TSMixerTorchModel, try_torch_predict


class TsmixerSimpleAlgorithm(BaseAlgorithm):
    """TSMixer MLP混合器

    纯MLP架构，交替在时间维和通道维做随机投影+ReLU，
    模拟TSMixer的TimeMix和ChannelMix操作。
    """

    name = "TSMixer混合器"
    algorithm_id = "tsmixer_simple"
    description = "纯MLP架构，时间维与通道维交替混合"
    category = "深度学习"
    default_weight = 1.2

    training_window = 10     # 训练时使用的历史窗口长度
    training_horizon = 3     # 训练时预测的未来步数

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行预测

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult: 预测结果
        """
        return try_torch_predict(
            self,
            video_data,
            threshold,
            TSMixerTorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建TSMixer PyTorch模型实例"""
        return TSMixerTorchModel(in_features=getattr(self, '_training_n_features', 5), window=10, horizon=self.training_horizon)

    def get_training_features(self) -> List[str]:
        """返回训练时使用的多维特征列表"""
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行numpy版本的TSMixer预测

        流程：
        1. 计算4个特征的百分比变化序列（播放量/点赞/投币/收藏）
        2. TimeMix：时间维度随机投影 + ReLU（模拟时间维MLP）
        3. ChannelMix：通道维度随机投影 + ReLU（模拟通道维MLP）
        4. 线性输出头解码为预测速度

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult: 预测结果
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足时降级
        if len(history) < 6 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            # 提取多维历史数据
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            likes = np.array([h.get("like", 0) for h in history], dtype=np.float64)
            coins = np.array([h.get("coin", 0) for h in history], dtype=np.float64)
            favs = np.array([h.get("favorite", 0) for h in history], dtype=np.float64)

            # 计算百分比变化（比绝对值更稳定）
            pct_views = np.diff(views) / np.maximum(views[:-1], 1)
            pct_likes = np.diff(likes) / np.maximum(likes[:-1], 1)
            pct_coins = np.diff(coins) / np.maximum(coins[:-1], 1)
            pct_favs = np.diff(favs) / np.maximum(favs[:-1], 1)

            # 拼接为特征矩阵 [T-1, 4]（T个时间步，4维特征）
            X = np.column_stack([pct_views, pct_likes, pct_coins, pct_favs])
            X = np.where(np.isfinite(X), X, 0)  # 处理 inf/nan

            # ===== TimeMix：时间维度混合（随机投影 + ReLU） =====
            W_time = np.random.RandomState(42).randn(X.shape[1], 4) * 0.1   # [4, 4]
            H_time = np.maximum(X @ W_time, 0)                               # ReLU激活

            # ===== ChannelMix：通道维度混合（随机投影 + ReLU） =====
            W_channel = np.random.RandomState(43).randn(H_time.shape[1], 1) * 0.1  # [4, 1]
            H_channel = np.maximum(H_time @ W_channel, 0)                           # ReLU激活

            # ===== 输出头：线性投影到预测值 =====
            W_out = np.random.RandomState(44).randn(H_channel.shape[0], 1) * 0.01  # [T-1, 1]
            v_pred = H_channel.T @ W_out  # [1, 1]

            # 转换为每小时速度（百分比变化 × 绝对播放量平台 / 3600秒）
            predicted_velocity = max(0, float(v_pred[0, 0]) * abs(np.mean(views[-5:])) / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity  # 预测过低时使用当前速度

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                # 置信度随数据量对数增长
                confidence = min(0.8, 0.4 + 0.05 * np.log1p(len(history)))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "tsmixer", "window": len(history)},
                timestamp=datetime.now(),
            )
        except Exception:
            return self._fallback(velocity, current_views, threshold)

    def _fallback(self, velocity, current_views, threshold):
        """回退预测：当数据不足或推理异常时的安全兜底方案

        Args:
            velocity: 当前速度
            current_views: 当前播放量
            threshold: 目标阈值

        Returns:
            PredictionResult: 回退预测结果
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
                metadata={"method": "tsmixer", "reason": "fallback"},
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
            metadata={"method": "tsmixer", "reason": "fallback"},
            timestamp=datetime.now(),
        )
