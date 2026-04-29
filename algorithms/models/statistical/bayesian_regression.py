"""
贝叶斯回归
基于贝叶斯推断的回归方法，提供不确定性估计
"""

import numpy as np
from typing import List, Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class BayesianRegressionAlgorithm(BaseAlgorithm):
    """
    Bayesian Linear Regression
    
    使用贝叶斯方法进行回归，提供预测的不确定性估计
    """
    
    name = "贝叶斯回归"
    algorithm_id = "bayesian_regression"
    description = "基于贝叶斯推断，提供不确定性估计"
    category = "概率模型"
    
    def __init__(self):
        super().__init__()
        self.alpha = 1.0  # 先验精度
        self.beta = 1.0   # 噪声精度
        self.mean = None
        self.cov = None
        
    def predict(
        self,
        video_data: Dict[str, Any],
        threshold: int = 100000
    ) -> PredictionResult:
        """
        预测到达目标播放量所需时间
        """
        current_views = video_data.get('view_count', 0)
        history_data = video_data.get('history_data', [])
        velocity = self.calculate_velocity(video_data)
        
        if not history_data or len(history_data) < 6:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=float('inf'),
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={'error': 'Insufficient data'},
                timestamp=datetime.now()
            )
            
        try:
            # 准备数据
            X, y = self._prepare_data(history_data)
            
            if len(X) < 5:
                return PredictionResult(
                    algorithm_name=self.name,
                    algorithm_id=self.algorithm_id,
                    target_threshold=threshold,
                    predicted_hours=float('inf'),
                    confidence=0.0,
                    current_views=current_views,
                    current_velocity=velocity,
                    metadata={'error': 'Insufficient processed data'},
                    timestamp=datetime.now()
                )
            
            # 贝叶斯推断
            self._bayesian_inference(X, y)
            
            if current_views >= threshold:
                return PredictionResult(
                    algorithm_name=self.name,
                    algorithm_id=self.algorithm_id,
                    target_threshold=threshold,
                    predicted_hours=0,
                    confidence=1.0,
                    current_views=current_views,
                    current_velocity=velocity,
                    metadata={'method': 'bayesian_regression', 'status': 'already_reached'},
                    timestamp=datetime.now()
                )
            
            # 预测
            last_features = X[-1]
            predicted_growth = np.dot(self.mean, last_features)
            
            # 预测不确定性
            uncertainty = np.sqrt(last_features @ self.cov @ last_features)
            
            if predicted_growth <= 0:
                views = [d.get('view_count', 0) for d in history_data]
                predicted_growth = max(1, np.mean([views[i] - views[i-1] 
                                                   for i in range(1, len(views))]))
            
            remaining = threshold - current_views
            days_needed = remaining / predicted_growth
            
            if days_needed < 0 or days_needed > 3650:
                return PredictionResult(
                    algorithm_name=self.name,
                    algorithm_id=self.algorithm_id,
                    target_threshold=threshold,
                    predicted_hours=float('inf'),
                    confidence=0.0,
                    current_views=current_views,
                    current_velocity=velocity,
                    metadata={'error': 'Prediction too far'},
                    timestamp=datetime.now()
                )
            
            predicted_hours = days_needed * 24
            
            # 置信度基于不确定性
            confidence = self._calculate_confidence(uncertainty, predicted_growth)
            
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={
                    'method': 'bayesian_regression',
                    'uncertainty': float(uncertainty),
                    'predicted_growth': float(predicted_growth)
                },
                timestamp=datetime.now()
            )
            
        except Exception as e:
            print(f"贝叶斯回归预测失败: {e}")
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=float('inf'),
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={'error': str(e)},
                timestamp=datetime.now()
            )
    
    def _prepare_data(
        self, 
        history_data: List[Dict[str, Any]]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        准备数据
        
        特征: [1, 播放量, 点赞, 投币, 分享]
        标签: 下一天的增长量
        """
        X = []
        y = []
        
        for i in range(len(history_data) - 1):
            current = history_data[i]
            next_data = history_data[i + 1]
            
            features = [
                1.0,  # 偏置项
                current.get('view', 0) / 10000,
                current.get('like', 0) / 1000,
                current.get('coin', 0) / 100,
                current.get('share', 0) / 100
            ]
            
            growth = next_data.get('view', 0) - current.get('view', 0)
            
            X.append(features)
            y.append(growth)
        
        return np.array(X), np.array(y)
    
    def _bayesian_inference(self, X: np.ndarray, y: np.ndarray):
        """
        执行贝叶斯推断
        
        计算后验分布: p(w|y,X) ~ N(mean, cov)
        """
        n_features = X.shape[1]
        
        # 先验协方差
        prior_cov = np.eye(n_features) / self.alpha
        
        # 后验协方差
        # cov = (alpha*I + beta*X^T*X)^-1
        self.cov = np.linalg.inv(
            self.alpha * np.eye(n_features) + 
            self.beta * X.T @ X
        )
        
        # 后验均值
        # mean = beta * cov * X^T * y
        self.mean = self.beta * self.cov @ X.T @ y
    
    def _calculate_confidence(
        self, 
        uncertainty: float,
        predicted_growth: float
    ) -> float:
        """计算置信度"""
        # 不确定性越低，置信度越高
        # 归一化不确定性
        relative_uncertainty = uncertainty / (abs(predicted_growth) + 100)
        
        confidence = max(0, 1 - relative_uncertainty * 0.5)
        
        # 确保预测为正
        if predicted_growth <= 0:
            confidence *= 0.5
        
        return min(0.95, max(0.3, confidence))
