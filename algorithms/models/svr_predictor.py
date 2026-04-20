"""
支持向量回归 (SVR)
基于支持向量机的回归方法，适用于非线性预测
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm


class SVRPredictorAlgorithm(BaseAlgorithm):
    """
    Support Vector Regression for View Prediction
    
    使用SVR进行播放量预测，适合处理非线性关系
    """
    
    name = "支持向量回归"
    description = "基于SVM的非线性回归预测"
    category = "机器学习"
    
    def __init__(self):
        super().__init__()
        self.epsilon = 0.1
        self.C = 1.0
        self.gamma = 0.1
        
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
        if not history_data or len(history_data) < 10:
            return None
            
        try:
            # 准备特征
            X, y = self._prepare_features(history_data)
            
            if len(X) < 5:
                return None
            
            # 训练SVR模型 (简化版，使用梯度下降)
            weights, bias = self._train_svr(X, y)
            
            if current_views >= target_views:
                return (0, 1.0)
            
            # 预测未来增长
            last_features = X[-1]
            current_growth = np.dot(weights, last_features) + bias
            
            if current_growth <= 0:
                # 从历史估计
                views = [d['view'] for d in history_data]
                current_growth = max(1, (views[-1] - views[0]) / len(views))
            
            remaining = target_views - current_views
            days_needed = remaining / current_growth
            
            if days_needed < 0 or days_needed > 3650:
                return None
            
            seconds_needed = int(days_needed * 86400)
            confidence = self._calculate_confidence(X, y, weights, bias)
            
            return (seconds_needed, confidence)
            
        except Exception as e:
            print(f"SVR预测失败: {e}")
            return None
    
    def _prepare_features(
        self, 
        history_data: List[Dict[str, Any]]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        准备特征和标签
        
        特征: [时间步, 当前播放量, 点赞数, 投币数, 分享数]
        标签: 下一天的增长量
        """
        X = []
        y = []
        
        for i in range(len(history_data) - 1):
            current = history_data[i]
            next_data = history_data[i + 1]
            
            # 特征
            features = [
                i,  # 时间步
                current.get('view', 0),
                current.get('like', 0),
                current.get('coin', 0),
                current.get('share', 0)
            ]
            
            # 标签: 增长量
            growth = next_data.get('view', 0) - current.get('view', 0)
            
            X.append(features)
            y.append(growth)
        
        # 归一化
        X = np.array(X, dtype=float)
        y = np.array(y, dtype=float)
        
        if len(X) > 0:
            self.X_mean = np.mean(X, axis=0)
            self.X_std = np.std(X, axis=0) + 1e-8
            X = (X - self.X_mean) / self.X_std
        
        return X, y
    
    def _train_svr(
        self, 
        X: np.ndarray, 
        y: np.ndarray
    ) -> Tuple[np.ndarray, float]:
        """
        训练简化版SVR模型
        
        Returns:
            (权重, 偏置)
        """
        n_samples, n_features = X.shape
        
        # 初始化
        weights = np.zeros(n_features)
        bias = 0.0
        
        # 梯度下降参数
        lr = 0.01
        epochs = 100
        
        for _ in range(epochs):
            for i in range(n_samples):
                prediction = np.dot(weights, X[i]) + bias
                error = y[i] - prediction
                
                # ε-不敏感损失
                if abs(error) > self.epsilon:
                    # 计算梯度
                    if error > 0:
                        grad_w = -X[i] + self.C * weights / n_samples
                        grad_b = -1
                    else:
                        grad_w = X[i] + self.C * weights / n_samples
                        grad_b = 1
                    
                    # 更新
                    weights -= lr * grad_w
                    bias -= lr * grad_b
        
        return weights, bias
    
    def _calculate_confidence(
        self, 
        X: np.ndarray,
        y: np.ndarray,
        weights: np.ndarray,
        bias: float
    ) -> float:
        """计算置信度"""
        n = len(X)
        
        # 基础置信度
        base_conf = min(0.85, 0.3 + n * 0.03)
        
        # 计算拟合误差
        if n >= 5:
            predictions = X @ weights + bias
            mape = np.mean(np.abs((y - predictions) / (np.abs(y) + 1)))
            fit_quality = max(0, 1 - mape)
            base_conf = 0.5 * base_conf + 0.5 * fit_quality
        
        return min(0.9, base_conf)
