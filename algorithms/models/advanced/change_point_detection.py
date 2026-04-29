"""
变化点检测算法 (Change Point Detection)
基于CUSUM（累积和）检测播放量增速的突变点
"""

import numpy as np
from typing import Dict, Any, List, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class ChangePointDetectionAlgorithm(BaseAlgorithm):
    """变化点检测算法
    
    检测播放量增速的突变点，根据当前所处的"增速阶段"调整预测策略。
    如果检测到近期有增速突变（加速/减速），则对预测速度进行相应调整。
    """
    
    name = "变化点检测"
    algorithm_id = "change_point_detection"
    description = "检测播放量增速突变点，动态调整预测策略"
    category = "统计模型"
    default_weight = 1.3
    
    def __init__(self):
        super().__init__()
        self.cusum_threshold = 2.0  # CUSUM检测阈值（标准差的倍数）
        self.min_data_points = 6       # 最少需要的数据点数
        
    def predict(self, video_data: Dict[str, Any], 
                threshold: int = 100000) -> PredictionResult:
        """执行预测
        
        Args:
            video_data: 视频数据，包含 history_data 列表
                        每个元素有 view_count 和 timestamp
            threshold: 目标播放量阈值
            
        Returns:
            PredictionResult
        """
        current_views = video_data.get('view_count', 0)
        history = video_data.get('history_data', [])
        
        if len(history) < self.min_data_points:
            # 数据太少，无法检测变化点，使用简单速度预测
            velocity = self._calculate_simple_velocity(history)
            return self._make_result(current_views, threshold, velocity, 
                                    confidence=0.3, change_points=[],
                                    strategy='insufficient_data')
        
        # 提取时间和播放量序列
        views, timestamps = self._extract_series(history)
        
        if len(views) < self.min_data_points:
            velocity = self._calculate_simple_velocity(history)
            return self._make_result(current_views, threshold, velocity,
                                    confidence=0.3, change_points=[],
                                    strategy='insufficient_data')
        
        # 计算速度序列（相邻时间点的播放量增量/时间增量）
        velocities, vel_timestamps = self._calculate_velocity_series(views, timestamps)
        
        if len(velocities) < 4:
            velocity = velocities[-1] if velocities else 0.0
            return self._make_result(current_views, threshold, velocity,
                                    confidence=0.4, change_points=[],
                                    strategy='short_series')
        
        # 使用CUSUM检测变化点
        change_points = self._detect_cusum(velocities)
        
        # 根据变化点调整预测策略
        strategy, adjusted_velocity, confidence = self._adjust_prediction(
            velocities, change_points, video_data
        )
        
        return self._make_result(
            current_views, threshold, adjusted_velocity, 
            confidence=confidence, 
            change_points=change_points,
            strategy=strategy,
            velocities=velocities
        )
    
    def _extract_series(self, history: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """提取播放量和时间戳序列"""
        views = []
        timestamps = []
        
        for entry in history:
            v = entry.get('view_count', entry.get('view', 0))
            t = entry.get('timestamp', 0)
            
            # 处理timestamp可能是datetime对象或字符串的情况
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
        
        # 按时间排序
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
            dt = (timestamps[i] - timestamps[i-1]) / 3600.0  # 转换为小时
            if dt <= 0:
                continue
            dv = views[i] - views[i-1]
            velocity = dv / dt  # 播放量/小时
            velocities.append(velocity)
            vel_times.append(timestamps[i])
        
        return np.array(velocities), np.array(vel_times)
    
    def _detect_cusum(self, series: np.ndarray) -> List[Dict]:
        """使用CUSUM算法检测变化点
        
        Returns:
            List[Dict]: 变化点列表，每个元素包含位置、类型、幅度
        """
        if len(series) < 4:
            return []
        
        # 标准化序列
        mean = np.mean(series)
        std = np.std(series)
        
        if std == 0:
            return []
        
        normalized = (series - mean) / std
        
        # CUSUM正向（检测上升变化点）
        cusum_pos = np.zeros(len(normalized))
        # CUSUM负向（检测下降变化点）
        cusum_neg = np.zeros(len(normalized))
        
        change_points = []
        
        for i in range(1, len(normalized)):
            # 正向CUSUM
            cusum_pos[i] = max(0, cusum_pos[i-1] + normalized[i] - 0.5)
            # 负向CUSUM
            cusum_neg[i] = max(0, cusum_neg[i-1] - normalized[i] - 0.5)
            
            # 检测变化点
            if cusum_pos[i] > self.cusum_threshold:
                change_points.append({
                    'index': i,
                    'type': 'acceleration',  # 增速
                    'magnitude': float(series[i] - mean),
                    'cusum_value': float(cusum_pos[i])
                })
                cusum_pos[i] = 0  # 重置
                
            elif cusum_neg[i] > self.cusum_threshold:
                change_points.append({
                    'index': i,
                    'type': 'deceleration',  # 减速
                    'magnitude': float(mean - series[i]),
                    'cusum_value': float(cusum_neg[i])
                })
                cusum_neg[i] = 0  # 重置
        
        return change_points
    
    def _adjust_prediction(self, velocities: np.ndarray, 
                          change_points: List[Dict],
                          video_data: Dict) -> Tuple[str, float, float]:
        """根据变化点调整预测策略
        
        Returns:
            (策略名称, 调整后的速度, 置信度)
        """
        if not change_points:
            # 无变化点，使用近期平均速度
            recent_vel = np.mean(velocities[-3:]) if len(velocities) >= 3 else velocities[-1]
            return 'stable', max(0, recent_vel), 0.7
        
        # 检查最近的变化点（最近3个数据点内）
        recent_window = min(3, len(velocities))
        recent_change = None
        
        for cp in reversed(change_points):
            if cp['index'] >= len(velocities) - recent_window:
                recent_change = cp
                break
        
        if recent_change is None:
            # 变化点较旧，影响减弱
            recent_vel = np.mean(velocities[-3:])
            return 'post_change_stable', max(0, recent_vel), 0.65
        
        # 根据最近变化点类型调整
        if recent_change['type'] == 'acceleration':
            # 近期加速，使用加速后的速度并考虑持续增长
            current_vel = velocities[-1]
            acceleration = self._estimate_acceleration(velocities)
            
            if acceleration > 0:
                # 仍在加速，预测速度 = 当前速度 + 加速度补偿
                adjusted_vel = current_vel * 1.2
                strategy = 'accelerating'
                confidence = 0.75
            else:
                # 加速后趋于稳定
                adjusted_vel = current_vel * 1.1
                strategy = 'post_acceleration'
                confidence = 0.7
                
        elif recent_change['type'] == 'deceleration':
            # 近期减速，降低速度预测
            current_vel = velocities[-1]
            adjusted_vel = current_vel * 0.8
            strategy = 'decelerating'
            confidence = 0.6
        else:
            adjusted_vel = velocities[-1]
            strategy = 'unknown_change'
            confidence = 0.5
        
        return strategy, max(0, adjusted_vel), confidence
    
    def _estimate_acceleration(self, velocities: np.ndarray) -> float:
        """估算加速度（速度的变化率）"""
        if len(velocities) < 3:
            return 0.0
        
        # 使用最近3个速度值计算加速度
        recent = velocities[-3:]
        # 简单差分
        accel = (recent[-1] - recent[0]) / (len(recent) - 1)
        return accel
    
    def _calculate_simple_velocity(self, history: List[Dict]) -> float:
        """计算简单速度（数据不足时使用）"""
        if len(history) < 2:
            return 0.0
        
        try:
            recent = history[-2:]
            v0 = float(recent[0].get('view_count', 0))
            v1 = float(recent[-1].get('view_count', 0))
            
            t0 = recent[0].get('timestamp', 0)
            t1 = recent[-1].get('timestamp', 0)
            
            if hasattr(t0, 'timestamp'):
                t0 = t0.timestamp()
            elif isinstance(t0, str):
                from datetime import datetime as dt
                t0 = dt.fromisoformat(t0).timestamp()
                
            if hasattr(t1, 'timestamp'):
                t1 = t1.timestamp()
            elif isinstance(t1, str):
                from datetime import datetime as dt
                t1 = dt.fromisoformat(t1).timestamp()
            
            dt_hours = (t1 - t0) / 3600.0
            if dt_hours <= 0:
                return 0.0
            
            return max(0.0, (v1 - v0) / dt_hours)
        except:
            return 0.0
    
    def _make_result(self, current_views: int, threshold: int, 
                    velocity: float, confidence: float,
                    change_points: List[Dict], strategy: str,
                    velocities: np.ndarray = None) -> PredictionResult:
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
        
        # 构造元数据
        metadata = {
            'strategy': strategy,
            'change_points': change_points,
            'change_point_count': len(change_points),
            'recent_velocity': float(velocities[-1]) if velocities is not None and len(velocities) > 0 else velocity,
            'velocity_trend': self._get_velocity_trend(velocities) if velocities is not None else 'unknown'
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
    
    def _get_velocity_trend(self, velocities: np.ndarray) -> str:
        """判断速度趋势"""
        if len(velocities) < 3:
            return 'insufficient_data'
        
        # 使用简单线性回归判断趋势
        x = np.arange(len(velocities))
        y = velocities
        
        # 计算斜率
        n = len(x)
        slope = (n * np.sum(x * y) - np.sum(x) * np.sum(y)) / (n * np.sum(x**2) - np.sum(x)**2)
        
        if slope > 0.1 * np.mean(velocities):
            return 'accelerating'
        elif slope < -0.1 * np.mean(velocities):
            return 'decelerating'
        else:
            return 'stable'
