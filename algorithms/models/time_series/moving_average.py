"""
移动平均预测算法
基于移动平均速度预测
"""

from datetime import datetime
from typing import Dict, Any, List
from algorithms.base import BaseAlgorithm, PredictionResult


class MovingAverageAlgorithm(BaseAlgorithm):
    """移动平均预测算法"""
    
    name = "移动平均"
    algorithm_id = "moving_average"
    description = "基于历史数据的移动平均速度"
    category = "基础速度"
    default_weight = 1.1
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        history = video_data.get('history_data', [])
        
        if len(history) >= 2:
            # 计算各时段速度
            velocities = []
            for i in range(1, len(history)):
                views_diff = history[i].get('view_count', 0) - history[i-1].get('view_count', 0)
                time_diff = (history[i].get('timestamp', 0) - history[i-1].get('timestamp', 0)) / 3600
                if time_diff > 0:
                    velocities.append(views_diff / time_diff)
            
            if velocities:
                # 移动平均
                avg_velocity = sum(velocities) / len(velocities)
            else:
                avg_velocity = self.calculate_velocity(video_data)
        else:
            avg_velocity = self.calculate_velocity(video_data)
        
        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours = 0
            confidence = 1.0
        elif avg_velocity <= 0:
            predicted_hours = float('inf')
            confidence = 0.0
        else:
            predicted_hours = remaining / avg_velocity
            # 数据点越多置信度越高
            confidence = min(1.0, 0.4 + len(history) * 0.1)
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=avg_velocity,
            metadata={
                'method': 'moving_average',
                'history_points': len(history)
            },
            timestamp=datetime.now()
        )
