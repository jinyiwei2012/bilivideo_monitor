"""
加权集成预测算法
加权平均多个基础预测
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class EnsembleWeightedAlgorithm(BaseAlgorithm):
    """加权集成预测算法"""
    
    name = "加权集成"
    algorithm_id = "ensemble_weighted"
    description = "加权平均多个基础预测结果"
    category = "集成模型"
    default_weight = 1.3
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        velocity = self.calculate_velocity(video_data)
        age_hours = self.get_video_age_hours(video_data)
        
        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours = 0
            confidence = 1.0
        elif velocity <= 0:
            predicted_hours = float('inf')
            confidence = 0.0
        else:
            base = remaining / velocity
            
            # 不同权重的预测
            weighted_predictions = [
                (base * 0.9, 0.15),   # 乐观
                (base * 1.1, 0.15),   # 悲观
                (base * (1 - self.get_engagement_rate(video_data) * 0.3), 0.25),  # 互动
                (base / (1 + self.get_quality_score(video_data) * 0.3), 0.25),   # 质量
                (base * (1 + min(age_hours, 72) / 72 * 0.2), 0.20),  # 时间
            ]
            
            # 加权平均
            total_weight = sum(w for _, w in weighted_predictions)
            weighted_sum = sum(p * w for p, w in weighted_predictions)
            predicted_hours = weighted_sum / total_weight
            
            # 置信度
            confidence = 0.7
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={'method': 'ensemble_weighted', 'weights': [w for _, w in weighted_predictions]},
            timestamp=datetime.now()
        )
