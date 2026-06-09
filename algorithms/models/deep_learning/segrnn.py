"""
SegRNN (Segment Recurrent Neural Network) — 分段循环神经网络
=============================================================

arXiv 2023论文的实现——将长序列切分为等长segment分段编码，
用GRU串联所有segment进行时序预测，用于B站视频播放量增长分析。

核心原理:
    1. 序列分段：将长序列按固定长度（seg_len）切分为多个segment
    2. 独立编码：每个segment独立计算统计量（如平均数）
    3. GRU串联：使用GRU（门控循环单元）按序处理所有segment的编码
    4. 输出预测：最终隐藏状态解码为未来增长预测

优势：
    - 相比直接处理长序列的RNN，分段处理显著减少时间步数
    - GRU比LSTM参数更少，训练更快

降级链：torch checkpoint（SegRNNTorchModel） → numpy分段均值 + 指数加权

参考论文：
    "SegRNN: Segment Recurrent Neural Network for Long-Term Time Series Forecasting"
    (arXiv 2023)
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import SegRNNTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class SegRNNAlgorithm(BaseAlgorithm):
    """SegRNN 分段循环网络

    通过将序列分段编码后用GRU串联的架构进行预测。
    每个segment长3个点，各段独立计算均值后由指数加权模拟GRU的门控行为。
    """

    name = "SegRNN分段"
    algorithm_id = "segrnn"
    description = "分段编码+GRU串联，处理长序列高效"
    category = "深度学习"
    default_weight = 1.3

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
            self, video_data, threshold, SegRNNTorchModel, self._numpy_predict,
            window=self.training_window, horizon=self.training_horizon,
        )

    def build_model(self):
        """构建SegRNN PyTorch模型实例

        Returns:
            SegRNNTorchModel: 分段编码+GRU串联模型
        """
        return SegRNNTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            window=self.training_window, horizon=self.training_horizon,
            seg_len=3, d_model=32,
        )

    def get_training_features(self) -> List[str]:
        """返回训练时使用的多维特征列表"""
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """执行numpy版本的SegRNN预测

        流程：
        1. 提取最近18个数据点的播放量序列
        2. 按seg_len=3分段，每段计算平均增长
        3. 使用指数加权（模拟GRU门控）融合各段信息
        4. 计算预测速度和到达阈值的时间

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
                metadata={"method": "segrnn_fallback"},
                timestamp=datetime.now(),
            )

        import numpy as np
        views = np.array([h.get("view_count", 0) for h in history[-18:]], dtype=np.float64)
        n = len(views)

        # ===== 分段处理 =====
        seg_len = 3  # 每段包含3个数据点
        segments = []
        for i in range(0, n - seg_len + 1, seg_len):
            seg = views[i:i + seg_len]
            if len(seg) >= 2:
                # 每段计算平均增长（均值差分）
                segments.append(np.mean(np.diff(seg)))

        if not segments:
            growth = velocity * 3600  # 无有效段时回退
        else:
            # 模拟 GRU 门控：指数加权平均，近期权重高（越近的段越重要）
            weights = np.exp(np.linspace(0, 1, len(segments)))  # 指数增长的权重
            weights = weights / weights.sum()                     # 归一化
            growth = np.sum(np.array(segments) * weights)         # 加权融合

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity  # 预测过低时使用当前速度兜底

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity
            # 置信度：段数越多、数据点越多，置信度越高
            confidence = min(0.85, 0.3 + 0.03 * min(len(segments), 6) + 0.02 * min(n, 20))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "segrnn_numpy", "segments": len(segments), "data_points": n},
            timestamp=datetime.now(),
        )
