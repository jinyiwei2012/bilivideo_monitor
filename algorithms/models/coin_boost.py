"""
投币加速预测算法
基于投币率预测视频质量传播
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class CoinBoostAlgorithm(BaseAlgorithm):
    """投币加速预测算法"""
    
    name = "投币加速"
    algorithm_id = "coin_boost"
    description = "基于投币率预测高质量视频传播"
    category = "互动率"
    default_weight = 1.3
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        coins = video_data.get('coin_count', 0)
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
                # 投币率 (投币比点赞更能体现质量)
                coin_rate = coins / current_views
                
                # 投币加速因子
                boost_factor = 1 + coin_rate * 30  # 投币权重更高
                adjusted_velocity = velocity * boost_factor
                
                predicted_hours = remaining / adjusted_velocity
                
                # 置信度
                confidence = min(1.0, 0.5 + coin_rate * 50)
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={
                'method': 'coin_boost',
                'coin_rate': coins / current_views if current_views > 0 else 0
            },
            timestamp=datetime.now()
        )
