"""
MSTL多重季节分解预测算法 (Multiple Seasonal-Trend decomposition using LOESS)

使用 statsmodels 的 MSTL 模块进行多重季节分解，
将时间序列分解为趋势分量和多个季节分量（如7天和14天周期），
分别预测后再合成最终结果。

核心原理：
    MSTL 是对经典 STL 分解的扩展，支持同时提取多个季节周期。
    对于B站视频播放量，可能存在：
    - 周周期（7天）：工作日 vs 周末的播放差异
    - 双周周期（14天）：UP主更新周期等长期规律

    通过 LOESS（局部加权回归）平滑技术，迭代分解趋势和季节分量。

适用场景：
    - 有足够历史数据（≥14点）的长期监控视频
    - 存在多重周期模式的视频（如周更UP主的视频）
    - 需要精确季节调整的场景

回退策略:
    - statsmodels MSTL 不可用时，使用 scipy.signal.savgol_filter 做趋势提取
    - 完全无外部依赖时使用简单速度估算

参考:
    Cleveland et al. (1990) "STL: A Seasonal-Trend Decomposition Procedure Based on Loess"
    Bandara et al. (2020) "Forecasting across time series databases using recurrent neural networks"
"""

import numpy as np
import warnings
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

# ── 可选依赖检测 ──────────────────────────────────
try:
    from statsmodels.tsa.seasonal import MSTL as _MSTL

    _HAS_MSTL = True
except ImportError:
    _HAS_MSTL = False


class MstlDecompositionAlgorithm(BaseAlgorithm):
    """MSTL 多重季节分解预测算法

    使用 MSTL 对播放量序列进行多重季节分解，
    提取趋势 + 多个季节周期分量，合成预测速度。

    属性:
        name (str): 算法显示名称 "MSTL多重季节"
        algorithm_id (str): 算法唯一标识 "mstl_decomposition"
        description (str): 算法描述
        category (str): 算法分类 "时间序列"
        default_weight (float): 集成预测中的默认权重 1.1
    """

    name = "MSTL多重季节"
    algorithm_id = "mstl_decomposition"
    description = "多重季节分解+趋势预测合成"
    category = "时间序列"
    default_weight = 1.1

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行MSTL多重季节分解预测

        参数:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 预测结果对象

        算法步骤（statsmodels MSTL 路径）:
            1. 动态选择季节周期（避免周期 > 数据长度的一半）
            2. MSTL 分解得到趋势和季节分量
            3. 用 np.gradient 估计趋势的变化速度
            4. 季节分量外推并计算季节效应
            5. 合成预测速度 = 趋势速度 × (1 + 0.3 × 季节效应)

        回退路径（scipy savgol_filter）:
            1. 使用 Savitzky-Golay 滤波器提取平滑趋势
            2. 季节分量 = 原始 - 趋势
            3. 类似地外推和合成
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足或速度为零时回退
        if len(history) < 10 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)

            if _HAS_MSTL and len(views) >= 14:
                try:
                    # 动态选择周期：避免 period > len/2 触发 statsmodels 警告
                    max_period = min(14, len(views) // 2)
                    periods = [p for p in [7, 14] if p <= max_period] or [max(3, max_period)]
                    with warnings.catch_warnings():
                        warnings.filterwarnings("ignore", message="A period")
                        stl = _MSTL(views, periods=periods)  # 多重季节分解
                        res = stl.fit()
                    trend = res.trend  # 趋势分量
                    seasonal = res.seasonal  # 季节分量
                    # 趋势的梯度（变化速度），取最近3点的平均
                    trend_grad = np.gradient(trend)
                    trend_vel = np.mean(trend_grad[-3:]) / 3600  # 转换为小时速度
                except Exception:
                    # MSTL 失败 → 使用速度作为趋势速度
                    trend_vel = velocity
                    seasonal = np.zeros_like(views)
            else:
                # statsmodels MSTL 不可用 → 使用 savgol_filter 提取趋势
                from scipy.signal import savgol_filter

                # 窗口大小选择（奇数，最小3）
                window = min(7, len(views) - 1 if len(views) % 2 == 0 else len(views))
                if window < 3:
                    window = 3
                if window % 2 == 0:
                    window += 1  # savgol 要求奇数窗口
                # Savitzky-Golay 滤波器：在移动窗口内做多项式拟合来平滑
                trend = savgol_filter(views, window, 1)
                seasonal = views - trend  # 季节分量 = 原始 - 趋势
                # 趋势最近5点的平均差分速度
                trend_vel = np.mean(np.diff(trend[-5:])) / 3600 if len(trend) >= 5 else velocity

            # ── 季节效应外推 ───────────────────────
            # 取最近7个点的季节模式，复制3份后取前7个作为预测
            seasonal_pattern = seasonal[-min(7, len(seasonal)) :]
            pred_seasonal = np.tile(seasonal_pattern, 3)[:7]  # 复制填充到7天
            # 季节效应 = 预测季节均值 / 最近7天播放量均值
            pred_seasonal_effect = np.mean(pred_seasonal) / max(np.mean(views[-7:]), 1)

            # ── 合成预测速度 ───────────────────────
            # 趋势速度 + 30%的季节效应调整
            predicted_velocity = max(0, trend_vel * (1 + 0.3 * pred_seasonal_effect))
            # 如果预测速度低于当前速度的30%，保留当前速度（保守）
            if predicted_velocity < velocity * 0.3:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                # 对数增长的置信度（数据越多，增速越慢）
                confidence = min(0.8, 0.4 + 0.04 * np.log1p(len(history)))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "mstl", "history_len": len(history)},
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
                metadata={"method": "mstl", "reason": "fallback"},
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
            metadata={"method": "mstl", "reason": "fallback"},
            timestamp=datetime.now(),
        )
