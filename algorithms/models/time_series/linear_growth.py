"""
线性增长预测算法
"""
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class LinearGrowthAlgorithm(BaseAlgorithm):
    """线性增长预测"""
    
    name = "线性增长"
    algorithm_id = "linear_growth"
    description = "基于历史平均增长率预测未来值"
    category = "时间序列"
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        history = video_data.get('history_data', [])
        velocity = self.calculate_velocity(video_data)
        
        if len(history) < 2:
            # 数据不足，使用默认值
            growth_rate = 0.01
            avg_growth = current_views * growth_rate
            confidence = 0.3
        else:
            views = [h.get('view_count', 0) for h in history]
            
            # 计算每期增长率
            growths = []
            for i in range(1, len(views)):
                if views[i-1] > 0:
                    growth = (views[i] - views[i-1]) / views[i-1]
                    growths.append(max(0, growth))
            
            if growths:
                avg_growth_rate = sum(growths) / len(growths)
            else:
                avg_growth_rate = 0.01
            
            # 计算平均绝对增长
            abs_growths = [max(0, views[i+1] - views[i]) for i in range(len(views)-1)]
            avg_growth = sum(abs_growths) / max(1, len(abs_growths))
            
            # 如果平均增长太小，使用相对增长
            if avg_growth < current_views * 0.001:
                avg_growth = current_views * avg_growth_rate
            
            confidence = min(0.9, 0.3 + len(history) * 0.1)
        
        # 预测达到阈值的时间
        predicted_hours = float('inf')
        if avg_growth > 0 and current_views < threshold:
            remaining = threshold - current_views
            if velocity > 0:
                predicted_hours = remaining / velocity
            else:
                predicted_hours = remaining / (avg_growth / 24)  # 假设日均增长
        elif current_views >= threshold:
            predicted_hours = 0
            confidence = 1.0
        
        metadata = {
            'avg_growth': avg_growth,
            'growth_rate': avg_growth / max(1, current_views),
            'data_points': len(history)
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
