"""
点赞动量预测算法
基于点赞增长动量预测
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class LikeMomentumAlgorithm(BaseAlgorithm):
    """点赞动量预测算法"""
    
    name = "点赞动量"
    algorithm_id = "like_momentum"
    description = "基于点赞增长动量预测播放量"
    category = "互动率"
    default_weight = 1.0
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        likes = video_data.get('like_count', 0)
        velocity = self.calculate_velocity(video_data)
        
        if likes == 0 or velocity <= 0:
            predicted_hours = float('inf')
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                # 点赞率
                like_rate = likes / current_views if current_views > 0 else 0
                
                # 高点赞率 = 高质量 = 更快传播
                momentum_factor = 1 + like_rate * 10
                adjusted_velocity = velocity * momentum_factor
                
                predicted_hours = remaining / adjusted_velocity
                
                # 置信度
                confidence = min(1.0, 0.5 + like_rate * 20)
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={
                'method': 'like_momentum',
                'like_rate': likes / current_views if current_views > 0 else 0
            },
            timestamp=datetime.now()
        )
