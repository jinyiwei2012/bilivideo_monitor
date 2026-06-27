"""
Stacking 元学习器 (Stacking Ensemble with Meta-Learner) 模块
=============================================================

本模块实现了基于二阶元学习的 Stacking 集成预测算法。
用二阶元学习器学习基模型的预测权重，超越简单加权平均。

核心原理：
    1. 训练阶段：各基模型输出预测，元学习器学习最优组合
    2. 预测阶段：元学习器综合基模型输出，给出最终预测
    3. 相比简单加权，捕捉模型间的非线性互补关系

Stacking 层次结构：
    Level 0 (基学习器): 7 个特征工程 + 2 个学习器 (Ridge + GBM)
    Level 1 (元学习器): Ridge 在验证集上学习最优融合权重

与 Blending 的区别：
    - Stacking 使用更复杂的基模型（7 维特征 + 多种建模角度）
    - Blending 使用 80/20 简单分割；Stacking 同样使用验证集策略
    - Stacking 元学习器权重反映各基模型的可信度

适用场景：数据量 ≥ 20 点的视频，需精密融合多种模型视角。
"""

import logging
import numpy as np
from typing import Dict, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_SKLEARN = False
try:
    from sklearn.linear_model import Ridge, Lasso
    from sklearn.ensemble import GradientBoostingRegressor
    _HAS_SKLEARN = True
except ImportError:
    pass


class StackingEnsembleAlgorithm(BaseAlgorithm):
    """
    Stacking 元学习器集成。

    两层学习结构：7 维特征作为基模型输入，
    Ridge + GBM 作为 Level 0 基学习器，
    Ridge 作为 Level 1 元学习器融合两者的输出。

    类属性：
        name (str): 算法名称 "Stacking元学习"
        algorithm_id (str): 算法唯一标识 "stacking_ensemble"
        description (str): 算法简述
        category (str): 所属类别 "集成学习"
        default_weight (float): 默认集成权重 1.7（最高之一，精密融合的价值）
    """

    name = "Stacking元学习"
    algorithm_id = "stacking_ensemble"
    description = "二阶元学习器学习基模型权重，超越简单加权"
    category = "集成学习"
    default_weight = 1.7

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """
        执行 Stacking 集成预测。

        策略：
            - 数据 ≥ 20 且有 sklearn：使用完整的 Stacking + 2 个基学习器
            - 数据 ≥ 5 但无 sklearn：使用 numpy 3 模型 Stacking
            - 数据 < 5：匀速外推回退

        Args:
            video_data (Dict): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        Returns:
            PredictionResult: 包含元权重、基预测的融合结果
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 20 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "stacking_fallback"}, timestamp=datetime.now(),
            )

        if _HAS_SKLEARN:
            try:
                result = self._sklearn_stack(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("Stacking sklearn 失败: %s", e)

        return self._numpy_stack(video_data, threshold)

    def _sklearn_stack(self, video_data, threshold):
        """
        sklearn 完整版 Stacking 集成。

        7 个基模型（特征维度）：
            1. 简单线性：polyfit 斜率
            2. 指数增长：log(polyfit) 斜率
            3. 加权移动平均速度
            4. 互动率趋势
            5. 投币趋势
            6. 加速度（二阶差分）
            7. 变异系数 (CV)

        Level 0: Ridge(alpha=1.0) + GBM(50 trees)
        Level 1: Ridge(alpha=0.1) 元学习器

        Args:
            video_data (Dict): 视频数据字典
            threshold (int): 目标阈值

        Returns:
            PredictionResult 或 None
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        likes = np.array([h.get("like_count", 0) for h in history], dtype=np.float64)
        coins = np.array([h.get("coin_count", 0) for h in history], dtype=np.float64)
        n = len(views)

        p = 7  # 特征窗口
        X, y = [], []
        for i in range(p, n - 1):
            feat = []
            # 基模型1: 简单线性趋势
            feat.append(np.polyfit(np.arange(p), views[i - p: i], 1)[0])
            # 基模型2: 对数线性趋势（指数增长检测）
            log_views = np.log(np.maximum(views[i - p: i], 1))
            feat.append(np.polyfit(np.arange(p), log_views, 1)[0])
            # 基模型3: 加权移动平均速度
            feat.append(np.mean(np.diff(views[i - p: i])))
            # 基模型4: 互动率趋势
            feat.append(np.mean(likes[i - p: i]) / max(np.mean(views[i - p: i]), 1))
            # 基模型5: 投币趋势
            feat.append(np.mean(coins[i - p: i]) / max(np.mean(views[i - p: i]), 1))
            # 基模型6: 加速度（二阶差分均值）
            diffs = np.diff(views[i - p: i + 1])
            feat.append(np.mean(np.diff(diffs)) if len(diffs) >= 2 else 0)
            # 基模型7: 变异系数（波动程度）
            sm = np.mean(views[i - p: i + 1])
            feat.append(np.std(views[i - p: i + 1]) / max(sm, 1))

            X.append(feat)
            y.append(views[i] - views[i - 1])

        if len(X) < 10:
            return None

        X, y = np.array(X), np.array(y)
        # 80/20 训练/验证分割
        split = int(len(X) * 0.8)
        X_train, X_val = X[:split], X[split:]
        y_train, y_val = y[:split], y[split:]

        if len(X_val) < 3:
            X_train, X_val = X, X  # 数据太少时全量训练
            y_train, y_val = y, y

        # ========== Level 0: 基模型训练 ==========
        ridge = Ridge(alpha=1.0).fit(X_train, y_train)     # 线性基模型
        gbm = GradientBoostingRegressor(n_estimators=50, max_depth=3, random_state=42).fit(X_train, y_train)  # 非线性基模型

        # ========== Level 1: 元学习器（用验证集训练） ==========
        # 将两个基模型在验证集上的预测作为元特征
        ridge_preds = ridge.predict(X_val).reshape(-1, 1)
        gbm_preds = gbm.predict(X_val).reshape(-1, 1)
        meta_X = np.column_stack([ridge_preds, gbm_preds])  # (n_val, 2) 元特征矩阵
        meta = Ridge(alpha=0.1).fit(meta_X, y_val)  # 元学习器学习最优线性组合

        # ========== 预测当前时刻 ==========
        last_feat = np.array([
            np.polyfit(np.arange(p), views[-p:], 1)[0],                          # 基模型1
            np.polyfit(np.arange(p), np.log(np.maximum(views[-p:], 1)), 1)[0],   # 基模型2
            np.mean(np.diff(views[-p:])),                                        # 基模型3
            np.mean(likes[-p:]) / max(np.mean(views[-p:]), 1),                   # 基模型4
            np.mean(coins[-p:]) / max(np.mean(views[-p:]), 1),                   # 基模型5
            np.mean(np.diff(np.diff(views[-(p + 1):]))) if n >= p + 2 else 0,   # 基模型6
            np.std(views[-p:]) / max(np.mean(views[-p:]), 1),                    # 基模型7
        ]).reshape(1, -1)

        # 基模型预测 → 元学习器融合
        r_pred = float(ridge.predict(last_feat)[0])  # Ridge 预测
        g_pred = float(gbm.predict(last_feat)[0])    # GBM 预测
        final_growth = float(meta.predict(np.array([[r_pred, g_pred]]))[0])  # 元学习器融合

        predicted_velocity = max(0, final_growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        meta_weights = meta.coef_
        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
        # 置信度：两个基模型权重差异越小（互补性好），置信度越高
        confidence = max(0.1, min(0.9, 0.9 - 0.4 * abs(meta_weights[0] - meta_weights[1])))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={
                "method": "stacking_sklearn",
                "meta_weights": [round(float(w), 3) for w in meta_weights],
                "base_preds": [round(r_pred, 2), round(g_pred, 2)],  # 两个基模型的原始预测
            },
            timestamp=datetime.now(),
        )

    def _numpy_stack(self, video_data, threshold):
        """
        numpy 简化版 Stacking 集成。

        使用 3 个简单基模型：
            1. 近期平均速度（最近 5 步 diffs 均值）
            2. 线性趋势（polyfit 斜率）
            3. 指数增长（log 线性拟合）

        元学习器：用验证集上各基模型的误差计算权重，误差越小权重越大。

        Args:
            video_data (Dict): 视频数据字典
            threshold (int): 目标阈值

        Returns:
            PredictionResult: 融合后的预测结果
        """
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)
        history = video_data.get("history_data", [])

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        n = len(views)

        # 三个简单基模型
        methods = []
        methods.append(np.mean(np.diff(views[-5:])) if n >= 5 else velocity * 3600)  # 模型1: 近期均值
        methods.append(np.polyfit(np.arange(min(10, n)), views[-min(10, n):], 1)[0] if n >= 3 else velocity * 3600)  # 模型2: 线性
        if n >= 4:
            log_v = np.log(np.maximum(views[-min(8, n):], 1))
            methods.append(np.polyfit(np.arange(len(log_v)), log_v, 1)[0] * views[-1])  # 模型3: 指数增长
        else:
            methods.append(methods[0])  # 数据不足时复制模型1

        # 元学习器：用过去的表现加权
        weights = np.ones(3)  # 初始等权
        if n >= 15:
            val_size = n // 4  # 用最后 25% 数据作为验证集
            errors = []
            for m, method_growth in enumerate(methods):
                # 用每个方法往前推一步，计算误差
                pred = views[-val_size - 1] + method_growth
                err = abs(pred - views[-val_size]) / max(views[-val_size], 1)
                errors.append(err)
            # softmax 得到权重：误差越小权重越大
            weights = np.exp(-np.array(errors))
            weights /= weights.sum()

        growth = np.dot(weights, methods)  # 加权融合
        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
        # 置信度：最优模型权重越大 → 预测越可信
        confidence = max(0.1, min(0.85, 0.3 + 0.2 * (weights.max() / max(weights.sum(), 1e-10))))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={
                "method": "stacking_numpy",
                "weights": [round(float(w), 3) for w in weights],  # 各基模型的融合权重
            },
            timestamp=datetime.now(),
        )
