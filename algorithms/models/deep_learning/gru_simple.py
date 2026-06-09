"""
GRU简化预测算法 (Gated Recurrent Unit Simplified)
基于门控循环单元思想，比 LSTM 参数更少、训练更快。

核心思路：
1. GRU 仅有两个门：更新门 (z) 和重置门 (r)，省略了 LSTM 的遗忘门
2. 更新门 (z)：决定保留多少过去的隐藏状态（类似 LSTM 的遗忘门 + 输入门）
3. 重置门 (r)：决定忘记多少过去的记忆（影响候选隐藏状态的计算）
4. 候选隐藏状态 h'：基于重置后的过去信息 + 当前输入计算
5. 最终隐藏状态 h = (1-z)*h_{t-1} + z*h'：插值组合旧状态和候选状态

与 LSTM 的对比：
- LSTM：3 个门（遗忘、输入、输出）+ 独立细胞状态
- GRU：2 个门（更新、重置），无独立细胞状态
- GRU 通常比 LSTM 训练更快、更少过拟合，在小样本任务上常优于 LSTM
"""

from datetime import datetime
import math
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import GRUTorchModel, try_torch_predict


class GRUSimpleAlgorithm(BaseAlgorithm):
    """GRU简化预测算法

    GRU 使用更新门和重置门替代 LSTM 的三个门，
    研究表明在播放量预测任务上 GRU 通常优于 LSTM。

    降级链：torch checkpoint → numpy GRU → velocity 兜底
    """

    name = "GRU简化"
    algorithm_id = "gru_simple"
    description = "基于门控循环单元(GRU)的简化预测，比LSTM参数更少"
    category = "深度学习"
    default_weight = 1.3

    training_window = 10
    """训练窗口长度（时间步数）"""
    training_horizon = 3
    """预测步数"""

    def predict(self, video_data, threshold=100000):
        """预测到达目标播放量所需时间。

        优先使用 torch 模型推理，失败降级到 numpy GRU。

        Args:
            video_data: 视频数据字典，含 view_count, history_data, bvid 等字段
            threshold: 目标播放量阈值，默认 100000

        Returns:
            PredictionResult 预测结果对象
        """
        return try_torch_predict(
            self,
            video_data,
            threshold,
            GRUTorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建训练用的 PyTorch 模型。

        Returns:
            GRUTorchModel 实例
        """
        return GRUTorchModel(in_features=getattr(self, '_training_n_features', 5), horizon=self.training_horizon)

    def get_training_features(self):
        """获取训练使用的特征列表。

        Returns:
            特征名称列表
        """
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """numpy 降级预测 - GRU 核心实现。

        手动实现 GRU 的门控机制：
        1. 构建归一化输入特征（对数播放量、对数速度、年龄、增长率）
        2. 计算更新门 z（决定保留旧状态的比例）
        3. 计算重置门 r（决定忽略旧状态的比例）
        4. 计算候选隐藏状态 h'（基于 r * 旧状态 + 新输入）
        5. 线性插值得到最终隐藏状态 h = (1-z)*旧 + z*候选
        6. 调整速度并输出预测

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=0,
                confidence=1.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "gru_simple"},
                timestamp=datetime.now(),
            )

        if velocity <= 0 or len(history) < 2:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.3,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "gru_simple", "notes": "insufficient_data"},
                timestamp=datetime.now(),
            )

        # ── 构建输入特征 ──────────────────────────
        views_seq = [h.get("view_count", 0) for h in history[-8:]]  # 取最近 8 条
        age_hours = self.get_video_age_hours(video_data)
        quality = self.get_quality_score(video_data)

        # 归一化特征（将不同量纲的输入压缩到相近范围）
        log_views = math.log(max(current_views, 1)) / 20.0  # 对数压缩
        log_vel = math.log(max(velocity, 0.001)) / 10.0  # 对数压缩
        norm_age = min(age_hours / 168.0, 1.0)  # 1周归一化 [0, 1]
        recent_growth_rate = 0.0  # 最近增长率
        if len(views_seq) >= 2:
            recent_growth_rate = (views_seq[-1] - views_seq[-2]) / max(views_seq[-2], 1)

        # ── GRU 门控机制 ──────────────────────────
        # 更新门 (z): 决定多少过去的信息传递给未来
        # z = sigmoid(W_z * [h_{t-1}, x_t])
        z_update = 1.0 / (1.0 + math.exp(-(0.3 * log_vel + 0.2 * recent_growth_rate - 0.15 * norm_age)))

        # 重置门 (r): 决定忘记多少过去的信息
        # r = sigmoid(W_r * [h_{t-1}, x_t])
        r_reset = 1.0 / (1.0 + math.exp(-(0.25 * log_views + 0.3 * quality - 0.1 * norm_age)))

        # 候选隐藏状态: h' = tanh(W * [r * h_{t-1}, x_t])
        # r 越小 → 越多的过去信息被遗忘
        candidate = math.tanh(r_reset * log_vel * 0.5 + 0.3 * quality + 0.2 * recent_growth_rate)

        # 最终隐藏状态: h = (1 - z) * h_{t-1} + z * h'
        # z 控制旧状态与候选状态的融合比例
        hidden_state = (1 - z_update) * log_vel + z_update * candidate

        # ── 预测输出 ──────────────────────────
        adjusted_velocity = velocity * (0.5 + hidden_state)  # hidden_state 调整倍率
        if adjusted_velocity <= 0:
            adjusted_velocity = velocity * 0.5  # 保底

        predicted_hours = remaining / adjusted_velocity

        # 置信度（基于数据量和视频质量）
        n_points = len(history)
        conf = min(1.0, 0.4 + n_points * 0.04 + quality * 0.2)

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=conf,
            current_views=current_views,
            current_velocity=adjusted_velocity,
            metadata={
                "method": "gru_simple",
                "update_gate": round(z_update, 3),
                "reset_gate": round(r_reset, 3),
                "hidden_state": round(hidden_state, 3),
                "sequence_length": len(views_seq),
            },
            timestamp=datetime.now(),
        )
