"""
互动率预测算法
基于视频互动率预测传播潜力
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class EngagementRateAlgorithm(BaseAlgorithm):
    """互动率预测算法"""
    
    name = "互动率模型"
    algorithm_id = "engagement_rate"
    description = "基于点赞、投币、收藏等互动率预测"
    category = "互动率"
    default_weight = 1.1
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        velocity = self.calculate_velocity(video_data)
        engagement_rate = self.get_engagement_rate(video_data)
        
        if velocity <= 0:
            predicted_hours = float('inf')
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                # 基础时间
                base_hours = remaining / velocity
                
                # 根据互动率调整
                # 高互动率 = 更快传播
                engagement_factor = 1 + engagement_rate * 2
                adjusted_velocity = velocity * engagement_factor
                
                predicted_hours = remaining / adjusted_velocity
                
                # 置信度基于互动率稳定性
                confidence = min(1.0, 0.5 + engagement_rate * 5)
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={
                'method': 'engagement_rate',
                'engagement_rate': engagement_rate,
                'engagement_factor': 1 + engagement_rate * 2
            },
            timestamp=datetime.now()
        )
