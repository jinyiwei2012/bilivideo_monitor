"""
Holt-Winters指数平滑模型
经典的时间序列预测方法，考虑趋势和季节性
适用于有周期性波动的播放量预测
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm


class HoltWintersAlgorithm(BaseAlgorithm):
    """
    Holt-Winters Triple Exponential Smoothing
    
    考虑三个成分:
    - 水平 (Level)
    - 趋势 (Trend)
    - 季节性 (Seasonality)
    """
    
    name = "Holt-Winters指数平滑"
    description = "经典时间序列预测，考虑趋势和季节性"
    category = "时间序列"
    
    def __init__(self):
        super().__init__()
        self.alpha = 0.3  # 水平平滑参数
        self.beta = 0.1   # 趋势平滑参数
        self.gamma = 0.1  # 季节性平滑参数
        self.season_length = 7  # 假设周季节性
        
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
            
            # 计算增长差分
            diffs = [views[i] - views[i-1] for i in range(1, len(views))]
            
            if len(diffs) < 7:
                return None
            
            # 应用Holt-Winters
            level, trend, seasons = self._fit(diffs)
            
            if current_views >= target_views:
                return (0, 1.0)
            
            remaining = target_views - current_views
            
            # 预测未来增长
            predicted_total = 0
            days = 0
            max_days = 3650
            
            while predicted_total < remaining and days < max_days:
                days += 1
                # 预测第days天的增长
                season_idx = (len(diffs) + days - 1) % self.season_length
                forecast = level + days * trend + seasons[season_idx]
                forecast = max(0, forecast)  # 增长不能为负
                predicted_total += forecast
            
            if days >= max_days:
                return None
            
            seconds_needed = days * 86400
            confidence = self._calculate_confidence(diffs, level, trend)
            
            return (seconds_needed, confidence)
            
        except Exception as e:
            print(f"Holt-Winters预测失败: {e}")
            return None
    
    def _fit(self, series: List[float]) -> Tuple[float, float, List[float]]:
        """
        拟合Holt-Winters模型
        
        Returns:
            (当前水平, 当前趋势, 季节性因子)
        """
        n = len(series)
        
        # 初始化水平
        level = np.mean(series[:self.season_length])
        
        # 初始化趋势
        trend = (np.mean(series[self.season_length:2*self.season_length]) - 
                 np.mean(series[:self.season_length])) / self.season_length
        
        # 初始化季节性
        seasons = []
        for i in range(self.season_length):
            season_values = [series[j] for j in range(i, n, self.season_length)]
            seasons.append(np.mean(season_values) - level)
        
        # 迭代更新
        for t in range(n):
            value = series[t]
            season_idx = t % self.season_length
            
            # 更新水平
            old_level = level
            level = self.alpha * (value - seasons[season_idx]) + (1 - self.alpha) * (level + trend)
            
            # 更新趋势
            trend = self.beta * (level - old_level) + (1 - self.beta) * trend
            
            # 更新季节性
            seasons[season_idx] = self.gamma * (value - level) + (1 - self.gamma) * seasons[season_idx]
        
        return level, trend, seasons
    
    def _calculate_confidence(
        self, 
        diffs: List[float],
        level: float,
        trend: float
    ) -> float:
        """计算置信度"""
        n = len(diffs)
        
        # 基础置信度
        base_conf = min(0.9, 0.4 + n * 0.02)
        
        # 趋势稳定性
        if trend > 0:
            # 正趋势是好的
            trend_stability = min(1.0, trend / (np.mean(diffs) + 1))
            base_conf = 0.7 * base_conf + 0.3 * trend_stability
        
        return min(0.95, base_conf)
