"""
评论趋势预测算法
基于评论活跃度预测
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class CommentTrendAlgorithm(BaseAlgorithm):
    """评论趋势预测算法"""
    
    name = "评论趋势"
    algorithm_id = "comment_trend"
    description = "基于评论活跃度预测视频热度"
    category = "互动率"
    default_weight = 0.9
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        replies = video_data.get('reply_count', 0)
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
                # 评论率
                comment_rate = replies / current_views
                
                # 评论活跃 = 讨论热度高
                trend_factor = 1 + comment_rate * 20
                adjusted_velocity = velocity * trend_factor
                
                predicted_hours = remaining / adjusted_velocity
                
                # 置信度
                confidence = min(1.0, 0.5 + comment_rate * 40)
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={
                'method': 'comment_trend',
                'comment_rate': replies / current_views if current_views > 0 else 0
            },
            timestamp=datetime.now()
        )
