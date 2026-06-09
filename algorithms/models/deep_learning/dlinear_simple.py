"""
DLinear简化版 (DLinear Simplified — Decomposition Linear)
简单但有效的线性模型，在某些时序预测任务上超越 Transformer。

核心思路（简化版）：
1. 将序列分解为趋势分量和剩余（季节）分量
2. 对两个分量分别使用线性映射（一次多项式拟合）预测未来值
3. 叠加趋势预测 + 剩余预测 → 最终预测

论文：Are Transformers Effective for Time Series Forecasting? (AAAI 2023)
该论文颠覆性地证明了简单的线性模型在某些标准时序 benchmark 上优于复杂 Transformer。

为什么"简单"能赢？
- 时序预测的核心问题是趋势外推，不需要复杂的非线性变换
- Transformer 的注意力机制在短序列上反而可能引入噪声
- DLinear 的分解策略让模型只需学习"趋势"和"波动"两个简单分量
"""

import numpy as np
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import DLinearTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class DLinearSimpleAlgorithm(BaseAlgorithm):
    """DLinear简化版算法

    核心思路（简化）：
    1. 将序列分解为趋势分量和剩余分量
    2. 对两个分量分别使用线性映射
    3. 叠加得到最终预测

    论文：Are Transformers Effective for Time Series Forecasting? (AAAI 2023)

    降级链：torch checkpoint → numpy 分解+线性 → velocity 兜底
    """

    name = "DLinear简化版"
    algorithm_id = "dlinear_simple"
    description = "简单但有效的线性模型，分解为趋势和剩余分量"
    category = "线性模型"
    default_weight = 1.6

    def __init__(self):
        """初始化 DLinear 算法。

        设置回看窗口、预测步长、最少数据点数和移动平均核大小。
        """
        super().__init__()
        self.lookback_window = 8  # 回看窗口长度
        self.forecast_horizon = 5  # 预测步长
        self.min_data_points = 10  # 最少需要的序列长度
        self.decomposition_kernel = 3  # 移动平均核大小（用于趋势-季节分解）

    training_window = 10
    """训练窗口长度（时间步数）"""
    training_horizon = 3
    """预测步数"""

    def predict(self, video_data, threshold=100000):
        """预测到达目标播放量所需时间。

        优先使用 torch 模型推理，失败降级到 numpy 分解+线性。

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
            DLinearTorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建训练用的 PyTorch 模型。

        Returns:
            DLinearTorchModel 实例
        """
        return DLinearTorchModel(in_features=getattr(self, '_training_n_features', 5), window=10, horizon=self.training_horizon)

    def get_training_features(self):
        """获取训练使用的特征列表。

        Returns:
            特征名称列表
        """
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """Numpy 降级预测 - DLinear 核心实现。

        流程：
        1. 提取速度序列 → 2. 趋势/季节分解 → 3. 各分量线性预测 →
        4. 叠加 → 5. 置信度评估

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
                trend_coeffs=None,
                residual_mean=0.0,
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
                trend_coeffs=None,
                residual_mean=0.0,
                reason="short_series",
            )

        # 计算速度序列
        velocities, _ = self._calculate_velocity_series(views, timestamps)

        if len(velocities) < self.lookback_window:
            # 数据不够回看窗口
            avg_vel = np.mean(velocities) if len(velocities) > 0 else 10.0
            return self._make_result(
                current_views,
                threshold,
                avg_vel,
                confidence=0.4,
                trend_coeffs=None,
                residual_mean=0.0,
                reason="insufficient_lookback",
            )

        # DLinear核心：分解 + 线性映射
        trend, residual = self._decompose(velocities)

        # 对趋势分量进行线性预测
        trend_forecast = self._linear_forecast(trend)

        # 对剩余分量进行线性预测
        residual_forecast = self._linear_forecast(residual)

        # 叠加趋势 + 剩余
        combined_forecast = trend_forecast + residual_forecast

        # 取最后一个预测值作为最终速度
        if len(combined_forecast) > 0:
            predicted_velocity = combined_forecast[-1]
        else:
            predicted_velocity = velocities[-1]

        # 计算置信度
        confidence = self._calculate_confidence(velocities, combined_forecast)

        return self._make_result(
            current_views,
            threshold,
            predicted_velocity,
            confidence=confidence,
            trend_coeffs=np.polyfit(range(len(trend)), trend, 1).tolist() if len(trend) > 1 else None,
            residual_mean=float(np.mean(residual)),
            reason="dlinear",
        )

    def _decompose(self, series: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """分解序列为趋势分量和剩余（季节）分量。

        使用移动平均（卷积）提取趋势，剩余 = 原始 − 趋势。
        这是 DLinear 的核心步骤：趋势捕获低频信号，季节捕获高频波动。

        Args:
            series: 一维序列数组

        Returns:
            (趋势分量, 剩余分量) 元组
        """
        if len(series) < self.decomposition_kernel:
            # 序列太短，不分解（返回原始为趋势，零为剩余）
            return series.copy(), np.zeros_like(series)

        # 移动平均提取趋势（低频分量）
        kernel = np.ones(self.decomposition_kernel) / self.decomposition_kernel
        trend = np.convolve(series, kernel, mode="same")

        # 剩余分量 = 原始 − 趋势（高频分量，如日周期、突发）
        residual = series - trend

        return trend, residual

    def _linear_forecast(self, series: np.ndarray) -> np.ndarray:
        """线性预测（简化版）。

        使用一次多项式（线性回归）拟合历史序列，外推未来值。
        DLinear 的核心思想是"线性就足够好了"。

        Args:
            series: 历史序列数组

        Returns:
            预测的未来值数组 [forecast_horizon]
        """
        if len(series) < 2:
            return np.array([series[0] if len(series) > 0 else 0.0] * self.forecast_horizon)

        # 一次多项式拟合（线性回归）
        x = np.arange(len(series))
        coeffs = np.polyfit(x, series, 1)

        # 外推预测
        future_x = np.arange(len(series), len(series) + self.forecast_horizon)
        forecast = np.polyval(coeffs, future_x)

        return forecast

    def _calculate_confidence(self, series: np.ndarray, forecast: np.ndarray) -> float:
        """计算预测置信度（简化交叉验证）。

        用大步长扫描（最多约 8 次 polyfit）评估历史拟合误差，
        避免遍历所有点造成 O(n²) 复杂度。

        Args:
            series: 历史序列
            forecast: 预测序列（未直接使用，保留接口兼容）

        Returns:
            置信度 [0.3, 0.9]
        """
        if len(forecast) == 0:
            return 0.3

        # 基于历史拟合误差，使用大步长扫描减少 polyfit 调用次数
        if len(series) >= self.lookback_window // 2:
            errors = []
            step = max(1, len(series) // 8)  # 最多约8次polyfit
            for i in range(step, min(len(series), self.lookback_window), step):
                if i >= 2:
                    x = np.arange(i)
                    y = series[:i]
                    try:
                        coeffs = np.polyfit(x, y, 1)
                        # 用后一半点做验证
                        split = i // 2
                        pred = np.polyval(coeffs, np.arange(split, i))
                        actual = y[split:]
                        # 对称平均绝对百分比误差
                        errors.append(np.mean(np.abs(pred - actual) / (np.abs(actual) + 1e-6)))
                    except Exception as e:
                        logger.debug("DLinear置信度计算失败: %s", e)

            if errors:
                confidence = max(0.3, 1.0 - np.mean(errors))  # 误差越小置信度越高
            else:
                confidence = 0.5
        else:
            confidence = 0.4

        return min(0.9, confidence)

    def _extract_series(self, history: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """提取播放量和时间戳序列。

        按时间排序确保序列按时间推进。

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
        """计算速度序列（每小时播放量增量）。

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
            dt = (timestamps[i] - timestamps[i - 1]) / 3600.0  # 转换为小时
            if dt <= 0:
                continue
            dv = views[i] - views[i - 1]  # 播放量增量
            velocity = dv / dt  # 每小时速度
            velocities.append(velocity)
            vel_times.append(timestamps[i])

        return np.array(velocities), np.array(vel_times)

    def _make_result(
        self,
        current_views: int,
        threshold: int,
        velocity: float,
        confidence: float,
        trend_coeffs: Optional[List[float]],
        residual_mean: float,
        reason: str,
    ) -> PredictionResult:
        """构造 PredictionResult 预测结果。

        Args:
            current_views: 当前播放量
            threshold: 目标播放量阈值
            velocity: 预测速度（每小时播放量）
            confidence: 置信度 [0, 1]
            trend_coeffs: 趋势多项式系数列表
            residual_mean: 剩余分量均值
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
            "trend_slope": trend_coeffs[0] if trend_coeffs and len(trend_coeffs) > 0 else 0.0,
            "residual_mean": residual_mean,
            "lookback_window": self.lookback_window,
            "forecast_horizon": self.forecast_horizon,
            "method": "dlinear_simplified",
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
