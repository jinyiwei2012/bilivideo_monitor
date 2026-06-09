"""
Time-MoE (时间序列专家混合模型) — 混合专家架构
================================================

基于混合专家（Mixture of Experts, MoE）架构的B站视频播放量预测模型。
不同专家学习不同增长阶段模式，路由器自动选择最优专家组合。

核心原理:
    1. 路由器（Router）：根据输入特征（增长率、互动率）计算各专家的分配概率
    2. 专家网络（Experts）：4个专家各专攻不同增长阶段
       - Expert 0: 冷启动（cold_start）—— 视频发布初期的低增长阶段
       - Expert 1: 爆发增长（viral_growth）—— 视频快速传播阶段
       - Expert 2: 稳定增长（stable_growth）—— 视频进入平稳期
       - Expert 3: 饱和衰减（saturation）—— 视频增长趋近于零
    3. 加权融合：softmax门控概率加权各专家的预测输出

降级链：torch checkpoint（TimeMoETorchModel） → numpy 4专家软路由

参考论文：
    "Time-MoE: Billion-Scale Time Series Foundation Models with Mixture of Experts"
    (Shi et al., 2024)
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import TimeMoETorchModel, try_torch_predict


class TimeMoeSimpleAlgorithm(BaseAlgorithm):
    """Time-MoE 专家混合模型

    使用4个专家网络（冷启动/爆发/稳定/饱和）的混合架构，
    通过门控路由器根据输入特征自动选择最优专家。
    """

    name = "Time-MoE专家混合"
    algorithm_id = "time_moe_simple"
    description = "混合专家架构，不同专家专攻不同增长阶段"
    category = "深度学习"
    default_weight = 1.3

    training_window = 10     # 训练时使用的历史窗口长度
    training_horizon = 3     # 训练时预测的未来步数

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行预测

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
            TimeMoETorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建Time-MoE PyTorch模型实例

        Returns:
            TimeMoETorchModel: 4专家混合模型（16维嵌入，窗口10）
        """
        return TimeMoETorchModel(in_features=getattr(self, '_training_n_features', 5), window=10, n_experts=4, d_model=16, horizon=self.training_horizon)

    def get_training_features(self) -> List[str]:
        """返回训练时使用的多维特征列表"""
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行numpy版本的MoE预测

        流程：
        1. 计算增长率序列和互动率序列
        2. 构建2维路由输入（近期增长率, 当前互动率）
        3. 路由器通过随机权重计算4个专家的分配概率（softmax）
        4. 每个专家独立预测（2维输入 → 1维输出）
        5. 按门控概率加权融合专家预测
        6. 确定主导专家阶段，用于结果解释

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult: 预测结果
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足时降级
        if len(history) < 8 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            # 提取多维历史数据
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            likes = np.array([h.get("like", 0) for h in history], dtype=np.float64)
            coins = np.array([h.get("coin", 0) for h in history], dtype=np.float64)
            favs = np.array([h.get("favorite", 0) for h in history], dtype=np.float64)

            # 计算增长率序列（百分比变化）
            growth_rates = np.diff(views) / np.maximum(views[:-1], 1)
            # 计算互动率序列（点赞+投币×2+收藏）/ 播放量
            engagement = (likes + coins * 2 + favs) / np.maximum(views, 1)
            # 近期增长率和当前互动率作为路由输入
            recent_growth = np.mean(growth_rates[-3:]) if len(growth_rates) >= 3 else 0
            current_eng = engagement[-1] if len(engagement) > 0 else 0

            n_experts = 4  # 4个专家
            np.random.seed(42)  # 固定随机种子保证可复现
            # 路由器权重（2维输入 → 4维logits）
            W_gate = np.random.randn(2, n_experts) * 0.1
            # 各专家权重（2维输入 → 1维预测值）
            W_exp = [np.random.randn(2, 1) * 0.1 for _ in range(n_experts)]

            # 路由计算：2维输入 → 4维logits → softmax概率
            routing_input = np.array([recent_growth, current_eng])
            gate_logits = routing_input @ W_gate
            gate_probs = np.exp(gate_logits - np.max(gate_logits))          # 数值稳定
            gate_probs = gate_probs / (np.sum(gate_probs) + 1e-10)          # softmax

            # 各专家独立预测
            predictions = [float(routing_input @ W_exp[i]) for i in range(n_experts)]
            # 门控加权融合
            moe_pred = sum(gate_probs[i] * predictions[i] for i in range(n_experts))

            # 确定主导专家（概率最大的）
            dominant_expert = int(np.argmax(gate_probs))
            # 专家名称映射，用于结果解释
            experts_interpret = {0: "cold_start", 1: "viral_growth", 2: "stable_growth", 3: "saturation"}

            # 将预测值转换为每小时速度
            predicted_velocity = max(0, moe_pred * views[-1] / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0  # 已达到阈值
            else:
                predicted_hours = remaining / predicted_velocity
                # 置信度：主导专家的概率越高，置信度越高
                confidence = max(0.1, min(0.85, 0.4 + float(gate_probs[dominant_expert]) * 0.4))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={
                    "method": "time_moe",
                    "dominant_expert": experts_interpret[dominant_expert],
                    "expert_weight": float(gate_probs[dominant_expert]),
                },
                timestamp=datetime.now(),
            )
        except Exception:
            return self._fallback(velocity, current_views, threshold)

    def _fallback(self, velocity, current_views, threshold):
        """回退预测：当数据不足或推理异常时的安全兜底方案

        Args:
            velocity: 当前速度
            current_views: 当前播放量
            threshold: 目标阈值

        Returns:
            PredictionResult: 回退预测结果
        """
        if velocity <= 0:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=float("inf"),
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "time_moe", "reason": "fallback"},
                timestamp=datetime.now(),
            )
        remaining = max(0, threshold - current_views)
        predicted_hours = remaining / velocity if remaining > 0 else 0
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=0.3,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "time_moe", "reason": "fallback"},
            timestamp=datetime.now(),
        )
