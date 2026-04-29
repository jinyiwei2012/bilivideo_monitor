"""
平均集成预测算法
简单平均多个基础预测
"""

from datetime import datetime
from typing import Dict, Any, List
from algorithms.base import BaseAlgorithm, PredictionResult


class EnsembleAverageAlgorithm(BaseAlgorithm):
    """平均集成预测算法"""
    
    name = "平均集成"
    algorithm_id = "ensemble_average"
    description = "简单平均多个基础预测结果"
    category = "集成模型"
    default_weight = 1.0
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        velocity = self.calculate_velocity(video_data)
        
        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours = 0
            confidence = 1.0
        elif velocity <= 0:
            predicted_hours = float('inf')
            confidence = 0.0
        else:
            # 基础预测
            base = remaining / velocity
            
            # 多种变体
            predictions = [
                base,  # 线性
                base * 0.8,  # 乐观
                base * 1.2,  # 悲观
                base * (1 + self.get_engagement_rate(video_data)),  # 互动调整
                base / (1 + self.get_quality_score(video_data) * 0.5),  # 质量调整
            ]
            
            # 简单平均
            predicted_hours = sum(predictions) / len(predictions)
            
            # 置信度基于方差
            variance = sum((p - predicted_hours) ** 2 for p in predictions) / len(predictions)
            confidence = max(0.3, 1 - variance / (predicted_hours ** 2 + 1))
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={'method': 'ensemble_average', 'ensemble_size': 5},
            timestamp=datetime.now()
        )
