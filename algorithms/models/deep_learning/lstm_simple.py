"""
LSTM简化预测算法
===============

基于长短期记忆网络（LSTM）思想的简化实现，用于预测B站视频播放量达到指定阈值所需的时间。

核心原理:
    1. 模拟LSTM的三个门控机制：遗忘门、输入门、输出门
    2. 遗忘门：基于视频年龄的时间衰减，视频越老，遗忘越多
    3. 输入门：基于最近数据变化量（增长率），决定新信息的接纳程度
    4. 输出门：基于视频质量评分，控制最终输出强度
    5. 细胞状态更新后输出调整后的速度预测

降级链：torch checkpoint（LSTMTorchModel） → numpy简化门控实现

参考论文：
    "Long Short-Term Memory" (Hochreiter & Schmidhuber, 1997)
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import LSTMTorchModel, try_torch_predict


class LSTMSimpleAlgorithm(BaseAlgorithm):
    """LSTM简化预测算法

    基于LSTM三网关思想（遗忘门/输入门/输出门）的简化实现。
    当有训练好的torch checkpoint时优先使用，否则退化为numpy版本的门控机制模拟。
    """

    name = "LSTM简化"
    algorithm_id = "lstm_simple"
    description = "基于LSTM序列建模思想的简化预测（torch checkpoint 优先，否则 numpy 简化）"
    category = "深度学习"
    default_weight = 1.3

    training_window = 10     # 训练时使用的历史窗口长度
    training_horizon = 3     # 训练时预测的未来步数

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行预测

        优先使用PyTorch模型进行预测，若checkpoint不存在或推理失败，则回退到numpy实现。

        Args:
            video_data: 视频数据字典，包含view_count、history_data等字段
            threshold: 目标播放量阈值，默认100000

        Returns:
            PredictionResult: 预测结果，包含预测小时数、置信度等信息
        """
        return try_torch_predict(
            self,
            video_data,
            threshold,
            LSTMTorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建LSTM PyTorch模型实例

        Returns:
            LSTMTorchModel: LSTM模型，输入特征数由_training_n_features决定，预测步数为training_horizon
        """
        return LSTMTorchModel(in_features=getattr(self, '_training_n_features', 5), horizon=self.training_horizon)

    def get_training_features(self):
        """返回训练时使用的多维特征列表

        Returns:
            list: 包含播放量、点赞、投币、收藏、分享5个特征名
        """
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行numpy版本的LSTM简化预测（无torch时的回退方案）

        模拟LSTM的三大门控机制：
        - 遗忘门：基于视频年龄的时间衰减因子
        - 输入门：基于最近播放量变化率的信号强弱
        - 输出门：基于视频质量评分调节最终输出

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult: 预测结果
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 计算距离阈值还差多少播放量
        remaining = threshold - current_views
        if remaining <= 0:
            # 已经达到阈值
            predicted_hours = 0
            confidence = 1.0
        elif velocity <= 0:
            # 增长停滞，无法达到阈值
            predicted_hours = float("inf")
            confidence = 0.0
        elif len(history) < 2:
            # 历史数据太少，直接线性外推
            predicted_hours = remaining / velocity
            confidence = 0.4
        else:
            # ===== 简化的LSTM门控机制 =====

            # 提取序列特征：最近10个数据点的播放量序列
            views_seq = [h.get("view_count", 0) for h in history[-10:]]

            # 遗忘门：基于时间衰减，视频发布超过24小时后遗忘效应增强
            age_hours = self.get_video_age_hours(video_data)
            forget_gate = 1 / (1 + age_hours / 24)  # 24小时后遗忘增加

            # 输入门：基于新数据的变化率决定信息接入程度
            if len(views_seq) >= 2:
                recent_change = (views_seq[-1] - views_seq[-2]) / max(views_seq[-2], 1)
                input_gate = min(1.0, max(0.0, recent_change * 10))
            else:
                input_gate = 0.5

            # 输出门：基于视频质量评分
            quality = self.get_quality_score(video_data)
            output_gate = quality

            # 细胞状态更新：遗忘旧速度 + 输入新信息
            cell_state = velocity * forget_gate + velocity * input_gate * 0.1

            # 预测输出：细胞状态经输出门过滤
            adjusted_velocity = cell_state * output_gate
            if adjusted_velocity <= 0:
                adjusted_velocity = velocity * 0.5  # 兜底值

            predicted_hours = remaining / adjusted_velocity

            # 置信度：历史数据越多、质量越高，置信度越高
            confidence = min(1.0, 0.5 + len(history) * 0.05 + quality * 0.2)

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "lstm_simple", "sequence_length": len(history)},
            timestamp=datetime.now(),
        )
