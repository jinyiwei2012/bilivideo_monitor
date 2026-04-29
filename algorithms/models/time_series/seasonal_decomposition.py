"""
季节性分解模型
将时间序列分解为趋势、季节性和残差成分
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm


class SeasonalDecompositionAlgorithm(BaseAlgorithm):
    """
    Seasonal Decomposition for View Prediction
    
    将播放量增长分解为:
    - 趋势成分 (Trend)
    - 季节性成分 (Seasonal)
    - 残差成分 (Residual)
    """
    
    name = "季节性分解"
    description = "分解趋势、季节性和残差成分"
    category = "时间序列"
    
    def __init__(self):
        super().__init__()
        self.period = 7  # 周季节性
        self.trend = None
        self.seasonal = None
        self.residual = None
        
    def predict(
        self,
        current_views: int,
        target_views: int,
        history_data: List[Dict[str, Any]],
        video_info: Dict[str, Any]
    ) -> Optional[Tuple[int, float]]:
        """
        预测到达目标播放量所需时间
        """
        if not history_data or len(history_data) < 14:
            return None
            
        try:
            views = [d['view'] for d in history_data]
            
            # 计算增长量
            growth = [views[i] - views[i-1] for i in range(1, len(views))]
            
            if len(growth) < 10:
                return None
            
            # 分解时间序列
            self._decompose(growth)
            
            if current_views >= target_views:
                return (0, 1.0)
            
            # 预测未来
            remaining = target_views - current_views
            predicted_total = 0
            days = 0
            max_days = 3650
            
            while predicted_total < remaining and days < max_days:
                days += 1
                
                # 趋势预测 (线性外推)
                trend_pred = self.trend[-1] if self.trend is not None else np.mean(growth[-5:])
                
                # 季节性预测
                season_idx = (len(growth) + days - 1) % self.period
                seasonal_pred = self.seasonal[season_idx] if self.seasonal is not None else 0
                
                # 组合预测
                forecast = trend_pred + seasonal_pred
                forecast = max(0, forecast)
                
                predicted_total += forecast
            
            if days >= max_days:
                return None
            
            seconds_needed = days * 86400
            confidence = self._calculate_confidence(growth)
            
            return (seconds_needed, confidence)
            
        except Exception as e:
            print(f"季节性分解预测失败: {e}")
            return None
    
    def _decompose(self, series: List[float]):
        """
        执行季节性分解 (简化版STL)
        
        使用移动平均提取趋势，然后计算季节性
        """
        n = len(series)
        
        # 提取趋势 (中心化移动平均)
        trend_window = self.period if self.period % 2 == 1 else self.period + 1
        half_window = trend_window // 2
        
        self.trend = []
        for i in range(n):
            if i < half_window or i >= n - half_window:
                self.trend.append(series[i])
            else:
                window = series[i - half_window:i + half_window + 1]
                self.trend.append(np.mean(window))
        
        # 去趋势
        detrended = [series[i] - self.trend[i] for i in range(n)]
        
        # 计算季节性 (周期平均)
        self.seasonal = []
        for i in range(self.period):
            season_values = [detrended[j] for j in range(i, n, self.period)]
            self.seasonal.append(np.mean(season_values) if season_values else 0)
        
        # 中心化季节性
        season_mean = np.mean(self.seasonal)
        self.seasonal = [s - season_mean for s in self.seasonal]
        
        # 计算残差
        self.residual = []
        for i in range(n):
            season_idx = i % self.period
            fitted = self.trend[i] + self.seasonal[season_idx]
            self.residual.append(series[i] - fitted)
    
    def _calculate_confidence(self, growth: List[float]) -> float:
        """计算置信度"""
        n = len(growth)
        
        # 基础置信度
        base_conf = min(0.85, 0.3 + n * 0.015)
        
        # 残差大小
        if self.residual is not None and len(self.residual) > 0:
            residual_std = np.std(self.residual)
            signal_std = np.std(growth)
            
            if signal_std > 0:
                snr = signal_std / (residual_std + 1)
                quality = min(1.0, snr / 5)
                base_conf = 0.6 * base_conf + 0.4 * quality
        
        return min(0.9, base_conf)
