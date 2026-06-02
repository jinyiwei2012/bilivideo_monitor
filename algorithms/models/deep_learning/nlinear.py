"""
NLinear (Normalization-Linear) — 实例归一化 + 线性映射预测
===========================================================

AAAI 2023论文的实现——极简却高效的时序预测方法，用于B站视频播放量增长预测。

核心原理:
    1. 实例归一化（Instance Normalization）:
       对每个输入窗口减去自身均值、除以自身标准差，消除非平稳性导致的
       分布偏移（distribution shift），使线性模型也能适应时序数据。
    2. 极简线性层:
       归一化后的窗口数据通过单层全连接直接映射到预测步数，无激活函数、
       无注意力机制、无卷积。
    3. 反归一化:
       预测结果乘以原标准差再加原均值，恢复原始量纲。

关键发现:
    论文在多个基准数据集上证明，这种「归一化+线性」的极简结构在多步预测
    任务上打平甚至超越 Informer、Autoformer 等复杂 Transformer 模型，
    挑战了"时序预测必须用深度非线性模型"的固有观念。

降级链：torch checkpoint（NLinearTorchModel） → numpy polyfit线性拟合 + 外推

参考论文：
    "Are Transformers Effective for Time Series Forecasting?"
    (Zeng et al., AAAI 2023)
    https://arxiv.org/abs/2205.13504
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import NLinearTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class NLinearAlgorithm(BaseAlgorithm):
    """
    NLinear 算法适配器
    ====================
    将视频监控数据适配到 NLinear 模型。

    核心流程:
        1. 从 video_data 中提取播放量历史序列
        2. 对数据做实例归一化 (减均值/除标准差)
        3. 用一阶多项式拟合归一化后的序列趋势
        4. 外推趋势线获得未来播放量增长估计
        5. 反归一化还原到原始量纲

    Torch 模式: 使用 NLinearTorchModel (单层 Linear 映射)
    NumPy 模式: 使用 polyfit 一阶线性拟合 + 外推
    """

    name = "NLinear线性"
    algorithm_id = "nlinear"
    description = "实例归一化 + 单层线性映射，极简高效"
    category = "深度学习"
    default_weight = 1.5

    training_window = 10     # 训练时使用的历史窗口长度
    training_horizon = 3     # 训练时预测的未来步数

    def predict(self, video_data, threshold=100000):
        """执行预测，优先使用 PyTorch 模型，回退到 NumPy 实现

        Args:
            video_data: dict, 包含 view_count、history_data 等字段
            threshold: int, 目标播放量阈值

        Returns:
            PredictionResult: 包含 predicted_hours、confidence 等字段
        """
        return try_torch_predict(
            self, video_data, threshold, NLinearTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        """构建 PyTorch 模型实例

        Returns:
            NLinearTorchModel: 单层 Linear(window * in_features -> horizon) 的极简模型
        """
        return NLinearTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon,
        )

    def get_training_features(self) -> List[str]:
        """返回训练时使用的特征列表

        Returns:
            List[str]: 视频指标特征名列表
        """
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """
        NLinear 的纯 NumPy 实现预测

        算法流程:
            1. 提取历史播放量序列
            2. 实例归一化: normalized = (views - mean) / (std + eps)
            3. 一阶线性拟合并外推 5 步
            4. 反归一化得到预测播放量
            5. 计算到达阈值所需的小时数

        Args:
            video_data: dict, 视频数据
            threshold: int, 目标阈值

        Returns:
            PredictionResult: 预测结果
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 历史数据不足或增量为零时，用当前速度做线性外推
        if len(history) < 5 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3 if velocity > 0 else 0.0,
                current_views=current_views, current_velocity=velocity,
                metadata={"method": "nlinear_fallback"},
                timestamp=datetime.now(),
            )

        # 提取播放量历史序列
        views = []
        for h in history:
            v = h.get("view_count", 0)
            if v > 0:
                views.append(float(v))

        # 有效数据点不足时再次回退
        if len(views) < 5:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.4, current_views=current_views, current_velocity=velocity,
                metadata={"method": "nlinear_fallback"},
                timestamp=datetime.now(),
            )

        # === 核心步骤1: 实例归一化 (Instance Normalization) ===
        # 减均值、除标准差，消除分布偏移
        import numpy as np
        arr = np.array(views[-15:])        # 取最近 15 个数据点
        mean = np.mean(arr)
        std = np.std(arr) + 1e-5           # 加 epsilon 防止除零
        normalized = (arr - mean) / std    # Z-score 归一化

        # === 核心步骤2: 线性拟合 + 外推 ===
        # 用一阶多项式拟合归一化后的序列，模拟论文中的单层 Linear
        if len(normalized) >= 5:
            x = np.arange(len(normalized))
            coef = np.polyfit(x, normalized, 1)                      # 一阶线性拟合
            future = np.polyval(coef, np.arange(len(normalized), len(normalized) + 5))  # 外推 5 步
            future_views = future * std + mean                       # 反归一化恢复量纲
            growth = max(0, np.mean(np.diff(future_views)))          # 平均每步增长
        else:
            growth = velocity * 3600  # 回退到小时级速度

        # === 核心步骤3: 转换为小时速度并计算到达时间 ===
        predicted_velocity = max(0, growth / 3600)  # 转换为每秒增速
        if predicted_velocity < 1:
            predicted_velocity = velocity            # 增速过低时用当前速度

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0    # 已达阈值
        else:
            predicted_hours = remaining / predicted_velocity
            confidence = min(0.85, 0.4 + len(views) * 0.02)  # 数据点越多置信度越高

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "nlinear_numpy", "data_points": len(views)},
            timestamp=datetime.now(),
        )
