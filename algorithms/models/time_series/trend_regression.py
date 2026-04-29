"""
趋势回归预测算法
基于历史趋势的多项式回归
"""

from datetime import datetime
from typing import Dict, Any, List
import numpy as np
from algorithms.base import BaseAlgorithm, PredictionResult


class TrendRegressionAlgorithm(BaseAlgorithm):
    """趋势回归预测算法"""
    
    name = "趋势回归"
    algorithm_id = "trend_regression"
    description = "基于历史数据的多项式回归预测"
    category = "机器学习"
    default_weight = 1.2
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        history = video_data.get('history_data', [])
        
        if len(history) < 3:
            velocity = self.calculate_velocity(video_data)
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
            elif velocity <= 0:
                predicted_hours = float('inf')
            else:
                predicted_hours = remaining / velocity
            confidence = 0.4
        else:
            try:
                # 准备数据
                base_time = history[0].get('timestamp', 0)
                X = np.array([(h.get('timestamp', 0) - base_time) / 3600 for h in history])
                y = np.array([h.get('view_count', 0) for h in history])
                
                # 多项式回归 (2次)
                degree = min(2, len(history) - 1)
                coeffs = np.polyfit(X, y, degree)
                poly = np.poly1d(coeffs)
                
                # 求解达到阈值的时间
                # poly(t) = threshold
                coeffs_target = coeffs.copy()
                coeffs_target[-1] -= threshold
                roots = np.roots(coeffs_target)
                
                # 找实数正根
                real_roots = [r.real for r in roots if np.isreal(r) and r.real > X[-1]]
                
                if real_roots:
                    predicted_hours = min(real_roots) - (history[-1].get('timestamp', 0) - base_time) / 3600
                    if predicted_hours < 0:
                        predicted_hours = 0
                    confidence = 0.7
                else:
                    # 无解，使用当前速度
                    velocity = (y[-1] - y[-2]) / (X[-1] - X[-2]) if len(X) > 1 and X[-1] != X[-2] else 0
                    remaining = threshold - current_views
                    predicted_hours = remaining / velocity if velocity > 0 else float('inf')
                    confidence = 0.5
                    
            except Exception:
                velocity = self.calculate_velocity(video_data)
                remaining = threshold - current_views
                if remaining <= 0:
                    predicted_hours = 0
                elif velocity <= 0:
                    predicted_hours = float('inf')
                else:
                    predicted_hours = remaining / velocity
                confidence = 0.4
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=self.calculate_velocity(video_data),
            metadata={'method': 'trend_regression', 'history_points': len(history)},
            timestamp=datetime.now()
        )
