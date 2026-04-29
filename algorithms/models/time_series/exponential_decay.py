"""
指数衰减预测算法
考虑播放量增长速度随时间自然衰减
"""

from datetime import datetime
import math
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class ExponentialDecayAlgorithm(BaseAlgorithm):
    """指数衰减预测算法"""
    
    name = "指数衰减"
    algorithm_id = "exponential_decay"
    description = "考虑播放量增长速度随时间指数衰减"
    category = "时间衰减"
    default_weight = 1.3
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        velocity = self.calculate_velocity(video_data)
        age_hours = self.get_video_age_hours(video_data)
        
        if velocity <= 0 or age_hours <= 0:
            predicted_hours = float('inf')
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                # 衰减系数 (24小时后速度减半)
                decay_rate = 0.693 / 24  # ln(2) / 24
                
                # 计算初始速度（假设发布时的速度）
                v0 = velocity * math.exp(decay_rate * age_hours)
                
                # 积分求解: ∫v0 * e^(-decay_rate * t) dt = remaining
                # 解得: t = -ln(1 - decay_rate * remaining / v0) / decay_rate
                
                numerator = decay_rate * remaining / v0
                if numerator >= 1:
                    predicted_hours = float('inf')
                    confidence = 0.3
                else:
                    predicted_hours = -math.log(1 - numerator) / decay_rate
                    # 置信度基于模型拟合程度
                    confidence = 0.7
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={'method': 'exponential_decay', 'decay_rate': 0.693/24},
            timestamp=datetime.now()
        )
