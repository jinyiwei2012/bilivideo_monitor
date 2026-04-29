"""
移动平均预测算法
"""
from typing import Dict, List, Tuple
from ...prediction_base import BasePredictionAlgorithm


class MovingAverageAlgorithm(BasePredictionAlgorithm):
    """简单移动平均预测"""
    
    name = "移动平均"
    description = "使用历史数据的简单移动平均预测"
    
    def __init__(self):
        super().__init__()
        self.window_size = 5
    
    def predict(self, history: List[Tuple], current_value: float, **kwargs) -> Dict:
        """执行预测"""
        thresholds = kwargs.get('thresholds', [100000, 1000000, 10000000])
        threshold_names = kwargs.get('threshold_names', ['10万', '100万', '1000万'])
        
        if len(history) < 2:
            prediction = current_value
        else:
            views = [v for _, v in history]
            window = min(self.window_size, len(views))
            
            # 计算移动平均
            ma = sum(views[-window:]) / window
            
            # 考虑趋势
            if len(views) >= 3:
                recent_avg = sum(views[-3:]) / 3
                old_avg = sum(views[:3]) / 3
                trend = (recent_avg - old_avg) / 3
                prediction = ma + trend * 0.3
            else:
                prediction = ma
        
        prediction = max(0, prediction)
        
        # 计算置信度
        confidence = min(0.75, 0.2 + len(history) * 0.08)
        
        # 预测达到阈值
        growth = prediction - current_value
        threshold_predictions = []
        
        if abs(growth) > 0:
            for threshold, name in zip(thresholds, threshold_names):
                if threshold > current_value:
                    remaining = threshold - current_value
                    periods_needed = int(remaining / growth) + 1 if growth > 0 else 999
                    threshold_predictions.append({
                        'threshold': threshold,
                        'name': name,
                        'periods_needed': periods_needed,
                        'minutes': periods_needed * 75 / 60
                    })
        
        metadata = {
            'ma_value': prediction,
            'window_size': min(self.window_size, len(history)),
            'trend': '上涨' if growth > 0 else '下跌',
            'threshold_predictions': threshold_predictions
        }
        
        self.last_prediction = prediction
        
        return {
            'prediction': prediction,
            'confidence': confidence,
            'metadata': metadata
        }
