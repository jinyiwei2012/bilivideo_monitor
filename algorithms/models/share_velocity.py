"""
分享速度预测算法
基于分享率预测病毒传播
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class ShareVelocityAlgorithm(BaseAlgorithm):
    """分享速度预测算法"""
    
    name = "分享速度"
    algorithm_id = "share_velocity"
    description = "基于分享率预测病毒传播潜力"
    category = "互动率"
    default_weight = 1.5
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        shares = video_data.get('share_count', 0)
        velocity = self.calculate_velocity(video_data)
        
        if current_views == 0 or velocity <= 0:
            predicted_hours = float('inf')
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                # 分享率
                share_rate = shares / current_views
                
                # 分享是病毒传播的关键指标
                viral_boost = 1 + share_rate * 50
                adjusted_velocity = velocity * viral_boost
                
                predicted_hours = remaining / adjusted_velocity
                
                # 置信度
                confidence = min(1.0, 0.5 + share_rate * 100)
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={
                'method': 'share_velocity',
                'share_rate': shares / current_views if current_views > 0 else 0
            },
            timestamp=datetime.now()
        )
