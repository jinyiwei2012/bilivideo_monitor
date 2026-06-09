"""
Blending 集成 (Blending Ensemble) 模块
======================================

本模块实现了 Blending 集成预测算法，用留出验证集训练元学习器，
防止 Stacking 中可能的信息泄露问题。

算法来源：
    Blending 是 Kaggle 竞赛实践中广泛使用的集成技术，由 Netflix Prize 参赛者推广。
    与标准 Stacking 的区别在于使用单一 holdout 验证集而非 K-fold 交叉验证，
    大幅降低计算开销并减少信息泄露风险。

区别于 Stacking：
    - Stacking: K-fold 交叉验证产生元特征，训练集信息可能泄露到元特征。
    - Blending: 固定 holdout 验证集（如 80/20 分割），更简单、更防过拟合。
    - 代价：元学习器的训练数据量减少（仅 holdout 部分），数据少时性能可能下降。

核心流程：
    1. 用 80% 数据训练多个基学习器（Ridge, GBM）。
    2. 基学习器在剩下 20% holdout 上做预测，生成元特征。
    3. 用元特征和真实值训练元学习器（Ridge）。
    4. 最终预测 = 元学习器（基学习器预测）。

适用场景：数据量 ≥ 25 点的视频，需防止数据泄露的精密预测。
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

_HAS_SKLEARN = False
try:
    from sklearn.linear_model import Ridge
    from sklearn.ensemble import GradientBoostingRegressor
    _HAS_SKLEARN = True
except ImportError:
    pass


class BlendingEnsembleAlgorithm(BaseAlgorithm):
    """
    Blending 集成预测器。

    使用 80/20 分割策略训练基学习器和元学习器。基学习器包括 Ridge（捕获线性模式）
    和 GradientBoostingRegressor（捕获非线性模式），元学习器用 Ridge 融合两者输出。

    与 Stacking 的关键区别：
        - 使用单一 holdout 而非 K-fold，避免数据泄露。
        - 元学习器训练数据更少，但更纯粹（未见过的数据）。
        - sklearn 不可用时回退到 NumPy 简易版本。

    类属性：
        name (str): 算法名称 "Blending集成"
        algorithm_id (str): 算法唯一标识 "blending_ensemble"
        description (str): 算法简述
        category (str): 所属类别 "集成学习"
        default_weight (float): 默认集成权重 1.6（高）
    """

    name = "Blending集成"
    algorithm_id = "blending_ensemble"
    description = "留出验证集训练元学习器，防过拟合"
    category = "集成学习"
    default_weight = 1.6

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """
        执行 Blending 集成预测。

        Args:
            video_data (Dict): 包含 view_count、history_data 的视频数据字典。
            threshold (int): 目标播放量阈值，默认 100000。

        Returns:
            PredictionResult: 包含预测到达阈值所需小时数、置信度的结果。

        策略：
            - 数据点 >= 30 且有 sklearn → 使用完整的 Blending + GBM 元学习器。
            - 数据点 >= 25 但无 sklearn → 使用 NumPy 简易版本（均值/中位数加权）。
            - 数据点 < 25 → 匀速外推回退。
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足时回退
        if len(history) < 25 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "blending_fallback"}, timestamp=datetime.now(),
            )

        # 优先使用 sklearn 完整版
        if _HAS_SKLEARN and len(history) >= 30:
            try:
                return self._sklearn_blend(video_data, threshold)
            except Exception:
                pass

        # 回退到 NumPy 简易版
        return self._numpy_blend(video_data, threshold)

    def _sklearn_blend(self, video_data, threshold):
        """
        sklearn 完整版 Blending：Ridge + GBM 基学习器 + Ridge 元学习器。

        特征工程（6 维）：
            1. 线性趋势（polyfit 斜率）
            2. 移动平均速度
            3. 点赞率（like / view）
            4. 投币率（coin / view）
            5. 播放量变异系数（波动程度）
            6. 最近增长比率

        两层结构：
            Level 0 (基学习器): Ridge(alpha=1.0), GBM(60 trees), Ridge(alpha=0.1)
            Level 1 (元学习器): Ridge(alpha=0.5) 在 holdout 上训练

        Args:
            video_data (Dict): 视频数据字典。
            threshold (int): 目标阈值。

        Returns:
            PredictionResult 或 None（训练数据不足时）。
        """
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)
        history = video_data.get("history_data", [])

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        likes = np.array([h.get("like_count", 0) for h in history], dtype=np.float64)
        coins = np.array([h.get("coin_count", 0) for h in history], dtype=np.float64)
        n = len(views)

        p = 6  # 特征窗口大小
        X_all, y_all = [], []
        # 滑动窗口构造特征和目标
        for i in range(p, n - 1):
            feat = [
                np.polyfit(np.arange(p), views[i - p: i], 1)[0],           # 特征1: 线性趋势
                np.mean(np.diff(views[i - p: i])),                          # 特征2: 平均速度
                np.mean(likes[i - p: i]) / max(np.mean(views[i - p: i]), 1),  # 特征3: 点赞率
                np.mean(coins[i - p: i]) / max(np.mean(views[i - p: i]), 1),  # 特征4: 投币率
                np.std(views[i - p: i]) / max(np.mean(views[i - p: i]), 1),   # 特征5: 变异系数
                max(views[i - 1] / max(views[i - 2], 1) - 1, 0),           # 特征6: 最近增长率
            ]
            X_all.append(feat)
            y_all.append(views[i] - views[i - 1])  # 目标: 单步播放量增量

        if len(X_all) < 15:
            return None  # 训练数据不足

        X_all, y_all = np.array(X_all), np.array(y_all)

        # Blending 核心：固定 80/20 分割，holdout 完全不参与基学习器训练
        split = int(len(X_all) * 0.8)
        X_train, X_hold = X_all[:split], X_all[split:]    # train = 80%, holdout = 20%
        y_train, y_hold = y_all[:split], y_all[split:]

        # 如果 holdout 太小（<3），退化到全量训练（小样本场景）
        if len(X_hold) < 3:
            X_train, X_hold = X_all, X_all
            y_train, y_hold = y_all, y_all

        # ========== Layer 0: 基学习器 ==========
        # 3 个不同特性的基学习器：捕获线性 + 非线性 + 弱正则化视角
        models = [
            Ridge(alpha=1.0),                                              # 线性正则化模型（主模型）
            GradientBoostingRegressor(n_estimators=60, max_depth=3, random_state=42),  # 非线性模型
            Ridge(alpha=0.1),                                              # 弱正则化 Ridge（不同角度）
        ]
        meta_X_hold = []  # 元特征矩阵：每个基学习器在 holdout 上的预测
        for m in models:
            m.fit(X_train, y_train)  # 仅用 80% 数据训练基学习器
            meta_X_hold.append(m.predict(X_hold))  # 在 20% holdout 上预测作为元特征
        meta_X_hold = np.column_stack(meta_X_hold)  # 合并为 (n_hold, 3) 元特征矩阵

        # ========== Layer 1: 元学习器 ==========
        # 用 holdout 上的基学习器预测作为输入，学习最优融合权重
        meta = Ridge(alpha=0.5).fit(meta_X_hold, y_hold)

        # ========== 当前时刻预测 ==========
        # 用最近 6 个数据点构造特征
        last_feat = np.array([
            np.polyfit(np.arange(p), views[-p:], 1)[0],        # 特征1
            np.mean(np.diff(views[-p:])),                       # 特征2
            np.mean(likes[-p:]) / max(np.mean(views[-p:]), 1),  # 特征3
            np.mean(coins[-p:]) / max(np.mean(views[-p:]), 1),  # 特征4
            np.std(views[-p:]) / max(np.mean(views[-p:]), 1),   # 特征5
            max(views[-1] / max(views[-2], 1) - 1, 0),         # 特征6
        ]).reshape(1, -1)

        # 基学习器预测 → 元学习器融合
        base_preds = [float(m.predict(last_feat)[0]) for m in models]
        growth = float(meta.predict(np.array([base_preds]))[0])

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")

        # 置信度：元学习器权重差异越大，说明不同模型观点分歧越大，置信度相对降低
        confidence = max(0.1, min(0.9, 0.5 + 0.1 * abs(meta.coef_[1] - meta.coef_[0])))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={
                "method": "blending_sklearn",
                "meta_coef": [round(float(c), 3) for c in meta.coef_],
                "holdout_size": len(X_hold),
            },
            timestamp=datetime.now(),
        )

    def _numpy_blend(self, video_data, threshold):
        """
        NumPy 简易版 Blending：只用播放量数据，均值/中位数偏见加权。

        用 train 数据的均值和中位数作为两个"基模型"，在 holdout 上计算偏置，
        偏置越小权重越大，最终加权平均。

        Args:
            video_data (Dict): 视频数据字典。
            threshold (int): 目标阈值。

        Returns:
            PredictionResult: 包含预测到达时间、置信度的结果对象。
        """
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)
        history = video_data.get("history_data", [])

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        n = len(views)
        diffs = np.diff(views)  # 逐点增量序列
        split = int(n * 0.8)    # 80/20 分割

        if split >= 5 and n - split >= 3:
            train_diffs = diffs[:split]    # 训练集增量（80%）
            hold_diffs = diffs[split:]     # 验证集增量（20%）
            train_mean = np.mean(train_diffs)    # 基模型1: 均值预测
            train_median = np.median(train_diffs)  # 基模型2: 中位数预测
            hold_mean = np.mean(hold_diffs)  # 验证集真实均值

            # 计算各基模型在 holdout 上的偏置（与验证集真实均值的差距）
            biases = [abs(train_mean - hold_mean), abs(train_median - hold_mean)]
            total_bias = sum(biases)
            if total_bias > 1e-10:
                # 偏置越小权重越高（Blending 核心：用 holdout 表现评价基模型）
                w = [1 - b / (total_bias + 1e-10) for b in biases]
                w = [x / sum(w) for x in w]  # 归一化
                growth = w[0] * train_mean + w[1] * train_median
            else:
                growth = train_mean  # 偏置相等时使用均值
        else:
            growth = np.mean(diffs) if len(diffs) > 0 else velocity * 3600  # 数据不足时回退

        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
        # 置信度随数据量增加
        confidence = min(0.85, 0.35 + 0.02 * min(n, 25))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={"method": "blending_numpy"}, timestamp=datetime.now(),
        )
