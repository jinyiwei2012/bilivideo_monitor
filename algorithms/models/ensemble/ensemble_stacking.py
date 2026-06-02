"""
堆叠集成预测算法模块
====================

本模块实现了基于元学习（Meta-Learning）的两层堆叠集成预测算法。
第一层由多个基础学习器独立预测，第二层元学习器综合第一层输出
给出最终预测。

核心原理：
    1. 第一层（基础学习器）：4 个学习器分别从速度/互动/质量/时间角度预测
    2. 第二层（元学习器）：将第一层输出 + 原始特征作为输入，加权融合
    3. 元权重模拟了"如果知道各学习器的输出，应该如何信任它们"

与简单平均集成的区别：
    - 简单平均：所有预测器等权平均
    - 堆叠集成：学习最优权重组合，给更可靠的学习器更高权重

适用场景：
    - 中等数据量的视频（需要多种视角交叉验证）
    - 需要捕获学习器间非线性互补关系的场景
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class EnsembleStackingAlgorithm(BaseAlgorithm):
    """
    堆叠集成预测算法

    采用两层结构：第一层 4 个基础学习器独立预测，
    第二层元学习器学习如何最优组合它们的结果。
    元权重模拟了训练好的模型在类似视频上的表现。

    类属性：
        name (str): 算法名称 "堆叠集成"
        algorithm_id (str): 算法唯一标识 "ensemble_stacking"
        description (str): 算法简述
        category (str): 所属类别 "集成模型"
        default_weight (float): 默认集成权重 1.4（中高）
    """

    name = "堆叠集成"
    algorithm_id = "ensemble_stacking"
    description = "基于元学习的堆叠集成预测"
    category = "集成模型"
    default_weight = 1.4

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行两层堆叠集成预测。

        第一层 - 4 个基础学习器：
            1. 速度模型（权重 0.30）：基于当前播放速度的匀速外推
            2. 互动模型（权重 0.20）：互动率越高，到达越快
            3. 质量模型（权重 0.25）：质量评分越高，到达越快
            4. 时间模型（权重 0.15）：视频发布越久，可能有衰减

        第二层 - 元学习器：
            - 输入：4 个学习器输出 + 3 个原始特征（互动率/质量/时间）
            - 权重：[0.30, 0.20, 0.25, 0.15, 0.05, 0.03, 0.02]
            - 对归一化后的特征做加权求和，得到融合结果
            - 最终预测 = 基础预测 * (0.5 + 融合结果)

        Args:
            video_data (Dict): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        Returns:
            PredictionResult: 包含预测到达时间、置信度、元数据的结果对象
        """
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            # 已达标
            predicted_hours = 0
            confidence = 1.0
        elif velocity <= 0:
            # 无增长
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            # 第一层：基础学习器
            base = remaining / velocity  # 基准匀速预测

            # 学习器1: 速度模型 — 纯匀速
            learner1 = base

            # 学习器2: 互动模型 — 高互动 → 更快（除以互动率）
            engagement = self.get_engagement_rate(video_data)
            learner2 = base / (1 + engagement)

            # 学习器3: 质量模型 — 高质量 → 更快
            quality = self.get_quality_score(video_data)
            learner3 = base / (0.8 + quality * 0.4)

            # 学习器4: 时间模型 — 新视频可能有增长空间
            age_hours = self.get_video_age_hours(video_data)
            learner4 = base * (1 + min(age_hours / 48, 1) * 0.3)

            # 第二层：元学习器（加权组合所有学习器 + 原始特征）
            meta_features = [learner1, learner2, learner3, learner4, engagement, quality, min(age_hours / 168, 1)]

            # 元权重：模拟训练好的权重，更信任速度和互动模型
            meta_weights = [0.30, 0.20, 0.25, 0.15, 0.05, 0.03, 0.02]

            # 特征归一化：前 4 个除以基准值，后 3 个直接使用
            normalized_features = [
                meta_features[0] / (base + 1),  # 归一化学习器输出
                meta_features[1] / (base + 1),
                meta_features[2] / (base + 1),
                meta_features[3] / (base + 1),
                meta_features[4],  # 原始特征直接使用
                meta_features[5],
                meta_features[6],
            ]

            # 加权融合得到最终预测
            blend = sum(f * w for f, w in zip(normalized_features, meta_weights))
            predicted_hours = base * (0.5 + blend)  # 以基准值为中心调整

            # 防止异常负值
            if predicted_hours < 0:
                predicted_hours = base

            confidence = 0.75  # 固定置信度（多层结构通常较稳定）

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "ensemble_stacking", "learners": 4},
            timestamp=datetime.now(),
        )
