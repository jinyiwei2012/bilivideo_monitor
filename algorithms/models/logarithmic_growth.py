"""
对数增长预测算法
基于对数增长模型
"""

from datetime import datetime
import math
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class LogarithmicGrowthAlgorithm(BaseAlgorithm):
    """对数增长预测算法"""
    
    name = "对数增长"
    algorithm_id = "logarithmic_growth"
    description = "基于对数增长曲线的播放量预测"
    category = "时间衰减"
    default_weight = 0.9
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        age_hours = self.get_video_age_hours(video_data)
        
        if age_hours <= 0:
            predicted_hours = float('inf')
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                # 对数增长模型: views = a * ln(t) + b
                # 基于当前数据拟合参数
                a = current_views / math.log(max(age_hours, 1) + 1)
                
                # 预测达到阈值的时间
                # threshold = a * ln(t_target) => t_target = exp(threshold / a)
                try:
                    target_time = math.exp(threshold / a)
                    predicted_hours = target_time - age_hours
                    
                    if predicted_hours < 0:
                        predicted_hours = 0
                    
                    confidence = 0.6
                except:
                    predicted_hours = float('inf')
                    confidence = 0.2
        
        velocity = self.calculate_velocity(video_data)
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={'method': 'logarithmic_growth'},
            timestamp=datetime.now()
        )
