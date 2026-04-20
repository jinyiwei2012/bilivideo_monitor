"""
Bass扩散模型
基于创新扩散理论，模拟产品/内容在市场中的传播过程
适用于视频播放量的病毒式传播预测
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from algorithms.base import BaseAlgorithm


class BassDiffusionAlgorithm(BaseAlgorithm):
    """
    Bass Diffusion Model
    
    公式: f(t) = [p + q*F(t)/m] * [m - F(t)]
    其中:
    - p: 创新系数 (外部影响)
    - q: 模仿系数 (内部口碑传播)
    - m: 市场潜力 (最大播放量)
    - F(t): 到时间t的累积采用者
    """
    
    name = "Bass扩散模型"
    description = "基于创新扩散理论，模拟病毒式传播过程"
    category = "扩散模型"
    
    def __init__(self):
        super().__init__()
        self.p = 0.03  # 创新系数
        self.q = 0.38  # 模仿系数 (社交媒体通常较高)
        self.m = 10000000  # 市场潜力 (默认1000万)
        
    def predict(
        self,
        current_views: int,
        target_views: int,
        history_data: List[Dict[str, Any]],
        video_info: Dict[str, Any]
    ) -> Optional[Tuple[int, float]]:
        """
        预测到达目标播放量所需时间
        
        Args:
            current_views: 当前播放量
            target_views: 目标播放量
            history_data: 历史数据列表
            video_info: 视频信息
            
        Returns:
            (预测秒数, 置信度) 或 None
        """
        if not history_data or len(history_data) < 2:
            return None
            
        try:
            # 从视频信息调整参数
            self._adjust_parameters(video_info)
            
            # 计算当前时间点
            current_time = datetime.now()
            earliest = datetime.strptime(history_data[0]['timestamp'], '%Y-%m-%d %H:%M:%S')
            t_days = (current_time - earliest).total_seconds() / 86400
            
            # 如果已达到目标
            if current_views >= target_views:
                return (0, 1.0)
            
            # 使用Bass模型预测
            # F(t) = m * (1 - exp(-(p+q)*t)) / (1 + (q/p)*exp(-(p+q)*t))
            
            # 估计当前处于曲线的哪个位置
            # 反解t来估计当前时间
            
            # 预测未来增长
            days_needed = self._predict_days_to_target(
                current_views, target_views, t_days
            )
            
            if days_needed is None or days_needed > 3650:  # 超过10年视为无效
                return None
                
            seconds_needed = int(days_needed * 86400)
            
            # 计算置信度 (基于数据点数量和拟合质量)
            confidence = self._calculate_confidence(history_data)
            
            return (seconds_needed, confidence)
            
        except Exception as e:
            print(f"Bass扩散模型预测失败: {e}")
            return None
    
    def _adjust_parameters(self, video_info: Dict[str, Any]):
        """根据视频特征调整Bass模型参数"""
        # 根据粉丝数调整市场潜力
        if 'follower' in video_info:
            follower = video_info['follower']
            # 市场潜力与粉丝数相关
            self.m = max(follower * 3, 1000000)
        
        # 根据互动率调整模仿系数
        if 'like' in video_info and 'view' in video_info:
            like_rate = video_info['like'] / max(video_info['view'], 1)
            # 高互动率意味着更强的口碑传播
            self.q = min(0.5, 0.3 + like_rate * 10)
        
        # 根据视频质量调整创新系数
        if 'quality_score' in video_info:
            quality = video_info['quality_score']
            self.p = min(0.1, 0.02 + quality * 0.05)
    
    def _predict_days_to_target(
        self, 
        current_views: int, 
        target_views: int,
        current_t: float
    ) -> Optional[float]:
        """预测到达目标所需天数"""
        
        # Bass模型累积函数
        def bass_cumulative(t):
            if self.p + self.q == 0:
                return 0
            exp_term = np.exp(-(self.p + self.q) * t)
            return self.m * (1 - exp_term) / (1 + (self.q / self.p) * exp_term)
        
        # 如果目标超过市场潜力，调整市场潜力
        if target_views > self.m * 0.95:
            self.m = target_views * 1.2
        
        # 使用数值方法求解
        # 二分查找找到目标时间
        t_low, t_high = current_t, current_t + 365 * 10  # 最多10年
        
        for _ in range(100):  # 最大迭代次数
            t_mid = (t_low + t_high) / 2
            views_mid = bass_cumulative(t_mid)
            
            if abs(views_mid - target_views) < self.m * 0.001:
                return t_mid - current_t
            
            if views_mid < target_views:
                t_low = t_mid
            else:
                t_high = t_mid
        
        return t_high - current_t
    
    def _calculate_confidence(self, history_data: List[Dict[str, Any]]) -> float:
        """计算预测置信度"""
        n_points = len(history_data)
        
        # 基础置信度
        base_confidence = min(0.95, 0.5 + n_points * 0.02)
        
        # 如果数据点足够多，计算拟合质量
        if n_points >= 5:
            try:
                views = [d['view'] for d in history_data]
                # 检查增长是否平滑
                growth_rates = []
                for i in range(1, len(views)):
                    if views[i-1] > 0:
                        rate = (views[i] - views[i-1]) / views[i-1]
                        growth_rates.append(rate)
                
                if growth_rates:
                    # 变异系数越小，置信度越高
                    cv = np.std(growth_rates) / (np.mean(growth_rates) + 1e-10)
                    fit_quality = max(0, 1 - cv)
                    base_confidence = 0.6 * base_confidence + 0.4 * fit_quality
                    
            except Exception:
                pass
        
        return min(0.95, base_confidence)
