"""
生存分析算法 (Survival Analysis)
预测视频"停止增长"的时间，使用Kaplan-Meier估计的简化版
"""

import numpy as np
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class SurvivalAnalysisAlgorithm(BaseAlgorithm):
    """生存分析算法
    
    预测视频"停止增长"的时间（即播放量基本稳定的时间）。
    使用Kaplan-Meier估计的简化版，结合视频的生命周期特征。
    """
    
    name = "生存分析"
    algorithm_id = "survival_analysis"
    description = "预测视频停止增长的时间，调整长期预测策略"
    category = "统计模型"
    default_weight = 1.2
    
    def __init__(self):
        super().__init__()
        self.growth_threshold = 1.0  # 播放量/小时低于此值视为"停止增长"
        self.min_data_points = 5
        
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测
        
        Args:
            video_data: 视频数据，包含 history_data 列表
            threshold: 目标播放量阈值
            
        Returns:
            PredictionResult
        """
        current_views = video_data.get('view_count', 0)
        history = video_data.get('history_data', [])
        
        if len(history) < self.min_data_points:
            # 数据太少，使用简单预测
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.3, 
                survival_prob=0.5,
                predicted_growth_stop_hours=float('inf'),
                reason='insufficient_data'
            )
        
        # 提取时间和播放量序列
        views, timestamps = self._extract_series(history)
        
        if len(views) < self.min_data_points:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.3,
                survival_prob=0.5,
                predicted_growth_stop_hours=float('inf'),
                reason='short_series'
            )
        
        # 计算速度序列
        velocities, vel_times = self._calculate_velocity_series(views, timestamps)
        
        if len(velocities) < 3:
            velocity = velocities[-1] if len(velocities) > 0 else 0.0
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.4,
                survival_prob=0.5,
                predicted_growth_stop_hours=float('inf'),
                reason='short_velocity_series'
            )
        
        # 使用Kaplan-Meier简化版估计生存函数
        survival_prob, growth_stop_hours = self._kaplan_meier_simplified(
            velocities, vel_times, current_views
        )
        
        # 根据生存概率调整预测
        adjusted_velocity, confidence = self._adjust_prediction(
            velocities, survival_prob, growth_stop_hours
        )
        
        return self._make_result(
            current_views, threshold, adjusted_velocity,
            confidence=confidence,
            survival_prob=survival_prob,
            predicted_growth_stop_hours=growth_stop_hours,
            reason='kaplan_meier'
        )
    
    def _kaplan_meier_simplified(self, velocities: np.ndarray, 
                                  vel_times: np.ndarray,
                                  current_views: int) -> Tuple[float, float]:
        """Kaplan-Meier生存分析简化版
        
        简化假设：
        1. 速度低于阈值是"事件"（停止增长）
        2. 使用经验分布函数代替K-M估计
        
        Returns:
            (生存概率, 预测增长停止时间(小时))
        """
        # 定义"事件"：速度低于阈值
        events = velocities < self.growth_threshold
        
        if np.any(events):
            # 找到第一个"事件"发生的时间
            first_event_idx = np.argmax(events)
            event_time = vel_times[first_event_idx]
            
            # 计算当前时间到事件时间的间隔
            current_time = vel_times[-1]
            hours_to_event = (event_time - current_time) / 3600.0
            
            if hours_to_event > 0:
                # 还在增长，但预测会停止
                survival_prob = 0.3  # 接近事件，生存概率低
                return survival_prob, hours_to_event
            else:
                # 已经停止增长
                survival_prob = 0.1
                return survival_prob, 0.0
        
        # 没有发生"事件"，所有速度都高于阈值
        # 使用趋势外推预测何时会低于阈值
        if len(velocities) >= 3:
            # 计算速度衰减率
            accel = self._calculate_acceleration(velocities)
            
            if accel < 0:
                # 速度在下降，预测何时低于阈值
                current_vel = velocities[-1]
                decay_rate = abs(accel)
                
                if decay_rate > 0:
                    hours_to_threshold = (current_vel - self.growth_threshold) / decay_rate
                    hours_to_threshold = max(0, hours_to_threshold)
                    
                    # 根据时间长短计算生存概率
                    if hours_to_threshold > 168:  # 一周后
                        survival_prob = 0.8
                    elif hours_to_threshold > 48:  # 两天后
                        survival_prob = 0.6
                    elif hours_to_threshold > 12:  # 12小时后
                        survival_prob = 0.4
                    else:
                        survival_prob = 0.2
                    
                    return survival_prob, hours_to_threshold
            
        # 速度稳定或上升，生存概率高
        # 使用历史数据的趋势来判断
        if len(velocities) >= 2:
            trend = np.polyfit(range(len(velocities)), velocities, 1)[0]
            
            if trend > 0:
                # 速度在上升，生存概率很高
                return 0.9, float('inf')
            elif abs(trend) < 0.1 * np.mean(velocities):
                # 速度稳定，生存概率中等
                return 0.7, 168.0  # 预计一周后可能停止
        
        # 默认：生存概率中等
        return 0.5, 72.0  # 默认3天后可能停止增长
    
    def _adjust_prediction(self, velocities: np.ndarray,
                           survival_prob: float,
                           growth_stop_hours: float) -> Tuple[float, float]:
        """根据生存概率调整预测
        
        Returns:
            (调整后的速度, 置信度)
        """
        current_vel = velocities[-1]
        
        if survival_prob < 0.3:
            # 即将停止增长，降低速度预测
            adjusted_vel = current_vel * 0.5
            confidence = 0.7
        elif survival_prob < 0.5:
            # 可能即将停止增长
            adjusted_vel = current_vel * 0.7
            confidence = 0.65
        elif survival_prob < 0.7:
            # 中等生存概率
            adjusted_vel = current_vel * 0.85
            confidence = 0.6
        else:
            # 生存概率高，保持当前速度
            adjusted_vel = current_vel
            confidence = 0.55
        
        # 如果预测增长停止时间很短，进一步降低速度
        if growth_stop_hours < 24 and growth_stop_hours > 0:
            time_factor = growth_stop_hours / 24.0
            adjusted_vel = adjusted_vel * (0.5 + 0.5 * time_factor)
        
        return max(adjusted_vel, 0.0), confidence
    
    def _calculate_acceleration(self, velocities: np.ndarray) -> float:
        """计算加速度"""
        if len(velocities) < 2:
            return 0.0
        
        recent = velocities[-min(3, len(velocities)):]
        accel = (recent[-1] - recent[0]) / (len(recent) - 1)
        return accel
    
    def _extract_series(self, history: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """提取播放量和时间戳序列"""
        views = []
        timestamps = []
        
        for entry in history:
            v = entry.get('view_count', entry.get('view', 0))
            t = entry.get('timestamp', 0)
            
            if hasattr(t, 'timestamp'):
                t = t.timestamp()
            elif isinstance(t, str):
                try:
                    from datetime import datetime as dt
                    t = dt.fromisoformat(t).timestamp()
                except:
                    continue
            
            if v > 0 and t > 0:
                views.append(float(v))
                timestamps.append(float(t))
        
        if len(views) > 1:
            sorted_indices = np.argsort(timestamps)
            views = [views[i] for i in sorted_indices]
            timestamps = [timestamps[i] for i in sorted_indices]
        
        return np.array(views), np.array(timestamps)
    
    def _calculate_velocity_series(self, views: np.ndarray, 
                                   timestamps: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """计算速度序列"""
        if len(views) < 2:
            return np.array([]), np.array([])
        
        velocities = []
        vel_times = []
        
        for i in range(1, len(views)):
            dt = (timestamps[i] - timestamps[i-1]) / 3600.0
            if dt <= 0:
                continue
            dv = views[i] - views[i-1]
            velocity = dv / dt
            velocities.append(velocity)
            vel_times.append(timestamps[i])
        
        return np.array(velocities), np.array(vel_times)
    
    def _make_result(self, current_views: int, threshold: int,
                     velocity: float, confidence: float,
                     survival_prob: float, 
                     predicted_growth_stop_hours: float,
                     reason: str) -> PredictionResult:
        """构造预测结果"""
        
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
        
        metadata = {
            'survival_probability': survival_prob,
            'predicted_growth_stop_hours': predicted_growth_stop_hours,
            'growth_threshold': self.growth_threshold,
            'reason': reason,
            'method': 'survival_analysis'
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
