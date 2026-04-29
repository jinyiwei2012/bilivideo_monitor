"""
指数平滑模型
Holt线性指数平滑，考虑趋势
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm


class ExponentialSmoothingAlgorithm(BaseAlgorithm):
    """
    Holt's Linear Exponential Smoothing
    
    双参数指数平滑，同时平滑水平和趋势
    """
    
    name = "指数平滑"
    description = "Holt线性指数平滑，考虑趋势"
    category = "时间序列"
    
    def __init__(self):
        super().__init__()
        self.alpha = 0.3  # 水平平滑参数
        self.beta = 0.1   # 趋势平滑参数
        self.level = None
        self.trend = None
        
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
        if not history_data or len(history_data) < 5:
            return None
            
        try:
            views = [d['view'] for d in history_data]
            
            # 计算增长量
            growth = [views[i] - views[i-1] for i in range(1, len(views))]
            
            if len(growth) < 4:
                return None
            
            # 拟合模型
            self._fit(growth)
            
            if current_views >= target_views:
                return (0, 1.0)
            
            remaining = target_views - current_views
            
            # 预测未来
            predicted_total = 0
            days = 0
            max_days = 3650
            
            while predicted_total < remaining and days < max_days:
                days += 1
                # h步预测: level + h * trend
                forecast = self.level + days * self.trend
                forecast = max(0, forecast)
                predicted_total += forecast
            
            if days >= max_days:
                return None
            
            seconds_needed = days * 86400
            confidence = self._calculate_confidence(growth)
            
            return (seconds_needed, confidence)
            
        except Exception as e:
            print(f"指数平滑预测失败: {e}")
            return None
    
    def _fit(self, series: List[float]):
        """
        拟合Holt线性指数平滑
        
        l_t = alpha * y_t + (1-alpha) * (l_{t-1} + b_{t-1})
        b_t = beta * (l_t - l_{t-1}) + (1-beta) * b_{t-1}
        """
        n = len(series)
        
        # 初始化
        levels = [series[0]]
        trends = [series[1] - series[0] if n > 1 else 0]
        
        for t in range(1, n):
            y = series[t]
            
            # 更新水平
            level = self.alpha * y + (1 - self.alpha) * (levels[-1] + trends[-1])
            
            # 更新趋势
            trend = self.beta * (level - levels[-1]) + (1 - self.beta) * trends[-1]
            
            levels.append(level)
            trends.append(trend)
        
        self.level = levels[-1]
        self.trend = trends[-1]
    
    def _calculate_confidence(self, growth: List[float]) -> float:
        """计算置信度"""
        n = len(growth)
        
        # 基础置信度
        base_conf = min(0.85, 0.3 + n * 0.025)
        
        # 趋势稳定性
        if self.trend is not None:
            if self.trend > 0:
                # 正趋势增加置信度
                trend_factor = min(1.0, self.trend / 100)
                base_conf = 0.8 * base_conf + 0.2 * trend_factor
            else:
                # 负趋势降低置信度
                base_conf *= 0.7
        
        return min(0.9, base_conf)
