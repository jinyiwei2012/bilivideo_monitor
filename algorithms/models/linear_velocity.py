"""
线性速度预测算法
基于当前播放速度线性预测
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class LinearVelocityAlgorithm(BaseAlgorithm):
    """线性速度预测算法"""
    
    name = "线性速度"
    algorithm_id = "linear_velocity"
    description = "基于当前播放速度进行线性预测"
    category = "基础速度"
    default_weight = 1.0
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        velocity = self.calculate_velocity(video_data)
        
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
                # 置信度随时间递减
                age_hours = self.get_video_age_hours(video_data)
                confidence = min(1.0, max(0.3, 1 - age_hours / 168))  # 一周后置信度降低
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={'method': 'linear_velocity'},
            timestamp=datetime.now()
        )
