"""
Gompertz增长模型
"""
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class GompertzAlgorithm(BaseAlgorithm):
    """Gompertz增长模型预测"""
    
    name = "Gompertz"
    algorithm_id = "gompertz"
    description = "基于Gompertz增长曲线预测，适用于视频热度增长"
    category = "增长模型"
    
    def __init__(self):
        super().__init__()
        self.K = 10000000  # 最大容量默认值
        
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        history = video_data.get('history_data', [])
        velocity = self.calculate_velocity(video_data)
        
        if len(history) < 3:
            # 数据不足，使用简单增长预测
            if velocity > 0:
                predicted_hours = (threshold - current_views) / velocity
            else:
                predicted_hours = float('inf')
            confidence = 0.3
            metadata = {'method': 'gompertz_simple', 'reason': 'insufficient_data'}
        else:
            views = [h.get('view_count', 0) for h in history]
            
            # 计算相对增长率
            growth_rates = []
            for i in range(1, len(views)):
                if views[i-1] > 0:
                    rate = (views[i] - views[i-1]) / views[i-1]
                    growth_rates.append(max(0, rate))
            
            if growth_rates:
                avg_rate = sum(growth_rates) / len(growth_rates)
            else:
                avg_rate = 0.01
            
            # Gompertz模型预测
            prediction = current_views * (1 + avg_rate)
            # 限制在最大容量内
            prediction = min(self.K * 0.5, prediction)
            
            if velocity > 0:
                predicted_hours = (threshold - current_views) / velocity
            else:
                predicted_hours = float('inf')
            
            confidence = min(0.8, 0.2 + len(history) * 0.1)
            metadata = {
                'method': 'gompertz',
                'max_capacity': self.K,
                'average_growth_rate': avg_rate
            }
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=max(0, predicted_hours),
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata=metadata,
            timestamp=datetime.now()
        )
