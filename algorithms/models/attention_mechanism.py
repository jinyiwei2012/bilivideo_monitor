"""
注意力机制预测模型
模拟Transformer的注意力机制，关注重要的时间点
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm


class AttentionMechanismAlgorithm(BaseAlgorithm):
    """
    Attention-Based View Prediction
    
    使用注意力机制关注历史数据中的重要时间点
    类似于Transformer的简化版本
    """
    
    name = "注意力机制模型"
    description = "关注重要时间点，类似Transformer"
    category = "深度学习"
    
    def __init__(self):
        super().__init__()
        self.d_model = 16  # 模型维度
        self.n_heads = 2   # 注意力头数
        
    def predict(
        self,
        current_views: int,
        target_views: int,
        history_data: List[Dict[str, Any]],
        video_info: Dict[str, Any]
    ) -> Optional[Tuple[int, float]]:
        """
        预测到达目标播放量所需时间
        """
        if not history_data or len(history_data) < 8:
            return None
            
        try:
            # 准备序列数据
            sequence = self._prepare_sequence(history_data)
            
            if len(sequence) < 5:
                return None
            
            # 应用注意力机制
            context = self._apply_attention(sequence)
            
            if current_views >= target_views:
                return (0, 1.0)
            
            # 基于上下文预测增长率
            predicted_growth = self._predict_growth(context, sequence)
            
            if predicted_growth <= 0:
                views = [d['view'] for d in history_data]
                predicted_growth = max(1, np.mean([views[i] - views[i-1] 
                                                   for i in range(1, len(views))]))
            
            remaining = target_views - current_views
            days_needed = remaining / predicted_growth
            
            if days_needed < 0 or days_needed > 3650:
                return None
            
            seconds_needed = int(days_needed * 86400)
            confidence = self._calculate_confidence(sequence, context)
            
            return (seconds_needed, confidence)
            
        except Exception as e:
            print(f"注意力机制预测失败: {e}")
            return None
    
    def _prepare_sequence(
        self, 
        history_data: List[Dict[str, Any]]
    ) -> np.ndarray:
        """
        准备序列数据
        
        每个时间步包含: [播放量, 增长率, 点赞率, 时间编码]
        """
        sequence = []
        
        for i, data in enumerate(history_data):
            view = data.get('view', 0)
            like = data.get('like', 0)
            
            # 计算增长率
            if i > 0:
                prev_view = history_data[i-1].get('view', 0)
                growth_rate = view - prev_view
            else:
                growth_rate = 0
            
            # 点赞率
            like_rate = like / max(view, 1)
            
            # 时间编码 (位置编码简化版)
            time_enc = np.sin(i / 10)
            
            sequence.append([view / 10000, growth_rate / 1000, like_rate * 10, time_enc])
        
        return np.array(sequence)
    
    def _apply_attention(self, sequence: np.ndarray) -> np.ndarray:
        """
        应用简化版注意力机制
        
        使用缩放点积注意力
        """
        n = len(sequence)
        
        # 使用最后几个时间步作为查询
        query = sequence[-3:].mean(axis=0)  # [d_model]
        
        # 所有时间步作为键和值
        keys = sequence  # [n, d_model]
        values = sequence[:, 1]  # 使用增长率作为值 [n]
        
        # 计算注意力分数
        scores = np.dot(keys, query) / np.sqrt(self.d_model)  # [n]
        
        # Softmax
        exp_scores = np.exp(scores - np.max(scores))
        attention_weights = exp_scores / np.sum(exp_scores)
        
        # 加权求和
        context = np.sum(attention_weights * values)
        
        return context
    
    def _predict_growth(
        self, 
        context: float, 
        sequence: np.ndarray
    ) -> float:
        """
        基于上下文预测增长率
        """
        # 最近的增长率
        recent_growth = sequence[-1][1] * 1000  # 反归一化
        
        # 注意力上下文
        attention_growth = context * 1000  # 反归一化
        
        # 结合两者
        predicted = 0.6 * recent_growth + 0.4 * attention_growth
        
        return max(1, predicted)
    
    def _calculate_confidence(
        self, 
        sequence: np.ndarray,
        context: float
    ) -> float:
        """计算置信度"""
        n = len(sequence)
        
        # 基础置信度
        base_conf = min(0.85, 0.3 + n * 0.025)
        
        # 序列稳定性
        growth_rates = sequence[:, 1]
        if len(growth_rates) > 1:
            cv = np.std(growth_rates) / (np.mean(np.abs(growth_rates)) + 0.001)
            stability = max(0, 1 - cv)
            base_conf = 0.6 * base_conf + 0.4 * stability
        
        return min(0.9, base_conf)
