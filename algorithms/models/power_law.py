"""
幂律衰减预测算法
基于幂律分布的衰减模型
"""

from datetime import datetime
import math
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class PowerLawAlgorithm(BaseAlgorithm):
    """幂律衰减预测算法"""
    
    name = "幂律衰减"
    algorithm_id = "power_law"
    description = "基于幂律分布的播放量衰减模型"
    category = "时间衰减"
    default_weight = 1.2
    
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
                # 幂律指数
                alpha = 1.5
                
                # 当前速度 v = v0 * (t0 / t)^alpha
                # 积分求解
                v0 = velocity * (age_hours ** alpha)
                
                # 预测时间
                predicted_hours = ((remaining * (alpha - 1) / v0) + 
                                  (age_hours ** (1 - alpha))) ** (1 / (1 - alpha)) - age_hours
                
                if predicted_hours < 0 or math.isnan(predicted_hours):
                    predicted_hours = float('inf')
                    confidence = 0.3
                else:
                    confidence = 0.65
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={'method': 'power_law', 'alpha': 1.5},
            timestamp=datetime.now()
        )
