"""
UP主历史表现贝叶斯模型 (UPcaster History Bayesian Model)
利用UP主历史数据，通过贝叶斯估计提升预测准确性

核心思路：
1. 使用UP主历史视频的平均增速作为先验分布
2. 结合当前视频的实际数据，更新后验分布
3. 使用后验分布的均值作为预测速度
"""

import numpy as np
from typing import Dict, Any, List, Optional
from datetime import datetime
from collections import defaultdict
from algorithms.base import BaseAlgorithm, PredictionResult


class UpcasterHistoryBayesianAlgorithm(BaseAlgorithm):
    """UP主历史表现贝叶斯模型
    
    通过贝叶斯推断，将UP主历史表现作为先验，
    结合当前视频数据得到更准确的预测。
    """
    
    name = "UP主历史贝叶斯"
    algorithm_id = "upcaster_history_bayesian"
    description = "利用UP主历史数据，通过贝叶斯估计提升预测准确性"
    category = "贝叶斯模型"
    default_weight = 1.4
    
    def __init__(self):
        super().__init__()
        self.min_history_videos = 3  # 最少需要多少历史视频才能建立可靠的先验
        self.prior_weight = 0.3       # 先验分布的权重
        
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测
        
        Args:
            video_data: 视频数据，可包含：
                - upcaster_history: UP主历史视频的表现数据列表
                - upcaster_avg_velocity: UP主平均增速
                - upcaster_success_rate: UP主成功率（达到某阈值的视频比例）
                - view_count, history_data 等标准字段
            threshold: 目标播放量阈值
            
        Returns:
            PredictionResult
        """
        current_views = video_data.get('view_count', 0)
        
        # 获取UP主历史数据
        upcaster_history = video_data.get('upcaster_history', [])
        upcaster_avg_vel = video_data.get('upcaster_avg_velocity')
        upcaster_success_rate = video_data.get('upcaster_success_rate')
        
        # 计算当前视频的速度
        current_velocity = self.calculate_velocity(video_data)
        
        # 如果没有UP主历史数据，退化为普通预测
        if not upcaster_history and upcaster_avg_vel is None:
            return self._predict_fallback(video_data, threshold, current_velocity)
        
        # 使用贝叶斯更新
        posterior_velocity, confidence = self._bayesian_update(
            current_velocity, upcaster_history, 
            upcaster_avg_vel, upcaster_success_rate, video_data
        )
        
        # 计算预测时间
        if posterior_velocity <= 0:
            predicted_hours = float('inf')
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                predicted_hours = remaining / posterior_velocity
        
        # 构造元数据
        metadata = {
            'prior_velocity': float(upcaster_avg_vel) if upcaster_avg_vel else None,
            'current_velocity': current_velocity,
            'posterior_velocity': posterior_velocity,
            'upcaster_history_count': len(upcaster_history),
            'prior_weight': self.prior_weight,
            'method': 'bayesian_update'
        }
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=posterior_velocity,
            metadata=metadata,
            timestamp=datetime.now()
        )
    
    def _bayesian_update(self, current_vel: float, 
                         history: List[Dict], prior_avg: Optional[float],
                         prior_success: Optional[float],
                         video_data: Dict) -> Tuple[float, float]:
        """贝叶斯更新
        
        使用共轭先验：假设速度服从正态分布，使用正态分布先验
        
        Returns:
            (后验速度, 置信度)
        """
        # 构造先验分布 N(mu_prior, sigma_prior^2)
        if prior_avg is not None:
            mu_prior = prior_avg
            # 根据历史数据数量确定先验方差
            if len(history) >= self.min_history_videos:
                # 有充足历史数据，先验方差小
                sigma_prior_sq = (mu_prior * 0.3) ** 2
            else:
                # 历史数据少，先验方差大
                sigma_prior_sq = (mu_prior * 0.5) ** 2
        else:
            # 从history计算先验
            if len(history) >= self.min_history_videos:
                vels = [h.get('avg_velocity', 0) for h in history]
                mu_prior = np.mean(vels)
                sigma_prior_sq = np.var(vels) + 1e-6
            else:
                # 无先验信息，使用当前速度作为先验
                mu_prior = current_vel if current_vel > 0 else 100.0
                sigma_prior_sq = (mu_prior * 0.5) ** 2
        
        # 当前视频的观测（似然）
        # 使用当前视频的历史数据估计观测方差
        history_data = video_data.get('history_data', [])
        if len(history_data) >= 2:
            # 计算速度的标准差作为观测方差
            vels = self._extract_velocities(history_data)
            if len(vels) >= 2:
                sigma_obs_sq = np.var(vels) + 1e-6
                n_observations = len(vels)
            else:
                sigma_obs_sq = (current_vel * 0.4) ** 2 + 1e-6
                n_observations = 1
        else:
            sigma_obs_sq = (current_vel * 0.5) ** 2 + 1e-6
            n_observations = 1
        
        # 贝叶斯更新（正态分布的共轭先验）
        # 后验均值 = (mu_prior/sigma_prior^2 + n*current_vel/sigma_obs^2) / (1/sigma_prior^2 + n/sigma_obs^2)
        # 为简化，使用加权平均
        prior_weight = self.prior_weight
        obs_weight = 1.0 - prior_weight
        
        if current_vel > 0:
            posterior_mu = prior_weight * mu_prior + obs_weight * current_vel
        else:
            posterior_mu = mu_prior  # 当前无有效速度，完全使用先验
        
        # 置信度计算
        # 历史数据越多、当前数据越充足，置信度越高
        history_bonus = min(0.3, len(history) * 0.05)
        data_bonus = min(0.2, n_observations * 0.05)
        prior_strength = 0.5 if len(history) >= self.min_history_videos else 0.3
        
        confidence = min(0.95, prior_strength + history_bonus + data_bonus)
        
        return max(0, posterior_mu), confidence
    
    def _extract_velocities(self, history_data: List[Dict]) -> List[float]:
        """从history_data中提取速度序列"""
        if len(history_data) < 2:
            return []
        
        vels = []
        for i in range(1, len(history_data)):
            v0 = float(history_data[i-1].get('view_count', 0))
            v1 = float(history_data[i].get('view_count', 0))
            
            t0 = history_data[i-1].get('timestamp', 0)
            t1 = history_data[i].get('timestamp', 0)
            
            # 处理timestamp格式
            if hasattr(t0, 'timestamp'):
                t0 = t0.timestamp()
            elif isinstance(t0, str):
                try:
                    from datetime import datetime as dt
                    t0 = dt.fromisoformat(t0).timestamp()
                except:
                    continue
            
            if hasattr(t1, 'timestamp'):
                t1 = t1.timestamp()
            elif isinstance(t1, str):
                try:
                    from datetime import datetime as dt
                    t1 = dt.fromisoformat(t1).timestamp()
                except:
                    continue
            
            dt_hours = (t1 - t0) / 3600.0
            if dt_hours <= 0:
                continue
            
            vel = (v1 - v0) / dt_hours
            if vel > 0:
                vels.append(vel)
        
        return vels
    
    def _predict_fallback(self, video_data: Dict, threshold: int, 
                          velocity: float) -> PredictionResult:
        """退化为普通预测（无UP主历史数据）"""
        current_views = video_data.get('view_count', 0)
        
        if velocity <= 0:
            predicted_hours = float('inf')
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                predicted_hours = remaining / velocity
                confidence = 0.4  # 无历史数据，置信度较低
        
        metadata = {
            'method': 'fallback_no_history',
            'prior_velocity': None,
            'posterior_velocity': velocity
        }
        
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata=metadata,
            timestamp=datetime.now()
        )
