"""
线性增长预测算法
"""
from typing import Dict, List, Tuple
from ...prediction_base import BasePredictionAlgorithm


class LinearGrowthAlgorithm(BasePredictionAlgorithm):
    """线性增长预测"""
    
    name = "线性增长"
    description = "基于历史平均增长率预测未来值"
    
    def predict(self, history: List[Tuple], current_value: float, **kwargs) -> Dict:
        """执行预测"""
        thresholds = kwargs.get('thresholds', [100000, 1000000, 10000000])
        threshold_names = kwargs.get('threshold_names', ['10万', '100万', '1000万'])
        
        if len(history) < 2:
            # 数据不足，使用默认值
            growth_rate = 0.01
            avg_growth = current_value * growth_rate
        else:
            views = [v for _, v in history]
            
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
            if avg_growth < current_value * 0.001:
                avg_growth = current_value * avg_growth_rate
        
        # 预测下一周期
        prediction = current_value + avg_growth
        
        # 计算置信度（基于数据点数量）
        confidence = min(0.9, 0.3 + len(history) * 0.1)
        
        # 预测达到阈值时间
        threshold_predictions = []
        for threshold, name in zip(thresholds, threshold_names):
            if threshold > current_value:
                remaining = threshold - current_value
                if avg_growth > 0:
                    periods_needed = int(remaining / avg_growth) + 1
                    threshold_predictions.append({
                        'threshold': threshold,
                        'name': name,
                        'periods_needed': periods_needed,
                        'minutes': periods_needed * 75 / 60
                    })
        
        metadata = {
            'avg_growth': avg_growth,
            'growth_rate': avg_growth / max(1, current_value),
            'threshold_predictions': threshold_predictions,
            'data_points': len(history)
        }
        
        self.last_prediction = prediction
        
        return {
            'prediction': prediction,
            'confidence': confidence,
            'metadata': metadata
        }
