"""
卡尔曼滤波器
最优状态估计算法，可以处理噪声数据
适用于播放量数据的平滑和预测
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm


class KalmanFilterAlgorithm(BaseAlgorithm):
    """
    Kalman Filter for View Count Prediction
    
    状态空间模型:
    - 状态: [播放量, 增长率]
    - 观测: 实际播放量
    """
    
    name = "卡尔曼滤波器"
    description = "最优状态估计，处理噪声数据"
    category = "时间序列"
    
    def __init__(self):
        super().__init__()
        # 状态转移矩阵
        self.F = np.array([[1, 1], [0, 1]])
        # 观测矩阵
        self.H = np.array([[1, 0]])
        # 过程噪声协方差
        self.Q = np.array([[0.01, 0], [0, 0.001]])
        # 观测噪声协方差
        self.R = np.array([[10000]])
        
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
        if not history_data or len(history_data) < 5:
            return None
            
        try:
            views = [d['view'] for d in history_data]
            
            # 应用卡尔曼滤波
            x, P = self._kalman_filter(views)
            
            if current_views >= target_views:
                return (0, 1.0)
            
            # 从状态估计当前值和增长率
            current_estimate = x[0, 0]
            growth_rate = x[1, 0]
            
            if growth_rate <= 0:
                # 尝试从历史数据估计增长率
                if len(views) >= 2:
                    recent_growth = (views[-1] - views[-5]) / 4 if len(views) >= 5 else views[-1] - views[-2]
                    growth_rate = max(1, recent_growth)
                else:
                    return None
            
            remaining = target_views - current_views
            
            # 预测所需时间
            days_needed = remaining / growth_rate
            
            if days_needed < 0 or days_needed > 3650:
                return None
            
            seconds_needed = int(days_needed * 86400)
            
            # 置信度基于估计协方差
            confidence = self._calculate_confidence(P, growth_rate)
            
            return (seconds_needed, confidence)
            
        except Exception as e:
            print(f"卡尔曼滤波预测失败: {e}")
            return None
    
    def _kalman_filter(
        self, 
        measurements: List[float]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        执行卡尔曼滤波
        
        Args:
            measurements: 观测值列表
            
        Returns:
            (最终状态估计, 最终协方差矩阵)
        """
        # 初始化状态 [播放量, 增长率]
        if len(measurements) >= 2:
            x = np.array([[measurements[0]], 
                         [measurements[1] - measurements[0]]])
        else:
            x = np.array([[measurements[0]], [0]])
        
        # 初始化协方差
        P = np.array([[1000000, 0], [0, 10000]])
        
        for z in measurements[1:]:
            # 预测步骤
            x = self.F @ x
            P = self.F @ P @ self.F.T + self.Q
            
            # 更新步骤
            y = z - (self.H @ x)[0, 0]  # 残差
            S = self.H @ P @ self.H.T + self.R
            K = P @ self.H.T @ np.linalg.inv(S)  # 卡尔曼增益
            
            x = x + K * y
            P = (np.eye(2) - K @ self.H) @ P
        
        return x, P
    
    def _calculate_confidence(
        self, 
        P: np.ndarray,
        growth_rate: float
    ) -> float:
        """计算置信度"""
        # 协方差越小，置信度越高
        position_variance = P[0, 0]
        velocity_variance = P[1, 1]
        
        # 归一化方差
        pos_conf = max(0, 1 - position_variance / 100000000)
        vel_conf = max(0, 1 - velocity_variance / 10000)
        
        # 增长率必须为正
        if growth_rate <= 0:
            vel_conf *= 0.5
        
        confidence = 0.6 * pos_conf + 0.4 * vel_conf
        return min(0.95, max(0.3, confidence))
