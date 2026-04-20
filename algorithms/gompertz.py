"""
Gompertz增长模型
"""
from typing import Dict, List, Tuple
from .prediction_base import BasePredictionAlgorithm


class GompertzAlgorithm(BasePredictionAlgorithm):
    """Gompertz增长模型预测"""
    
    name = "Gompertz"
    description = "基于Gompertz增长曲线预测，适用于视频热度增长"
    
    def __init__(self):
        super().__init__()
        self.K = 10000000  # 最大容量默认值
    
    def predict(self, history: List[Tuple], current_value: float, **kwargs) -> Dict:
        """执行预测"""
        thresholds = kwargs.get('thresholds', [100000, 1000000, 10000000])
        threshold_names = kwargs.get('threshold_names', ['10万', '100万', '1000万'])
        
        if len(history) < 3:
            # 数据不足，使用简单增长预测
            prediction = current_value * 1.05
        else:
            views = [v for _, v in history]
            
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
            
            # 简单预测
            prediction = current_value * (1 + avg_rate)
            # 限制在最大容量内
            prediction = min(self.K * 0.5, prediction)
        
        prediction = max(0, prediction)
        
        # 计算置信度
        confidence = min(0.8, 0.2 + len(history) * 0.1)
        
        # 预测达到阈值
        growth = prediction - current_value
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
            'max_capacity': self.K,
            'predicted_growth': growth,
            'growth_rate': growth / max(1, current_value),
            'threshold_predictions': threshold_predictions
        }
        
        self.last_prediction = prediction
        
        return {
            'prediction': prediction,
            'confidence': confidence,
            'metadata': metadata
        }
