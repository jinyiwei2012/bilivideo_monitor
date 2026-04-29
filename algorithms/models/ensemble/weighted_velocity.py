"""
加权速度预测算法
考虑近期速度权重更高
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class WeightedVelocityAlgorithm(BaseAlgorithm):
    """加权速度预测算法"""
    
    name = "加权速度"
    algorithm_id = "weighted_velocity"
    description = "近期播放速度权重更高"
    category = "基础速度"
    default_weight = 1.2
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        base_velocity = self.calculate_velocity(video_data)
        
        # 获取历史数据（如果有）
        history = video_data.get('history_data', [])
        
        if len(history) >= 2:
            # 计算加权速度（近期权重更高）
            total_weight = 0
            weighted_velocity = 0
            
            for i, record in enumerate(history):
                weight = (i + 1) / len(history)  # 越新权重越高
                if i > 0:
                    views_diff = record.get('view_count', 0) - history[i-1].get('view_count', 0)
                    time_diff = record.get('timestamp', 0) - history[i-1].get('timestamp', 0)
                    if time_diff > 0:
                        velocity = views_diff / (time_diff / 3600)
                        weighted_velocity += velocity * weight
                        total_weight += weight
            
            if total_weight > 0:
                final_velocity = weighted_velocity / total_weight
            else:
                final_velocity = base_velocity
        else:
            final_velocity = base_velocity
        
        if final_velocity <= 0:
            predicted_hours = float('inf')
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                predicted_hours = remaining / final_velocity
                # 有历史数据时置信度更高
                confidence = min(1.0, 0.5 + len(history) * 0.1)
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=final_velocity,
            metadata={'method': 'weighted_velocity', 'history_points': len(history)},
            timestamp=datetime.now()
        )
