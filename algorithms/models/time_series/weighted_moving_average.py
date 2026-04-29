"""
加权移动平均预测算法
"""
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class WeightedMovingAverageAlgorithm(BaseAlgorithm):
    """加权移动平均预测"""
    
    name = "加权移动平均"
    algorithm_id = "weighted_moving_average"
    description = "使用加权移动平均，近期数据权重更高"
    category = "时间序列"
    
    def __init__(self):
        super().__init__()
        # 默认权重：越近权重越高
        self.default_weights = [0.1, 0.15, 0.2, 0.25, 0.3]
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        history = video_data.get('history_data', [])
        velocity = self.calculate_velocity(video_data)
        
        if len(history) < 2:
            prediction = current_views
            confidence = 0.3
            weights = []
        else:
            views = [h.get('view_count', 0) for h in history]
            window_size = min(len(self.default_weights), len(views))
            
            # 截取对应长度的权重
            weights = self.default_weights[-window_size:]
            # 归一化权重
            total_weight = sum(weights)
            weights = [w / total_weight for w in weights]
            
            # 计算加权平均
            wma = sum(views[-window_size + i] * weights[i] for i in range(window_size))
            
            # 考虑趋势调整
            if len(views) >= 3:
                recent = sum(views[-2:]) / 2
                older = sum(views[:2]) / 2
                trend = (recent - older) / 2
                prediction = wma + trend * 0.5
            else:
                prediction = wma
            
            prediction = max(0, prediction)
            confidence = min(0.8, 0.25 + len(history) * 0.08)
        
        # 计算预测达到阈值的时间
        growth = prediction - current_views
        predicted_hours = float('inf')
        
        if growth > 0 and current_views < threshold:
            remaining = threshold - current_views
            if velocity > 0:
                predicted_hours = remaining / velocity
            else:
                predicted_hours = float('inf')
        elif current_views >= threshold:
            predicted_hours = 0
            confidence = 1.0
        
        metadata = {
            'wma_value': prediction,
            'weights': weights if len(history) >= 2 else [],
            'trend': '上涨' if growth > 0 else '下跌'
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
