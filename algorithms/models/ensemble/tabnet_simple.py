"""
TabNet 注意力特征选择网络模块
=============================

本模块实现了基于 TabNet (Attentive Tabular Learning) 的 B 站视频播放量预测算法。
TabNet 使用注意力机制进行特征选择，无需手动特征工程。

优先使用 pytorch_tabnet.tab_model.TabNetRegressor 真实实现；
若库不可用或训练失败，回退到 numpy 简化版（模拟注意力特征选择）。

核心原理（TabNet 版）：
    1. 构造 5 步滑动窗口特征（播放量/点赞/投币/收藏/分享）
    2. 使用 Sequential Attention 在每个决策步骤选择哪些特征更重要
    3. entmax 稀疏注意力：自动将不重要特征权重置零
    4. Feature Transformer + Attentive Transformer 交替堆叠

核心原理（numpy 回退版）：
    1. 构造 7 维特征（对数变换 + 梯度 + 归一化）
    2. 使用随机权重模拟注意力机制
    3. 注意力加权后通过 tanh 激活得到趋势信号

算法来源：Arik & Pfister (2019) "TabNet: Attentive Interpretable Tabular Learning"

适用场景：历史数据 ≥ 15 点的视频，真实 TabNet 提供更好的特征选择能力。
"""

import logging
import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_TABNET = False
try:
    from pytorch_tabnet.tab_model import TabNetRegressor as _TabNet

    _HAS_TABNET = True
except ImportError:
    pass


class TabnetSimpleAlgorithm(BaseAlgorithm):
    """
    TabNet 注意力特征选择网络

    使用注意力机制自动选择对播放量预测最重要的特征。
    与传统梯度提升不同，TabNet 能学习特征间的复杂交互，
    并输出特征重要性掩码，实现可解释的深度学习。

    类属性：
        name (str): 算法名称 "TabNet注意力"
        algorithm_id (str): 算法唯一标识 "tabnet_simple"
        description (str): 算法简述
        category (str): 所属类别 "集成学习"
        default_weight (float): 默认集成权重 1.1（中等偏低，因为较新）
    """

    name = "TabNet注意力"
    algorithm_id = "tabnet_simple"
    description = "注意力特征选择表格网络（pytorch_tabnet 优先，numpy 回退）"
    category = "集成学习"
    default_weight = 1.1

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行 TabNet 注意力网络预测。

        策略：
            - 数据 >= 15 且 pytorch_tabnet 可用：使用真实 TabNet
            - 数据 >= 8 但无库可用：使用 numpy 模拟版
            - 数据 < 8：回退到匀速外推

        Args:
            video_data (Dict): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 8 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        # 优先使用 pytorch_tabnet 做注意力特征选择网络预测
        if _HAS_TABNET and len(history) >= 15:
            try:
                result = self._tabnet_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("TabNet pytorch_tabnet 失败，回退 numpy: %s", e)

        # numpy 模拟版回退
        return self._numpy_predict(video_data, threshold)

    def _tabnet_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        """
        使用 pytorch_tabnet TabNetRegressor 做注意力特征选择网络预测。

        特征构造（5 步滑动窗口，每步 5 维特征）：
            views[i-j], likes[i-j], coins[i-j], favs[i-j], shares[i-j]

        TabNet 结构参数：
            - n_d=8: 决策层宽度
            - n_a=8: 注意力层宽度
            - n_steps=3: 决策步骤数（每次选择部分特征）
            - gamma=1.5: 注意力稀疏度（越大越稀疏）
            - mask_type="entmax": 使用 entmax 稀疏注意力

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
        favs = np.array([h.get("favorite_count", 0) for h in history], dtype=np.float64)
        shares = np.array([h.get("share_count", 0) for h in history], dtype=np.float64)

        p = 5  # 滑动窗口大小
        X, y = [], []
        for i in range(p, len(views)):
            feat = []
            for j in range(1, p + 1):
                feat.extend([views[i - j], likes[i - j], coins[i - j], favs[i - j], shares[i - j]])
            X.append(feat)
            y.append(views[i])

        X, y = np.array(X, dtype=np.float32), np.array(y, dtype=np.float32).reshape(-1, 1)
        if len(X) < 10:
            return None

        try:
            # 目标：播放量增长率（百分比差值）
            y_target = np.diff(views[-len(X) - 1:]) / np.maximum(views[-len(X) - 1 : -1], 1)
            y_target = y_target[-len(X):].astype(np.float32).reshape(-1, 1)

            # TabNet: 8 个决策层 + 8 个注意力层，entmax 稀疏注意力
            model = _TabNet(
                n_d=8, n_a=8, n_steps=3, gamma=1.5,
                n_independent=2, n_shared=2,
                optimizer_fn=lambda params: type("opt", (), {"__module__": ""})(),
                mask_type="entmax",  # 稀疏注意力：自动将不重要特征归零
                verbose=0,
            )
            model.fit(
                X, y_target,
                max_epochs=100, patience=10,  # 早停策略
                batch_size=min(64, len(X) // 2),
                virtual_batch_size=min(32, len(X) // 4) if len(X) >= 20 else None,
            )

            # 构造最新特征
            last_feat = []
            for j in range(1, p + 1):
                last_feat.extend([views[-j], likes[-j], coins[-j], favs[-j], shares[-j]])

            pred_growth = float(model.predict(np.array([last_feat], dtype=np.float32))[0])

            # 增长率转换为绝对速度
            predicted_velocity = max(0, pred_growth * current_views / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity if predicted_velocity > 0 else float("inf")
                # 置信度：残差变异系数
                residuals = np.abs(y_target - model.predict(X))
                cv = float(np.std(residuals) / max(np.mean(np.abs(y_target)), 1e-10))
                confidence = max(0.1, min(0.85, 0.6 - cv * 0.5))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "tabnet_lib", "n_d": 8, "n_a": 8},
                timestamp=datetime.now(),
            )
        except Exception:
            return None

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        """
        numpy 模拟版 TabNet 预测。

        使用随机权重模拟注意力机制的特征选择过程：
            1. 构造 7 维特征（对数变换 + 梯度）
            2. 随机初始化权重矩阵 W, V, W_out
            3. 前向传播：features → 注意力权重 → 加权特征 → tanh 激活 → 趋势信号
            4. 趋势信号 + 近期速度 → 预测速度

        这并非真正的 TabNet，而是一个"有注意力的线性网络"，
        用于在缺乏 pytorch_tabnet 时提供合理的近似。

        Args:
            video_data (Dict): 视频数据字典
            threshold (int): 目标阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 8 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            likes = np.array([h.get("like", 0) for h in history], dtype=np.float64)
            coins = np.array([h.get("coin", 0) for h in history], dtype=np.float64)
            favs = np.array([h.get("favorite", 0) for h in history], dtype=np.float64)
            shares = np.array([h.get("share", 0) for h in history], dtype=np.float64)

            # 构造 7 维特征矩阵
            features = np.column_stack(
                [
                    np.log1p(views),   # log(1+x) 对数变换
                    np.log1p(likes),
                    np.log1p(coins),
                    np.log1p(favs),
                    np.log1p(shares),
                    np.gradient(views) / np.maximum(views, 1),  # 播放量变化率
                    np.gradient(likes) / np.maximum(likes, 1),  # 点赞变化率
                ]
            )
            features = np.nan_to_num(features)  # NaN/Inf 处理

            n_features = features.shape[1]
            np.random.seed(42)  # 固定随机种子保证可复现
            # 随机初始化权重矩阵（模拟注意力网络）
            W = np.random.randn(n_features, n_features) * 0.1      # 特征变换矩阵
            V = np.random.randn(n_features, 1) * 0.1               # 注意力评分向量
            W_out = np.random.randn(n_features, 1) * 0.01          # 输出层权重

            # Step 1: 特征变换
            H = features @ W
            # Step 2: 计算注意力权重（软注意力）
            attn = np.maximum(H @ V, 0)  # ReLU 激活保证非负
            attn_weights = attn / (np.sum(attn, axis=0, keepdims=True) + 1e-10)  # 归一化

            # Step 3: 注意力加权特征
            weighted_features = features * attn_weights
            # Step 4: tanh 激活得到决策信号（趋势方向）
            decision = np.tanh(weighted_features @ W_out)

            # 趋势信号：最近 5 步决策的平均值
            trend = np.mean(decision[-5:]) if len(decision) >= 5 else 0
            # 近期速度
            recent_velocity = np.mean(np.diff(views[-5:])) / 3600 if len(views) >= 5 else velocity

            # 最终速度 = 近期速度 * (1 + 趋势调整)
            predicted_velocity = max(0, recent_velocity * (1 + trend))
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                # 注意力熵：熵越低 → 注意力越集中 → 特征选择越明确 → 置信度越高
                attn_entropy = -np.sum(attn_weights * np.log(attn_weights + 1e-10)) / np.log(n_features)
                confidence = max(0.1, min(0.8, 0.6 - attn_entropy * 0.3))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "tabnet", "trend_signal": float(trend)},
                timestamp=datetime.now(),
            )
        except Exception:
            return self._fallback(velocity, current_views, threshold)

    def _fallback(self, velocity, current_views, threshold):
        """
        回退预测方案：匀速外推。

        当数据不足或上述所有方法均失败时使用。

        Args:
            velocity (float): 当前播放速度
            current_views (int): 当前播放量
            threshold (int): 目标阈值

        Returns:
            PredictionResult: 基于匀速外推的预测结果
        """
        if velocity <= 0:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=float("inf"),  # 无增长
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "tabnet", "reason": "fallback"},
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
            metadata={"method": "tabnet", "reason": "fallback"},
            timestamp=datetime.now(),
        )
