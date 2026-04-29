"""
指数平滑预测算法
"""
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class ExponentialSmoothingAlgorithm(BaseAlgorithm):
    """指数平滑预测"""
    
    name = "指数平滑"
    algorithm_id = "exponential_smoothing"
    description = "使用指数加权移动平均预测"
    category = "时间序列"
    
    def __init__(self):
        super().__init__()
        self.alpha = 0.3  # 平滑系数
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        history = video_data.get('history_data', [])
        velocity = self.calculate_velocity(video_data)
        
        if len(history) < 2:
            smoothed = current_views
            confidence = 0.3
        else:
            views = [h.get('view_count', 0) for h in history]
            
            # 指数平滑
            smoothed = views[0]
            for v in views[1:]:
                smoothed = self.alpha * v + (1 - self.alpha) * smoothed
            
            # 使用平滑值趋势调整预测
            if len(views) >= 3:
                recent_trend = (views[-1] - views[-3]) / 2
                prediction = smoothed + recent_trend * 0.5
            else:
                prediction = smoothed
            
            smoothed = max(0, prediction)
            confidence = min(0.85, 0.25 + len(history) * 0.1)
        
        # 计算预测达到阈值的时间
        growth = smoothed - current_views
        predicted_hours = float('inf')
        
        if growth > 0 and current_views < threshold:
            remaining = threshold - current_views
            # 估计每小时增长
            if velocity > 0:
                predicted_hours = remaining / velocity
            else:
                predicted_hours = float('inf')
        elif current_views >= threshold:
            predicted_hours = 0
            confidence = 1.0
        
        metadata = {
            'smoothed_value': smoothed,
            'alpha': self.alpha,
            'trend': growth
        }
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=max(0, predicted_hours),
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata=metadata,
            timestamp=datetime.now()
        )
