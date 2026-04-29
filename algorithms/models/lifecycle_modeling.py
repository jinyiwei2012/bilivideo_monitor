"""
视频生命周期建模算法 (Video Lifecycle Modeling)
将视频生命周期划分为不同阶段，针对不同阶段使用不同预测策略
"""

import numpy as np
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
from enum import Enum
from algorithms.base import BaseAlgorithm, PredictionResult


class LifecycleStage(Enum):
    """视频生命周期阶段"""
    INTRODUCTION = "导入期"    # 刚发布，播放量增长缓慢
    GROWTH = "成长期"          # 开始获得推荐，播放量快速增长
    MATURITY = "成熟期"        # 增长放缓，趋于稳定
    DECLINE = "衰退期"         # 播放量基本停止增长
    VIRAL = "病毒期"           # 突然爆火，增长速度极快


class LifecycleModelAlgorithm(BaseAlgorithm):
    """视频生命周期建模算法
    
    将视频生命周期划分为不同阶段，针对不同阶段使用不同预测策略。
    阶段判断基于播放量增速的变化模式。
    """
    
    name = "生命周期建模"
    algorithm_id = "lifecycle_modeling"
    description = "将视频划分为不同阶段，针对不同阶段使用不同预测策略"
    category = "生命周期模型"
    default_weight = 1.5
    
    def __init__(self):
        super().__init__()
        self.velocity_threshold_growth = 50     # 进入成长期的速速阈值（播放/小时）
        self.velocity_threshold_viral = 500     # 进入病毒期的速速阈值
        self.velocity_threshold_decline = 10    # 进入衰退期的速速阈值
        self.stable_period_hours = 6            # 判断稳定期需要的小时数
        
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
        
        if len(history) < 3:
            # 数据太少，无法判断阶段，使用简单预测
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, threshold, velocity, 
                confidence=0.3, stage=LifecycleStage.INTRODUCTION,
                reason='insufficient_data'
            )
        
        # 提取时间和播放量序列
        views, timestamps = self._extract_series(history)
        
        if len(views) < 3:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.3, stage=LifecycleStage.INTRODUCTION,
                reason='short_series'
            )
        
        # 计算速度序列
        velocities, _ = self._calculate_velocity_series(views, timestamps)
        
        if len(velocities) < 2:
            velocity = velocities[-1] if len(velocities) > 0 else 0.0
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.4, stage=LifecycleStage.INTRODUCTION,
                reason='single_velocity'
            )
        
        # 判断当前生命周期阶段
        stage, reason, stage_confidence = self._determine_stage(
            views, velocities, timestamps, video_data
        )
        
        # 根据阶段选择预测策略
        predicted_velocity, confidence = self._predict_for_stage(
            stage, views, velocities, timestamps, video_data
        )
        
        confidence = min(confidence, stage_confidence)
        
        return self._make_result(
            current_views, threshold, predicted_velocity,
            confidence=confidence, stage=stage,
            reason=reason
        )
    
    def _determine_stage(self, views: np.ndarray, 
                         velocities: np.ndarray,
                         timestamps: np.ndarray,
                         video_data: Dict) -> Tuple[LifecycleStage, str, float]:
        """判断当前生命周期阶段
        
        Returns:
            (阶段, 判断原因, 置信度)
        """
        # 计算关键指标
        current_vel = velocities[-1]
        avg_vel = np.mean(velocities)
        max_vel = np.max(velocities)
        min_vel = np.min(velocities)
        
        # 计算加速度（最近3个速度值的变化趋势）
        accel = self._calculate_acceleration(velocities)
        
        # 视频年龄
        age_hours = self.get_video_age_hours(video_data)
        
        # 速度的标准差（判断稳定性）
        vel_std = np.std(velocities)
        vel_cv = vel_std / (avg_vel + 1e-6)  # 变异系数
        
        # 判断阶段
        # 1. 病毒期：速度极快且加速度>0
        if current_vel >= self.velocity_threshold_viral and accel > 0:
            return LifecycleStage.VIRAL, 'high_velocity_with_acceleration', 0.85
        
        # 2. 病毒期（减速）：速度极快但开始减速
        if current_vel >= self.velocity_threshold_viral and accel <= 0:
            return LifecycleStage.VIRAL, 'high_velocity_decelerating', 0.75
        
        # 3. 成长期：速度超过阈值且加速度>0
        if current_vel >= self.velocity_threshold_growth and accel > 0:
            return LifecycleStage.GROWTH, 'velocity_above_threshold_accelerating', 0.8
        
        # 4. 成长期（稳定）：速度超过阈值但加速度≈0
        if current_vel >= self.velocity_threshold_growth and abs(accel) < 0.1 * current_vel:
            return LifecycleStage.GROWTH, 'velocity_above_threshold_stable', 0.75
        
        # 5. 成长期（减速）：速度超过阈值但开始减速
        if current_vel >= self.velocity_threshold_growth and accel < 0:
            # 检查是否进入成熟期
            if current_vel < self.velocity_threshold_growth * 0.5:
                return LifecycleStage.MATURITY, 'velocity_declining_to_maturity', 0.7
            return LifecycleStage.GROWTH, 'velocity_above_threshold_decelerating', 0.65
        
        # 6. 成熟期：速度稳定在较低水平
        if current_vel < self.velocity_threshold_growth and current_vel >= self.velocity_threshold_decline:
            if vel_cv < 0.5:  # 速度稳定
                return LifecycleStage.MATURITY, 'stable_low_velocity', 0.75
            else:
                return LifecycleStage.MATURITY, 'unstable_low_velocity', 0.6
        
        # 7. 衰退期：速度很低
        if current_vel < self.velocity_threshold_decline:
            return LifecycleStage.DECLINE, 'very_low_velocity', 0.8
        
        # 8. 导入期：默认阶段
        if age_hours < 24:
            return LifecycleStage.INTRODUCTION, 'early_stage', 0.6
        
        # 默认：导入期
        return LifecycleStage.INTRODUCTION, 'default', 0.5
    
    def _predict_for_stage(self, stage: LifecycleStage,
                            views: np.ndarray,
                            velocities: np.ndarray,
                            timestamps: np.ndarray,
                            video_data: Dict) -> Tuple[float, float]:
        """根据阶段选择预测策略
        
        Returns:
            (预测速度, 置信度)
        """
        if stage == LifecycleStage.INTRODUCTION:
            # 导入期：使用平均速度和趋势外推
            if len(velocities) >= 2:
                avg_vel = np.mean(velocities[-3:])  # 近期平均速度
                # 考虑增长趋势
                trend = self._calculate_acceleration(velocities)
                predicted_vel = avg_vel + trend * 2  # 外推2小时
                confidence = 0.5
            else:
                predicted_vel = velocities[-1] if len(velocities) > 0 else 10.0
                confidence = 0.3
                
        elif stage == LifecycleStage.GROWTH:
            # 成长期：使用近期速度，考虑增长惯性
            recent_vel = np.mean(velocities[-3:])
            accel = self._calculate_acceleration(velocities)
            
            if accel > 0:
                # 仍在加速，预测速度略高于当前
                predicted_vel = recent_vel * 1.1
                confidence = 0.75
            else:
                # 增速稳定或略有下降
                predicted_vel = recent_vel
                confidence = 0.7
                
        elif stage == LifecycleStage.MATURITY:
            # 成熟期：使用指数衰减模型
            current_vel = velocities[-1]
            # 估计衰减率（基于近期速度下降）
            if len(velocities) >= 3:
                decay_rate = (velocities[-3] - velocities[-1]) / (3 * 0.5)  # 粗略估计
                decay_rate = max(0, decay_rate)
            else:
                decay_rate = current_vel * 0.1  # 默认10%/周期
            
            # 预测速度 = 当前速度 * exp(-decay_rate * t)，简化使用线性衰减
            predicted_vel = current_vel - decay_rate * 2  # 2小时后的预测速度
            predicted_vel = max(predicted_vel, current_vel * 0.3)  # 最低保留30%
            confidence = 0.7
            
        elif stage == LifecycleStage.DECLINE:
            # 衰退期：速度很低，使用长期趋势
            if len(velocities) >= 3:
                # 计算长期衰减趋势
                long_term_slope = (velocities[-1] - velocities[0]) / len(velocities)
                predicted_vel = max(velocities[-1] + long_term_slope, 1.0)  # 最低1播放/小时
            else:
                predicted_vel = max(velocities[-1] * 0.8, 1.0)
            confidence = 0.8  # 衰退期预测反而比较准确
            
        elif stage == LifecycleStage.VIRAL:
            # 病毒期：增长速度极快，但可能很快衰减
            recent_vel = velocities[-1]
            accel = self._calculate_acceleration(velocities)
            
            if accel > 0:
                # 仍在加速（可能继续爆火）
                predicted_vel = recent_vel * 1.2
                confidence = 0.6  # 病毒期不确定性高
            else:
                # 开始减速（可能热度消退）
                predicted_vel = recent_vel * 0.7
                confidence = 0.65
        else:
            # 未知阶段
            predicted_vel = np.mean(velocities) if len(velocities) > 0 else 10.0
            confidence = 0.4
        
        return max(predicted_vel, 0.0), confidence
    
    def _calculate_acceleration(self, velocities: np.ndarray) -> float:
        """计算加速度（速度的变化率）"""
        if len(velocities) < 2:
            return 0.0
        
        # 使用最近3个点计算加速度
        recent = velocities[-min(3, len(velocities)):]
        if len(recent) < 2:
            return 0.0
        
        # 简单差分
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
                     stage: LifecycleStage, reason: str) -> PredictionResult:
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
            'stage': stage.value,
            'stage_reason': reason,
            'predicted_velocity': velocity,
            'method': 'lifecycle_based'
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
