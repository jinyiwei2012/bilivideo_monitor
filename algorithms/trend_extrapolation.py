"""
趋势外推预测算法
"""
from typing import Dict, List, Tuple
from .prediction_base import BasePredictionAlgorithm


class TrendExtrapolationAlgorithm(BasePredictionAlgorithm):
    """趋势外推预测（线性回归）"""
    
    name = "趋势外推"
    description = "使用线性回归外推未来趋势"
    
    def predict(self, history: List[Tuple], current_value: float, **kwargs) -> Dict:
        """执行预测"""
        thresholds = kwargs.get('thresholds', [100000, 1000000, 10000000])
        threshold_names = kwargs.get('threshold_names', ['10万', '100万', '1000万'])
        
        if len(history) < 3:
            # 数据不足
            prediction = current_value * 1.03
        else:
            views = [v for _, v in history]
            n = len(views)
            
            # 线性回归
            x_mean = (n - 1) / 2
            y_mean = sum(views) / n
            
            numerator = sum((i - x_mean) * (views[i] - y_mean) for i in range(n))
            denominator = sum((i - x_mean) ** 2 for i in range(n))
            
            if denominator > 0:
                slope = numerator / denominator
            else:
                slope = 0
            
            intercept = y_mean - slope * x_mean
            
            # 预测未来
            future_x = n  # 下周期
            prediction = slope * future_x + intercept
            prediction = max(0, prediction)
            
            # 未来预测列表
            future_predictions = []
            for i in range(1, 4):
                fx = n - 1 + i
                fy = max(0, slope * fx + intercept)
                future_predictions.append(fy)
        
        prediction = max(0, prediction)
        
        # 计算置信度
        confidence = min(0.85, 0.25 + len(history) * 0.1)
        
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
            'slope': slope if len(history) >= 3 else 0,
            'future_predictions': future_predictions if len(history) >= 3 else [],
            'threshold_predictions': threshold_predictions
        }
        
        self.last_prediction = prediction
        
        return {
            'prediction': prediction,
            'confidence': confidence,
            'metadata': metadata
        }
