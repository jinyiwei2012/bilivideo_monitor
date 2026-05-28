"""
注意力机制预测模型
模拟Transformer的注意力机制，关注重要的时间点
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
import logging

from algorithms.base import BaseAlgorithm
from algorithms.models.deep_learning._torch_upgrade import AttentionTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class AttentionMechanismAlgorithm(BaseAlgorithm):
    """
    Attention-Based View Prediction

    使用注意力机制关注历史数据中的重要时间点
    类似于Transformer的简化版本
    """

    name = "注意力机制模型"
    algorithm_id = "attention_mechanism"
    description = "关注重要时间点，类似Transformer（torch checkpoint 优先，否则 numpy 简化）"
    category = "深度学习"

    training_window = 10
    training_horizon = 3

    def __init__(self):
        super().__init__()
        self.d_model = 16  # 模型维度
        self.n_heads = 2  # 注意力头数

    def build_model(self):
        return AttentionTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            d_model=32,
            n_heads=4,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def get_training_features(self):
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def predict(
        self, current_views: int, target_views: int, history_data: List[Dict[str, Any]], video_info: Dict[str, Any]
    ) -> Optional[Tuple[int, float]]:
        """
        预测到达目标播放量所需时间
        """
        # torch 优先
        torch_result = self._try_torch_predict(current_views, target_views, history_data, video_info)
        if torch_result is not None:
            return torch_result

        if not history_data or len(history_data) < 8:
            return None

        try:
            # 准备序列数据
            sequence = self._prepare_sequence(history_data)

            if len(sequence) < 5:
                return None

            # 应用注意力机制
            context = self._apply_attention(sequence)

            if current_views >= target_views:
                return (0, 1.0)

            # 基于上下文预测增长率
            predicted_growth = self._predict_growth(context, sequence)

            if predicted_growth <= 0:
                views = [d["view"] for d in history_data]
                predicted_growth = max(1, np.mean([views[i] - views[i - 1] for i in range(1, len(views))]))

            remaining = target_views - current_views
            days_needed = remaining / predicted_growth

            if days_needed < 0 or days_needed > 3650:
                return None

            seconds_needed = int(days_needed * 86400)
            confidence = self._calculate_confidence(sequence, context)

            return (seconds_needed, confidence)

        except Exception as e:
            logger.warning(f"注意力机制预测失败: {e}")
            return None

    def _prepare_sequence(self, history_data: List[Dict[str, Any]]) -> np.ndarray:
        """
        准备序列数据

        每个时间步包含: [播放量, 增长率, 点赞率, 时间编码]
        """
        sequence = []

        for i, data in enumerate(history_data):
            view = data.get("view", 0)
            like = data.get("like", 0)

            # 计算增长率
            if i > 0:
                prev_view = history_data[i - 1].get("view", 0)
                growth_rate = view - prev_view
            else:
                growth_rate = 0

            # 点赞率
            like_rate = like / max(view, 1)

            # 时间编码 (位置编码简化版)
            time_enc = np.sin(i / 10)

            sequence.append([view / 10000, growth_rate / 1000, like_rate * 10, time_enc])

        return np.array(sequence)

    def _apply_attention(self, sequence: np.ndarray) -> np.ndarray:
        """
        应用简化版注意力机制

        使用缩放点积注意力
        """
        len(sequence)

        # 使用最后几个时间步作为查询
        query = sequence[-3:].mean(axis=0)  # [d_model]

        # 所有时间步作为键和值
        keys = sequence  # [n, d_model]
        values = sequence[:, 1]  # 使用增长率作为值 [n]

        # 计算注意力分数
        scores = np.dot(keys, query) / np.sqrt(self.d_model)  # [n]

        # Softmax
        exp_scores = np.exp(scores - np.max(scores))
        attention_weights = exp_scores / np.sum(exp_scores)

        # 加权求和
        context = np.sum(attention_weights * values)

        return context

    def _predict_growth(self, context: float, sequence: np.ndarray) -> float:
        """
        基于上下文预测增长率
        """
        # 最近的增长率
        recent_growth = sequence[-1][1] * 1000  # 反归一化

        # 注意力上下文
        attention_growth = context * 1000  # 反归一化

        # 结合两者
        predicted = 0.6 * recent_growth + 0.4 * attention_growth

        return max(1, predicted)

    def _calculate_confidence(self, sequence: np.ndarray, context: float) -> float:
        """计算置信度"""
        n = len(sequence)

        # 基础置信度
        base_conf = min(0.85, 0.3 + n * 0.025)

        # 序列稳定性
        growth_rates = sequence[:, 1]
        if len(growth_rates) > 1:
            cv = np.std(growth_rates) / (np.mean(np.abs(growth_rates)) + 0.001)
            stability = max(0, 1 - cv)
            base_conf = 0.6 * base_conf + 0.4 * stability

        return min(0.9, base_conf)

    def _try_torch_predict(
        self, current_views: int, target_views: int, history_data: List[Dict[str, Any]], video_info: Dict[str, Any]
    ) -> Optional[Tuple[int, float]]:
        """torch checkpoint 存在时跑真实推理；任何失败都返回 None 让上游降级。"""
        if not hasattr(self, "_ckpt"):
            from algorithms.training.checkpoint_manager import CheckpointManager

            self._ckpt = CheckpointManager(self.algorithm_id)
        try:
            from datetime import datetime

            wrapped_history = []
            for d in history_data:
                ts = d.get("timestamp", 0)
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts).timestamp()
                    except Exception:
                        ts = 0
                wrapped_history.append(
                    {
                        "view_count": d.get("view", d.get("view_count", 0)),
                        "like_count": d.get("like", d.get("like_count", 0)),
                        "coin_count": d.get("coin", d.get("coin_count", 0)),
                        "favorite_count": d.get("favorite", d.get("favorite_count", 0)),
                        "share_count": d.get("share", d.get("share_count", 0)),
                        "timestamp": ts,
                    }
                )
            video_data = {
                "view_count": current_views,
                "history_data": wrapped_history,
                "timestamp": datetime.now(),
                "bvid": video_info.get("bvid", ""),
            }
            result = try_torch_predict(
                self,
                video_data,
                target_views,
                AttentionTorchModel,
                lambda _v, _t: None,
                window=self.training_window,
                horizon=self.training_horizon,
                model_kwargs={"in_features": getattr(self, '_training_n_features', 5), "window": self.training_window, "horizon": self.training_horizon},
            )
            if result is None or not hasattr(result, "predicted_hours"):
                return None
            if result.predicted_hours == float("inf") or result.predicted_hours < 0:
                return None
            seconds = int(result.predicted_hours * 3600)
            return (seconds, result.confidence)
        except Exception as e:
            logger.debug("[attention_mechanism] torch path 异常: %s", e)
            return None
