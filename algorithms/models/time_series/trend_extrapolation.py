"""
趋势外推预测算法
"""
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class TrendExtrapolationAlgorithm(BaseAlgorithm):
    """趋势外推预测（线性回归）"""
    
    name = "趋势外推"
    algorithm_id = "trend_extrapolation"
    description = "使用线性回归外推未来趋势"
    category = "时间序列"
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        history = video_data.get('history_data', [])
        velocity = self.calculate_velocity(video_data)
        
        if len(history) < 3:
            # 数据不足
            prediction = current_views * 1.03
            confidence = 0.3
            slope = 0
            future_predictions = []
        else:
            views = [h.get('view_count', 0) for h in history]
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
            
            confidence = min(0.85, 0.25 + len(history) * 0.1)
        
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
            'slope': slope if len(history) >= 3 else 0,
            'future_predictions': future_predictions if len(history) >= 3 else [],
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
