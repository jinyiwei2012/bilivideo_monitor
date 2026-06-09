"""
Prophet预测算法 — 真实实现 + NumPy 降级

Facebook Prophet 是一种专门针对商业时间序列设计的预测模型。
它将时间序列分解为趋势（Trend）、季节性（Seasonality）和节假日（Holidays）效应。

核心原理（Prophet模型）:
    y(t) = g(t) + s(t) + h(t) + ε_t
    其中:
    - g(t): 趋势函数，使用分段逻辑增长或线性增长模型
    - s(t): 季节函数，使用傅里叶级数建模多周期季节模式
    - h(t): 节假日效应（本场景未使用）
    - ε_t: 误差项

    Prophet的优势:
    1. 自动检测趋势变化点（Changepoints）
    2. 对缺失数据和异常值鲁棒
    3. 可解释性强（每个成分都可以独立分析）
    4. 外推预测效果好

双级实现策略：
    1. prophet.Prophet 真实实现 — 使用 Prophet 库完整建模
    2. NumPy 简化版 — 手动实现线性趋势 + 傅里叶季节分解 + Ridge 回归

适用场景：
    - 有足够历史数据（≥7点）的中长期预测
    - 需要自动检测趋势变化的场景
    - B站视频播放量的周周期建模

参考:
    Taylor & Letham (2018) "Forecasting at Scale", American Statistician
"""

import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

# ── 可选依赖检测 ──────────────────────────────────
_HAS_PROPHET = False
try:
    logging.getLogger("prophet.plot").setLevel(logging.CRITICAL)
    from prophet import Prophet

    _HAS_PROPHET = True
except ImportError:
    pass


class ProphetSimpleAlgorithm(BaseAlgorithm):
    """Prophet 预测算法

    Facebook Prophet 的趋势+季节性分解预测，
    支持趋势变化点检测和傅里叶季节建模。

    属性:
        name (str): 算法显示名称 "Prophet"
        algorithm_id (str): 算法唯一标识 "prophet"
        description (str): 算法描述
        category (str): 算法分类 "时间序列"
        default_weight (float): 集成预测中的默认权重 1.3
        n_changepoints (int): 趋势变化点数量，默认 3
        seasonality_prior (float): 季节性先验强度，默认 0.5
        fourier_order (int): 傅里叶级数阶数，默认 3
    """

    name = "Prophet"
    algorithm_id = "prophet"
    description = "基于 Facebook Prophet 的趋势+季节性分解预测"
    category = "时间序列"
    default_weight = 1.3

    def __init__(self):
        """初始化 Prophet 算法参数"""
        super().__init__()
        self.n_changepoints = 3  # 趋势变化点数量
        self.seasonality_prior = 0.5  # 季节性先验（越大季节性越灵活）
        self.fourier_order = 3  # 傅里叶阶数（越高能拟合越复杂周期模式）

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行 Prophet 预测（三级级联回退策略）

        按优先级尝试：
        1. prophet.Prophet 真实实现
        2. NumPy 简化版（手动实现 Prophet 核心逻辑）
        3. NumPy 线性回退

        参数:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        # 已达标
        if remaining <= 0:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=0,
                confidence=1.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "prophet", "note": "already_reached"},
                timestamp=datetime.now(),
            )

        # 数据不足或速度为零 → NumPy 回退
        if len(history) < 7 or velocity <= 0:
            return self._numpy_predict(current_views, velocity, remaining, threshold)

        # 尝试 Prophet 真实实现
        if _HAS_PROPHET:
            try:
                result = self._prophet_predict(history, current_views, threshold)
                if result is not None:
                    predicted_hours, confidence = result
                    return PredictionResult(
                        algorithm_name=self.name,
                        algorithm_id=self.algorithm_id,
                        target_threshold=threshold,
                        predicted_hours=predicted_hours,
                        confidence=confidence,
                        current_views=current_views,
                        current_velocity=velocity,
                        metadata={"method": "prophet", "data_points": len(history)},
                        timestamp=datetime.now(),
                    )
            except Exception as e:
                logger.debug("Prophet 预测失败，回退 numpy: %s", e)

        # Prophet 不可用或失败 → NumPy Prophet 简化版
        return self._numpy_forecast(history, current_views, velocity, remaining, threshold)

    def _prophet_predict(self, history, current_views, threshold) -> Optional[Tuple[float, float]]:
        """使用 prophet.Prophet 库进行完整预测

        参数:
            history: 历史数据列表
            current_views: 当前播放量
            threshold: 目标阈值

        返回:
            Optional[Tuple[float, float]]: (预计小时数, 置信度) 或 None

        步骤:
            1. 构建 Prophet 所需的 DataFrame (ds=时间, y=播放量)
            2. 拟合 Prophet 模型（周季节性 + 自动趋势变化点）
            3. 生成未来日期并预测
            4. 在预测序列中寻找首次达到阈值的点
            5. 基于预测区间宽度计算置信度
        """
        df = self._build_prophet_df(history)
        if df is None or len(df) < 7:
            return None

        # 初始化 Prophet 模型
        model = Prophet(
            changepoint_prior_scale=0.05,  # 趋势变化灵活性（越小趋势越平滑）
            weekly_seasonality=True,  # 启用周季节性（B站重要的周期模式）
            daily_seasonality=False,  # 日季节性关闭（数据粒度通常是天级别）
            yearly_seasonality=False,  # 年季节性关闭（视频不太可能跟踪一年）
        )
        model.fit(df)

        # 预测未来天数：基于播放量增速和剩余量估算
        periods = min(365, max(30, int((threshold - current_views) / max(1, np.mean(np.diff(df["y"])))) + 7))
        future = model.make_future_dataframe(periods=periods)
        forecast = model.predict(future)

        # 在预测序列中寻找首次达到阈值的天数
        forecast_values = forecast["yhat"].values[-periods:]
        for i in range(periods):
            if forecast_values[i] >= threshold:
                predicted_hours = (i + 1) * 24
                break
        else:
            return None  # 预测期内无法达标

        # 置信度基于预测区间宽度
        # 区间越窄 → 预测越确定 → 置信度越高
        yhat_lower = forecast["yhat_lower"].values[-periods:]
        yhat_upper = forecast["yhat_upper"].values[-periods:]
        if i < len(yhat_upper):
            interval_width = yhat_upper[i] - yhat_lower[i]
            scale = max(abs(threshold), 1)
            confidence = max(0.1, min(0.85, 0.6 - (interval_width / scale) * 0.3))
        else:
            confidence = 0.3

        return (predicted_hours, confidence)

    def _build_prophet_df(self, history):
        """将历史数据转换为 Prophet 需要的 pandas DataFrame

        参数:
            history: 历史数据列表

        返回:
            pd.DataFrame 或 None: 包含 ds（时间）和 y（播放量）两列的数据框

        Prophet 要求:
            - ds: datetime 类型，表示时间戳
            - y: float 类型，表示观测值
        """
        try:
            import pandas as pd

            records = []
            for h in history:
                ts = h.get("timestamp", 0)
                if hasattr(ts, "timestamp"):
                    dt = datetime.fromtimestamp(ts.timestamp())
                elif isinstance(ts, (int, float)):
                    dt = datetime.fromtimestamp(ts)
                else:
                    continue
                records.append({"ds": dt, "y": float(h.get("view_count", 0))})

            if len(records) < 7:
                return None
            return pd.DataFrame(records)
        except Exception:
            return None

    def _numpy_forecast(self, history, current_views, velocity, remaining, threshold) -> PredictionResult:
        """NumPy 简化版 Prophet（手动实现核心逻辑）

        使用线性趋势 + 傅里叶季节分解 + Ridge 回归，
        实现 Prophet 的核心功能。

        参数:
            history: 历史数据列表
            current_views: 当前播放量
            velocity: 当前速度
            remaining: 剩余播放量
            threshold: 目标阈值

        返回:
            PredictionResult: 预测结果对象

        步骤:
            1. 提取并按天转换时间序列
            2. 计算趋势变化点
            3. 构建趋势特征（分段线性）
            4. 构建季节特征（傅里叶级数）
            5. Ridge 回归拟合
            6. 外推预测并找达标点
        """
        try:
            t, y = self._extract_time_series(history)
            if t is None or len(t) < 7:
                return self._numpy_predict(current_views, velocity, remaining, threshold)

            n = len(t)
            period = 7.0  # 周周期（天）

            # 计算趋势变化点
            cp_t = self._compute_changepoints(t, n)

            # 构建特征矩阵：趋势（分段线性） + 季节（傅里叶级数）
            X_trend = self._build_trend_features(t, cp_t)
            X_seasonal = self._build_seasonal_features(t, period)
            X = np.column_stack([X_trend, X_seasonal])
            n_trend = X_trend.shape[1]

            # Ridge 回归拟合（对季节分量施加 L2 正则化）
            beta = self._fit_ridge(X, y, n_trend)

            # 外推预测
            forecast_result = self._compute_forecast(X, beta, n, cp_t, period, current_views, threshold, y)
            if forecast_result is None:
                return self._numpy_predict(current_views, velocity, remaining, threshold)

            predicted_hours, confidence = forecast_result
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "prophet_numpy", "data_points": len(history)},
                timestamp=datetime.now(),
            )
        except Exception:
            return self._numpy_predict(current_views, velocity, remaining, threshold)

    def _numpy_predict(self, current_views, velocity, remaining, threshold) -> PredictionResult:
        """NumPy 线性回退预测（最简单方式）

        参数:
            current_views: 当前播放量
            velocity: 当前速度
            remaining: 剩余播放量
            threshold: 目标阈值

        返回:
            PredictionResult: 预测结果对象
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
                metadata={"method": "prophet_fallback"},
                timestamp=datetime.now(),
            )
        predicted_hours = remaining / velocity
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=0.3,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "prophet_fallback"},
            timestamp=datetime.now(),
        )

    # ── NumPy 回退的辅助方法 ────────────────────────────

    def _extract_time_series(self, history):
        """从历史数据提取时间序列（转换为相对于起始时间的天数）

        参数:
            history: 历史数据列表

        返回:
            Tuple[np.ndarray, np.ndarray] 或 (None, None):
                - t_days: 相对天数数组
                - views: 播放量数组
        """
        t_days = []
        views = []
        base_time = None
        for h in history:
            ts = h.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                epoch = ts.timestamp()
            elif isinstance(ts, (int, float)):
                epoch = ts
            elif isinstance(ts, str):
                dt_obj = datetime.fromisoformat(str(ts)[:19].replace("T", " "))
                epoch = dt_obj.timestamp()
            else:
                continue
            if base_time is None:
                base_time = epoch  # 以第一个时间点为基准
            t_days.append((epoch - base_time) / 86400.0)  # 转换为天数
            views.append(float(h.get("view_count", 0)))
        if len(t_days) < 7 or not views:
            return None, None
        return np.array(t_days), np.array(views)

    def _compute_changepoints(self, t, n):
        """计算趋势变化点位置

        参数:
            t: 时间数组（天数）
            n: 数据点数

        返回:
            np.ndarray: 变化点的时间值数组

        原理:
            将时间线均匀分为 n_changepoints+1 段，
            变化点位于各段的边界处。
        """
        n_cp = min(self.n_changepoints, n - 2)
        cp_idx = np.linspace(0, n - 1, n_cp + 2, dtype=int)[1:-1]
        return t[cp_idx] if len(cp_idx) > 0 else np.array([t[-1]])

    def _build_trend_features(self, time_array, cp_t):
        """构建趋势特征矩阵（分段线性模型）

        参数:
            time_array: 时间数组
            cp_t: 变化点时间值

        返回:
            np.ndarray: 趋势特征矩阵

        特征结构:
            [1, t, max(0, t-s₁), max(0, t-s₂), ...]
            其中 s_i 是变化点，实现分段线性趋势
        """
        features = [np.ones(len(time_array)), time_array.copy()]  # 截距 + 线性趋势
        for cp in cp_t:
            # 变化点后的偏移量（分段线性）
            features.append(np.maximum(0, time_array - cp))
        return np.column_stack(features)

    def _build_seasonal_features(self, time_array, period):
        """构建季节特征矩阵（傅里叶级数）

        参数:
            time_array: 时间数组
            period: 周期长度（天）

        返回:
            np.ndarray: 季节特征矩阵

        傅里叶级数表示:
            s(t) = Σ [a_k × sin(2πkt/P) + b_k × cos(2πkt/P)]
            其中 k = 1..fourier_order, P = period
            共 2 × fourier_order 个特征
        """
        features = []
        for order in range(1, self.fourier_order + 1):
            features.append(np.sin(2 * np.pi * order * time_array / period))
            features.append(np.cos(2 * np.pi * order * time_array / period))
        n = len(time_array)
        return np.column_stack(features) if features else np.zeros((n, 0))

    def _fit_ridge(self, X, y, n_trend):
        """Ridge 回归（对季节分量施加 L2 正则化）

        参数:
            X: 特征矩阵 [趋势特征 | 季节特征]
            y: 目标值（播放量）
            n_trend: 趋势特征的数量（前 n_trend 列）

        返回:
            np.ndarray: 回归系数 β

        正则化策略:
            - 趋势分量不加正则化（避免过度平滑趋势）
            - 季节分量加 L2 正则化（λ = 1/seasonality_prior）
        """
        lam = 1.0 / max(self.seasonality_prior, 0.01)
        n_features = X.shape[1]
        # 正则化矩阵：趋势项无惩罚（0），季节项施加惩罚（lam）
        reg_matrix = np.diag([0] * n_trend + [lam] * (n_features - n_trend))
        try:
            return np.linalg.solve(X.T @ X + reg_matrix, X.T @ y)
        except np.linalg.LinAlgError:
            return np.linalg.lstsq(X.T @ X + reg_matrix, X.T @ y, rcond=None)[0]

    def _compute_forecast(self, X, beta, n, cp_t, period, current_views, threshold, y):
        """外推预测并寻找达标点

        参数:
            X: 历史特征矩阵
            beta: 回归系数
            n: 历史数据点数
            cp_t: 变化点
            period: 周期
            current_views: 当前播放量
            threshold: 目标阈值
            y: 历史播放量

        返回:
            Optional[Tuple[float, float]]: (预计小时数, 置信度) 或 None
        """
        # 确定预测天数
        days_ahead = min(365, int((threshold - current_views) / max(np.mean(np.diff(y)), 1)) + 7)
        days_ahead = max(7, days_ahead)

        # 构建未来特征矩阵
        future_t = np.arange(n, n + days_ahead)
        future_X_trend = self._build_trend_features(future_t, cp_t)
        future_X_seasonal = self._build_seasonal_features(future_t, period)
        future_X = np.column_stack([future_X_trend, future_X_seasonal])

        # 外推预测
        forecast = future_X @ beta

        # 寻找首次达到阈值的天数
        for i in range(days_ahead):
            if forecast[i] >= threshold:
                target_days = i + 1
                break
        else:
            return None  # 预测期内无法达标

        if target_days > 3650:
            return None  # 天数过长，视为无法达标

        predicted_hours = target_days * 24

        # 置信度基于拟合质量（残差/信号比）
        fitted = X @ beta
        residuals = y - fitted
        scale = np.std(y)
        fit_quality = max(0.0, 1.0 - np.std(residuals) / scale) if scale > 0 else 0.5
        confidence = min(0.9, 0.4 + 0.3 * fit_quality + 0.2 * min(1.0, n / 20))

        return (predicted_hours, confidence)
