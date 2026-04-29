"""
DLinear简化版 (DLinear Simplified)
简单但有效的线性模型，在某些任务上超越Transformer
"""

import numpy as np
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class DLinearSimpleAlgorithm(BaseAlgorithm):
    """DLinear简化版算法
    
    核心思路（简化）：
    1. 将序列分解为趋势分量和剩余分量
    2. 对两个分量分别使用线性映射
    3. 叠加得到最终预测
    
    论文：Are Transformers Effective for Time Series Forecasting? (AAAI 2023)
    """
    
    name = "DLinear简化版"
    algorithm_id = "dlinear_simple"
    description = "简单但有效的线性模型，分解为趋势和剩余分量"
    category = "线性模型"
    default_weight = 1.6
    
    def __init__(self):
        super().__init__()
        self.lookback_window = 10   # 回看窗口长度
        self.forecast_horizon = 5    # 预测步长
        self.min_data_points = 12      # 最少需要的序列长度
        self.decomposition_kernel = 3   # 移动平均核大小
        
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测
        
        Args:
            video_data: 视频数据，包含 history_data 列表
            threshold: 目标播放量阈值
            
        Returns:
            PredictionResult
        """
        current_views = video_data.get('view_count', 0)
        history = video_data.get('history_data', [])
        
        if len(history) < self.min_data_points:
            # 数据太少，退化为简单预测
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.3,
                trend_coeffs=None,
                residual_mean=0.0,
                reason='insufficient_data'
            )
        
        # 提取时间序列
        views, timestamps = self._extract_series(history)
        
        if len(views) < self.min_data_points:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.3,
                trend_coeffs=None,
                residual_mean=0.0,
                reason='short_series'
            )
        
        # 计算速度序列
        velocities, _ = self._calculate_velocity_series(views, timestamps)
        
        if len(velocities) < self.lookback_window:
            # 数据不够回看窗口
            avg_vel = np.mean(velocities) if len(velocities) > 0 else 10.0
            return self._make_result(
                current_views, threshold, avg_vel,
                confidence=0.4,
                trend_coeffs=None,
                residual_mean=0.0,
                reason='insufficient_lookback'
            )
        
        # DLinear核心：分解 + 线性映射
        trend, residual = self._decompose(velocities)
        
        # 对趋势分量进行线性预测
        trend_forecast = self._linear_forecast(trend)
        
        # 对剩余分量进行线性预测
        residual_forecast = self._linear_forecast(residual)
        
        # 叠加
        combined_forecast = trend_forecast + residual_forecast
        
        # 取最后一个预测值
        if len(combined_forecast) > 0:
            predicted_velocity = combined_forecast[-1]
        else:
            predicted_velocity = velocities[-1]
        
        # 计算置信度
        confidence = self._calculate_confidence(velocities, combined_forecast)
        
        return self._make_result(
            current_views, threshold, predicted_velocity,
            confidence=confidence,
            trend_coeffs=np.polyfit(range(len(trend)), trend, 1).tolist() if len(trend) > 1 else None,
            residual_mean=float(np.mean(residual)),
            reason='dlinear'
        )
    
    def _decompose(self, series: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """分解序列为趋势分量和剩余分量
        
        使用移动平均提取趋势，剩余作为残差
        """
        if len(series) < self.decomposition_kernel:
            # 序列太短，不分解
            return series.copy(), np.zeros_like(series)
        
        # 移动平均提取趋势
        kernel = np.ones(self.decomposition_kernel) / self.decomposition_kernel
        trend = np.convolve(series, kernel, mode='same')
        
        # 剩余分量
        residual = series - trend
        
        return trend, residual
    
    def _linear_forecast(self, series: np.ndarray) -> np.ndarray:
        """线性预测（简化版）
        
        使用线性回归预测未来值
        """
        if len(series) < 2:
            return np.array([series[0] if len(series) > 0 else 0.0] * self.forecast_horizon)
        
        # 线性回归
        x = np.arange(len(series))
        coeffs = np.polyfit(x, series, 1)
        
        # 预测未来
        future_x = np.arange(len(series), len(series) + self.forecast_horizon)
        forecast = np.polyval(coeffs, future_x)
        
        return forecast
    
    def _calculate_confidence(self, series: np.ndarray, forecast: np.ndarray) -> float:
        """计算预测置信度"""
        if len(forecast) == 0:
            return 0.3
        
        # 基于历史拟合误差
        if len(series) >= self.lookback_window:
            # 使用交叉验证思想
            errors = []
            for i in range(1, min(len(series), self.lookback_window)):
                if i >= 2:
                    # 用前i-1个点拟合，预测第i个点
                    x = np.arange(i - 1)
                    y = series[:i-1]
                    try:
                        coeffs = np.polyfit(x, y, 1)
                        pred = np.polyval(coeffs, i - 1)
                        error = abs(pred - series[i-1]) / (series[i-1] + 1e-6)
                        errors.append(error)
                    except:
                        pass
            
            if errors:
                mae = np.mean(errors)
                confidence = max(0.3, 1.0 - mae)
            else:
                confidence = 0.5
        else:
            confidence = 0.4
        
        return min(0.9, confidence)
    
    def _extract_series(self, history: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """提取播放量和时间戳序列"""
        views = []
        timestamps = []
        
        for entry in history:
            v = entry.get('view_count', entry.get('view', 0))
            t = entry.get('timestamp', 0)
            
            if hasattr(t, 'timestamp'):
                t = t.timestamp()
            elif isinstance(t, str):
                try:
                    from datetime import datetime as dt
                    t = dt.fromisoformat(t).timestamp()
                except:
                    continue
            
            if v > 0 and t > 0:
                views.append(float(v))
                timestamps.append(float(t))
        
        if len(views) > 1:
            sorted_indices = np.argsort(timestamps)
            views = [views[i] for i in sorted_indices]
            timestamps = [timestamps[i] for i in sorted_indices]
        
        return np.array(views), np.array(timestamps)
    
    def _calculate_velocity_series(self, views: np.ndarray, 
                                   timestamps: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """计算速度序列"""
        if len(views) < 2:
            return np.array([]), np.array([])
        
        velocities = []
        vel_times = []
        
        for i in range(1, len(views)):
            dt = (timestamps[i] - timestamps[i-1]) / 3600.0
            if dt <= 0:
                continue
            dv = views[i] - views[i-1]
            velocity = dv / dt
            velocities.append(velocity)
            vel_times.append(timestamps[i])
        
        return np.array(velocities), np.array(vel_times)
    
    def _make_result(self, current_views: int, threshold: int,
                     velocity: float, confidence: float,
                     trend_coeffs: Optional[List[float]],
                     residual_mean: float,
                     reason: str) -> PredictionResult:
        """构造预测结果"""
        
        if velocity <= 0:
            predicted_hours = float('inf')
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                predicted_hours = remaining / velocity
        
        metadata = {
            'reason': reason,
            'trend_slope': trend_coeffs[0] if trend_coeffs and len(trend_coeffs) > 0 else 0.0,
            'residual_mean': residual_mean,
            'lookback_window': self.lookback_window,
            'forecast_horizon': self.forecast_horizon,
            'method': 'dlinear_simplified'
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
            timestamp=datetime.now()
        )
