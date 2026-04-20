"""
高斯过程回归
非参数化的概率模型，提供不确定性估计
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm


class GaussianProcessAlgorithm(BaseAlgorithm):
    """
    Gaussian Process Regression
    
    使用高斯过程进行非参数化回归
    适用于小样本、需要不确定性估计的场景
    """
    
    name = "高斯过程回归"
    description = "非参数化概率模型，适合小样本"
    category = "概率模型"
    
    def __init__(self):
        super().__init__()
        self.length_scale = 1.0  # RBF核长度尺度
        self.sigma_f = 1.0       # 信号方差
        self.sigma_n = 0.1       # 噪声标准差
        self.X_train = None
        self.y_train = None
        self.K_inv = None
        
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
        if not history_data or len(history_data) < 6:
            return None
            
        try:
            # 准备数据
            X, y = self._prepare_data(history_data)
            
            if len(X) < 5:
                return None
            
            # 训练高斯过程
            self._fit(X, y)
            
            if current_views >= target_views:
                return (0, 1.0)
            
            # 预测未来多个点
            last_t = X[-1][0]
            future_ts = np.array([[last_t + i] for i in range(1, 31)])  # 预测未来30天
            
            predictions, variances = self._predict_points(future_ts)
            
            # 累积预测增长
            cumulative = 0
            days = 0
            for pred in predictions:
                cumulative += max(0, pred)
                days += 1
                if current_views + cumulative >= target_views:
                    break
            
            if days >= 30 and current_views + cumulative < target_views:
                # 需要更远的预测
                remaining = target_views - current_views - cumulative
                avg_growth = np.mean(predictions) if len(predictions) > 0 else 100
                if avg_growth > 0:
                    days += int(remaining / avg_growth)
            
            if days > 3650:
                return None
            
            seconds_needed = days * 86400
            
            # 置信度基于预测方差
            avg_variance = np.mean(variances[:min(days, len(variances))])
            confidence = self._calculate_confidence(avg_variance)
            
            return (seconds_needed, confidence)
            
        except Exception as e:
            print(f"高斯过程预测失败: {e}")
            return None
    
    def _prepare_data(
        self, 
        history_data: List[Dict[str, Any]]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        准备数据
        
        X: 时间步
        y: 日增长量
        """
        X = []
        y = []
        
        for i in range(1, len(history_data)):
            prev = history_data[i-1]
            curr = history_data[i]
            
            t = i
            growth = curr.get('view', 0) - prev.get('view', 0)
            
            X.append([t])
            y.append(growth)
        
        return np.array(X), np.array(y)
    
    def _rbf_kernel(
        self, 
        x1: np.ndarray, 
        x2: np.ndarray
    ) -> np.ndarray:
        """
        RBF核函数
        
        k(x1, x2) = sigma_f^2 * exp(-||x1-x2||^2 / (2*length_scale^2))
        """
        # 计算欧氏距离
        if x1.ndim == 1:
            x1 = x1.reshape(-1, 1)
        if x2.ndim == 1:
            x2 = x2.reshape(-1, 1)
        
        dist_sq = np.sum(x1**2, axis=1).reshape(-1, 1) + \
                  np.sum(x2**2, axis=1) - \
                  2 * x1 @ x2.T
        
        return self.sigma_f**2 * np.exp(-dist_sq / (2 * self.length_scale**2))
    
    def _fit(self, X: np.ndarray, y: np.ndarray):
        """训练高斯过程"""
        self.X_train = X
        self.y_train = y
        
        # 计算核矩阵
        K = self._rbf_kernel(X, X)
        K += self.sigma_n**2 * np.eye(len(X))  # 添加噪声
        
        # 计算逆矩阵
        self.K_inv = np.linalg.inv(K)
    
    def _predict_points(
        self, 
        X_test: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        预测新点
        
        Returns:
            (均值, 方差)
        """
        # 计算测试点与训练点的核
        K_s = self._rbf_kernel(self.X_train, X_test)
        
        # 计算测试点之间的核
        K_ss = self._rbf_kernel(X_test, X_test)
        
        # 预测均值
        mu = K_s.T @ self.K_inv @ self.y_train
        
        # 预测方差
        cov = K_ss - K_s.T @ self.K_inv @ K_s
        var = np.diag(cov)
        
        return mu, var
    
    def _calculate_confidence(self, variance: float) -> float:
        """计算置信度"""
        # 方差越小，置信度越高
        std = np.sqrt(variance)
        
        # 归一化
        confidence = max(0, 1 - std / 10000)
        
        return min(0.9, max(0.3, confidence))
