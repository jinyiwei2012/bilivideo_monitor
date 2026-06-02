"""
N-BEATS简化版 (Neural Basis Expansion Analysis for Time Series Forecasting)
============================================================================

ICLR 2020论文的简化实现，使用基函数展开捕捉时序模式，用于B站视频播放量增长预测。

核心原理:
    1. 双重残差结构：每个Block输出backcast（回看拟合）和forecast（未来预测）
    2. 趋势分解：Block 1使用多项式基函数捕捉趋势分量
    3. 季节性分解：Block 2使用傅里叶基函数（正弦/余弦）捕捉周期分量
    4. 残差分量：去除趋势和季节后剩余的随机波动
    5. 层叠架构：多个Block通过残差连接级联，每层预测一层残差

简化版实现：
    - 趋势Block：polyfit一阶线性拟合 + 外推
    - 季节Block：FFT提取主要频率分量
    - 残差Block：简单均值外推

降级链：torch checkpoint（NBeatsTorchModel） → numpy多Block分解

参考论文：
    "N-BEATS: Neural basis expansion analysis for interpretable time series forecasting"
    (Oreshkin et al., ICLR 2020)

原始代码已有详细中文注释，此处仅增强模块级文档。
"""

import numpy as np
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import NBeatsTorchModel, try_torch_predict


class NBeatsSimpleAlgorithm(BaseAlgorithm):
    """N-BEATS简化版算法

    核心思路（简化）：
    1. 使用多层全连接网络
    2. 网络输出被分解为"趋势"和"季节性"分量
    3. 各分量分别预测，最后叠加

    论文：N-BEATS: Neural basis expansion analysis for interpretable time series forecasting
    (ICLR 2020, Oreshkin et al.)
    """

    name = "N-BEATS简化版"
    algorithm_id = "n_beats_simple"
    description = "使用基函数展开捕捉时序模式，分解为趋势和季节性分量"
    category = "深度学习"
    default_weight = 1.5

    def __init__(self):
        """初始化N-BEATS算法参数

        设置神经网络架构参数：回看窗口、预测步长、Block数量和每层数。
        """
        super().__init__()
        self.lookback_window = 10      # 回看窗口长度（输入序列长度）
        self.forecast_horizon = 5      # 预测步长（输出序列长度）
        self.hidden_size = 16          # 隐藏层大小（简化版用较小值）
        self.num_blocks = 2            # Block数量（趋势+季节）
        self.num_layers = 2            # 每个Block的层数
        self.min_data_points = 12      # 最少需要的序列长度

    training_window = 10     # 训练时使用的历史窗口长度
    training_horizon = 3     # 训练时预测的未来步数

    def predict(self, video_data, threshold=100000):
        """执行预测

        优先使用torch模型，否则回退到numpy实现。

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
            NBeatsTorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建N-BEATS PyTorch模型实例"""
        return NBeatsTorchModel(in_features=getattr(self, '_training_n_features', 5), window=10, horizon=self.training_horizon)

    def get_training_features(self):
        """返回训练时使用的多维特征列表"""
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """执行预测

        Args:
            video_data: 视频数据，包含 history_data 列表
            threshold: 目标播放量阈值

        Returns:
            PredictionResult
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        # 数据不足时退化为简单线性预测
        if len(history) < self.min_data_points:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views,
                threshold,
                velocity,
                confidence=0.3,
                trend_slope=0.0,
                seasonality=None,
                residual=None,
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
                trend_slope=0.0,
                seasonality=None,
                residual=None,
                reason="short_series",
            )

        # 计算速度序列（使用速度作为输入特征，更稳定）
        velocities, _ = self._calculate_velocity_series(views, timestamps)

        if len(velocities) < self.lookback_window:
            # 数据不够回看窗口，使用平均速度
            avg_vel = np.mean(velocities) if len(velocities) > 0 else 10.0
            return self._make_result(
                current_views,
                threshold,
                avg_vel,
                confidence=0.4,
                trend_slope=0.0,
                seasonality=None,
                residual=None,
                reason="insufficient_lookback",
            )

        # N-BEATS核心：分block预测趋势、季节和残差分量
        trend_forecast, seasonality_forecast, residual_forecast = self._n_beats_forecast(velocities)

        # 组合三个分量的预测结果
        combined_forecast = trend_forecast + seasonality_forecast + residual_forecast

        # 取最后一个预测值作为未来速度
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
            trend_slope=(
                float(np.polyfit(range(len(trend_forecast)), trend_forecast, 1)[0]) if len(trend_forecast) > 1 else 0.0
            ),
            seasonality=seasonality_forecast.tolist() if len(seasonality_forecast) > 0 else None,
            residual=residual_forecast.tolist() if len(residual_forecast) > 0 else None,
            reason="n_beats",
        )

    def _n_beats_forecast(self, series: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """N-BEATS预测核心（简化版）

        每个block输出：
        1. 回看分量（用于分解输入）
        2. 预测分量（未来预测）

        简化版：
        - Block 1: 趋势分量
        - Block 2: 季节性分量
        - 剩余：残差分量

        Returns:
            (趋势预测, 季节性预测, 残差预测)
        """
        # 取最后 lookback_window 个点作为输入
        if len(series) > self.lookback_window:
            input_series = series[-self.lookback_window :]
        else:
            input_series = series

        # Block 1: 趋势分量（使用线性趋势拟合 + 外推）
        trend_coeffs = np.polyfit(range(len(input_series)), input_series, 1)
        trend_line = np.polyval(trend_coeffs, np.arange(len(input_series) + self.forecast_horizon))
        trend_lookback = trend_line[: len(input_series)]    # 回看部分的趋势拟合
        trend_forecast = trend_line[len(input_series) :]    # 预测部分的趋势外推

        # 去除趋势得到残差
        detrended = input_series - trend_lookback

        # Block 2: 季节性分量（使用FFT频域分析提取周期模式）
        seasonality_lookback = self._extract_seasonality(detrended)
        # 预测未来季节性（假设周期性延续）
        if len(seasonality_lookback) > 0:
            seasonality_forecast = self._forecast_seasonality(seasonality_lookback, self.forecast_horizon)
        else:
            seasonality_forecast = np.zeros(self.forecast_horizon)

        # 残差分量：去除趋势和季节后的剩余
        residual = detrended - seasonality_lookback
        # 残差预测（使用简单均值作为未来值的估计）
        residual_forecast = np.full(self.forecast_horizon, np.mean(residual) if len(residual) > 0 else 0.0)

        return trend_forecast, seasonality_forecast, residual_forecast

    def _extract_seasonality(self, series: np.ndarray) -> np.ndarray:
        """提取季节性分量（简化版）

        使用FFT快速傅里叶变换提取主要频率分量，保留前20%的频率。
        如果FFT失败则返回零向量。

        Args:
            series: 输入序列

        Returns:
            np.ndarray: 季节性分量（与输入同长度）
        """
        if len(series) < 4:
            return np.array([])

        # 简化：假设周期为4（对应4个数据点一个周期）
        period = min(4, len(series) // 2)
        if period < 2:
            return np.array([])

        # 使用正弦拟合简化版
        np.arange(len(series))
        # 简单季节性：用移动平均去除后取残差
        try:
            from numpy.fft import rfft, irfft

            # 使用FFT提取主要频率分量（简化）
            fft = rfft(series)
            # 保留前20%的频率分量，滤除高频噪声
            keep = max(1, len(fft) // 5)
            fft_filtered = np.zeros_like(fft, dtype=complex)
            fft_filtered[:keep] = fft[:keep]
            seasonality = irfft(fft_filtered, n=len(series))
            return seasonality
        except Exception:
            # FFT失败，返回零
            return np.zeros(len(series))

    def _forecast_seasonality(self, seasonality: np.ndarray, horizon: int) -> np.ndarray:
        """预测未来季节性

        简化：假设最后一个周期会重复，将最近的周期模式平铺到预测步长。

        Args:
            seasonality: 历史季节性分量
            horizon: 预测步长

        Returns:
            np.ndarray: 未来季节性预测（长度=horizon）
        """
        if len(seasonality) == 0:
            return np.zeros(horizon)

        # 取最后 period 个值作为周期模式
        period = min(4, len(seasonality))
        pattern = seasonality[-period:]

        # 重复模式以覆盖预测步长
        repeats = (horizon + period - 1) // period
        forecast = np.tile(pattern, repeats)[:horizon]

        return forecast

    def _calculate_confidence(self, series: np.ndarray, forecast: np.ndarray) -> float:
        """计算预测置信度

        基于历史预测误差估计置信度：
        用前i个点预测第i+1个点（简易交叉验证），计算MAE并映射到[0.3, 0.9]。

        Args:
            series: 历史速度序列
            forecast: 预测序列

        Returns:
            float: 置信度 [0.3, 0.9]
        """
        if len(forecast) == 0:
            return 0.3

        # 基于历史误差估计（简化交叉验证）
        if len(series) >= self.lookback_window:
            errors = []
            for i in range(1, min(len(series), self.lookback_window)):
                # 用前i个点预测第i+1个点（简单线性外推）
                if i >= 2:
                    slope = (series[-i + 1] - series[-i]) / 1.0
                    pred = series[-i + 1] + slope
                    error = abs(pred - series[-i + 1]) / (series[-i + 1] + 1e-6)
                    errors.append(error)

            if errors:
                mae = np.mean(errors)
                confidence = max(0.3, 1.0 - mae)
            else:
                confidence = 0.5
        else:
            confidence = 0.4

        return min(0.9, confidence)

    def _extract_series(self, history: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """提取播放量和时间戳序列

        从历史记录中提取播放量和时间戳，支持多种时间戳格式（float、datetime对象、ISO字符串），
        按时间排序确保序列时间顺序正确。

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
        """计算速度序列

        向前差分计算每两个相邻时间点之间的播放量增长速率（每小时）。

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
            dt = (timestamps[i] - timestamps[i - 1]) / 3600.0  # 转换为小时
            if dt <= 0:
                continue
            dv = views[i] - views[i - 1]                       # 播放量变化
            velocity = dv / dt                                  # 每小时速度
            velocities.append(velocity)
            vel_times.append(timestamps[i])

        return np.array(velocities), np.array(vel_times)

    def _make_result(
        self,
        current_views: int,
        threshold: int,
        velocity: float,
        confidence: float,
        trend_slope: float,
        seasonality: Optional[List[float]],
        residual: Optional[List[float]],
        reason: str,
    ) -> PredictionResult:
        """构造预测结果

        Args:
            current_views: 当前播放量
            threshold: 目标阈值
            velocity: 预测速度（每小时）
            confidence: 置信度 [0, 1]
            trend_slope: 趋势斜率
            seasonality: 季节性分量序列
            residual: 残差分量序列
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
            "trend_slope": trend_slope,
            "has_seasonality": seasonality is not None,
            "has_residual": residual is not None,
            "lookback_window": self.lookback_window,
            "forecast_horizon": self.forecast_horizon,
            "method": "n_beats_simplified",
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
