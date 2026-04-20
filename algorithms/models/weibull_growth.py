"""
Weibull增长模型
灵活的增长模型，可以模拟多种增长模式
适用于不同生命周期的视频增长预测
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from scipy.optimize import curve_fit
from algorithms.base import BaseAlgorithm


class WeibullGrowthAlgorithm(BaseAlgorithm):
    """
    Weibull Growth Model
    
    公式: V(t) = K * (1 - exp(-(t/λ)^k))
    其中:
    - K: 最大播放量
    - λ: 尺度参数
    - k: 形状参数 (k<1递减, k=1指数, k>1递增)
    """
    
    name = "Weibull增长模型"
    description = "灵活的增长模型，适应不同生命周期"
    category = "扩散模型"
    
    def __init__(self):
        super().__init__()
        self.K = 1000000  # 最大播放量
        self.lam = 30     # 尺度参数
        self.k = 1.5      # 形状参数
        
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
        if not history_data or len(history_data) < 3:
            return None
            
        try:
            times, views = self._prepare_data(history_data)
            
            if len(times) < 3:
                return None
            
            # 拟合Weibull曲线
            self._fit_curve(times, views, video_info)
            
            if current_views >= target_views:
                return (0, 1.0)
            
            if target_views >= self.K * 0.99:
                self.K = target_views * 1.2
            
            current_t = times[-1]
            target_t = self._find_time_for_views(target_views)
            
            if target_t is None:
                return None
                
            days_needed = target_t - current_t
            
            if days_needed < 0 or days_needed > 3650:
                return None
            
            seconds_needed = int(days_needed * 86400)
            confidence = self._calculate_confidence(times, views)
            
            return (seconds_needed, confidence)
            
        except Exception as e:
            print(f"Weibull模型预测失败: {e}")
            return None
    
    def _prepare_data(
        self, 
        history_data: List[Dict[str, Any]]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """准备数据"""
        times = []
        views = []
        
        base_time = datetime.strptime(
            history_data[0]['timestamp'], 
            '%Y-%m-%d %H:%M:%S'
        )
        
        for data in history_data:
            t = datetime.strptime(data['timestamp'], '%Y-%m-%d %H:%M:%S')
            days = (t - base_time).total_seconds() / 86400
            times.append(max(0.1, days))  # 避免t=0
            views.append(data['view'])
        
        return np.array(times), np.array(views)
    
    def _weibull(self, t, K, lam, k):
        """Weibull累积分布函数"""
        return K * (1 - np.exp(-np.power(t / lam, k)))
    
    def _fit_curve(
        self, 
        times: np.ndarray, 
        views: np.ndarray,
        video_info: Dict[str, Any]
    ):
        """拟合Weibull曲线"""
        try:
            K_est = max(views) * 2.5
            lam_est = np.median(times) if len(times) > 0 else 30
            k_est = 1.5
            
            p0 = [K_est, lam_est, k_est]
            bounds = ([max(views), 1, 0.1], [K_est * 10, times[-1] * 10, 5.0])
            
            popt, _ = curve_fit(
                self._weibull, times, views,
                p0=p0, bounds=bounds, maxfev=5000
            )
            
            self.K, self.lam, self.k = popt
            
        except Exception:
            self.K = max(views) * 3
            self.lam = 30
            self.k = 1.5
            
            if 'follower' in video_info:
                self.K = max(self.K, video_info['follower'] * 2.5)
    
    def _find_time_for_views(self, target_views: int) -> Optional[float]:
        """找到达到目标播放量所需时间"""
        try:
            # V = K * (1 - exp(-(t/λ)^k))
            # 1 - V/K = exp(-(t/λ)^k)
            # -ln(1 - V/K) = (t/λ)^k
            # t = λ * (-ln(1 - V/K))^(1/k)
            
            if target_views >= self.K:
                return None
            
            ratio = 1 - target_views / self.K
            if ratio <= 0 or ratio >= 1:
                return None
            
            t = self.lam * np.power(-np.log(ratio), 1.0 / self.k)
            return max(0, t)
        except Exception:
            return None
    
    def _calculate_confidence(
        self, 
        times: np.ndarray, 
        views: np.ndarray
    ) -> float:
        """计算置信度"""
        n = len(times)
        base_conf = min(0.9, 0.4 + n * 0.03)
        
        if n >= 5:
            try:
                predicted = self._weibull(times, self.K, self.lam, self.k)
                mape = np.mean(np.abs((views - predicted) / (views + 1)))
                fit_quality = max(0, 1 - mape)
                base_conf = 0.5 * base_conf + 0.5 * fit_quality
            except Exception:
                pass
        
        return min(0.95, base_conf)
