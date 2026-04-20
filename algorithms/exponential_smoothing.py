"""
指数平滑预测算法
"""
from typing import Dict, List, Tuple
from .prediction_base import BasePredictionAlgorithm


class ExponentialSmoothingAlgorithm(BasePredictionAlgorithm):
    """指数平滑预测"""
    
    name = "指数平滑"
    description = "使用指数加权移动平均预测"
    
    def __init__(self):
        super().__init__()
        self.alpha = 0.3  # 平滑系数
    
    def predict(self, history: List[Tuple], current_value: float, **kwargs) -> Dict:
        """执行预测"""
        thresholds = kwargs.get('thresholds', [100000, 1000000, 10000000])
        threshold_names = kwargs.get('threshold_names', ['10万', '100万', '1000万'])
        
        if len(history) < 2:
            smoothed = current_value
        else:
            views = [v for _, v in history]
            
            # 指数平滑
            smoothed = views[0]
            for v in views[1:]:
                smoothed = self.alpha * v + (1 - self.alpha) * smoothed
            
            # 使用平滑值趋势调整预测
            if len(views) >= 3:
                recent_trend = (views[-1] - views[-3]) / 2
                prediction = smoothed + recent_trend * 0.5
            else:
                prediction = smoothed
        smoothed = max(0, prediction)
        
        # 计算置信度
        confidence = min(0.85, 0.25 + len(history) * 0.1)
        
        # 预测达到阈值
        growth = smoothed - current_value
        threshold_predictions = []
        
        if growth > 0:
            for threshold, name in zip(thresholds, threshold_names):
                if threshold > current_value:
                    remaining = threshold - current_value
                    periods_needed = int(remaining / growth) + 1
                    threshold_predictions.append({
                        'threshold': threshold,
                        'name': name,
                        'periods_needed': periods_needed,
                        'minutes': periods_needed * 75 / 60
                    })
        
        metadata = {
            'smoothed_value': smoothed,
            'alpha': self.alpha,
            'trend': growth,
            'threshold_predictions': threshold_predictions
        }
        
        self.last_prediction = smoothed
        
        return {
            'prediction': smoothed,
            'confidence': confidence,
            'metadata': metadata
        }
