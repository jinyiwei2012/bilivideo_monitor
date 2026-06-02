"""
TBATS预测算法 (Trigonometric seasonal, Box-Cox, ARMA, Trend, Seasonal)

TBATS 是一种强大的时间序列预测模型，特别设计用于处理复杂的季节性模式。

核心原理（TBATS 模型组件）：
    T - Trigonometric: 使用三角傅里叶项建模季节性（而非传统的虚拟变量法）
    B - Box-Cox: 对数据进行 Box-Cox 变换以稳定方差
    A - ARMA: 对残差使用 ARMA 模型捕捉短期动态
    T - Trend: 趋势成分
    S - Seasonal: 季节性成分

    TBATS 的形式:
        y_t^(ω) = l_{t-1} + φb_{t-1} + Σ s_{t-m}^{(i)} + d_t
        其中:
        - y_t^(ω) 是 Box-Cox 变换后的数据
        - l_t 是水平
        - b_t 是趋势
        - s_t 是季节分量（用三角函数表示）
        - d_t 是 ARMA 残差

优势:
    1. 自动处理复杂多重季节性模式
    2. 自动进行 Box-Cox 变换优化方差稳定性
    3. 对长周期季节模式有高效表示（三角函数比虚拟变量更节省参数）

双级实现策略：
    1. tbats 库真实实现（支持7天和14天双重周期）
    2. NumPy 简化版 — 手动实现 Box-Cox + 三角函数 + AR 组分

适用场景：
    - 有复杂多重周期模式的视频
    - 数据量充足（≥15点）的长期预测
    - 播放量增长方差较大需要稳定的场景

参考:
    De Livera, Hyndman & Snyder (2011)
    "Forecasting Time Series with Complex Seasonal Patterns Using Exponential Smoothing"
"""

import logging
import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

# ── 可选依赖检测 ──────────────────────────────────
_HAS_TBATS = False
try:
    from tbats import TBATS as _TBATS

    _HAS_TBATS = True
except ImportError:
    pass


class TbatsSimpleAlgorithm(BaseAlgorithm):
    """TBATS 三角函数季节分解

    使用三角函数（傅里叶级数）建模多重季节模式，
    结合 Box-Cox 变换和 AR 残差建模进行预测。

    双周期设计:
        - 7天周期: 周内波动（工作日 vs 周末）
        - 14天周期: 双周模式（UP主更新周期等）

    属性:
        name (str): 算法显示名称 "TBATS季节分解"
        algorithm_id (str): 算法唯一标识 "tbats_simple"
        description (str): 算法描述
        category (str): 算法分类 "时间序列"
        default_weight (float): 集成预测中的默认权重 1.2
    """

    name = "TBATS季节分解"
    algorithm_id = "tbats_simple"
    description = "三角函数多重季节分解（tbats 库优先，numpy 回退）"
    category = "时间序列"
    default_weight = 1.2

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行 TBATS 预测（两级级联回退）

        按优先级尝试：
        1. tbats 库真实 TBATS 实现（7天+14天双重周期）
        2. NumPy 简化版手动实现

        参数:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 8 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        # 优先使用 tbats 库进行多重季节分解预测
        if _HAS_TBATS and len(history) >= 15:
            try:
                result = self._tbats_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("TBATS 库失败，回退 numpy: %s", e)

        return self._numpy_predict(video_data, threshold)

    def _tbats_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        """使用 tbats 库进行 Box-Cox 变换 + 三角函数多重季节分解预测

        参数:
            video_data: 视频数据字典
            threshold: 目标阈值

        返回:
            PredictionResult 或 None

        TBATS 库功能:
            - seasonal_periods=[7, 14]: 同时建模7天和14天周期
            - use_box_cox=True: 自动进行 Box-Cox 变换
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)

        if len(views) < 15:
            return None

        try:
            # TBATS: 支持 7 天和 14 天双重周期，Box-Cox 变换稳定方差
            estimator = _TBATS(seasonal_periods=[7, 14], use_box_cox=True)
            fitted = estimator.fit(views)
            # 预测未来 14 天
            forecast_views = np.array(forecast)

            target_idx = np.where(forecast_views >= threshold)[0]
            if len(target_idx) > 0 and target_idx[0] < 14:
                predicted_hours = (target_idx[0] + 1) * 24
                # 置信度基于预测序列的相对波动程度
                confidence = max(0.1, min(0.85, 0.6 - np.std(forecast_views) / max(np.mean(forecast_views), 1) * 5))
            else:
                remaining = threshold - current_views
                predicted_hours = remaining / velocity if velocity > 0 else float("inf")
                confidence = 0.35

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "tbats_lib", "periods": [7, 14]},
                timestamp=datetime.now(),
            )
        except Exception:
            return None

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        """NumPy 简化版 TBATS 预测（手动实现核心逻辑）

        手动实现 TBATS 的核心组件：
        1. Box-Cox 变换（λ=0.5 的平方根变换）
        2. 三角函数季节分解（7天和14天周期）
        3. 多项式趋势提取
        4. AR(1) 残差建模
        5. 外推合成预测

        参数:
            video_data: 视频数据字典
            threshold: 目标阈值

        返回:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 8 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)

            # ── Box-Cox 变换（λ=0.5，平方根变换） ──
            # Box-Cox 变换: y^(λ) = (y^λ - 1) / λ  (λ≠0)
            # λ=0.5 用于稳定方差较大的序列
            boxcox_lambda = 0.5
            transformed = (views**boxcox_lambda - 1) / boxcox_lambda if boxcox_lambda != 0 else np.log(views)

            n = len(transformed)
            t = np.arange(n)

            # ── 三角函数季节分解 ───────────────────
            # 对每个周期 period，用一对 sin/cos 基函数拟合
            periods = [7, 14]
            seasonal_components = np.zeros(n)
            for p in periods:
                if p > n // 2:  # 周期不能超过数据长度的一半
                    continue
                cos_wave = np.cos(2 * np.pi * t / p)
                sin_wave = np.sin(2 * np.pi * t / p)
                # 计算振幅（通过内积投影）
                amp_cos = np.sum(transformed * cos_wave) / n
                amp_sin = np.sum(transformed * sin_wave) / n
                seasonal_components += amp_cos * cos_wave + amp_sin * sin_wave

            # ── 趋势提取 ───────────────────────────
            # 去季节后做线性回归提取趋势
            detrended = transformed - seasonal_components
            trend_coeffs = np.polyfit(t, detrended, 1)  # 线性趋势
            trend = np.polyval(trend_coeffs, t)

            # ── AR(1) 残差建模 ─────────────────────
            # 残差 = 原始 - 季节 - 趋势
            resid = detrended - trend
            # AR(1): r_t = φ × r_{t-1} + ε_t
            ar_coeffs = np.polyfit(resid[:-1], resid[1:], 1) if len(resid) > 1 else [0]
            ar_pred = ar_coeffs[0] * resid[-1] if len(ar_coeffs) > 0 else 0

            # ── 外推预测 ───────────────────────────
            future_steps = 7  # 预测7步
            future_t = np.arange(n, n + future_steps)

            # 外推季节分量
            future_seasonal = np.zeros(future_steps)
            for p in periods:
                if p > n // 2:
                    continue
                future_seasonal += amp_cos * np.cos(2 * np.pi * future_t / p) + amp_sin * np.sin(
                    2 * np.pi * future_t / p
                )

            # 外推趋势分量（线性外推）
            future_trend = np.polyval(trend_coeffs, future_t)

            # 外推 AR 残差（指数衰减）
            future_ar = np.array([ar_pred * (ar_coeffs[0] ** i) for i in range(future_steps)])

            # 合成变换后的预测值
            future_transformed = future_trend + future_seasonal + future_ar

            # ── 逆 Box-Cox 变换 ────────────────────
            # 逆变换: y = (y^(λ) × λ + 1)^(1/λ)
            future_views = (future_transformed * boxcox_lambda + 1) ** (1 / boxcox_lambda)
            # 预测速度 = 外推序列的平均差分 / 3600
            predicted_velocity = max(0, np.mean(np.diff(future_views)) / 3600)

            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                # 置信度基于预测序列的相对波动（变异系数）
                forecast_var = np.var(future_views) if len(future_views) > 1 else 1
                cv = np.sqrt(forecast_var) / max(np.mean(future_views), 1)
                confidence = max(0.1, min(0.85, 0.6 - cv * 5))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "tbats", "periods": list(periods)},
                timestamp=datetime.now(),
            )
        except Exception:
            return self._fallback(velocity, current_views, threshold)

    def _fallback(self, velocity, current_views, threshold):
        """回退预测：使用当前速度的保守估计

        参数:
            velocity: 当前增长速度
            current_views: 当前播放量
            threshold: 目标阈值

        返回:
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
                metadata={"method": "tbats", "reason": "fallback"},
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
            metadata={"method": "tbats", "reason": "fallback"},
            timestamp=datetime.now(),
        )
