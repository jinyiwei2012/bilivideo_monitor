"""
多层感知机 (MLP)
经典的前馈神经网络，用于播放量预测
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm


class MLPPredictorAlgorithm(BaseAlgorithm):
    """
    Multi-Layer Perceptron for View Prediction
    
    使用两层神经网络进行播放量增长预测
    """
    
    name = "多层感知机"
    description = "经典前馈神经网络预测"
    category = "深度学习"
    
    def __init__(self):
        super().__init__()
        self.input_size = 6
        self.hidden_size = 16
        self.output_size = 1
        
        # 初始化权重
        self.W1 = np.random.randn(self.input_size, self.hidden_size) * 0.1
        self.b1 = np.zeros(self.hidden_size)
        self.W2 = np.random.randn(self.hidden_size, self.output_size) * 0.1
        self.b2 = np.zeros(self.output_size)
        
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
            # 准备训练数据
            X, y = self._prepare_data(history_data)
            
            if len(X) < 5:
                return None
            
            # 训练网络
            self._train(X, y)
            
            if current_views >= target_views:
                return (0, 1.0)
            
            # 预测未来增长
            last_features = X[-1].reshape(1, -1)
            predicted_growth = self._forward(last_features)[0, 0]
            
            if predicted_growth <= 0:
                views = [d['view'] for d in history_data]
                predicted_growth = max(1, np.mean([views[i] - views[i-1] 
                                                   for i in range(1, len(views))]))
            
            remaining = target_views - current_views
            days_needed = remaining / predicted_growth
            
            if days_needed < 0 or days_needed > 3650:
                return None
            
            seconds_needed = int(days_needed * 86400)
            confidence = self._calculate_confidence(X, y)
            
            return (seconds_needed, confidence)
            
        except Exception as e:
            print(f"MLP预测失败: {e}")
            return None
    
    def _prepare_data(
        self, 
        history_data: List[Dict[str, Any]]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        准备训练数据
        
        特征: [播放量, 点赞, 投币, 分享, 评论, 时间步]
        标签: 下一天的增长量
        """
        X = []
        y = []
        
        for i in range(len(history_data) - 1):
            current = history_data[i]
            next_data = history_data[i + 1]
            
            features = [
                current.get('view', 0) / 10000,  # 归一化
                current.get('like', 0) / 1000,
                current.get('coin', 0) / 100,
                current.get('share', 0) / 100,
                current.get('reply', 0) / 100,
                i / 10  # 时间步
            ]
            
            growth = next_data.get('view', 0) - current.get('view', 0)
            
            X.append(features)
            y.append(growth)
        
        return np.array(X), np.array(y).reshape(-1, 1)
    
    def _relu(self, x: np.ndarray) -> np.ndarray:
        """ReLU激活函数"""
        return np.maximum(0, x)
    
    def _forward(self, X: np.ndarray) -> np.ndarray:
        """
        前向传播
        
        Returns:
            输出预测值
        """
        # 第一层
        self.z1 = X @ self.W1 + self.b1
        self.a1 = self._relu(self.z1)
        
        # 输出层
        self.z2 = self.a1 @ self.W2 + self.b2
        
        return self.z2
    
    def _train(self, X: np.ndarray, y: np.ndarray, epochs: int = 200, lr: float = 0.001):
        """训练网络"""
        n_samples = len(X)
        
        for _ in range(epochs):
            # 前向传播
            output = self._forward(X)
            
            # 计算损失和梯度
            error = output - y
            
            # 输出层梯度
            dW2 = self.a1.T @ error / n_samples
            db2 = np.mean(error, axis=0)
            
            # 隐藏层梯度
            da1 = error @ self.W2.T
            dz1 = da1 * (self.z1 > 0).astype(float)  # ReLU导数
            dW1 = X.T @ dz1 / n_samples
            db1 = np.mean(dz1, axis=0)
            
            # 更新权重
            self.W2 -= lr * dW2
            self.b2 -= lr * db2
            self.W1 -= lr * dW1
            self.b1 -= lr * db1
    
    def _calculate_confidence(self, X: np.ndarray, y: np.ndarray) -> float:
        """计算置信度"""
        n = len(X)
        
        # 基础置信度
        base_conf = min(0.85, 0.3 + n * 0.025)
        
        # 计算拟合误差
        if n >= 5:
            predictions = self._forward(X)
            mape = np.mean(np.abs((y - predictions) / (np.abs(y) + 1)))
            fit_quality = max(0, 1 - min(1, mape))
            base_conf = 0.5 * base_conf + 0.5 * fit_quality
        
        return min(0.9, base_conf)
