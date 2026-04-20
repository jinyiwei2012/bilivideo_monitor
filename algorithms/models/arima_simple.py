"""
ARIMA简化预测算法
简化版自回归积分滑动平均模型
"""

from datetime import datetime
from typing import Dict, Any, List
from algorithms.base import BaseAlgorithm, PredictionResult


class ArimaSimpleAlgorithm(BaseAlgorithm):
    """ARIMA简化预测算法"""
    
    name = "ARIMA简化"
    algorithm_id = "arima_simple"
    description = "简化版时间序列预测"
    category = "机器学习"
    default_weight = 1.3
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        history = video_data.get('history_data', [])
        
        if len(history) < 3:
            # 数据不足，使用线性预测
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
            # 简化ARIMA: 使用最近3个点的趋势
            recent = history[-3:]
            views = [r.get('view_count', 0) for r in recent]
            
            # 计算一阶差分
            diff1 = [views[i] - views[i-1] for i in range(1, len(views))]
            
            # 预测下一个差分
            if len(diff1) >= 2:
                # 简单平均趋势
                trend = sum(diff1) / len(diff1)
            else:
                trend = diff1[0] if diff1 else 0
            
            # 计算平均时间间隔
            times = [r.get('timestamp', 0) for r in recent]
            time_diffs = [(times[i] - times[i-1]) / 3600 for i in range(1, len(times))]
            avg_interval = sum(time_diffs) / len(time_diffs) if time_diffs else 1
            
            # 预测速度
            velocity = trend / avg_interval if avg_interval > 0 else 0
            
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
            elif velocity <= 0:
                predicted_hours = float('inf')
            else:
                predicted_hours = remaining / velocity
            
            confidence = min(1.0, 0.5 + len(history) * 0.05)
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity if 'velocity' in dir() else self.calculate_velocity(video_data),
            metadata={'method': 'arima_simple', 'history_points': len(history)},
            timestamp=datetime.now()
        )
