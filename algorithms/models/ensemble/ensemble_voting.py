"""
投票集成预测算法
基于投票的集成预测
"""

from datetime import datetime
from typing import Dict, Any
import statistics
from algorithms.base import BaseAlgorithm, PredictionResult


class EnsembleVotingAlgorithm(BaseAlgorithm):
    """投票集成预测算法"""
    
    name = "投票集成"
    algorithm_id = "ensemble_voting"
    description = "基于中位数投票的集成预测"
    category = "集成模型"
    default_weight = 1.2
    
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
            base = remaining / velocity
            
            # 生成多个预测
            predictions = [
                base * 0.7,
                base * 0.85,
                base,
                base * 1.15,
                base * 1.3,
                base * (1 - self.get_engagement_rate(video_data) * 0.5),
                base / (0.8 + self.get_quality_score(video_data) * 0.4),
            ]
            
            # 使用中位数（抗异常值）
            predicted_hours = statistics.median(predictions)
            
            # 置信度基于四分位距
            q1 = sorted(predictions)[len(predictions) // 4]
            q3 = sorted(predictions)[3 * len(predictions) // 4]
            iqr = q3 - q1
            confidence = max(0.3, 1 - iqr / (predicted_hours + 1))
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={'method': 'ensemble_voting', 'predictions_count': 7},
            timestamp=datetime.now()
        )
