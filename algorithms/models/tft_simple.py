"""
TFT简化版 (Temporal Fusion Transformer Simplified)
结合静态/动态特征，提供可解释性的时间序列预测
"""

import numpy as np
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class TFTSimpleAlgorithm(BaseAlgorithm):
    """TFT简化版算法
    
    核心思路（简化）：
    1. 特征加权（模拟变量选择网络）
    2. 门控残差网络（模拟GRN）
    3. 可解释多头注意力（模拟时态自注意力）
    4. 融合静态和动态特征
    
    论文：Temporal Fusion Transformers for Interpretable Multi-horizon Time Series Forecasting
    (Goold et al., 2019)
    """
    
    name = "TFT简化版"
    algorithm_id = "tft_simple"
    description = "结合静态/动态特征，提供可解释性的预测"
    category = "Transformer模型"
    default_weight = 1.4
    
    def __init__(self):
        super().__init__()
        self.look_back_window = 12  # 回看窗口长度
        self.forecast_horizon = 5   # 预测步长
        self.num_heads = 2            # 注意力头数
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
                feature_weights=None,
                attention_weights=None,
                reason='insufficient_data'
            )
        
        # 提取时间序列
        views, timestamps = self._extract_series(history)
        
        if len(views) < self.min_data_points:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.3,
                feature_weights=None,
                attention_weights=None,
                reason='short_series'
            )
        
        # 计算速度和特征
        velocities, _ = self._calculate_velocity_series(views, timestamps)
        
        if len(velocities) < self.look_back_window:
            velocity = velocities[-1] if len(velocities) > 0 else 0.0
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.4,
                feature_weights=None,
                attention_weights=None,
                reason='short_velocity_series'
            )
        
        # TFT核心：特征加权 + 门控网络 + 注意力
        features = self._extract_features(video_data, velocities)
        feature_weights = self._variable_selection(features)
        gated_output = self._gated_residual_network(features, feature_weights)
        attention_output, attention_weights = self._temporal_self_attention(gated_output)
        
        # 预测
        predicted_velocity, confidence = self._predict_from_tft(
            attention_output, features, velocities
        )
        
        return self._make_result(
            current_views, threshold, predicted_velocity,
            confidence=confidence,
            feature_weights=feature_weights,
            attention_weights=attention_weights,
            reason='tft'
        )
    
    def _extract_features(self, video_data: Dict, velocities: np.ndarray) -> np.ndarray:
        """提取特征（简化版）
        
        将视频数据转换为特征向量：
        1. 速度统计特征
        2. 互动率特征
        3. 视频年龄特征
        """
        features = []
        
        # 速度统计特征
        if len(velocities) > 0:
            features.extend([
                np.mean(velocities),
                np.std(velocities) if len(velocities) > 1 else 0.0,
                velocities[-1],  # 最近速度
                velocities[0] if len(velocities) > 0 else 0.0,  # 最早速度
            ])
        else:
            features.extend([0.0, 0.0, 0.0, 0.0])
        
        # 互动率特征
        engagement = self.get_engagement_rate(video_data)
        quality = self.get_quality_score(video_data)
        features.extend([engagement, quality])
        
        # 视频年龄特征
        age_hours = self.get_video_age_hours(video_data)
        features.append(age_hours)
        
        # 静态特征（模拟）
        # 视频类型（简化：根据标题关键词）
        title = video_data.get('title', '')
        if '教程' in title or '教学' in title:
            video_type = 0.0  # 教程类
        elif '搞笑' in title or '搞怪' in title:
            video_type = 1.0  # 搞笑类
        elif '音乐' in title or 'MV' in title:
            video_type = 2.0  # 音乐类
        else:
            video_type = 3.0  # 其他
        features.append(video_type)
        
        return np.array(features)
    
    def _variable_selection(self, features: np.ndarray) -> np.ndarray:
        """变量选择网络（简化版）
        
        为每个特征计算重要性权重
        """
        if len(features) == 0:
            return np.array([])
        
        # 简化：使用特征的绝对值作为重要性代理
        # 实际TFT使用神经网络学习权重
        importance = np.abs(features) + 1e-6
        
        # Softmax归一化
        exp_importance = np.exp(importance - np.max(importance))
        weights = exp_importance / (np.sum(exp_importance) + 1e-6)
        
        return weights
    
    def _gated_residual_network(self, features: np.ndarray, 
                                weights: np.ndarray) -> np.ndarray:
        """门控残差网络（简化版）
        
        模拟GRN的门控机制
        """
        if len(features) == 0:
            return np.array([])
        
        # 应用特征权重
        weighted_features = features * weights
        
        # 门控线性单元（GLU）简化版
        # 实际TFT使用：GLU(x) = (W1*x + b1) ⊗ sigmoid(W2*x + b2)
        # 简化：使用sigmoid门控
        gate = 1.0 / (1.0 + np.exp(-weighted_features))
        gated = weighted_features * gate
        
        # 残差连接
        output = gated + features * 0.1  # 简化的残差
        
        return output
    
    def _temporal_self_attention(self, features: np.ndarray) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """时态自注意力（简化版）
        
        模拟TFT的可解释多头注意力
        """
        if len(features) == 0:
            return features, None
        
        # 将特征视为序列（简化：每个特征是一个时间步）
        # 实际TFT的注意力是在时间维度上
        
        # 构造Q, K, V（使用特征本身）
        Q = features.reshape(-1, 1)
        K = features.reshape(-1, 1)
        V = features.reshape(-1, 1)
        
        # 计算注意力得分
        scores = np.dot(Q, K.T)
        
        # Softmax
        exp_scores = np.exp(scores - np.max(scores))
        attention_weights = exp_scores / (np.sum(exp_scores, axis=-1, keepdims=True) + 1e-6)
        
        # 加权求和
        attended = np.dot(attention_weights, V)
        
        return attended.flatten(), attention_weights
    
    def _predict_from_tft(self, 
                              tft_output: np.ndarray,
                              features: np.ndarray,
                              velocities: np.ndarray) -> Tuple[float, float]:
        """基于TFT输出预测
        
        Returns:
            (预测速度, 置信度)
        """
        if len(tft_output) == 0:
            predicted_vel = velocities[-1] if len(velocities) > 0 else 0.0
            confidence = 0.3
            return max(predicted_vel, 0.0), confidence
        
        # 使用TFT输出的均值作为预测
        predicted_vel = np.mean(tft_output)
        
        # 结合近期速度
        recent_vel = velocities[-1] if len(velocities) > 0 else 0.0
        
        # 加权平均
        final_vel = 0.3 * predicted_vel + 0.7 * recent_vel
        
        # 置信度：TFT输出的方差越小，置信度越高
        if len(tft_output) > 1:
            variance = np.var(tft_output)
            confidence = max(0.3, 1.0 - variance)
        else:
            confidence = 0.5
        
        return max(final_vel, 0.0), min(confidence, 0.9)
    
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
                     feature_weights: Optional[List[float]],
                     attention_weights: Optional[List[List[float]]],
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
            'reason': reason,
            'has_feature_weights': feature_weights is not None,
            'has_attention': attention_weights is not None,
            'look_back_window': self.look_back_window,
            'forecast_horizon': self.forecast_horizon,
            'method': 'tft_simplified'
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
