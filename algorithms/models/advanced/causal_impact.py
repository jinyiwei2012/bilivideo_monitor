"""
CausalImpact（因果推断）预测算法
===============================

基于贝叶斯结构时间序列模型（BSTS）的简化版CausalImpact方法，
用于量化视频互动指标（点赞、投币、收藏、分享）对播放量增长的因果贡献。

核心原理：
    1. 将历史数据分为"干预前"（训练集）和"干预后"（测试集）两个时期
    2. 用训练集构建协变量（互动指标）与播放量的线性回归关系
    3. 利用回归系数预测测试集的"反事实"播放量（即如果没有互动增长时的播放量）
    4. 实际播放量与反事实播放量之差即为互动指标的因果贡献
    5. 将因果贡献转化为速度增量，叠加到基础速度上

协变量构造：
    - 对数变换后的点赞/投币/收藏/分享（log1p，处理零值和长尾分布）
    - 点赞和投币的梯度（捕捉互动变化的加速度信号）

适用场景：
    - 需要量化互动指标对播放量增长的实际推动效果
    - 历史数据 ≥ 10 个点时可获得有意义的因果估计
    - 数据不足时回退为简单的速度外推
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class CausalImpactAlgorithm(BaseAlgorithm):
    """
    CausalImpact 因果推断预测算法

    主要功能：
        - 利用互动指标作为协变量，回归分析其与播放量的关系
        - 计算互动指标对播放量增长的因果贡献（impact）
        - 综合基础速度和因果贡献速度，生成最终预测

    算法原理：
        1. 将历史数据按时间中点分为前后两段（split）
        2. 前段数据训练线性回归：views ~ 1 + covariates
        3. 用训练好的系数预测后段的反事实值
        4. 因果效应 = 真实值 - 反事实值
        5. 近期因果效应的平均值转化为速度增量

    类属性：
        name (str)          : "CausalImpact因果"
        algorithm_id (str)  : "causal_impact"
        description (str)   : 算法简要描述
        category (str)      : "高级分析"
        default_weight (float): 1.0
    """

    name = "CausalImpact因果"
    algorithm_id = "causal_impact"
    description = "贝叶斯结构时间序列，量化互动指标因果贡献"
    category = "高级分析"
    default_weight = 1.0

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行因果推断预测

        算法流程：
            1. 检查历史数据是否充足（≥10个点）且速度为正值
            2. 从历史数据中提取播放量和各类互动指标（点赞、投币、收藏、分享）
            3. 对互动指标做对数变换（log1p）以稳定方差并处理长尾分布
            4. 计算互动指标的梯度（捕捉加速度信号）
            5. 将数据分为前后两段：前段训练回归模型，后段计算因果效应
            6. 计算 R² 值评估回归拟合质量
            7. 综合基础速度和因果贡献速度生成最终预测

        Args:
            video_data (Dict[str, Any]): 包含视频数据的字典，期望字段：
                - view_count (int)         : 当前总播放量
                - history_data (list[dict]): 历史数据点列表
                  每个点含 view, like, coin, favorite, share
            threshold (int): 目标播放量阈值，默认为 100,000

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # ── 数据不足或速度为0时使用回退策略 ──
        if len(history) < 10 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold, method="causal_impact")

        try:
            # ── 提取各类互动指标的时间序列 ──
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            likes = np.array([h.get("like", 0) for h in history], dtype=np.float64)
            coins = np.array([h.get("coin", 0) for h in history], dtype=np.float64)
            favs = np.array([h.get("favorite", 0) for h in history], dtype=np.float64)
            shares = np.array([h.get("share", 0) for h in history], dtype=np.float64)

            # ── 构造协变量矩阵 ──
            # 同时包含：水平值（对数变换）+ 梯度值（捕捉加速度/减速度）
            covariates = np.column_stack(
                [
                    np.log1p(likes),   # 点赞数对数变换，处理零值和偏态分布
                    np.log1p(coins),   # 投币数对数变换
                    np.log1p(favs),    # 收藏数对数变换
                    np.log1p(shares),  # 分享数对数变换
                    np.gradient(likes),  # 点赞梯度 → 捕捉点赞增长/下降的加速度
                    np.gradient(coins),  # 投币梯度 → 捕捉投币变化趋势
                ]
            )
            covariates = np.nan_to_num(covariates)  # 将 NaN 替换为 0

            # ── 将数据分为前后两段（按时间中点切分） ──
            split = max(len(views) // 2, 3)  # 至少保留3个点作为训练集
            y_pre = views[:split]   # 前段：训练集播放量
            X_pre = covariates[:split]  # 前段：训练集协变量
            y_post = views[split:]  # 后段：测试集播放量
            X_post = covariates[split:]  # 后段：测试集协变量

            # ── 添加截距项（偏置列） ──
            X_pre = np.column_stack([np.ones(len(X_pre)), X_pre])
            X_post = np.column_stack([np.ones(len(X_post)), X_post])

            # ── 最小二乘线性回归：views ~ 1 + covariates ──
            beta = np.linalg.lstsq(X_pre, y_pre, rcond=None)[0]  # 回归系数
            y_pred = X_post @ beta  # 对后段的"反事实"预测（如果没有互动增长时的播放量）

            # ── 因果效应 = 真实值 - 反事实值 ──
            impact = y_post - y_pred  # 逐点的因果贡献
            cum_impact = np.cumsum(impact)  # 累积因果贡献

            # ── 近期因果效应的平均值（最近5个点或全部），转化为速度增量 ──
            recent_impact = np.mean(impact[-min(5, len(impact)) :]) if len(impact) >= 1 else 0
            impact_velocity = recent_impact / 3600  # 因果贡献转换为每小时速度

            # ── 综合基础速度（70%）和因果贡献速度（30%） ──
            base_velocity = velocity * 0.7
            predicted_velocity = max(0, base_velocity + impact_velocity)
            if predicted_velocity < 1:
                predicted_velocity = velocity  # 速度过低时退化为当前速度

            # ── 计算预测时间和置信度 ──
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                # R² 决定系数：衡量回归拟合质量
                r2 = 1 - np.sum((y_post - y_pred) ** 2) / max(np.sum((y_post - np.mean(y_post)) ** 2), 1)
                confidence = max(0.1, min(0.85, 0.5 + 0.3 * max(0, r2)))  # R²越高，置信度越高

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={
                    "method": "causal_impact",
                    "cum_impact": float(cum_impact[-1]) if len(cum_impact) > 0 else 0,  # 累积因果贡献
                    "r2": float(r2),  # 回归拟合优度
                },
                timestamp=datetime.now(),
            )
        except Exception:
            # ── 异常回退处理 ──
            return self._fallback(velocity, current_views, threshold, method="causal_impact")
