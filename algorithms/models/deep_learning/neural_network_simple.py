"""
神经网络简化预测算法
===================

基于前馈神经网络思想的简化实现，模拟神经网络的输入层→隐藏层→输出层结构，
用于预测B站视频播放量达到指定阈值所需的时间。

核心原理:
    1. 输入层：提取7维特征（归一化播放量、速度、互动率、质量分、视频年龄、点赞率、投币率）
    2. 隐藏层：加权求和 + ReLU激活（简化的单层全连接）
    3. 输出层：基于隐藏层输出调整基准预测（线性等比缩放）

降级链：torch checkpoint（MLPTorchModel） → numpy手动前向传播
"""

from datetime import datetime
import math
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import MLPTorchModel, try_torch_predict


class NeuralNetworkSimpleAlgorithm(BaseAlgorithm):
    """神经网络简化预测算法

    模拟多层感知机的基础结构：输入特征 → 加权隐藏层(ReLU) → 输出调整因子。
    不使用PyTorch即可运行全流程，适合作为轻量级基线模型。
    """

    name = "神经网络简化"
    algorithm_id = "neural_network_simple"
    description = "基于神经网络前向传播的简化预测"
    category = "深度学习"
    default_weight = 1.2

    training_window = 10     # 训练时使用的历史窗口长度
    training_horizon = 3     # 训练时预测的未来步数

    def predict(self, video_data, threshold=100000):
        """执行预测

        优先使用torch模型，否则回退到numpy实现。

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult: 预测结果
        """
        return try_torch_predict(
            self,
            video_data,
            threshold,
            MLPTorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建MLP PyTorch模型实例"""
        return MLPTorchModel(in_features=getattr(self, '_training_n_features', 5), window=10, horizon=self.training_horizon)

    def get_training_features(self):
        """返回训练时使用的多维特征列表"""
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """执行预测（numpy手动实现）

        步骤：
        1. 构建7维输入特征向量
        2. 加权求和作为隐藏层输出
        3. ReLU激活（非负截断）
        4. 基于隐藏层输出调整基准线性预测

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult: 预测结果
        """
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours = 0
            confidence = 1.0
        elif velocity <= 0:
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            # ===== 输入层特征（7维） =====
            inputs = [
                math.log(max(current_views, 1)) / 20,                  # 归一化播放量（对数压缩）
                math.log(max(velocity, 0.001)) / 10,                  # 归一化速度
                self.get_engagement_rate(video_data),                  # 互动率 [0, 1]
                self.get_quality_score(video_data),                    # 质量评分 [0, 1]
                min(1.0, self.get_video_age_hours(video_data) / 168), # 年龄归一化（一周=1）
                video_data.get("like_count", 0) / max(current_views, 1) * 10,   # 点赞率 ×10
                video_data.get("coin_count", 0) / max(current_views, 1) * 100,  # 投币率 ×100
            ]

            # ===== 隐藏层（简化：固定加权求和 + ReLU激活） =====
            # 各权重含义：速度>互动>点赞>质量>投币>分享>年龄（负权重表示年龄越大活跃度越低）
            hidden_weights = [0.15, 0.25, 0.20, 0.15, -0.10, 0.10, 0.15]
            hidden_sum = sum(i * w for i, w in zip(inputs, hidden_weights))

            # ReLU激活：负值归零，模拟神经元的非线性响应
            hidden_output = max(0, hidden_sum)

            # ===== 输出层：调整基准线性预测 =====
            base_prediction = remaining / velocity                # 基准线性预测（小时数）
            adjustment = 1 - hidden_output * 0.5                 # 网络学习到的调整因子
            # 隐藏层输出越大（质量越好），调整因子越小，预测时间越短

            predicted_hours = base_prediction * adjustment
            if predicted_hours < 0:
                predicted_hours = base_prediction  # 防止负值

            # 置信度：隐藏层输出越高，置信度越高
            confidence = min(1.0, 0.5 + hidden_output)

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={
                "method": "neural_network_simple",
                "hidden_activation": hidden_output if "hidden_output" in dir() else 0,
            },
            timestamp=datetime.now(),
        )
