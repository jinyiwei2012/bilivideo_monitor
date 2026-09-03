"""
ARIMA预测算法 (Autoregressive Integrated Moving Average)

自回归积分滑动平均模型用于时间序列预测。
三级实现策略（按优先级）：
1. pmdarima.auto_arima — 自动选择最优(p,d,q)阶数
2. statsmodels.ARIMA — 固定(2,1,1)阶数
3. NumPy 简化版 — 无依赖的纯Python回退实现

核心原理：
    ARIMA(p,d,q)模型由三个部分组成：
    - AR(p): 自回归 — 当前值与过去p个值的线性关系
    - I(d): 差分 — 对序列做d次差分使其平稳
    - MA(q): 移动平均 — 当前值与过去q个预测误差的线性关系

    ARIMA模型可以捕捉时间序列中的趋势和自相关结构，
    是目前最经典和广泛使用的时间序列预测方法之一。

适用场景：
    - 有足够历史数据（≥20点推荐）的中长期预测
    - 播放量变化呈现自相关模式的视频
    - 作为时间序列预测的基线算法

参考:
    Box, G. E. P. & Jenkins, G. M. (1970)
    "Time Series Analysis: Forecasting and Control"
"""

import logging
from datetime import datetime
from typing import Dict, Any

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

# ── 可选依赖检测 ──────────────────────────────────
_HAS_STATSMODELS = False
try:
    from statsmodels.tsa.arima.model import ARIMA
    _HAS_STATSMODELS = True
except ImportError:
    pass

_HAS_PMDARIMA = False
try:
    import pmdarima as pm  # pmdarima: 自动 ARIMA 阶数选择（AutoARIMA）

    _HAS_PMDARIMA = True
except ImportError:
    pass


class ArimaSimpleAlgorithm(BaseAlgorithm):
    """ARIMA预测算法

    自回归积分滑动平均（ARIMA）预测，三级实现策略：
    1. pmdarima auto_arima（自动选阶）
    2. statsmodels ARIMA（固定阶数）
    3. NumPy简化版（纯Python回退）

    属性:
        name (str): 算法显示名称 "ARIMA简化"
        algorithm_id (str): 算法唯一标识 "arima_simple"
        description (str): 算法描述
        category (str): 算法分类 "机器学习"
        default_weight (float): 集成预测中的默认权重 1.3
    """

    name = "ARIMA简化"
    algorithm_id = "arima_simple"
    description = "自回归积分滑动平均预测（statsmodels 优先，numpy 回退）"
    category = "时间序列"
    default_weight = 1.3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行ARIMA预测（三级级联回退策略）

        按优先级尝试：
        1. pmdarima.auto_arima 自动ARIMA（数据≥20点）
        2. statsmodels ARIMA(2,1,1) 固定阶数（数据≥15点）
        3. NumPy简化版（数据≥3点）

        参数:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        # 优先使用 pmdarima 自动 ARIMA（自动选择最优阶数）
        if _HAS_PMDARIMA and len(history) >= 20:
            try:
                result = self._auto_arima_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("AutoARIMA pmdarima 失败: %s", e)

        # 回退到 statsmodels 固定阶数 ARIMA
        if _HAS_STATSMODELS and len(history) >= 15:
            try:
                result = self._statsmodels_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("ARIMA statsmodels 失败，回退 numpy: %s", e)

        # 最终回退到 NumPy 简化版
        return self._numpy_predict(video_data, threshold)

    def _auto_arima_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        """使用 pmdarima.auto_arima 自动选择最优 ARIMA 阶数进行预测

        通过 stepwise 搜索算法在 (p,d,q) 参数空间中自动寻找
        使 AIC（Akaike Information Criterion）最小的阶数组合。
        预测未来30个数据点（每天一个点），在预测序列中寻找
        首个达到目标阈值的点。

        参数:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        返回:
            PredictionResult 或 None（失败返回None）
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        # 提取时间戳和播放量序列
        timestamps, views_vals = [], []
        for h in history:
            ts = h.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts).timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))

        if len(views_vals) < 20:
            return None

        # 按时间排序确保序列正确
        order = np.argsort(timestamps)
        views = np.array(views_vals)[order]

        # 实际采样间隔（小时）：用相邻时间戳差的中位数换算，
        # 避免把每个采样点当成 1 天（间隔可能是 75s/几分钟/数小时）
        try:
            sorted_ts = np.array(timestamps)[order]
            diffs_h = np.diff(sorted_ts) / 3600.0
            diffs_h = diffs_h[diffs_h > 0]
            interval_h = float(np.median(diffs_h)) if len(diffs_h) else 24.0
        except Exception:
            interval_h = 24.0

        try:
            # 使用 stepwise 搜索自动选择最优 (p,d,q) 阶数
            # max_p=5, max_q=5, max_d=2: 限制搜索范围防止过拟合
            # stepwise=True: 使用逐步搜索（比全网格搜索快很多）
            model = pm.auto_arima(
                views, seasonal=False, stepwise=True, suppress_warnings=True,
                max_p=5, max_q=5, max_d=2, maxiter=10, trace=False,
                error_action="ignore",
            )
            # 预测未来 30 天（每天一个点）
            forecast = model.predict(n_periods=30)
            forecast_views = np.array(forecast)

            # 在预测序列中寻找首次达到阈值的点
            target_idx = np.where(forecast_views >= threshold)[0]
            if len(target_idx) > 0 and target_idx[0] < 30:
                predicted_hours = (target_idx[0] + 1) * interval_h  # 索引+1 = 采样点数，每点=实际间隔
                # AIC衡量模型拟合质量，AIC越小越好
                aic = getattr(model, "aic", lambda: 1000)() if callable(getattr(model, "aic", None)) else 1000
                confidence = max(0.1, min(0.9, 0.7 - aic * 0.00015))
            else:
                # 预测期内无法达标，使用当前速度估算
                velocity = self.calculate_velocity(video_data)
                remaining = threshold - current_views
                predicted_hours = remaining / velocity if velocity > 0 else float("inf")
                confidence = 0.4

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views,
                current_velocity=self.calculate_velocity(video_data),
                metadata={
                    "method": "auto_arima",
                    "order": str(getattr(model, "order", "?")),  # 自动选择的(p,d,q)阶数
                    "aic": round(float(model.aic()) if callable(getattr(model, "aic", None)) else 0, 1),
                },
                timestamp=datetime.now(),
            )
        except Exception:
            return None

    def _statsmodels_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        """使用 statsmodels ARIMA(2,1,1) 固定阶数进行预测

        固定使用 (p=2, d=1, q=1) 阶数，这是中等长度时间序列的常用配置。
        预测未来30步，寻找首个达到阈值的点。

        参数:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        返回:
            PredictionResult 或 None
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        # 提取并排序时间序列
        timestamps, views_vals = [], []
        for h in history:
            ts = h.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts).timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))

        if len(views_vals) < 15:
            return None

        order = np.argsort(timestamps)
        views = np.array(views_vals)[order]

        # 实际采样间隔（小时）：用相邻时间戳差的中位数换算，
        # 避免把每个采样点当成 1 天
        try:
            sorted_ts = np.array(timestamps)[order]
            diffs_h = np.diff(sorted_ts) / 3600.0
            diffs_h = diffs_h[diffs_h > 0]
            interval_h = float(np.median(diffs_h)) if len(diffs_h) else 24.0
        except Exception:
            interval_h = 24.0

        try:
            # ARIMA(2,1,1): 2阶自回归 + 1阶差分 + 1阶移动平均
            model = ARIMA(views, order=(2, 1, 1))
            fitted = model.fit()
            forecast = fitted.forecast(steps=30)  # 预测30步
            forecast_views = np.array(forecast)

            # 寻找首次达到阈值的预测点
            target_idx = np.where(forecast_views >= threshold)[0]
            if len(target_idx) > 0 and target_idx[0] < 30:
                predicted_hours = (target_idx[0] + 1) * interval_h
                aic = getattr(fitted, "aic", 1000)
                confidence = max(0.1, min(0.85, 0.7 - aic * 0.0002))
            else:
                velocity = self.calculate_velocity(video_data)
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
                current_velocity=self.calculate_velocity(video_data),
                metadata={"method": "arima_statsmodels", "order": "(2,1,1)"},
                timestamp=datetime.now(),
            )
        except Exception:
            return None

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        """使用 NumPy 简化版 ARIMA 进行预测（纯Python回退实现）

        当没有 statsmodels/pmdarima 库时使用。
        核心思路：
        1. 计算最近3个数据点的一阶差分（即增长量）
        2. 取差分的平均值作为趋势
        3. 用趋势除以平均时间间隔作为预测速度
        4. 剩余播放量除以预测速度得到达标时间

        参数:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        返回:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        if len(history) < 3:
            # 数据不足，使用线性预测
            velocity = self.calculate_velocity(video_data)
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
            elif velocity <= 0:
                predicted_hours = float("inf")
            else:
                predicted_hours = remaining / velocity
            confidence = 0.4
        else:
            # 简化ARIMA: 使用最近3个点的趋势
            recent = history[-3:]
            views = [r.get("view_count", 0) for r in recent]

            # 计算一阶差分（相邻点之间的变化量）
            diff1 = [views[i] - views[i - 1] for i in range(1, len(views))]

            # 预测下一个差分（未来增长）
            if len(diff1) >= 2:
                # 有2个差分时可计算平均趋势
                trend = sum(diff1) / len(diff1)
            else:
                trend = diff1[0] if diff1 else 0

            # 计算平均时间间隔（小时），用于将趋势转换为小时速度
            times = [r.get("timestamp", 0) for r in recent]
            time_diffs = [(times[i] - times[i - 1]) / 3600 for i in range(1, len(times))]
            avg_interval = sum(time_diffs) / len(time_diffs) if time_diffs else 1

            # 预测速度 = 趋势 / 平均间隔时间（单位：播放量/小时）
            velocity = trend / avg_interval if avg_interval > 0 else 0

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
            elif velocity <= 0:
                predicted_hours = float("inf")
            else:
                predicted_hours = remaining / velocity

            # 置信度随数据量增加而提高
            confidence = min(1.0, 0.5 + len(history) * 0.05)

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "arima_simple", "history_points": len(history)},
            timestamp=datetime.now(),
        )
