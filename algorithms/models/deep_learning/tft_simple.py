"""
TFT简化版 (Temporal Fusion Transformer Simplified)
===================================================

Google Cloud AI 2019论文的简化实现——结合静态/动态特征的多步时序预测模型，
提供可解释性的预测结果，用于B站视频播放量增长预测。

核心原理:
    1. 变量选择网络（VSN）：为每个输入特征计算重要性权重，过滤无关特征
    2. 门控残差网络（GRN）：使用GLU门控机制 + 残差连接处理特征交互
    3. 可解释多头注意力：在时间维度上计算自注意力，识别重要的历史时间点
    4. 静态/动态融合：同时利用静态特征（标题类型）和动态特征（速度、互动率）

简化版实现：
    - VSN: 使用绝对值代替神经网络学习的权重
    - GRN: 使用sigmoid门控代替GLU
    - 注意力: 仅在特征维度上计算注意力（非时间维度）

降级链：torch checkpoint（TFTTorchModel） → numpy特征选择 + 门控 + 注意力

参考论文：
    "Temporal Fusion Transformers for Interpretable Multi-horizon Time Series Forecasting"
    (Lim et al., International Journal of Forecasting, 2021)
"""

import numpy as np
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import TFTTorchModel, try_torch_predict


class TFTSimpleAlgorithm(BaseAlgorithm):
    """TFT简化版算法

    核心思路（简化）：
    1. 特征加权（模拟变量选择网络）
    2. 门控残差网络（模拟GRN）
    3. 可解释多头注意力（模拟时态自注意力）
    4. 融合静态和动态特征

    论文：Temporal Fusion Transformers for Interpretable Multi-horizon Time Series Forecasting
    (Goold et al., 2019)
    """

    name = "TFT简化版"
    algorithm_id = "tft_simple"
    description = "结合静态/动态特征，提供可解释性的预测"
    category = "Transformer模型"
    default_weight = 1.4

    def __init__(self):
        """初始化TFT算法参数

        设置回看窗口、预测步长和注意力头数等超参数。
        """
        super().__init__()
        self.look_back_window = 12     # 回看窗口长度（输入序列长度）
        self.forecast_horizon = 5      # 预测步长（输出序列长度）
        self.num_heads = 2             # 注意力头数
        self.min_data_points = 15      # 最少需要的数据点数

    training_window = 10     # 训练时使用的历史窗口长度
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
            self,
            video_data,
            threshold,
            TFTTorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建TFT PyTorch模型实例"""
        return TFTTorchModel(in_features=getattr(self, '_training_n_features', 5), horizon=self.training_horizon)

    def get_training_features(self):
        """返回训练时使用的多维特征列表"""
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """执行TFT预测（numpy实现）

        TFT核心流程：
        1. 提取特征向量（速度统计 + 互动率 + 视频年龄 + 标题类型）
        2. 变量选择网络：softmax归一化各特征的重要性
        3. 门控残差网络：sigmoid门控 + 残差连接
        4. 时态自注意力：计算特征之间的注意力得分
        5. 基于TFT输出融合近期速度做最终预测

        Args:
            video_data: 视频数据，包含 history_data 列表
            threshold: 目标播放量阈值

        Returns:
            PredictionResult
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        # 数据不足时退化为简单预测
        if len(history) < self.min_data_points:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views,
                threshold,
                velocity,
                confidence=0.3,
                feature_weights=None,
                attention_weights=None,
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
                feature_weights=None,
                attention_weights=None,
                reason="short_series",
            )

        # 计算速度和特征
        velocities, _ = self._calculate_velocity_series(views, timestamps)

        if len(velocities) < self.look_back_window:
            velocity = velocities[-1] if len(velocities) > 0 else 0.0
            return self._make_result(
                current_views,
                threshold,
                velocity,
                confidence=0.4,
                feature_weights=None,
                attention_weights=None,
                reason="short_velocity_series",
            )

        # TFT核心流程：特征选择 → 门控 → 注意力 → 预测
        features = self._extract_features(video_data, velocities)              # 提取多维特征
        feature_weights = self._variable_selection(features)                    # 变量选择网络
        gated_output = self._gated_residual_network(features, feature_weights)  # 门控残差网络
        attention_output, attention_weights = self._temporal_self_attention(gated_output)  # 时态自注意力

        # 预测
        predicted_velocity, confidence = self._predict_from_tft(attention_output, features, velocities)

        return self._make_result(
            current_views,
            threshold,
            predicted_velocity,
            confidence=confidence,
            feature_weights=feature_weights,
            attention_weights=attention_weights,
            reason="tft",
        )

    def _extract_features(self, video_data: Dict, velocities: np.ndarray) -> np.ndarray:
        """提取特征（简化版）

        将视频数据转换为特征向量：
        1. 速度统计特征（均值、标准差、最近速度、最早速度）
        2. 互动率特征（参与度、质量分）
        3. 视频年龄特征（发布至今的小时数）
        4. 静态特征（根据标题关键词判断视频类型）

        Args:
            video_data: 视频数据字典
            velocities: 速度序列

        Returns:
            np.ndarray: 特征向量（8维）
        """
        features = []

        # 速度统计特征（4维）
        if len(velocities) > 0:
            features.extend(
                [
                    np.mean(velocities),                                   # 平均速度
                    np.std(velocities) if len(velocities) > 1 else 0.0,    # 速度标准差
                    velocities[-1],                                        # 最近速度（最重要）
                    velocities[0] if len(velocities) > 0 else 0.0,         # 最早速度
                ]
            )
        else:
            features.extend([0.0, 0.0, 0.0, 0.0])

        # 互动率特征（2维）
        engagement = self.get_engagement_rate(video_data)  # 互动率（点赞+投币+收藏/播放量）
        quality = self.get_quality_score(video_data)       # 综合质量评分
        features.extend([engagement, quality])

        # 视频年龄特征（1维）
        age_hours = self.get_video_age_hours(video_data)   # 视频发布至今的小时数
        features.append(age_hours)

        # 静态特征：根据标题关键词判断视频类型（1维）
        title = video_data.get("title", "")
        if "教程" in title or "教学" in title:
            video_type = 0.0    # 教程类（增长较慢但持久）
        elif "搞笑" in title or "搞怪" in title:
            video_type = 1.0    # 搞笑类（短期爆发强）
        elif "音乐" in title or "MV" in title:
            video_type = 2.0    # 音乐类（中毒性传播）
        else:
            video_type = 3.0    # 其他类型
        features.append(video_type)

        return np.array(features)

    def _variable_selection(self, features: np.ndarray) -> np.ndarray:
        """变量选择网络（简化版）

        为每个特征计算重要性权重。
        简化：使用特征的绝对值作为重要性代理（实际TFT使用神经网络学习权重）。

        Args:
            features: 特征向量

        Returns:
            np.ndarray: softmax归一化后的特征权重（和=1）
        """
        if len(features) == 0:
            return np.array([])

        # 简化：使用特征的绝对值作为重要性代理
        # 实际TFT使用神经网络（带GRN）学习权重
        importance = np.abs(features) + 1e-6  # 防止零值

        # Softmax归一化（数值稳定版）
        exp_importance = np.exp(importance - np.max(importance))
        weights = exp_importance / (np.sum(exp_importance) + 1e-6)

        return weights

    def _gated_residual_network(self, features: np.ndarray, weights: np.ndarray) -> np.ndarray:
        """门控残差网络（简化版）

        模拟GRN的门控机制：
        1. 应用特征权重
        2. 通过sigmoid门控（模拟GLU的非线性门控）
        3. 残差连接：保留原始特征的10%

        Args:
            features: 特征向量
            weights: 特征重要性权重

        Returns:
            np.ndarray: 门控+残差后的输出
        """
        if len(features) == 0:
            return np.array([])

        # 应用特征权重：赋权后的特征
        weighted_features = features * weights

        # 门控线性单元（GLU）简化版
        # 实际TFT使用：GLU(x) = (W1*x + b1) ⊗ sigmoid(W2*x + b2)
        # 简化：使用sigmoid门控（值域[0,1]，模拟信息过滤）
        gate = 1.0 / (1.0 + np.exp(-weighted_features))   # sigmoid
        gated = weighted_features * gate                   # 门控输出

        # 残差连接：输出 = 门控输出 + 0.1×原始特征
        # 保证即使门控关闭，仍有小部分原始信息通过
        output = gated + features * 0.1

        return output

    def _temporal_self_attention(self, features: np.ndarray) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """时态自注意力（简化版）

        模拟TFT的可解释多头注意力：
        将特征视为序列（每个特征是一个"时间步"），
        计算特征间的自注意力以捕捉跨特征交互。

        Args:
            features: 特征向量

        Returns:
            (注意力加权输出, 注意力权重矩阵)
        """
        if len(features) == 0:
            return features, None

        # 将特征视为序列（简化：每个特征是一个"时间步"）
        # 实际TFT的注意力是在时间维度上计算的

        # 构造Q, K, V（使用特征本身，模拟自注意力）
        Q = features.reshape(-1, 1)
        K = features.reshape(-1, 1)
        V = features.reshape(-1, 1)

        # 计算注意力得分矩阵（Q·K^T）
        scores = np.dot(Q, K.T)

        # Softmax（沿K维度归一化）
        exp_scores = np.exp(scores - np.max(scores))           # 数值稳定
        attention_weights = exp_scores / (np.sum(exp_scores, axis=-1, keepdims=True) + 1e-6)

        # 加权求和得到注意力输出
        attended = np.dot(attention_weights, V)

        return attended.flatten(), attention_weights

    def _predict_from_tft(
        self, tft_output: np.ndarray, features: np.ndarray, velocities: np.ndarray
    ) -> Tuple[float, float]:
        """基于TFT输出预测未来速度

        TFT输出与近期速度做加权融合，TFT输出的方差反映预测可信度。

        Args:
            tft_output: TFT注意力层输出
            features: 原始特征向量
            velocities: 历史速度序列

        Returns:
            (预测速度, 置信度)
        """
        if len(tft_output) == 0:
            predicted_vel = velocities[-1] if len(velocities) > 0 else 0.0
            confidence = 0.3
            return max(predicted_vel, 0.0), confidence

        # 使用TFT输出的均值作为预测
        predicted_vel = np.mean(tft_output)

        # 结合近期速度做混合预测（TFT预测:近期速度 = 3:7）
        recent_vel = velocities[-1] if len(velocities) > 0 else 0.0

        # 加权平均：TFT输出提供全局视图，近期速度提供局部精度
        final_vel = 0.3 * predicted_vel + 0.7 * recent_vel

        # 置信度：TFT输出方差越小（特征间越一致），置信度越高
        if len(tft_output) > 1:
            variance = np.var(tft_output)
            confidence = max(0.3, 1.0 - variance)
        else:
            confidence = 0.5

        return max(final_vel, 0.0), min(confidence, 0.9)

    def _extract_series(self, history: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """提取播放量和时间戳序列

        从历史记录中提取播放量和时间戳，按时间排序。

        Args:
            history: 历史数据记录列表

        Returns:
            (播放量数组, 时间戳数组)
        """
        views = []
        timestamps = []

        for entry in history:
            v = entry.get("view_count", entry.get("view", 0))
            t = entry.get("timestamp", 0)

            # 统一时间戳格式
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

        # 按时间排序
        if len(views) > 1:
            sorted_indices = np.argsort(timestamps)
            views = [views[i] for i in sorted_indices]
            timestamps = [timestamps[i] for i in sorted_indices]

        return np.array(views), np.array(timestamps)

    def _calculate_velocity_series(self, views: np.ndarray, timestamps: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """计算速度序列（每小时播放量变化）

        Args:
            views: 播放量数组
            timestamps: 时间戳数组

        Returns:
            (速度数组, 对应的时间戳数组)
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
        feature_weights: Optional[List[float]],
        attention_weights: Optional[List[List[float]]],
        reason: str,
    ) -> PredictionResult:
        """构造预测结果

        Args:
            current_views: 当前播放量
            threshold: 目标阈值
            velocity: 预测速度（每小时）
            confidence: 置信度 [0, 1]
            feature_weights: 特征重要性权重
            attention_weights: 注意力权重矩阵
            reason: 预测来源标识

        Returns:
            PredictionResult: 标准化预测结果
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
            "has_feature_weights": feature_weights is not None,
            "has_attention": attention_weights is not None,
            "look_back_window": self.look_back_window,
            "forecast_horizon": self.forecast_horizon,
            "method": "tft_simplified",
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
