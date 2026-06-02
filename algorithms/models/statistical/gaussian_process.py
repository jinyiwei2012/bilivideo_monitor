"""
高斯过程回归 — Gaussian Process Regression
============================================

概率预测方法，输出点预测值和不确定性估计。

核心原理：
  1. 高斯过程 (GP) 是一种非参数贝叶斯方法，假设任意有限维联合分布服从多维高斯分布
  2. 先验由核函数（RBF + WhiteKernel）定义协方差结构
  3. 基于历史数据计算后验分布（预测均值 + 预测方差）
  4. 方差反映了预测的不确定性 — 数据稀疏区域方差大，密集区域方差小

实现策略：
  - 优先使用 sklearn GaussianProcessRegressor（数据量 >= 15 时）
  - 不可用时回退到 numpy 简化版 GP（RBF 核 + 线性求解）

适用场景：历史数据 >= 8 条，需要不确定性量化
"""

import logging
import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

# sklearn 可用性标记
_HAS_SKLEARN = False
try:
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, WhiteKernel

    _HAS_SKLEARN = True
except ImportError:
    pass


class GaussianProcessAlgorithm(BaseAlgorithm):
    """
    高斯过程回归预测算法

    通过 GP 对播放量时间序列建模，输出点预测 + 不确定性估计。
    支持 sklearn 和 numpy 两种后端。

    属性:
        default_weight (float): 默认集成权重 1.3，GP 的概率特性赋予更高信任
    """

    name = "高斯过程"
    algorithm_id = "gaussian_process"
    description = "概率高斯过程回归，输出点预测+不确定性"
    category = "统计模型"
    default_weight = 1.3

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """
        执行高斯过程预测

        流程:
          1. 检查数据量
          2. 若 sklearn 可用且数据 >= 15 条，优先使用 sklearn 版本
          3. 否则使用 numpy 简化版 GP

        参数:
            video_data (Dict): 视频数据
            threshold (int): 目标播放量阈值

        返回:
            PredictionResult: 包含预测小时数和不确定性
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足，使用当前速度的简单外推
        if len(history) < 8:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "gp_fallback"}, timestamp=datetime.now(),
            )

        # sklearn 版本：数据充足时使用成熟的 GP 实现
        if _HAS_SKLEARN and len(history) >= 15:
            try:
                result = self._sklearn_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("GP sklearn failed: %s", e)

        # numpy 回退：简化的 RBF 核 GP
        return self._numpy_predict(video_data, threshold)

    def _sklearn_predict(self, video_data, threshold):
        """
        使用 sklearn GaussianProcessRegressor 进行预测

        - 使用 RBF(3.0) + WhiteKernel(0.1) 核组合
        - RBF 捕捉平滑趋势，WhiteKernel 允许噪声
        - 预测未来 10 个点的播放量和标准差
        - 基于预测增长量和不确定性计算置信度

        参数:
            video_data: 视频数据
            threshold: 目标阈值

        返回:
            PredictionResult 或 None
        """
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)
        history = video_data.get("history_data", [])

        # 提取最近 30 个数据点的播放量序列
        views = np.array([h.get("view_count", 0) for h in history[-30:]], dtype=np.float64)
        n = len(views)
        X = np.arange(n).reshape(-1, 1)  # 以索引作为时间特征

        # RBF 核: 平滑趋势建模，长度尺度=3.0
        # WhiteKernel: 观测噪声建模，噪声水平=0.1
        kernel = RBF(length_scale=3.0) + WhiteKernel(noise_level=0.1)
        gp = GaussianProcessRegressor(kernel=kernel, normalize_y=True, n_restarts_optimizer=3)
        gp.fit(X, views)

        # 预测未来 10 个点
        X_pred = np.arange(n, n + 10).reshape(-1, 1)
        y_pred, y_std = gp.predict(X_pred, return_std=True)  # y_std = 预测标准差

        # 从预测序列估算增长速度（每数据点增量 / 3600秒转为每秒增量）
        growth = np.mean(np.diff(y_pred)) if len(y_pred) >= 2 else velocity * 3600
        predicted_velocity = max(0, growth / 3600)
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity
            # 不确定性 = 平均标准差 / 平均预测值
            uncertainty = float(np.mean(y_std)) / max(float(np.mean(y_pred)), 1)
            # 置信度随不确定性增大而降低
            confidence = max(0.1, min(0.9, 0.7 / (1 + uncertainty * 3)))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={"method": "gp_sklearn", "uncertainty": round(uncertainty, 4)},
            timestamp=datetime.now(),
        )

    def _numpy_predict(self, video_data, threshold):
        """
        使用 numpy 简化版 GP 进行预测

        简化版 GP 实现:
          1. 构建 RBF 核矩阵 K(x, x') = exp(-0.5 * ||x-x'||² / (n/4)²)
          2. 添加对角正则化（nugget = 0.1I）
          3. 求解线性系统 Kα = y 得到 α
          4. 对预测点计算 k(x*, x) · α 得到预测值

        参数:
            video_data: 视频数据
            threshold: 目标阈值

        返回:
            PredictionResult
        """
        current_views = video_data.get("view_count", 0)
        velocity = self.calculate_velocity(video_data)
        history = video_data.get("history_data", [])

        # 提取最近 20 个数据点
        views = np.array([h.get("view_count", 0) for h in history[-20:]], dtype=np.float64)
        n = len(views)

        # 构建 RBF 协方差矩阵
        # length_scale = n/4：长度尺度与数据量成正比
        x = np.arange(n)
        rbf = np.exp(-0.5 * ((x[:, None] - x[None, :]) / (n / 4)) ** 2)
        rbf += np.eye(n) * 0.1  # 对角正则化（nugget effect）

        # 求解 Kα = y，α = K⁻¹y
        try:
            alpha = np.linalg.solve(rbf, views)
        except np.linalg.LinAlgError:
            alpha = views  # 矩阵奇异时回退

        # 预测未来 5 个点的播放量
        x_pred = np.arange(n + 5)
        # k(x*, x) = RBF 核在预测点与训练点之间的协方差
        k_star = np.exp(-0.5 * ((x_pred[:, None] - x[None, :]) / (n / 4)) ** 2)
        y_pred = k_star @ alpha  # 预测值 = k* · α
        # 从预测序列估算增长速度
        growth = np.mean(np.diff(y_pred[-5:])) if n >= 5 else velocity * 3600

        predicted_velocity = max(0, growth / 3600)  # 转为每秒增量
        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 and predicted_velocity > 0 else float("inf")
        # 置信度随数据量增长，上限 0.85
        confidence = min(0.85, 0.35 + 0.02 * min(n, 20))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={"method": "gp_numpy", "data_points": n}, timestamp=datetime.now(),
        )
