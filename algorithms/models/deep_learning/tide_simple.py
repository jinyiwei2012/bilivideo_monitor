"""
TIDE (Time Series Dense Encoder) — 时序稠密编码器
===================================================

基于残差MLP的轻量级时序预测模型，用于B站视频播放量增长预测。
结构极简但在多种数据集上超越复杂Transformer架构。

核心原理:
    1. 全连接编码器：多层MLP将时序数据编码为稠密表示
    2. 残差连接：每层输出 = F(x) + x，缓解深层网络的梯度消失
    3. 解码预测：通过全连接层从编码表示解码出未来增长

降级链：torch checkpoint（TIDETorchModel） → numpy最近差分均值

参考论文：
    "TIDE: Time Series Dense Encoder for General Time Series Forecasting"
    (Das et al., 2023)
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import TIDETorchModel, try_torch_predict


class TideSimpleAlgorithm(BaseAlgorithm):
    """TIDE 时序稠密编码器

    残差MLP基线模型，结构简单但在多个基准上性能优异。
    numpy回退版本使用最近邻差分均值作为简单预测。
    """

    name = "TIDE稠密编码器"
    algorithm_id = "tide_simple"
    description = "残差MLP基线，简单但强大的时序预测"
    category = "深度学习"
    default_weight = 1.1

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
            TIDETorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建TIDE PyTorch模型实例"""
        return TIDETorchModel(in_features=getattr(self, '_training_n_features', 5), window=10, horizon=self.training_horizon)

    def get_training_features(self) -> List[str]:
        """返回训练时使用的多维特征列表"""
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行numpy版本的TIDE预测

        numpy回退方案非常简洁：
        1. 取最近5个数据点的平均差分作为未来速度估计
        2. 以当前速度的50%作为下限（防止预测值过低）

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult: 预测结果
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足时返回无预测
        if len(history) < 4 or velocity <= 0:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=float("inf"),
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "tide_simple", "reason": "insufficient_data"},
                timestamp=datetime.now(),
            )

        views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
        n = min(10, len(views) // 2)
        if n < 2:
            n = 2

        try:
            # 取最近5个数据点的平均差分作为未来速度（最近信息权重最高）
            future_velocity = max(0, np.mean(np.diff(views[-5:])) / 3600) if len(views) >= 5 else velocity
            # 不低于当前速度的50%（防止TIDE过度调低预测）
            predicted_velocity = max(future_velocity, velocity * 0.5)

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0  # 已达到阈值
            else:
                predicted_hours = remaining / predicted_velocity
                confidence = min(0.85, 0.5 + 0.01 * len(history))  # 数据越多置信度越高
        except Exception:
            predicted_hours = (
                remaining / velocity if velocity > 0 else float("inf") if "remaining" in dir() else float("inf")
            )
            confidence = 0.3

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "tide_simple", "history_len": len(history)},
            timestamp=datetime.now(),
        )
