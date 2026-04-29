"""
PatchTST简化版 (Patch Time Series Transformer Simplified)
将时间序列分成patch，使用简化注意力机制捕捉长时间序列的局部模式
"""

import numpy as np
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class PatchTSTSimpleAlgorithm(BaseAlgorithm):
    """PatchTST简化版算法
    
    将速度序列分成patch（类似NLP中的token），
    使用简化注意力机制捕捉长时间序列的局部模式。
    核心思路来自论文：
    "A Time Series is Worth 64 Words: Long-term Forecasting with Transformers" (ICLR 2023)
    """
    
    name = "PatchTST简化版"
    algorithm_id = "patch_tst_simple"
    description = "使用Patch和简化注意力机制捕捉时间序列的局部模式"
    category = "Transformer模型"
    default_weight = 1.3
    
    def __init__(self):
        super().__init__()
        self.patch_len = 4        # 每个patch的长度
        self.stride = 2           # patch之间的步长
        self.d_model = 8          # 特征维度（简化版，原版是128/256）
        self.num_heads = 2        # 注意力头数
        self.min_seq_len = 8      # 最少需要的序列长度
        
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
        
        if len(history) < self.min_seq_len:
            # 数据太少，退化为简单预测
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.3,
                reason='insufficient_data',
                attention_weights=None
            )
        
        # 提取时间和播放量序列
        views, timestamps = self._extract_series(history)
        
        if len(views) < self.min_seq_len:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.3,
                reason='short_series',
                attention_weights=None
            )
        
        # 计算速度序列
        velocities, _ = self._calculate_velocity_series(views, timestamps)
        
        if len(velocities) < self.min_seq_len:
            velocity = velocities[-1] if len(velocities) > 0 else 0.0
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.4,
                reason='short_velocity_series',
                attention_weights=None
            )
        
        # PatchTST核心：分patch + 注意力机制
        patches = self._create_patches(velocities)
        
        if len(patches) < 2:
            velocity = velocities[-1]
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.4,
                reason='insufficient_patches',
                attention_weights=None
            )
        
        # 简化版自注意力
        patch_representations = self._patch_representation(patches)
        attention_weights, attended_repr = self._simplified_attention(patch_representations)
        
        # 基于注意力加权的表示预测未来速度
        predicted_velocity, confidence = self._predict_from_attention(
            attended_repr, velocities
        )
        
        return self._make_result(
            current_views, threshold, predicted_velocity,
            confidence=confidence,
            reason='patch_tst',
            attention_weights=attention_weights
        )
    
    def _create_patches(self, series: np.ndarray) -> List[np.ndarray]:
        """将序列分成多个patch
        
        Returns:
            patch列表，每个patch是一个numpy数组
        """
        patches = []
        n = len(series)
        
        for start in range(0, n - self.patch_len + 1, self.stride):
            end = start + self.patch_len
            patch = series[start:end]
            patches.append(patch)
        
        return patches
    
    def _patch_representation(self, patches: List[np.ndarray]) -> np.ndarray:
        """计算patch的表示（简化版）
        
        使用patch的统计量作为表示：
        - 均值
        - 标准差
        - 斜率
        - 最后一个值
        """
        representations = []
        
        for patch in patches:
            mean = np.mean(patch)
            std = np.std(patch) if len(patch) > 1 else 0.0
            
            # 计算斜率（线性趋势）
            x = np.arange(len(patch))
            if len(patch) > 1:
                slope = np.polyfit(x, patch, 1)[0]
            else:
                slope = 0.0
            
            last_value = patch[-1]
            
            # 拼接成表示向量（4维 -> 扩展到d_model维）
            repr_vector = np.array([mean, std, slope, last_value])
            
            # 扩展到d_model维度（简化：重复 + 线性投影）
            if self.d_model > 4:
                # 重复并截断/填充
                extended = np.tile(repr_vector, (self.d_model // 4) + 1)[:self.d_model]
            else:
                extended = repr_vector[:self.d_model]
            
            representations.append(extended)
        
        return np.array(representations)  # shape: (num_patches, d_model)
    
    def _simplified_attention(self, repr: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """简化版自注意力机制
        
        不使用完整的Transformer，而是使用简化的注意力计算：
        1. 使用最后一个patch作为query
        2. 计算所有patch与query的相似度
        3. 使用softmax得到注意力权重
        4. 加权求和得到注意力表示
        
        Returns:
            (注意力权重, 注意力加权表示)
        """
        if len(repr) == 0:
            return np.array([]), np.array([])
        
        if len(repr) == 1:
            return np.array([1.0]), repr[0]
        
        # 使用最后一个patch作为query
        query = repr[-1]
        
        # 计算相似度（点积）
        # 为简化，不使用QKV变换，直接计算相似度
        similarities = np.array([
            np.dot(query, k) / (np.linalg.norm(query) * np.linalg.norm(k) + 1e-6)
            for k in repr
        ])
        
        # Softmax得到注意力权重
        # 数值稳定性：减去最大值
        exp_similarities = np.exp(similarities - np.max(similarities))
        attention_weights = exp_similarities / (np.sum(exp_similarities) + 1e-6)
        
        # 加权求和
        attended = np.sum(repr * attention_weights[:, np.newaxis], axis=0)
        
        return attention_weights, attended
    
    def _predict_from_attention(self, attended_repr: np.ndarray,
                                  velocities: np.ndarray) -> Tuple[float, float]:
        """基于注意力表示预测未来速度
        
        Returns:
            (预测速度, 置信度)
        """
        if len(attended_repr) == 0:
            return velocities[-1] if len(velocities) > 0 else 0.0, 0.3
        
        # 使用注意力表示的第一个维度（对应均值）作为预测
        # 这是简化版，完整版会使用MLP预测
        predicted_mean = attended_repr[0]  # 假设第一个维度是均值
        
        # 结合近期速度
        recent_vel = velocities[-1]
        
        # 加权平均：注意力预测 + 近期速度
        # 如果注意力预测和近期速度差异大，降低置信度
        diff_ratio = abs(predicted_mean - recent_vel) / (recent_vel + 1e-6)
        
        if diff_ratio < 0.2:
            # 预测一致，高置信度
            weight_att = 0.3
            weight_recent = 0.7
            confidence = 0.75
        elif diff_ratio < 0.5:
            # 预测有差异，中等置信度
            weight_att = 0.2
            weight_recent = 0.8
            confidence = 0.6
        else:
            # 预测差异大，低置信度，更依赖近期速度
            weight_att = 0.1
            weight_recent = 0.9
            confidence = 0.5
        
        predicted_velocity = weight_att * predicted_mean + weight_recent * recent_vel
        
        return max(predicted_velocity, 0.0), confidence
    
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
                     reason: str,
                     attention_weights: Optional[np.ndarray]) -> PredictionResult:
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
            'patch_len': self.patch_len,
            'stride': self.stride,
            'num_patches': len(attention_weights) if attention_weights is not None else 0,
            'attention_weights': attention_weights.tolist() if attention_weights is not None else None,
            'method': 'patch_tst_simplified'
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
