"""
LSTM简化预测算法
基于LSTM思想的简化实现
"""

from datetime import datetime
from typing import Dict, Any, List
from collections import deque
from algorithms.base import BaseAlgorithm, PredictionResult


class LSTMSimpleAlgorithm(BaseAlgorithm):
    """LSTM简化预测算法"""
    
    name = "LSTM简化"
    algorithm_id = "lstm_simple"
    description = "基于LSTM序列建模思想的简化预测"
    category = "深度学习"
    default_weight = 1.3
    
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        history = video_data.get('history_data', [])
        velocity = self.calculate_velocity(video_data)
        
        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours = 0
            confidence = 1.0
        elif velocity <= 0:
            predicted_hours = float('inf')
            confidence = 0.0
        elif len(history) < 2:
            predicted_hours = remaining / velocity
            confidence = 0.4
        else:
            # 简化的LSTM门控机制
            # 提取序列特征
            views_seq = [h.get('view_count', 0) for h in history[-10:]]  # 最近10个
            
            # 遗忘门：基于时间衰减
            age_hours = self.get_video_age_hours(video_data)
            forget_gate = 1 / (1 + age_hours / 24)  # 24小时后遗忘增加
            
            # 输入门：基于新数据
            if len(views_seq) >= 2:
                recent_change = (views_seq[-1] - views_seq[-2]) / max(views_seq[-2], 1)
                input_gate = min(1.0, max(0.0, recent_change * 10))
            else:
                input_gate = 0.5
            
            # 输出门：基于质量
            quality = self.get_quality_score(video_data)
            output_gate = quality
            
            # 细胞状态更新
            cell_state = velocity * forget_gate + velocity * input_gate * 0.1
            
            # 预测输出
            adjusted_velocity = cell_state * output_gate
            if adjusted_velocity <= 0:
                adjusted_velocity = velocity * 0.5
            
            predicted_hours = remaining / adjusted_velocity
            
            # 置信度
            confidence = min(1.0, 0.5 + len(history) * 0.05 + quality * 0.2)
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={'method': 'lstm_simple', 'sequence_length': len(history)},
            timestamp=datetime.now()
        )
