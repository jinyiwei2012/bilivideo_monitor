"""
病毒传播潜力算法
检测视频是否具有病毒式传播特征
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class ViralPotentialAlgorithm(BaseAlgorithm):
    """病毒传播潜力算法"""
    
    name = "病毒潜力"
    algorithm_id = "viral_potential"
    description = "检测视频是否具有病毒式传播特征"
    category = "互动率"
    default_weight = 1.4
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        velocity = self.calculate_velocity(video_data)
        age_hours = self.get_video_age_hours(video_data)
        
        # 计算病毒指标
        views = video_data.get('view_count', 0)
        likes = video_data.get('like_count', 0)
        shares = video_data.get('share_count', 0)
        
        if views == 0 or age_hours <= 0:
            predicted_hours = float('inf')
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                # 病毒指标
                share_rate = shares / views
                like_rate = likes / views
                
                # 早期高互动 = 病毒潜力
                viral_score = (share_rate * 10 + like_rate * 5) * (24 / max(age_hours, 1))
                
                # 病毒加速因子
                if viral_score > 1:
                    viral_factor = 1 + viral_score
                else:
                    viral_factor = 1
                
                adjusted_velocity = velocity * viral_factor
                predicted_hours = remaining / adjusted_velocity
                
                # 置信度基于病毒分数
                confidence = min(1.0, viral_score / 3)
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={
                'method': 'viral_potential',
                'viral_score': viral_score if 'viral_score' in dir() else 0
            },
            timestamp=datetime.now()
        )
