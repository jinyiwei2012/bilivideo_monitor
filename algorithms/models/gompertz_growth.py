"""
Gompertz增长曲线模型
描述增长初期慢、中期快、后期饱和的S型增长过程
适用于视频播放量的长期增长预测
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from scipy.optimize import curve_fit
from algorithms.base import BaseAlgorithm


class GompertzGrowthAlgorithm(BaseAlgorithm):
    """
    Gompertz Growth Curve Model
    
    公式: V(t) = a * exp(-b * exp(-c * t))
    其中:
    - a: 渐近线 (最大播放量)
    - b: 位移参数
    - c: 增长率参数
    - t: 时间
    """
    
    name = "Gompertz增长曲线"
    description = "S型增长模型，适用于长期增长预测"
    category = "扩散模型"
    
    def __init__(self):
        super().__init__()
        self.a = 1000000  # 渐近线
        self.b = 5.0      # 位移
        self.c = 0.1      # 增长率
        
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
            # 准备数据
            times, views = self._prepare_data(history_data)
            
            if len(times) < 3:
                return None
            
            # 拟合Gompertz曲线
            self._fit_curve(times, views, video_info)
            
            # 如果已达到目标
            if current_views >= target_views:
                return (0, 1.0)
            
            # 预测到达目标的时间
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
            print(f"Gompertz模型预测失败: {e}")
            return None
    
    def _prepare_data(
        self, 
        history_data: List[Dict[str, Any]]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """准备时间和播放量数据"""
        times = []
        views = []
        
        base_time = datetime.strptime(
            history_data[0]['timestamp'], 
            '%Y-%m-%d %H:%M:%S'
        )
        
        for data in history_data:
            t = datetime.strptime(data['timestamp'], '%Y-%m-%d %H:%M:%S')
            days = (t - base_time).total_seconds() / 86400
            times.append(days)
            views.append(data['view'])
        
        return np.array(times), np.array(views)
    
    def _gompertz(self, t, a, b, c):
        """Gompertz函数"""
        return a * np.exp(-b * np.exp(-c * t))
    
    def _fit_curve(
        self, 
        times: np.ndarray, 
        views: np.ndarray,
        video_info: Dict[str, Any]
    ):
        """拟合Gompertz曲线"""
        try:
            # 设置初始参数
            max_views = max(views) * 3  # 估计最大播放量
            p0 = [max_views, 5.0, 0.1]
            
            # 设置边界
            bounds = ([max(views), 0.1, 0.001], [max_views * 10, 20.0, 1.0])
            
            # 拟合
            popt, _ = curve_fit(
                self._gompertz, times, views, 
                p0=p0, bounds=bounds, maxfev=5000
            )
            
            self.a, self.b, self.c = popt
            
        except Exception:
            # 拟合失败，使用启发式参数
            self.a = max(views) * 2.5
            self.b = 4.0
            self.c = 0.15
            
            # 根据视频信息调整
            if 'follower' in video_info:
                self.a = max(self.a, video_info['follower'] * 2)
    
    def _find_time_for_views(self, target_views: int) -> Optional[float]:
        """找到达到目标播放量所需时间"""
        # 反解Gompertz方程
        # V = a * exp(-b * exp(-c * t))
        # ln(V/a) = -b * exp(-c * t)
        # -ln(V/a) / b = exp(-c * t)
        # ln(-ln(V/a) / b) = -c * t
        # t = -ln(-ln(V/a) / b) / c
        
        if target_views >= self.a * 0.99:
            return None  # 无法达到
        
        try:
            inner = -np.log(target_views / self.a) / self.b
            if inner <= 0:
                return None
            t = -np.log(inner) / self.c
            return max(0, t)
        except Exception:
            return None
    
    def _calculate_confidence(
        self, 
        times: np.ndarray, 
        views: np.ndarray
    ) -> float:
        """计算预测置信度"""
        n = len(times)
        
        # 基础置信度
        base_conf = min(0.9, 0.4 + n * 0.03)
        
        # 计算拟合误差
        if n >= 5:
            try:
                predicted = self._gompertz(times, self.a, self.b, self.c)
                mse = np.mean((views - predicted) ** 2)
                rmse = np.sqrt(mse)
                
                # 归一化误差
                relative_error = rmse / (np.mean(views) + 1)
                fit_quality = max(0, 1 - relative_error)
                
                base_conf = 0.5 * base_conf + 0.5 * fit_quality
            except Exception:
                pass
        
        return min(0.95, base_conf)
