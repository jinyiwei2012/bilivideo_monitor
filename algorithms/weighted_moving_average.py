"""
加权移动平均预测算法
"""
from typing import Dict, List, Tuple
from .prediction_base import BasePredictionAlgorithm


class WeightedMovingAverageAlgorithm(BasePredictionAlgorithm):
    """加权移动平均预测"""
    
    name = "加权移动平均"
    description = "使用加权移动平均，近期数据权重更高"
    
    def __init__(self):
        super().__init__()
        # 默认权重：越近权重越高
        self.default_weights = [0.1, 0.15, 0.2, 0.25, 0.3]
    
    def predict(self, history: List[Tuple], current_value: float, **kwargs) -> Dict:
        """执行预测"""
        thresholds = kwargs.get('thresholds', [100000, 1000000, 10000000])
        threshold_names = kwargs.get('threshold_names', ['10万', '100万', '1000万'])
        
        if len(history) < 2:
            prediction = current_value
        else:
            views = [v for _, v in history]
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
        
        # 计算置信度
        confidence = min(0.8, 0.25 + len(history) * 0.08)
        
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
            'wma_value': prediction,
            'weights': weights if len(history) >= 2 else [],
            'trend': '上涨' if growth > 0 else '下跌',
            'threshold_predictions': threshold_predictions
        }
        
        self.last_prediction = prediction
        
        return {
            'prediction': prediction,
            'confidence': confidence,
            'metadata': metadata
        }
