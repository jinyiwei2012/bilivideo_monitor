"""
预测算法基类
所有预测算法必须继承此基类
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
import time


class BasePredictionAlgorithm(ABC):
    """预测算法基类"""
    
    name: str = "基础算法"
    description: str = "算法描述"
    
    def __init__(self):
        self.weight = 1.0  # 初始权重
        self.last_prediction = None  # 上次预测值
        self.accuracy_history = []  # 准确率历史
    
    @abstractmethod
    def predict(self, history: List[Tuple], current_value: float, **kwargs) -> Dict:
        """
        执行预测
        
        Args:
            history: 历史数据 [(timestamp, value), ...]
            current_value: 当前值
            **kwargs: 其他参数
            
        Returns:
            Dict: 预测结果 {
                'prediction': float,  # 预测值
                'confidence': float,   # 置信度 0-1
                'metadata': dict      # 其他元数据
            }
        """
        pass
    
    def update_accuracy(self, predicted: float, actual: float):
        """更新算法准确率"""
        if actual > 0:
            error = abs(predicted - actual) / actual
            accuracy = max(0, 1 - error)
        else:
            accuracy = 0.5 if predicted == actual else 0
        
        self.accuracy_history.append(accuracy)
        
        # 只保留最近20条记录
        if len(self.accuracy_history) > 20:
            self.accuracy_history = self.accuracy_history[-20:]
    
    def get_accuracy(self) -> float:
        """获取平均准确率"""
        if not self.accuracy_history:
            return 0.5
        return sum(self.accuracy_history) / len(self.accuracy_history)
    
    def set_weight(self, weight: float):
        """设置权重"""
        self.weight = max(0.01, min(10.0, weight))
    
    def get_info(self) -> Dict:
        """获取算法信息"""
        return {
            'name': self.name,
            'description': self.description,
            'weight': self.weight,
            'accuracy': self.get_accuracy(),
        }
