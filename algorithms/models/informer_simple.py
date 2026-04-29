"""
Informer简化版 (Informer Simplified)
高效Transformer，使用ProbSparse自注意力降低复杂度
"""

import numpy as np
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class InformerSimpleAlgorithm(BaseAlgorithm):
    """Informer简化版算法
    
    核心思路（简化）：
    1. ProbSparse自注意力：只计算最重要的注意力连接
    2. 自注意力蒸馏：下采样减少序列长度
    3. 生成式解码器：避免误差累积
    
    论文：Informer: Beyond Efficient Transformer for Long Sequence 
    Time-Series Forecasting (AAAI 2021, Zhou et al.)
    """
    
    name = "Informer简化版"
    algorithm_id = "informer_simple"
    description = "使用ProbSparse自注意力，高效处理长序列"
    category = "Transformer模型"
    default_weight = 1.3
    
    def __init__(self):
        super().__init__()
        self.look_back_window = 12  # 回看窗口长度
        self.forecast_horizon = 5   # 预测步长
        self.factor = 3               # ProbSparse因子（控制稀疏度）
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
                attention_weights=None,
                distilled_length=None,
                reason='insufficient_data'
            )
        
        # 提取时间序列
        views, timestamps = self._extract_series(history)
        
        if len(views) < self.min_data_points:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.3,
                attention_weights=None,
                distilled_length=None,
                reason='short_series'
            )
        
        # 计算速度序列
        velocities, _ = self._calculate_velocity_series(views, timestamps)
        
        if len(velocities) < self.look_back_window:
            velocity = velocities[-1] if len(velocities) > 0 else 0.0
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.4,
                attention_weights=None,
                distilled_length=None,
                reason='short_velocity_series'
            )
        
        # Informer核心：ProbSparse注意力 + 蒸馏
        attention_weights, distilled = self._informer_forward(velocities)
        
        # 基于注意力加权的表示预测
        predicted_velocity, confidence = self._predict_from_attention(
            attention_weights, distilled, velocities
        )
        
        return self._make_result(
            current_views, threshold, predicted_velocity,
            confidence=confidence,
            attention_weights=attention_weights.tolist() if attention_weights is not None else None,
            distilled_length=len(distilled) if distilled is not None else None,
            reason='informer'
        )
    
    def _informer_forward(self, series: np.ndarray) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """Informer前向传播（简化版）
        
        Returns:
            (注意力权重, 蒸馏后的序列)
        """
        if len(series) < self.look_back_window:
            return None, series
        
        # 取最后 look_back_window 个点
        if len(series) > self.look_back_window:
            input_series = series[-self.look_back_window:]
        else:
            input_series = series
        
        # ProbSparse自注意力（简化版）
        attention_weights = self._probsparse_attention(input_series)
        
        # 自注意力蒸馏（下采样）
        distilled = self._attention_distilling(input_series)
        
        return attention_weights, distilled
    
    def _probsparse_attention(self, series: np.ndarray) -> np.ndarray:
        """ProbSparse自注意力（简化版）
        
        核心思想：不是所有注意力连接都需要计算，
        只计算最重要的那些（稀疏注意力）。
        
        简化版：
        1. 计算每个位置的"重要性"得分
        2. 只保留最重要的 factor 个连接
        3. 其他位置使用均值填充
        """
        n = len(series)
        if n < 2:
            return np.eye(n) if n > 0 else np.array([])
        
        # 构造Q, K, V（简化：使用序列本身）
        # 实际Transformer中QKV是通过线性变换得到的，这里简化
        Q = series.reshape(-1, 1)
        K = series.reshape(-1, 1)
        V = series.reshape(-1, 1)
        
        # 计算注意力得分（点积）
        scores = np.dot(Q, K.T)  # shape: (n, n)
        
        # ProbSparse：只保留每个query的最重要的factor个key
        factor = min(self.factor, n)
        
        attention_weights = np.zeros((n, n))
        
        for i in range(n):
            # 第i个query对所有key的得分
            query_scores = scores[i, :]
            
            # 选择最重要的factor个
            topk_indices = np.argsort(query_scores)[-factor:]
            
            # 只对这些计算softmax
            topk_scores = query_scores[topk_indices]
            exp_scores = np.exp(topk_scores - np.max(topk_scores))
            softmax_topk = exp_scores / (np.sum(exp_scores) + 1e-6)
            
            attention_weights[i, topk_indices] = softmax_topk
        
        return attention_weights
    
    def _attention_distilling(self, series: np.ndarray) -> np.ndarray:
        """自注意力蒸馏（简化版）
        
        通过下采样减少序列长度。
        简化版：使用最大池化（取局部最大值）
        """
        n = len(series)
        if n < 4:
            return series
        
        # 下采样率：保留约一半
        downsample_rate = 2
        
        # 最大池化（简化版注意力蒸馏）
        distilled = []
        for i in range(0, n - downsample_rate + 1, downsample_rate):
            # 取局部最大值作为蒸馏后的表示
            local_max = np.max(series[i:i+downsample_rate])
            distilled.append(local_max)
        
        return np.array(distilled)
    
    def _predict_from_attention(self, 
                                attention_weights: Optional[np.ndarray],
                                distilled: Optional[np.ndarray],
                                velocities: np.ndarray) -> Tuple[float, float]:
        """基于注意力加权的表示预测
        
        Returns:
            (预测速度, 置信度)
        """
        if distilled is None or len(distilled) == 0:
            predicted_vel = velocities[-1]
            confidence = 0.4
            return max(predicted_vel, 0.0), confidence
        
        # 使用蒸馏后的序列预测
        # 简化：使用最近几个蒸馏值的趋势
        if len(distilled) >= 2:
            # 计算趋势
            x = np.arange(len(distilled))
            slope = np.polyfit(x, distilled, 1)[0]
            
            # 预测下一个值
            next_value = distilled[-1] + slope
            
            # 结合近期速度
            recent_vel = velocities[-1]
            
            # 加权平均
            predicted_vel = 0.3 * next_value + 0.7 * recent_vel
            
            # 置信度：蒸馏后的序列越平滑，置信度越高
            if len(distilled) >= 3:
                smoothness = 1.0 / (np.std(distilled) + 1e-6)
                confidence = min(0.8, 0.5 + 0.1 * smoothness)
            else:
                confidence = 0.6
        else:
            predicted_vel = velocities[-1]
            confidence = 0.5
        
        return max(predicted_vel, 0.0), confidence
    
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
                     attention_weights: Optional[List],
                     distilled_length: Optional[int],
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
            'has_attention': attention_weights is not None,
            'distilled_length': distilled_length,
            'look_back_window': self.look_back_window,
            'factor': self.factor,
            'method': 'informer_simplified'
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
