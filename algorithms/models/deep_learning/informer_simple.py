"""
Informer简化版 (Informer Simplified)
高效Transformer，使用 ProbSparse 自注意力降低 O(L²) 复杂度到 O(L log L)。

核心思路（简化版）：
1. ProbSparse 自注意力：不是所有注意力连接都需要计算，只保留每个 query 最重要的 factor 个 key
2. 自注意力蒸馏：通过最大池化下采样减少序列长度（模拟论文中的 Conv1d 蒸馏层）
3. 生成式解码器：直接一次生成多步预测，避免自回归误差累积

论文：Informer: Beyond Efficient Transformer for Long Sequence Time-Series Forecasting (AAAI 2021, Zhou et al.)

为什么需要 ProbSparse？
- 标准 Transformer 的自注意力是 O(L²)，长序列计算不可行
- 稀疏性假设：在实际时序中，注意力分布通常集中在少数关键位置
- 只计算 Top-K 注意力的稀疏连接，大幅降低计算量
"""

import numpy as np
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import InformerTorchModel, try_torch_predict


class InformerSimpleAlgorithm(BaseAlgorithm):
    """Informer简化版算法

    核心思路（简化）：
    1. ProbSparse自注意力：只计算最重要的注意力连接
    2. 自注意力蒸馏：下采样减少序列长度
    3. 生成式解码器：避免误差累积

    论文：Informer: Beyond Efficient Transformer for Long Sequence
    Time-Series Forecasting (AAAI 2021, Zhou et al.)

    降级链：torch checkpoint → numpy ProbSparse+蒸馏 → velocity 兜底
    """

    name = "Informer简化版"
    algorithm_id = "informer_simple"
    description = "使用ProbSparse自注意力，高效处理长序列"
    category = "Transformer模型"
    default_weight = 1.3

    def __init__(self):
        """初始化 Informer 算法。

        设置回看窗口长度、预测步长、稀疏因子和最少数据点数。
        """
        super().__init__()
        self.look_back_window = 12  # 回看窗口长度（标准 Transformer 输入）
        self.forecast_horizon = 5  # 预测步长（生成式解码器一次生成）
        self.factor = 3  # ProbSparse因子（控制稀疏度：每个 query 保留的 key 数）
        self.min_data_points = 15  # 最少数据点数

    training_window = 10
    """训练窗口长度（时间步数）"""
    training_horizon = 3
    """预测步数"""

    def predict(self, video_data, threshold=100000):
        """预测到达目标播放量所需时间。

        优先使用 torch 模型推理，失败降级到 numpy。

        Args:
            video_data: 视频数据字典，含 view_count, history_data, bvid 等字段
            threshold: 目标播放量阈值，默认 100000

        Returns:
            PredictionResult 预测结果对象
        """
        return try_torch_predict(
            self,
            video_data,
            threshold,
            InformerTorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建训练用的 PyTorch 模型。

        Returns:
            InformerTorchModel 实例
        """
        return InformerTorchModel(in_features=getattr(self, '_training_n_features', 5), window=10, horizon=self.training_horizon)

    def get_training_features(self):
        """获取训练使用的特征列表。

        Returns:
            特征名称列表
        """
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """Numpy 降级预测 - Informer 核心实现。

        流程：
        1. 提取速度序列 → 2. ProbSparse 注意力 → 3. 自注意力蒸馏 →
        4. 趋势预测 + 速度估计

        Args:
            video_data: 视频数据字典，包含 history_data 列表
            threshold: 目标播放量阈值

        Returns:
            PredictionResult 预测结果
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        if len(history) < self.min_data_points:
            # 数据太少，退化为简单预测
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views,
                threshold,
                velocity,
                confidence=0.3,
                attention_weights=None,
                distilled_length=None,
                reason="insufficient_data",
            )

        # 提取时间序列
        views, timestamps = self._extract_series(history)

        if len(views) < self.min_data_points:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views,
                threshold,
                velocity,
                confidence=0.3,
                attention_weights=None,
                distilled_length=None,
                reason="short_series",
            )

        # 计算速度序列
        velocities, _ = self._calculate_velocity_series(views, timestamps)

        if len(velocities) < self.look_back_window:
            velocity = velocities[-1] if len(velocities) > 0 else 0.0
            return self._make_result(
                current_views,
                threshold,
                velocity,
                confidence=0.4,
                attention_weights=None,
                distilled_length=None,
                reason="short_velocity_series",
            )

        # Informer核心：ProbSparse注意力 + 蒸馏
        attention_weights, distilled = self._informer_forward(velocities)

        # 基于注意力加权的表示预测
        predicted_velocity, confidence = self._predict_from_attention(attention_weights, distilled, velocities)

        return self._make_result(
            current_views,
            threshold,
            predicted_velocity,
            confidence=confidence,
            attention_weights=attention_weights.tolist() if attention_weights is not None else None,
            distilled_length=len(distilled) if distilled is not None else None,
            reason="informer",
        )

    def _informer_forward(self, series: np.ndarray) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """Informer 前向传播（简化版）。

        取最后 look_back_window 个点作为输入，依次执行：
        1. ProbSparse 自注意力 → 2. 自注意力蒸馏。

        Args:
            series: 速度序列数组

        Returns:
            (注意力权重矩阵, 蒸馏后的序列)
        """
        if len(series) < self.look_back_window:
            return None, series

        # 取最后 look_back_window 个点
        if len(series) > self.look_back_window:
            input_series = series[-self.look_back_window :]
        else:
            input_series = series

        # ProbSparse自注意力（简化版）
        attention_weights = self._probsparse_attention(input_series)

        # 自注意力蒸馏（下采样）
        distilled = self._attention_distilling(input_series)

        return attention_weights, distilled

    def _probsparse_attention(self, series: np.ndarray) -> np.ndarray:
        """ProbSparse 自注意力（简化版 n×n 矩阵）。

        核心思想：不是所有注意力连接都需要计算，只保留每个 query 的 Top-K 个 key。

        简化版实现：
        1. 用序列本身直接构造 Q, K（省略线性变换）
        2. 计算 QK^T 点积得分
        3. 对每个 query，只保留 factor 个最高分 key 的 softmax 权重
        4. 其他位置的注意力权重为零（稀疏性）

        Args:
            series: 输入序列 [L]

        Returns:
            注意力权重矩阵 [L, L]（稀疏：每行仅有 factor 个非零元素）
        """
        n = len(series)
        if n < 2:
            return np.eye(n) if n > 0 else np.array([])

        # 构造Q, K, V（简化：使用序列本身，省略线性变换）
        # 实际Transformer中QKV是通过线性变换得到的，这里简化
        Q = series.reshape(-1, 1)
        K = series.reshape(-1, 1)
        series.reshape(-1, 1)  # V（虽未直接用到，但保留结构完整）

        # 计算注意力得分（点积）
        scores = np.dot(Q, K.T)  # shape: (n, n)

        # ProbSparse：只保留每个query的最重要的factor个key
        factor = min(self.factor, n)

        attention_weights = np.zeros((n, n))

        for i in range(n):
            # 第i个query对所有key的得分
            query_scores = scores[i, :]

            # 选择最重要的factor个
            topk_indices = np.argsort(query_scores)[-factor:]

            # 只对这些计算softmax
            topk_scores = query_scores[topk_indices]
            exp_scores = np.exp(topk_scores - np.max(topk_scores))
            softmax_topk = exp_scores / (np.sum(exp_scores) + 1e-6)

            attention_weights[i, topk_indices] = softmax_topk

        return attention_weights

    def _attention_distilling(self, series: np.ndarray) -> np.ndarray:
        """自注意力蒸馏（简化版）。

        通过最大池化下采样减少序列长度。
        在论文中，蒸馏层使用 Conv1d + ELU + MaxPool 对特征做压缩。

        简化版：每 2 步取局部最大值（最大池化），保留约一半长度。

        Args:
            series: 输入序列

        Returns:
            蒸馏后的序列（长度约为原来一半）
        """
        n = len(series)
        if n < 4:
            return series

        # 下采样率：保留约一半
        downsample_rate = 2

        # 最大池化（简化版注意力蒸馏）
        distilled = []
        for i in range(0, n - downsample_rate + 1, downsample_rate):
            # 取局部最大值作为蒸馏后的表示
            local_max = np.max(series[i : i + downsample_rate])
            distilled.append(local_max)

        return np.array(distilled)

    def _predict_from_attention(
        self, attention_weights: Optional[np.ndarray], distilled: Optional[np.ndarray], velocities: np.ndarray
    ) -> Tuple[float, float]:
        """基于注意力加权的表示进行预测。

        对蒸馏后的序列做一次多项式趋势拟合，
        结合最近速度做加权平均。

        Args:
            attention_weights: 注意力权重矩阵
            distilled: 蒸馏后的序列
            velocities: 原始速度序列

        Returns:
            (预测速度, 置信度)
        """
        if distilled is None or len(distilled) == 0:
            predicted_vel = velocities[-1]
            confidence = 0.4
            return max(predicted_vel, 0.0), confidence

        # 使用蒸馏后的序列预测
        # 简化：使用最近几个蒸馏值的趋势
        if len(distilled) >= 2:
            # 一次多项式趋势拟合
            x = np.arange(len(distilled))
            slope = np.polyfit(x, distilled, 1)[0]

            # 预测下一个值 = 最后值 + 趋势
            next_value = distilled[-1] + slope

            # 结合近期速度加权平均（最近速度占 70%）
            recent_vel = velocities[-1]

            # 加权平均（偏重近期实际速度）
            predicted_vel = 0.3 * next_value + 0.7 * recent_vel

            # 置信度：蒸馏后的序列越平滑，置信度越高
            if len(distilled) >= 3:
                smoothness = 1.0 / (np.std(distilled) + 1e-6)
                confidence = min(0.8, 0.5 + 0.1 * smoothness)
            else:
                confidence = 0.6
        else:
            predicted_vel = velocities[-1]
            confidence = 0.5

        return max(predicted_vel, 0.0), confidence

    def _extract_series(self, history: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """提取播放量和时间戳序列。

        按时间排序并过滤无效数据。

        Args:
            history: 历史数据列表

        Returns:
            (播放量数组, 时间戳数组)
        """
        views = []
        timestamps = []

        for entry in history:
            v = entry.get("view_count", entry.get("view", 0))
            t = entry.get("timestamp", 0)

            if hasattr(t, "timestamp"):
                t = t.timestamp()
            elif isinstance(t, str):
                try:
                    from datetime import datetime as dt

                    t = dt.fromisoformat(t).timestamp()
                except Exception:
                    continue

            if v > 0 and t > 0:
                views.append(float(v))
                timestamps.append(float(t))

        if len(views) > 1:
            sorted_indices = np.argsort(timestamps)  # 按时间排序
            views = [views[i] for i in sorted_indices]
            timestamps = [timestamps[i] for i in sorted_indices]

        return np.array(views), np.array(timestamps)

    def _calculate_velocity_series(self, views: np.ndarray, timestamps: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """计算速度序列。

        Args:
            views: 播放量数组
            timestamps: 时间戳数组

        Returns:
            (速度数组, 速度时间戳数组)
        """
        if len(views) < 2:
            return np.array([]), np.array([])

        velocities = []
        vel_times = []

        for i in range(1, len(views)):
            dt = (timestamps[i] - timestamps[i - 1]) / 3600.0
            if dt <= 0:
                continue
            dv = views[i] - views[i - 1]
            velocity = dv / dt
            velocities.append(velocity)
            vel_times.append(timestamps[i])

        return np.array(velocities), np.array(vel_times)

    def _make_result(
        self,
        current_views: int,
        threshold: int,
        velocity: float,
        confidence: float,
        attention_weights: Optional[List],
        distilled_length: Optional[int],
        reason: str,
    ) -> PredictionResult:
        """构造 PredictionResult 预测结果。

        Args:
            current_views: 当前播放量
            threshold: 目标播放量阈值
            velocity: 预测速度（每小时播放量）
            confidence: 置信度 [0, 1]
            attention_weights: 注意力权重矩阵（用于记录/调试）
            distilled_length: 蒸馏后序列长度
            reason: 预测原因标识

        Returns:
            PredictionResult 预测结果对象
        """

        if velocity <= 0:
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                predicted_hours = remaining / velocity

        metadata = {
            "reason": reason,
            "has_attention": attention_weights is not None,
            "distilled_length": distilled_length,
            "look_back_window": self.look_back_window,
            "factor": self.factor,
            "method": "informer_simplified",
        }

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata=metadata,
            timestamp=datetime.now(),
        )
