"""
DeepAR (概率自回归模型 / Probabilistic Autoregressive Model)
基于 RNN 的概率预测模型，输出未来播放量的概率分布而非点估计。

核心思路：
1. 自回归：用历史值预测未来值（返回率建模）
2. 概率化：输出正态分布的均值（μ）和标准差（σ）
3. 蒙特卡洛采样：多次采样估算到达目标播放量的概率
4. 不确定性量化：利用 σ 评估预测可靠性

与普通回归的区别：
- 不输出单点预测值，而是输出概率分布
- 能量化"可能多久达到目标"的不确定性
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import DeepARTorchModel, try_torch_predict


class DeeparSimpleAlgorithm(BaseAlgorithm):
    """DeepAR 概率自回归预测算法。

    核心机制：
    - 返回率建模：用相对增长 (Δviews/prev_views) 替代绝对增量，更稳定
    - 正态假设：假设返回率服从正态分布 N(μ, σ)
    - 蒙特卡洛模拟：200 条采样路径，每条路径 30 天外推
    - 概率阈值：统计 30 天后播放量 ≥ 目标的采样比例

    降级链：torch checkpoint → numpy 返回率 MC → velocity 兜底
    """

    name = "DeepAR概率"
    algorithm_id = "deepar_simple"
    description = "概率自回归，输出未来播放量概率分布"
    category = "深度学习"
    default_weight = 1.3

    training_window = 10
    """训练窗口长度（时间步数）"""
    training_horizon = 3
    """预测步数"""

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """预测到达目标播放量所需时间。

        优先使用 torch 模型推理，失败降级到 numpy。

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值，默认 100000

        Returns:
            PredictionResult 预测结果对象
        """
        return try_torch_predict(
            self,
            video_data,
            threshold,
            DeepARTorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建训练用的 PyTorch 模型。

        Returns:
            DeepARTorchModel 实例
        """
        return DeepARTorchModel(in_features=getattr(self, '_training_n_features', 5), hidden=32, horizon=self.training_horizon)

    def get_training_features(self) -> List[str]:
        """获取训练使用的特征列表。

        Returns:
            特征名称列表
        """
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """numpy 降级预测 - 简化版 DeepAR。

        返回率建模 → 蒙特卡洛采样 → 中值速度预测。

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 8 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold, method="deepar")

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            # 返回率 = (v_t - v_{t-1}) / v_{t-1}（相对增长比例）
            returns = np.diff(views) / np.maximum(views[:-1], 1)
            mu_ret = np.mean(returns)  # 平均返回率
            sigma_ret = np.std(returns) + 1e-10  # 返回率波动

            n_samples = 200  # 蒙特卡洛采样路径数
            np.random.seed(42)  # 固定随机种子确保可重复性
            future_returns = np.random.normal(mu_ret, sigma_ret, (n_samples, 30))  # [200, 30]
            future_views_samples = np.zeros((n_samples, 30))
            future_views_samples[:, 0] = views[-1] * (1 + future_returns[:, 0])
            for t in range(1, 30):
                future_views_samples[:, t] = future_views_samples[:, t - 1] * (1 + future_returns[:, t])
            future_views_samples = np.maximum(future_views_samples, 0)  # 非负约束

            remaining = threshold - current_views
            if remaining <= 0:
                return PredictionResult(
                    algorithm_name=self.name,
                    algorithm_id=self.algorithm_id,
                    target_threshold=threshold,
                    predicted_hours=0,
                    confidence=1.0,
                    current_views=current_views,
                    current_velocity=velocity,
                    metadata={"method": "deepar", "mu_return": float(mu_ret), "sigma_return": float(sigma_ret)},
                    timestamp=datetime.now(),
                )

            # 各采样路径的速度（前 7 天的平均小时速度）
            velocity_samples = np.mean(np.diff(future_views_samples[:, :7]) / 3600, axis=1)
            median_velocity = max(0, np.median(velocity_samples))  # 使用中位数更稳健
            if median_velocity < 1:
                median_velocity = velocity

            predicted_hours = remaining / median_velocity
            # 概率目标：30 天后播放量 ≥ 目标的采样占比
            prob_reach = np.mean(future_views_samples[:, -1] >= threshold)
            # 不确定性：噪声比（σ/μ）越大 → 越不确定
            uncertainty = sigma_ret / max(abs(mu_ret), 1e-10)
            confidence = max(0.05, min(0.85, prob_reach * 0.8 + 0.1 / (1 + uncertainty)))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={
                    "method": "deepar",
                    "mu_return": float(mu_ret),
                    "sigma_return": float(sigma_ret),
                    "prob_reach": float(prob_reach),
                },
                timestamp=datetime.now(),
            )
        except Exception:
            return self._fallback(velocity, current_views, threshold, method="deepar")
