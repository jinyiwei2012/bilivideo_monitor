"""
贝叶斯模型平均 (Bayesian Model Averaging, BMA) 模块
===================================================

本模块实现了基于 BIC 准则的贝叶斯模型平均集成预测算法。
用 BIC/AIC 对多模型输出做贝叶斯加权，替代固定权重。

算法来源：
    Hoeting et al. (1999) "Bayesian Model Averaging: A Tutorial", Statistical Science.
    核心思想：不选单一"最佳"模型，而是用后验概率对所有候选模型做加权平均，
    从而自动考虑模型不确定性，提升预测稳健性。

核心原理：
    1. 先构造多个不同复杂度（线性/二次/指数/三次/移动平均）的基预测器。
    2. 对每个模型计算 BIC = n * log(MSE) + k * log(n)，其中 k 为参数个数惩罚。
    3. 后验模型概率 w_i ∝ exp(-0.5 * ΔBIC_i)，即 BIC 越小（拟合越好且越简单）权重越高。
    4. 最终预测 = Σ w_i * pred_i，这是近似贝叶斯模型平均。

适用场景：数据量中等的视频，需自动权衡简单模型与复杂模型的预测信号。
"""

import numpy as np
from typing import Dict, List, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class BayesianModelAveragingAlgorithm(BaseAlgorithm):
    """
    贝叶斯模型平均 (BMA) 集成预测器。

    同时使用 5 种不同复杂度的基预测器（线性、二次、移动平均、指数、三次），
    用 BIC 准则计算每个模型的后验权重，最终加权融合得到预测值。

    关键优势：
        - 自动惩罚过复杂的模型（BIC 中的 k*log(n) 项），防止过拟合。
        - 数据越少，简单模型（移动平均）自动获得更高权重。
        - 不依赖单一模型的假设，鲁棒性更强。

    类属性：
        name (str): 算法名称 "贝叶斯平均"
        algorithm_id (str): 算法唯一标识 "bayesian_averaging"
        description (str): 算法简述
        category (str): 所属类别 "集成学习"
        default_weight (float): 默认集成权重 1.5（高）
    """

    name = "贝叶斯平均"
    algorithm_id = "bayesian_averaging"
    description = "BIC后验加权，替代固定权重，信息论最优"
    category = "集成学习"
    default_weight = 1.5

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """
        执行 BMA 预测。

        Args:
            video_data (Dict): 包含 view_count、history_data 等字段的视频数据字典。
            threshold (int): 目标播放量阈值，默认 100000。

        Returns:
            PredictionResult: 包含预测到达阈值所需小时数、置信度、元数据的预测结果。

        流程：
            1. 数据不足（<12 点）时回退到简单匀速外推。
            2. 构造 5 个基模型（线性/二次/移动平均/指数/三次）。
            3. 用历史最后 30% 数据做验证集，计算各模型的 BIC。
            4. softmax 得到后验权重，加权融合得到最终预测速度。
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据量不足时回退到匀速外推
        if len(history) < 12 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "bma_fallback"}, timestamp=datetime.now(),
            )

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        n = len(views)

        # ========== 构建基模型池：5 个不同复杂度的预测器 ==========
        methods = []  # 各模型预测的增量（播放量/数据点）
        names = []    # 模型名称，用于 k 值映射

        # M1: 线性拟合 — 复杂度 k=2（斜率+截距）
        # 仅需 3 个数据点，适合早期视频
        if n >= 3:
            methods.append(np.polyfit(np.arange(min(10, n)), views[-min(10, n):], 1)[0])
            names.append("linear")

        # M2: 二次多项式 — 复杂度 k=3（二次+一次+常数）
        # 需要 5 个数据点，适合捕捉曲率变化
        if n >= 5:
            methods.append(np.polyfit(np.arange(min(10, n)), views[-min(10, n):], 2)[0])
            names.append("quadratic")

        # M3: 移动平均 — 复杂度 k=1（最简模型，仅一个均值参数）
        # 数据少时的最强基线模型，BIC 惩罚最小
        methods.append(np.mean(np.diff(views[-min(8, n):])))
        names.append("moving_avg")

        # M4: 指数增长 — 复杂度 k=2（对 log 值做线性拟合）
        # 适合病毒式传播视频
        if n >= 5:
            try:
                log_v = np.log(np.maximum(views[-min(10, n):], 1))
                methods.append(np.polyfit(np.arange(len(log_v)), log_v, 1)[0] * views[-1])
                names.append("exponential")
            except Exception:
                pass  # log 变换失败时跳过（极端情况）

        # M5: 三次多项式 — 复杂度 k=4（最高阶，仅数据充足时启用）
        # BIC 会对高 k 强烈惩罚，只有拟合极好时才有效
        if n >= 8:
            methods.append(np.polyfit(np.arange(min(10, n)), views[-min(10, n):], 3)[0])
            names.append("cubic")

        # 基模型不足 2 个时直接使用简单匀速
        if len(methods) < 2:
            growth = velocity * 3600
        else:
            # ========== BIC 计算：用最后 30% 数据做验证集 ==========
            val_start = max(1, int(n * 0.7))
            actual = np.diff(views[val_start - 1:])  # 验证集的实际增量序列

            bics = []         # 各模型的 BIC 值
            valid_methods = []  # 对应有 BIC 的模型预测
            valid_names = []    # 对应模型名

            for i, method_growth in enumerate(methods):
                if i >= len(actual):
                    continue

                # 将模型预测的恒定增量与验证集实际增量比较
                pred_diffs = np.full(len(actual), method_growth)
                mse = np.mean((actual - pred_diffs) ** 2)
                if mse < 1e-10:
                    mse = 1e-10  # 防止 log(0)

                # BIC = n * log(MSE) + k * log(n)，k 为模型参数个数
                # k_map 映射：模型名 → 参数个数（作为复杂度惩罚项）
                k_map = {"linear": 2, "quadratic": 3, "moving_avg": 1, "exponential": 2, "cubic": 4}
                k = k_map.get(names[i], 2)
                bic = len(actual) * np.log(mse) + k * np.log(len(actual))
                bics.append(bic)
                valid_methods.append(method_growth)
                valid_names.append(names[i])

            if not bics:
                growth = methods[0]  # 没有 BIC 可用，取第一个基模型
            else:
                # ========== ΔBIC → softmax → 后验权重 ==========
                bics = np.array(bics)
                delta_bic = bics - bics.min()  # 每个模型相对于最优模型的 BIC 差距
                weights = np.exp(-0.5 * delta_bic)  # 后验权重正比于 exp(-0.5 * ΔBIC)
                weights /= weights.sum()  # 归一化使权重和为 1
                growth = np.dot(weights, valid_methods)  # 加权平均得到最终预测增量

        # 转换为每秒播放量速度（每小时播放量 = growth / 3600）
        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        # 计算到达阈值所需时间
        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")

        # 置信度：综合最优模型权重、模型数量
        # 最优模型权重越大 → 说明某个模型明显更优 → 预测更可信
        n_models = len(bics) if "bics" in dir() else len(methods)
        top_weight = weights.max() if "weights" in dir() else 1.0
        confidence = max(0.1, min(0.9, 0.3 + 0.3 * top_weight + 0.02 * min(n_models, 5)))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={
                "method": "bma",
                "n_models": n_models,
                "top_weight": round(float(top_weight), 3),
                "delta_bic": round(float(delta_bic.max() - delta_bic.min()), 1) if "delta_bic" in dir() else 0,
            },
            timestamp=datetime.now(),
        )
