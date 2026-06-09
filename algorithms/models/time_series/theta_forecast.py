"""
Theta预测算法 (Theta Forecast Algorithm)

Theta预测方法是M3预测竞赛的冠军方法（区别于 theta_method.py 中的亚军实现）。
通过构造两条不同的Theta线（θ=0 和 θ=2），一条代表长期趋势（线性外推），
一条代表去趋势后的短期波动（指数平滑外推），然后组合两者得到最终预测。

核心原理：
    1. Theta-0线（θ=0）: 等同于原始序列的线性趋势外推
    2. Theta-2线（θ=2）: 对序列做"二倍差分"变换（2×原始 - 趋势），
       放大短期波动特征，用指数平滑外推
    3. 最终预测 = (Theta-0预测 + Theta-2预测) / 2

数学基础:
    - Theta-0: ŷ₀(t) = a + b × t  (线性回归外推)
    - Theta-2: y₂ = 2y_t - trend_t
      ŷ₂(t) = SES(ŷ₂)  (指数平滑外推)
    - 组合预测: ŷ(t) = 0.5 × ŷ₀(t) + 0.5 × ŷ₂(t)

参考:
    Assimakopoulos & Nikolopoulos (2000)
    "The theta model: a decomposition approach to forecasting"

适用场景：
    - 有明显趋势的时间序列
    - 需要同时捕捉长期趋势和短期波动的场景
    - M3竞赛验证过的最有效轻量方法之一
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
import logging

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)


class ThetaForecastAlgorithm(BaseAlgorithm):
    """Theta预测算法（M3冠军版本）

    通过构造两条Theta线（θ=0线性外推 + θ=2指数平滑），
    组合两者得到最终预测结果。

    双线策略:
        - Theta-0线: 纯线性回归外推，捕捉长期趋势
        - Theta-2线: 放大短期波动后指数平滑，捕捉近期变化
        - 最终 = 两者等权平均

    属性:
        name (str): 算法显示名称 "Theta预测"
        algorithm_id (str): 算法唯一标识 "theta_forecast"
        description (str): 算法描述
        category (str): 算法分类 "时间序列"
        default_weight (float): 集成预测中的默认权重 1.2
    """

    name = "Theta预测"
    algorithm_id = "theta_forecast"
    description = "M3预测竞赛获胜方法，双线组合预测"
    category = "时间序列"
    default_weight = 1.2

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行Theta预测

        构造两条Theta线（θ=0和θ=2），分别外推后组合预测。

        参数:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 预测结果对象

        算法步骤:
            1. 对原始序列做线性回归，得到趋势线（Theta-0）
            2. 构造Theta-2线: theta₂ = 2 × views - trend
            3. 对Theta-2线做指数平滑
            4. 分别外推两条线到未来
            5. 组合预测 = 0.5 × Theta-0预测 + 0.5 × Theta-2预测
            6. 在组合预测中寻找首次达到阈值的点
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        # 已达标
        if remaining <= 0:
            return self._make_result(0, 1.0, current_views, velocity, {"method": "theta"}, threshold)

        # 数据不足
        if len(history) < 4 or velocity <= 0:
            return self._make_result(
                remaining / velocity if velocity > 0 else float("inf"),
                0.3,
                current_views,
                velocity,
                {"method": "theta", "notes": "insufficient_data"},
                threshold,
            )

        views_sorted = self._extract_views(history)
        if views_sorted is None or len(views_sorted) < 4:
            return self._make_result(
                remaining / velocity,
                0.3,
                current_views,
                velocity,
                {"method": "theta_fallback"},
                threshold,
            )

        try:
            return self._compute_theta(views_sorted, current_views, velocity, remaining, threshold)
        except Exception as e:
            logger.warning(f"Theta预测失败: {e}")
            return self._make_result(
                remaining / velocity if velocity > 0 else float("inf"),
                0.0,
                current_views,
                velocity,
                {"error": str(e)},
                threshold,
            )

    def _extract_views(self, history):
        """从历史记录中提取并排序播放量序列

        参数:
            history: 历史数据列表

        返回:
            np.ndarray 或 None: 按时间排序的播放量数组
        """
        timestamps, views_vals = [], []
        for h in history:
            ts = h.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(str(ts)[:19].replace("T", " ")).timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))
        if len(views_vals) < 4:
            return None
        order = np.argsort(timestamps)
        return np.array(views_vals)[order]

    def _compute_theta(self, views_sorted, current_views, velocity, remaining, threshold):
        """执行Theta算法核心计算

        参数:
            views_sorted: 按时间排序的播放量数组
            current_views: 当前播放量
            velocity: 当前速度
            remaining: 剩余播放量
            threshold: 目标阈值

        返回:
            PredictionResult: 预测结果对象
        """
        n = len(views_sorted)
        x = np.arange(n, dtype=float)

        # ── Theta-0线（线性趋势） ────────────────
        # 对原始序列做线性回归
        coeffs = np.polyfit(x, views_sorted, 1)
        trend_vals = np.polyval(coeffs, x)

        # ── Theta-2线（2×原始 - 趋势） ──────────
        # 放大短期波动特征
        theta_2 = 2 * views_sorted - trend_vals

        # 对Theta-2线做指数平滑（SES）
        alpha = 0.3
        smoothed = np.zeros(n)
        smoothed[0] = theta_2[0]
        for i in range(1, n):
            smoothed[i] = alpha * theta_2[i] + (1 - alpha) * smoothed[i - 1]

        # ── 确定预测步长 ────────────────────────
        growth_per_day = np.mean(np.diff(views_sorted)) if n > 1 else velocity * 24
        n_future = min(365, max(10, int((threshold - current_views) / max(growth_per_day, 1)) + 5))
        future_x = np.arange(n, n + n_future)  # 未来的时间索引

        # ── Theta-0外推：线性趋势外推 ──────────
        forecast_0 = np.polyval(coeffs, future_x)

        # ── Theta-2外推：指数平滑值逐渐向趋势靠拢 ──
        ses_last = smoothed[-1]  # 指数平滑的最新值
        forecast_2 = np.empty(n_future)
        for i in range(n_future):
            # 短期用平滑值，长期向线性趋势回归
            w = min(1.0, i / max(n_future // 2, 1))
            forecast_2[i] = (1 - w) * ses_last + w * forecast_0[i]

        # ── 组合预测 = (Theta-0 + Theta-2) / 2 ──
        combined = 0.5 * forecast_0 + 0.5 * forecast_2

        # ── 寻找达标点 ─────────────────────────
        target_days = next((i + 1 for i in range(n_future) if combined[i] >= threshold), None)

        if target_days is None or target_days > 3650:
            predicted_hours = remaining / velocity
            confidence = 0.4
        else:
            predicted_hours = target_days * 24
            # 置信度基于拟合质量（残差相对于信号的大小）
            residuals = views_sorted - trend_vals
            scale = np.std(views_sorted)
            fit_quality = max(0.0, 1.0 - np.std(residuals) / max(scale, 1))
            confidence = min(0.9, 0.4 + 0.3 * fit_quality + 0.2 * min(1.0, n / 20))

        return self._make_result(
            predicted_hours,
            confidence,
            current_views,
            velocity,
            {
                "method": "theta",
                "trend_slope": coeffs[0],
                "ses_last": float(ses_last),
                "forecast_horizon": n_future,
                "data_points": n,
            },
            threshold,
        )

    def _make_result(self, predicted_hours, confidence, current_views, velocity, metadata, threshold):
        """构造 PredictionResult 预测结果对象

        参数:
            predicted_hours: 预计达到阈值的小时数
            confidence: 预测置信度 (0.0 ~ 1.0)
            current_views: 当前播放量
            velocity: 当前增长速度
            metadata: 元数据字典
            threshold: 目标阈值

        返回:
            PredictionResult: 标准预测结果对象
        """
        metadata.setdefault("method", "theta")
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata=metadata,
            timestamp=datetime.now(),
        )
