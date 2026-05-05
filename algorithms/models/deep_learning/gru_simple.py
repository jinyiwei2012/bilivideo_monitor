"""
GRU简化预测算法
基于门控循环单元思想，比LSTM参数更少、训练更快
"""
from datetime import datetime
from typing import Dict, Any, List, Tuple
import math
from algorithms.base import BaseAlgorithm, PredictionResult


class GRUSimpleAlgorithm(BaseAlgorithm):
    """GRU简化预测算法

    GRU 使用更新门和重置门替代 LSTM 的三个门，
    研究表明在播放量预测任务上 GRU 通常优于 LSTM。
    """

    name = "GRU简化"
    algorithm_id = "gru_simple"
    description = "基于门控循环单元(GRU)的简化预测，比LSTM参数更少"
    category = "深度学习"
    default_weight = 1.3

    def predict(self, video_data: Dict[str, Any],
                threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get('view_count', 0)
        history = video_data.get('history_data', [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=0, confidence=1.0,
                current_views=current_views, current_velocity=velocity,
                metadata={'method': 'gru_simple'}, timestamp=datetime.now()
            )

        if velocity <= 0 or len(history) < 2:
            predicted_hours = remaining / velocity if velocity > 0 else float('inf')
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={'method': 'gru_simple', 'notes': 'insufficient_data'},
                timestamp=datetime.now()
            )

        # ── 构建输入特征 ──────────────────────────
        views_seq = [h.get('view_count', 0) for h in history[-8:]]
        age_hours = self.get_video_age_hours(video_data)
        quality = self.get_quality_score(video_data)

        # 归一化特征
        log_views = math.log(max(current_views, 1)) / 20.0
        log_vel = math.log(max(velocity, 0.001)) / 10.0
        norm_age = min(age_hours / 168.0, 1.0)  # 1周归一化
        recent_growth_rate = 0.0
        if len(views_seq) >= 2:
            recent_growth_rate = (views_seq[-1] - views_seq[-2]) / max(views_seq[-2], 1)

        # ── GRU 门控机制 ──────────────────────────
        # 更新门 (z): 决定多少过去的信息传递给未来
        # z = sigmoid(W_z * [h_{t-1}, x_t])
        z_update = 1.0 / (1.0 + math.exp(-(
            0.3 * log_vel + 0.2 * recent_growth_rate - 0.15 * norm_age
        )))

        # 重置门 (r): 决定忘记多少过去的信息
        # r = sigmoid(W_r * [h_{t-1}, x_t])
        r_reset = 1.0 / (1.0 + math.exp(-(
            0.25 * log_views + 0.3 * quality - 0.1 * norm_age
        )))

        # 候选隐藏状态: h' = tanh(W * [r * h_{t-1}, x_t])
        candidate = math.tanh(
            r_reset * log_vel * 0.5 + 0.3 * quality + 0.2 * recent_growth_rate
        )

        # 最终隐藏状态: h = (1 - z) * h_{t-1} + z * h'
        hidden_state = (1 - z_update) * log_vel + z_update * candidate

        # ── 预测输出 ──────────────────────────
        adjusted_velocity = velocity * (0.5 + hidden_state)
        if adjusted_velocity <= 0:
            adjusted_velocity = velocity * 0.5

        predicted_hours = remaining / adjusted_velocity

        # 置信度
        n_points = len(history)
        conf = min(1.0, 0.4 + n_points * 0.04 + quality * 0.2)

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=conf, current_views=current_views,
            current_velocity=adjusted_velocity,
            metadata={
                'method': 'gru_simple',
                'update_gate': round(z_update, 3),
                'reset_gate': round(r_reset, 3),
                'hidden_state': round(hidden_state, 3),
                'sequence_length': len(views_seq),
            },
            timestamp=datetime.now()
        )
