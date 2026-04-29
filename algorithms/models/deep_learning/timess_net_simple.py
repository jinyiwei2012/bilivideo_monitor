"""
TimesNet简化版 (TimesNet Simplified)
将1D时间序列转换为2D，捕获周期内和周期间的模式
"""

import numpy as np
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class TimesNetSimpleAlgorithm(BaseAlgorithm):
    """TimesNet简化版算法
    
    核心思路（简化）：
    1. 将1D时间序列转换为2D（按不同周期长度reshape）
    2. 使用简化2D卷积提取特征
    3. 融合多周期特征进行预测
    
    论文：TimesNet: Temporal 2D-Variation Modeling for General Time Series Analysis
    (ICLR 2023, Wu et al.)
    """
    
    name = "TimesNet简化版"
    algorithm_id = "times_net_simple"
    description = "将1D序列转为2D，捕获周期内和周期间的模式"
    category = "深度学习"
    default_weight = 1.4
    
    def __init__(self):
        super().__init__()
        self.periods = [3, 6, 12]  # 候选周期长度
        self.min_seq_len = 15      # 最少需要的序列长度
        self.conv_kernel = 2         # 简化卷积核大小
        self.min_data_points = 15
        
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
            # 数据太少，退化为简单预测
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.3,
                period_features=None,
                reason='insufficient_data'
            )
        
        # 提取时间序列
        views, timestamps = self._extract_series(history)
        
        if len(views) < self.min_seq_len:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.3,
                period_features=None,
                reason='short_series'
            )
        
        # 计算速度序列
        velocities, _ = self._calculate_velocity_series(views, timestamps)
        
        if len(velocities) < self.min_seq_len:
            velocity = velocities[-1] if len(velocities) > 0 else 0.0
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.4,
                period_features=None,
                reason='short_velocity_series'
            )
        
        # TimesNet核心：多周期特征提取
        period_features = self._extract_multi_period_features(velocities)
        
        if not period_features:
            # 无法提取周期特征，使用平均速度
            avg_vel = np.mean(velocities)
            return self._make_result(
                current_views, threshold, avg_vel,
                confidence=0.4,
                period_features=None,
                reason='no_period_found'
            )
        
        # 基于多周期特征预测
        predicted_velocity, confidence = self._predict_from_period_features(
            period_features, velocities
        )
        
        return self._make_result(
            current_views, threshold, predicted_velocity,
            confidence=confidence,
            period_features=period_features,
            reason='times_net'
        )
    
    def _extract_multi_period_features(self, series: np.ndarray) -> Dict[int, np.ndarray]:
        """提取多周期特征
        
        对每个候选周期长度，将1D序列转换为2D，
        然后使用简化2D卷积提取特征。
        
        Returns:
            字典：{周期长度: 特征向量}
        """
        features = {}
        
        for period in self.periods:
            if len(series) < period * 2:
                continue  # 序列太短，无法使用此周期
            
            # 将1D序列转换为2D
            # 例如：series = [1,2,3,4,5,6], period=3
            # 2D = [[1,2,3], [4,5,6]]
            try:
                # 截断到 period 的整数倍
                truncate_len = (len(series) // period) * period
                truncated = series[:truncate_len]
                
                # reshape 为 2D
                matrix_2d = truncated.reshape(-1, period)
                
                # 简化2D卷积（手动实现）
                conv_features = self._simple_2d_conv(matrix_2d)
                
                features[period] = conv_features
            except:
                continue
        
        return features
    
    def _simple_2d_conv(self, matrix: np.ndarray) -> np.ndarray:
        """简化2D卷积
        
        使用固定卷积核：
        1. 每一列的均值（周期内模式）
        2. 每一行的均值（周期间模式）
        3. 全局均值
        """
        if matrix.size == 0:
            return np.array([0.0, 0.0, 0.0])
        
        # 周期内模式（列均值）
        col_means = np.mean(matrix, axis=0)
        
        # 周期间模式（行均值）
        row_means = np.mean(matrix, axis=1)
        
        # 简化"卷积"：使用统计特征代替
        features = [
            np.mean(col_means),      # 全局均值
            np.std(col_means),       # 周期内变异
            np.mean(row_means),      # 周期均值
            np.std(row_means),       # 周期间变异
            np.mean(matrix),         # 全局均值
            np.std(matrix)           # 全局变异
        ]
        
        return np.array(features)
    
    def _predict_from_period_features(self, 
                                    period_features: Dict[int, np.ndarray],
                                    velocities: np.ndarray) -> Tuple[float, float]:
        """基于多周期特征预测
        
        Returns:
            (预测速度, 置信度)
        """
        if not period_features:
            return velocities[-1] if len(velocities) > 0 else 0.0, 0.3
        
        # 融合多周期特征
        all_features = []
        for period, feats in period_features.items():
            all_features.extend(feats)
        
        if not all_features:
            return velocities[-1], 0.3
        
        # 使用特征预测（简化：加权平均）
        feature_mean = np.mean(all_features)
        
        # 结合近期速度
        recent_vel = velocities[-1]
        
        # 判断周期性强度
        periodicity_strength = self._calculate_periodicity(velocities)
        
        if periodicity_strength > 0.6:
            # 强周期性，更多依赖周期特征
            weight_feature = 0.6
            weight_recent = 0.4
            confidence = 0.7
        elif periodicity_strength > 0.3:
            # 中等周期性
            weight_feature = 0.4
            weight_recent = 0.6
            confidence = 0.6
        else:
            # 弱周期性，更多依赖近期速度
            weight_feature = 0.2
            weight_recent = 0.8
            confidence = 0.5
        
        predicted_velocity = weight_feature * feature_mean + weight_recent * recent_vel
        
        return max(predicted_velocity, 0.0), confidence
    
    def _calculate_periodicity(self, series: np.ndarray) -> float:
        """计算周期性强度
        
        使用自相关简化版
        """
        if len(series) < 6:
            return 0.0
        
        # 计算自相关（lag=3）
        lag = min(3, len(series) // 2)
        if lag < 1:
            return 0.0
        
        try:
            # 归一化序列
            normalized = (series - np.mean(series)) / (np.std(series) + 1e-6)
            
            # 计算自相关
            autocorr = np.corrcoef(normalized[lag:], normalized[:-lag])[0, 1]
            
            # 映射到[0, 1]
            periodicity = max(0, autocorr)
            return periodicity
        except:
            return 0.0
    
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
                     period_features: Optional[Dict],
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
        
        # 构造元数据
        metadata = {
            'reason': reason,
            'periods_used': list(period_features.keys()) if period_features else [],
            'num_periods': len(period_features) if period_features else 0,
            'method': 'times_net_simplified'
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
