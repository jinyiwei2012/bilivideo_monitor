"""
移动平均预测算法
"""
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class MovingAverageAlgorithm(BaseAlgorithm):
    """简单移动平均预测"""
    
    name = "移动平均"
    algorithm_id = "moving_average"
    description = "使用历史数据的简单移动平均预测"
    category = "时间序列"
    
    def __init__(self):
        super().__init__()
        self.window_size = 5
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        history = video_data.get('history_data', [])
        velocity = self.calculate_velocity(video_data)
        
        if len(history) < 2:
            prediction = current_views
            confidence = 0.3
        else:
            views = [h.get('view_count', 0) for h in history]
            window = min(self.window_size, len(views))
            
            # 计算移动平均
            ma = sum(views[-window:]) / window
            
            # 考虑趋势
            if len(views) >= 3:
                recent_avg = sum(views[-3:]) / 3
                old_avg = sum(views[:3]) / 3
                trend = (recent_avg - old_avg) / 3
                prediction = ma + trend * 0.3
            else:
                prediction = ma
            
            prediction = max(0, prediction)
            confidence = min(0.75, 0.2 + len(history) * 0.08)
        
        # 计算预测达到阈值的时间
        growth = prediction - current_views
        predicted_hours = float('inf')
        
        if growth > 0 and current_views < threshold:
            remaining = threshold - current_views
            if velocity > 0:
                predicted_hours = remaining / velocity
            else:
                predicted_hours = float('inf')
        elif current_views >= threshold:
            predicted_hours = 0
            confidence = 1.0
        
        metadata = {
            'ma_value': prediction,
            'window_size': min(self.window_size, len(history)),
            'trend': '上涨' if growth > 0 else '下跌'
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
