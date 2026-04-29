"""
质量分数预测算法
基于视频质量评分预测
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class QualityScoreAlgorithm(BaseAlgorithm):
    """质量分数预测算法"""
    
    name = "质量分数"
    algorithm_id = "quality_score"
    description = "基于视频质量评分预测传播速度"
    category = "互动率"
    default_weight = 1.0
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        velocity = self.calculate_velocity(video_data)
        quality_score = self.get_quality_score(video_data)
        
        if velocity <= 0:
            predicted_hours = float('inf')
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                # 质量越高，传播越快
                quality_factor = 0.5 + quality_score  # 0.5 - 1.5
                adjusted_velocity = velocity * quality_factor
                
                predicted_hours = remaining / adjusted_velocity
                
                # 置信度基于质量分数
                confidence = 0.4 + quality_score * 0.5
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={
                'method': 'quality_score',
                'quality_score': quality_score,
                'quality_factor': 0.5 + quality_score
            },
            timestamp=datetime.now()
        )
