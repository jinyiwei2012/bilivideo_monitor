"""
Chronos (亚马逊时序基础模型 / Chronos Time Series Foundation Model)
基于T5架构的zero-shot时序预训练模型，无需微调直接预测。

核心思路：
1. 借鉴 Transformer T5 架构，将时序建模为 token 序列
2. 零样本预测：预训练模型可直接用于未见过的序列，无需任务特定训练
3. 趋势-季节分解：一次多项式提取趋势 + 多周期模式叠加季节分量

预测流程（numpy 简化版）：
1. 多项式拟合提取线性趋势
2. 计算残差（原始 - 趋势）
3. 多个季节周期（7天、14天）的模式叠加
4. 外推趋势 + 外推季节性 → 未来播放量
5. 反算增长速度和置信度
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import ChronosTorchModel, try_torch_predict


class ChronosBaseAlgorithm(BaseAlgorithm):
    """Chronos 零样本时序预测算法。

    核心机制：
    - 多项式趋势拟合：一次多项式提取线性增长趋势
    - 多周期季节分解：叠加 7 天和 14 天两种周期模式
    - 外推预测：趋势外推 + 季节模式外推组合
    - 置信度评估：残差标准差越小 → 拟合越好 → 置信度越高

    降级链：torch checkpoint → numpy trend+seasonal → velocity 兜底
    """

    name = "Chronos零样本"
    algorithm_id = "chronos_base"
    description = "T5时序基础模型，零样本概率预测"
    category = "深度学习"
    default_weight = 1.4

    training_window = 10
    """训练窗口长度（时间步数）"""
    training_horizon = 3
    """预测步数"""

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """预测到达目标播放量所需时间。

        优先使用 torch 模型推理，失败降级到 numpy。

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
            ChronosTorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建训练用的 PyTorch 模型。

        Returns:
            ChronosTorchModel 实例
        """
        return ChronosTorchModel(in_features=getattr(self, '_training_n_features', 5), window=10, d_model=32, n_heads=2, horizon=self.training_horizon)

    def get_training_features(self) -> List[str]:
        """获取训练使用的特征列表。

        Returns:
            特征名称列表
        """
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """numpy 降级预测 - Chronos 简化版。

        趋势-季节分解 + 外推预测。

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 5 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            n = min(10, len(views) // 2)  # 预测步数
            if n < 2:
                n = 2

            # 一次多项式趋势拟合
            x = np.arange(len(views))
            coeffs = np.polyfit(x, views, 1)  # 一次多项式系数
            trend = np.polyval(coeffs, x)  # 趋势线
            residuals = views - trend  # 残差（季节性+噪声）

            # 多周期季节模式叠加（7天、14天）
            seasonal_periods = [7, 14]
            seasonal_pattern = np.zeros_like(residuals)
            for p in seasonal_periods:
                if p < len(residuals):
                    pattern = residuals[-p:]  # 最近的 p 天作为周期模式
                    seasonal_pattern += np.tile(pattern, len(residuals) // p + 1)[: len(residuals)] / len(
                        seasonal_periods
                    )

            # 外推趋势 + 外推季节性
            future_x = np.arange(len(views), len(views) + n)
            future_trend = np.polyval(coeffs, future_x)  # 未来趋势
            future_seasonal = np.tile(seasonal_pattern[-min(7, len(seasonal_pattern)) :], 3)[:n]  # 未来季节
            future_views = future_trend + future_seasonal  # 未来播放量 = 趋势 + 季节
            future_views = np.maximum(future_views, 0)  # 非负约束

            predicted_velocity = max(0, np.mean(np.diff(future_views)) / 3600)  # 每小时速度
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                # 置信度：残差相对标准差越小 → 拟合越好
                residual_std = np.std(residuals) / max(np.mean(views), 1)
                confidence = max(0.1, min(0.85, 0.5 - residual_std * 5))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "chronos", "trend_slope": float(coeffs[0])},
                timestamp=datetime.now(),
            )
        except Exception:
            return self._fallback(velocity, current_views, threshold)

    def _fallback(self, velocity, current_views, threshold):
        """兜底预测：无法计算时的最简方案。

        Args:
            velocity: 当前速度（每小时播放量）
            current_views: 当前播放量
            threshold: 目标播放量阈值

        Returns:
            PredictionResult 兜底预测结果
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
                metadata={"method": "chronos", "reason": "fallback"},
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
            metadata={"method": "chronos", "reason": "fallback"},
            timestamp=datetime.now(),
        )
