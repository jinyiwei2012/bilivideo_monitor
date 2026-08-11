"""
注意力机制预测模型 (Attention-Based View Prediction Model)
模拟Transformer的注意力机制，动态关注历史数据中的重要时间点。

核心思路：
1. 准备多维输入序列（播放量、增长率、点赞率、位置编码）
2. 用最近几步作为查询（Query），所有历史步作为键（Key）和值（Value）
3. 计算缩放点积注意力分数，加权求和得到上下文向量
4. 基于注意力上下文和近期增长率的加权平均预估未来增长

与标准Transformer的区别：
- 简化版：仅用一个注意力头，不使用多头机制
- 直接对原始序列做注意力，无需位置编码叠加
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
import logging

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import AttentionTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class AttentionMechanismAlgorithm(BaseAlgorithm):
    """
    注意力机制预测算法 (Attention-Based View Prediction)

    使用注意力机制关注历史数据中的重要时间点，
    类似于Transformer的简化版本。

    降级链：torch checkpoint → numpy 注意力 → velocity 兜底
    """

    name = "注意力机制模型"
    algorithm_id = "attention_mechanism"
    description = "关注重要时间点，类似Transformer（torch checkpoint 优先，否则 numpy 简化）"
    category = "深度学习"

    training_window = 10
    """训练窗口长度（时间步数）"""
    training_horizon = 3
    """预测步数"""

    def __init__(self):
        """初始化注意力机制模型。

        设置模型维度 d_model=16（控制缩放点积的缩放因子），
        注意力头数 n_heads=2（伪多头，用于计算缩放因子）。
        """
        super().__init__()
        self.d_model = 16  # 模型维度（控制注意力分数缩放）
        self.n_heads = 2  # 注意力头数

    def build_model(self):
        """构建训练用的 PyTorch 模型。

        Returns:
            AttentionTorchModel 实例
        """
        return AttentionTorchModel(
            in_features=getattr(self, '_training_n_features', 5),
            d_model=32,
            n_heads=4,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def get_training_features(self):
        """获取训练使用的特征列表。

        Returns:
            特征名称列表
        """
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """统一预测接口：从 video_data 提取参数, 委托 _predict_inner, 包装为 PredictionResult。"""
        current_views = video_data.get("view_count", 0)
        history_data = self._normalize_history(video_data.get("history_data", []))
        result = self._predict_inner(current_views, threshold, history_data, video_data)
        return self._to_prediction_result(result, current_views, video_data, threshold)

    def _predict_inner(
        self, current_views: int, target_views: int, history_data: List[Dict[str, Any]], video_info: Dict[str, Any]
    ) -> Optional[Tuple[int, float]]:
        """预测到达目标播放量所需时间。

        优先尝试 torch checkpoint 推理，失败则降级到 numpy 注意力机制。

        Args:
            current_views: 当前播放量
            target_views: 目标播放量阈值
            history_data: 历史数据列表，每项含 view, like, coin, favorite, share 等字段
            video_info: 视频信息字典

        Returns:
            (预测秒数, 置信度) 元组，失败返回 None
        """
        # torch 优先
        torch_result = self._try_torch_predict(current_views, target_views, history_data, video_info)
        if torch_result is not None:
            return torch_result

        if not history_data or len(history_data) < 8:
            return None

        try:
            # 准备序列数据（多变量输入）
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

            seconds_needed = int(days_needed * 86400)  # 转换为秒
            confidence = self._calculate_confidence(sequence, context)

            return (seconds_needed, confidence)

        except Exception as e:
            logger.warning(f"注意力机制预测失败: {e}")
            return None

    def _prepare_sequence(self, history_data: List[Dict[str, Any]]) -> np.ndarray:
        """准备多维输入序列。

        每个时间步包含 4 个特征（已归一化）:
        - [0]: 播放量 / 10000（对数尺度归一化）
        - [1]: 增长率 / 1000（增量归一化，第一帧为 0）
        - [2]: 点赞率 × 10（比例归一化）
        - [3]: sin(i/10)（简化的位置编码，提供时序信息）

        Args:
            history_data: 历史数据列表

        Returns:
            numpy 数组 [N, 4]
        """
        sequence = []

        for i, data in enumerate(history_data):
            view = data.get("view", 0)
            like = data.get("like", 0)

            # 计算增长率（相邻帧差值）
            if i > 0:
                prev_view = history_data[i - 1].get("view", 0)
                growth_rate = view - prev_view
            else:
                growth_rate = 0

            # 点赞率 = 点赞 / 播放（避免除以零）
            like_rate = like / max(view, 1)

            # 时间编码 (位置编码简化版，使用正弦函数)
            time_enc = np.sin(i / 10)

            sequence.append([view / 10000, growth_rate / 1000, like_rate * 10, time_enc])

        return np.array(sequence)

    def _apply_attention(self, sequence: np.ndarray) -> np.ndarray:
        """应用简化版缩放点积注意力机制。

        使用最近 3 步的平均作为查询向量（Query），
        所有时间步作为键（Key）和值（Value），
        计算缩放点积注意力分数并加权汇聚。

        Query 的设计思路：最近多步能更好地反映当前趋势方向。

        Args:
            sequence: 多维序列 [N, 4]

        Returns:
            context: 注意力加权后的上下文标量值
        """
        len(sequence)

        # 使用最后几个时间步作为查询（反映当前趋势方向）
        query = sequence[-3:].mean(axis=0)  # [d_model]

        # 所有时间步作为键和值
        keys = sequence  # [n, d_model] — 键（用于计算相似度）
        values = sequence[:, 1]  # 使用增长率作为值 [n]

        # 计算注意力分数（缩放点积）
        scores = np.dot(keys, query) / np.sqrt(self.d_model)  # [n] 缩放防梯度爆炸

        # Softmax 归一化
        exp_scores = np.exp(scores - np.max(scores))  # 减去最大值防数值溢出
        attention_weights = exp_scores / np.sum(exp_scores)

        # 加权求和得到上下文
        context = np.sum(attention_weights * values)

        return context

    def _predict_growth(self, context: float, sequence: np.ndarray) -> float:
        """基于注意力上下文预测未来增长率。

        综合近期增长率（60% 权重）和注意力上下文（40% 权重）：
        - 近期增长率反映最新趋势
        - 注意力上下文反映历史相似模式

        Args:
            context: 注意力加权上下文值
            sequence: 完整的多维序列

        Returns:
            预测的每日播放量增长（不低于 1）
        """
        # 最近的增长率（反归一化）
        recent_growth = sequence[-1][1] * 1000  # 反归一化（乘以1000）

        # 注意力上下文（反归一化）
        attention_growth = context * 1000  # 反归一化（乘以1000）

        # 结合两者（近期偏重 60%）
        predicted = 0.6 * recent_growth + 0.4 * attention_growth

        return max(1, predicted)  # 保底最小值

    def _calculate_confidence(self, sequence: np.ndarray, context: float) -> float:
        """计算预测置信度。

        基于两个因素：
        1. 数据量：更多数据点 → 更高置信度（基础 0.3，每点 +0.025，上限 0.85）
        2. 序列稳定性：增长率变异系数越低 → 序列越稳定 → 置信度越高

        Args:
            sequence: 多维序列
            context: 注意力上下文值（未使用，保留接口兼容）

        Returns:
            置信度 [0, 0.9]
        """
        n = len(sequence)

        # 基础置信度（基于数据量）
        base_conf = min(0.85, 0.3 + n * 0.025)

        # 序列稳定性（增长率变异系数评估）
        growth_rates = sequence[:, 1]  # 增长率列
        if len(growth_rates) > 1:
            cv = np.std(growth_rates) / (np.mean(np.abs(growth_rates)) + 0.001)  # 变异系数
            stability = max(0, 1 - cv)  # CV 越小越稳定
            base_conf = 0.6 * base_conf + 0.4 * stability

        return min(0.9, base_conf)

    def _try_torch_predict(
        self, current_views: int, target_views: int, history_data: List[Dict[str, Any]], video_info: Dict[str, Any]
    ) -> Optional[Tuple[int, float]]:
        """尝试使用 PyTorch checkpoint 进行推理。

        如果 checkpoint 存在且推理成功，返回预测结果；
        任何失败都返回 None，让上游降级到 numpy 方案。

        Args:
            current_views: 当前播放量
            target_views: 目标播放量
            history_data: 历史数据列表
            video_info: 视频信息字典

        Returns:
            (预测秒数, 置信度) 或 None
        """
        if not hasattr(self, "_ckpt"):
            from algorithms.training.checkpoint_manager import CheckpointManager

            self._ckpt = CheckpointManager(self.algorithm_id)
        try:
            from datetime import datetime

            # 包装历史数据，统一字段名
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
