"""
SARIMA季节性预测算法 (Seasonal ARIMA)

季节性差分自回归移动平均模型，是 ARIMA 的季节性扩展。
在 ARIMA(p,d,q) 的基础上增加了季节性成分 (P,D,Q,m)。

核心原理：
    SARIMA(p,d,q)(P,D,Q,m) 模型 = 非季节部分 × 季节部分
    - 非季节: AR(p)、I(d)、MA(q) — 处理一般趋势和自相关
    - 季节: SAR(P)、SI(D)、SMA(Q) — 处理以 m 为周期的季节效应

    季节差分: (1 - B^m)^D y_t = y_t - y_{t-m}（D阶季节差分）
    季节自回归: 使用过去 P 个季节周期的值
    季节移动平均: 使用过去 Q 个季节周期的预测误差

三级实现策略：
    1. pmdarima.auto_arima — 自动选择最优 (p,d,q)(P,D,Q,m) 阶数
    2. statsmodels SARIMAX — 固定阶数 (1,1,1)(1,0,0,7)
    3. NumPy 简化版 — 手动实现 SARIMA 各步骤

适用场景：
    - 有明显周周期（m=7）的播放量数据
    - 需要同时建模趋势和季节模式
    - 数据量充足（≥24点推荐）的长期预测

参考:
    Box, Jenkins, Reinsel & Ljung (2015)
    "Time Series Analysis: Forecasting and Control", 5th Edition
"""

import logging
import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

# ── 可选依赖检测 ──────────────────────────────────
_HAS_STATSMODELS = False
try:
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    _HAS_STATSMODELS = True
except ImportError:
    pass

_HAS_PMDARIMA = False
try:
    import pmdarima as pm  # pmdarima: 自动 SARIMA 阶数选择

    _HAS_PMDARIMA = True
except ImportError:
    pass


class SARIMASimpleAlgorithm(BaseAlgorithm):
    """SARIMA (Seasonal ARIMA) 季节性差分自回归移动平均

    在 ARIMA 基础上增加了季节成分 (P,D,Q,m)，
    能够同时捕捉非季节趋势和季节周期性。

    参数含义:
        p,d,q: 非季节 ARIMA 阶数
        P,D,Q: 季节 ARIMA 阶数
        m: 季节周期长度（默认7天）

    属性:
        name (str): 算法显示名称 "SARIMA季节预测"
        algorithm_id (str): 算法唯一标识 "sarima_simple"
        description (str): 算法描述
        category (str): 算法分类 "时间序列"
        default_weight (float): 集成预测中的默认权重 1.2
        p,d,q (int): 非季节阶数，默认 (1,1,1)
        P,D,Q,m (int): 季节阶数，默认 (1,0,0,7)
    """

    name = "SARIMA季节预测"
    algorithm_id = "sarima_simple"
    description = "季节性差分自回归移动平均（statsmodels 优先，numpy 回退）"
    category = "时间序列"
    default_weight = 1.2

    def __init__(self):
        """初始化 SARIMA 模型参数"""
        super().__init__()
        self.p, self.d, self.q = 1, 1, 1  # 非季节 ARIMA(1,1,1)
        self.P, self.D, self.Q, self.m = 1, 0, 0, 7  # 季节 (1,0,0)₇

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行 SARIMA 预测（三级级联回退策略）

        按优先级尝试：
        1. pmdarima.auto_arima 自动 SARIMA（数据≥24点）
        2. statsmodels SARIMAX 固定阶数（数据≥15点）
        3. NumPy 简化版手动实现

        参数:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        # 优先使用 pmdarima 自动 SARIMA（自动选择季节和非季节阶数）
        if _HAS_PMDARIMA and len(history) >= 24:
            try:
                result = self._auto_sarima_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("AutoSARIMA pmdarima 失败: %s", e)

        # 回退到 statsmodels 固定阶数
        if _HAS_STATSMODELS and len(history) >= 15:
            try:
                result = self._statsmodels_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("SARIMA statsmodels 失败: %s", e)

        # 最终回退到 NumPy 简化版
        return self._numpy_predict(video_data, threshold)

    def _auto_sarima_predict(self, video_data, threshold):
        """使用 pmdarima.auto_arima 自动选择最优 SARIMA 阶数进行季节预测

        参数:
            video_data: 视频数据字典
            threshold: 目标阈值

        返回:
            PredictionResult 或 None

        自动搜索策略:
            - seasonal=True: 启用季节模式搜索
            - m=min(7, n//4): 季节周期（不超过数据长度的1/4）
            - stepwise=True: 逐步搜索（快速，非穷举）
            - max_P=2, max_Q=2: 限制季节阶数范围
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)
        views_sorted = self._prepare_series(history)
        n = len(views_sorted)
        if n < 24:
            return None
        try:
            # 使用 stepwise 搜索自动选择最优 (p,d,q)(P,D,Q,m) 阶数
            model = pm.auto_arima(
                views_sorted, seasonal=True, m=min(7, n // 4), stepwise=True,
                suppress_warnings=True, max_p=5, max_q=5, max_P=2, max_Q=2,
                maxiter=10, trace=False, error_action="ignore",
            )
            forecast = model.predict(n_periods=30)  # 预测30天
            forecast_views = np.array(forecast)
            target_idx = np.where(forecast_views >= threshold)[0]
            if len(target_idx) > 0 and target_idx[0] < 30:
                predicted_hours = (target_idx[0] + 1) * 24
                aic = float(model.aic()) if callable(getattr(model, "aic", None)) else 1000
                confidence = max(0.1, min(0.9, 0.7 - aic * 0.00015))
            else:
                remaining = threshold - current_views
                predicted_hours = remaining / velocity if velocity > 0 else float("inf")
                confidence = 0.4
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views,
                current_velocity=velocity,
                metadata={
                    "method": "auto_sarima",
                    "order": str(getattr(model, "order", "?")),
                    "seasonal_order": str(getattr(model, "seasonal_order", "?")),
                    "aic": round(aic, 1) if "aic" in dir() else 0,
                },
                timestamp=datetime.now(),
            )
        except Exception:
            return None

    def _statsmodels_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        """使用 statsmodels SARIMAX 固定阶数预测

        参数:
            video_data: 视频数据字典
            threshold: 目标阈值

        返回:
            PredictionResult 或 None

        使用 statsmodels 的 SARIMAX 模型进行参数估计和预测。
        SARIMAX = SARIMA + eXogenous variables（本场景不使用外生变量）
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        views_sorted = self._prepare_series(history)
        n = len(views_sorted)
        if n < 15:
            return None

        try:
            model = SARIMAX(
                views_sorted,
                order=(self.p, self.d, self.q),  # 非季节 ARIMA(1,1,1)
                seasonal_order=(self.P, self.D, self.Q, min(self.m, n // 2)),  # 季节 (1,0,0)ₘ
                enforce_stationarity=False,  # 不强制平稳性（允许非平稳序列）
                enforce_invertibility=False,  # 不强制可逆性
            )
            fitted = model.fit(disp=False)
            forecast = fitted.forecast(steps=30)  # 预测30步
            forecast_views = np.array(forecast)

            target_idx = np.where(forecast_views >= threshold)[0]
            if len(target_idx) > 0 and target_idx[0] < 30:
                predicted_hours = (target_idx[0] + 1) * 24
                aic = getattr(fitted, "aic", 1000)
                confidence = max(0.1, min(0.85, 0.7 - aic * 0.0002))
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
                metadata={
                    "method": "sarima_statsmodels",
                    "order": f"({self.p},{self.d},{self.q})x({self.P},{self.D},{self.Q},{self.m})",
                    "aic": round(float(aic), 1) if "aic" in dir() else 0,
                },
                timestamp=datetime.now(),
            )
        except Exception:
            return None

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        """NumPy 简化版 SARIMA 预测（手动实现全部步骤）

        完整 SARIMA 流程：
        1. 准备序列（提取 + 排序）
        2. d 阶差分 + D 阶季节差分 → 使序列平稳
        3. Yule-Walker 估计 AR 系数
        4. 计算残差并估计 MA 系数
        5. 提取季节性模式
        6. 多步迭代预测
        7. 寻找达标点

        参数:
            video_data: 视频数据字典
            threshold: 目标阈值

        返回:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return self._build_result(threshold, 0, 1.0, velocity, current_views, method="sarima_already")

        if len(history) < max(4, self.m + 2) or velocity <= 0:
            hours = remaining / velocity if velocity > 0 else float("inf")
            return self._build_result(threshold, hours, 0.3, velocity, current_views, notes="insufficient_data")

        views_sorted = self._prepare_series(history)
        n = len(views_sorted)
        if n < 4:
            hours = remaining / velocity
            return self._build_result(threshold, hours, 0.3, velocity, current_views, method="sarima_fallback")

        try:
            # 步骤1-2: 差分处理（使序列平稳）
            diff_series = self._differencing(views_sorted)  # d阶常规差分
            diff_series = self._seasonal_differencing(diff_series)  # D阶季节差分

            if len(diff_series) < 2:
                hours = remaining / velocity
                return self._build_result(threshold, hours, 0.3, velocity, current_views, method="sarima_diff_failed")

            # 去中心化（均值为零）
            y_centered = diff_series - np.mean(diff_series)

            # 步骤3: AR 系数估计（Yule-Walker/最小二乘）
            p = min(self.p, len(y_centered) - 1)
            ar_coeffs = self._estimate_ar(y_centered, p)

            # 步骤4: MA 系数估计
            q = min(self.q, len(y_centered) - p - 1)
            residuals = self._compute_residuals(y_centered, ar_coeffs, p)  # 计算AR残差
            ma_coeffs = self._estimate_ma(y_centered, residuals, q)  # 用残差估计MA系数

            # 步骤5: 提取季节性模式
            seasonal_pattern = self._compute_seasonal_pattern(views_sorted, self.m)

            # 步骤6: 多步预测
            growth_rate = float(np.mean(np.diff(views_sorted))) if n > 1 else velocity * 24
            forecast_days = min(365, max(14, int((threshold - current_views) / max(growth_rate, 1)) + 7))

            pred_values = self._forecast(
                views_sorted, ar_coeffs, ma_coeffs, seasonal_pattern, p, q, self.m, forecast_days
            )

            # 步骤7: 寻找达标点
            combined = np.array(pred_values[n:])  # 仅看预测部分
            target_idx = np.where(combined >= threshold)[0]

            if len(target_idx) > 0 and target_idx[0] < 300:
                predicted_hours = (target_idx[0] + 1) * 24
                # 季节强度评估
                seasonal_strength = 0.0
                if self.m > 0 and len(seasonal_pattern) > 0:
                    seasonal_strength = min(1.0, float(np.std(seasonal_pattern) / max(np.std(views_sorted), 1)))
                # 综合置信度
                n_points_conf = min(1.0, n / 30)
                conf = min(0.9, 0.35 + 0.25 * n_points_conf + 0.2 * seasonal_strength + 0.1 * min(1.0, velocity / 100))
            else:
                predicted_hours = remaining / velocity
                conf = 0.35

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=conf,
                current_views=current_views,
                current_velocity=velocity,
                metadata={
                    "method": "sarima",
                    "ar_order": p,
                    "diff_order": self.d,
                    "ma_order": q,
                    "seasonal_period": self.m,
                    "seasonal_strength": round(seasonal_strength, 3) if self.m > 0 else 0,
                    "forecast_horizon": forecast_days,
                    "data_points": n,
                },
                timestamp=datetime.now(),
            )
        except Exception as e:
            hours = remaining / velocity if velocity > 0 else float("inf")
            return self._build_result(threshold, hours, 0.0, velocity, current_views, error=str(e))

    # ── 子步骤 ─────────────────────────────────────────
    @staticmethod
    def _prepare_series(history: List[Dict]) -> np.ndarray:
        """从历史记录提取并按时间排序播放量数组

        参数:
            history (List[Dict]): 历史数据列表

        返回:
            np.ndarray: 按时间升序排列的播放量数组
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
        if len(views_vals) < 1:
            return np.array([])
        order = np.argsort(timestamps)
        return np.array(views_vals)[order]

    def _differencing(self, series: np.ndarray) -> np.ndarray:
        """d 阶常规差分（消除趋势）

        参数:
            series (np.ndarray): 原始序列

        返回:
            np.ndarray: 差分后的序列

        公式: Δy_t = y_t - y_{t-1}, Δ^d y_t = Δ(Δ^{d-1} y_t)
        """
        diff = series.copy()
        for _ in range(self.d):
            diff = np.diff(diff)
            if len(diff) == 0:
                break
        return diff

    def _seasonal_differencing(self, series: np.ndarray) -> np.ndarray:
        """D 阶季节性差分（消除季节效应）

        参数:
            series (np.ndarray): 输入序列

        返回:
            np.ndarray: 季节差分后的序列

        公式: Δ_m y_t = y_t - y_{t-m}, Δ_m^D y_t = Δ_m(Δ_m^{D-1} y_t)
        """
        if not (self.m > 0 and self.D > 0 and len(series) > self.m):
            return series
        diff = series.copy()
        for _ in range(self.D):
            if len(diff) > self.m:
                # y_t - y_{t-m}
                diff = diff[self.m :] - diff[: -self.m]
        return diff

    @staticmethod
    def _estimate_ar(y_centered: np.ndarray, p: int) -> np.ndarray:
        """AR 系数估计 (Yule-Walker / 最小二乘)

        参数:
            y_centered (np.ndarray): 去中心化的序列
            p (int): AR 阶数

        返回:
            np.ndarray: AR 系数 [φ₁, φ₂, ..., φ_p]

        方法: 最小二乘回归
            y_t = φ₁y_{t-1} + φ₂y_{t-2} + ... + φ_py_{t-p} + ε_t
        """
        if p <= 0:
            return np.zeros(0)
        # 构造滞后矩阵
        ar_matrix = np.column_stack([y_centered[p - i - 1 : len(y_centered) - i - 1] for i in range(p)])
        if ar_matrix.shape[0] <= p or ar_matrix.shape[1] <= 0:
            return np.zeros(p)
        try:
            return np.linalg.lstsq(ar_matrix, y_centered[p:], rcond=None)[0]
        except np.linalg.LinAlgError:
            return np.zeros(p)

    @staticmethod
    def _compute_residuals(y_centered: np.ndarray, ar_coeffs: np.ndarray, p: int) -> np.ndarray:
        """计算 AR 残差 ε_t = y_t - Σ φ_i × y_{t-i}

        参数:
            y_centered: 去中心化序列
            ar_coeffs: AR 系数
            p: AR 阶数

        返回:
            np.ndarray: 残差序列
        """
        residuals = y_centered.copy()
        if p > 0 and len(ar_coeffs) == p:
            for i in range(p, len(y_centered)):
                residuals[i] = y_centered[i] - np.dot(ar_coeffs, y_centered[i - p : i])
        return residuals

    @staticmethod
    def _estimate_ma(y_centered: np.ndarray, residuals: np.ndarray, q: int) -> np.ndarray:
        """MA 系数估计（最小二乘）

        参数:
            y_centered: 去中心化序列
            residuals: AR 残差
            q: MA 阶数

        返回:
            np.ndarray: MA 系数 [θ₁, θ₂, ..., θ_q]

        回归: y_t = θ₁ε_{t-1} + θ₂ε_{t-2} + ... + θ_qε_{t-q} + η_t
        """
        if q <= 0:
            return np.zeros(0)
        ma_matrix = np.column_stack([residuals[q - j - 1 : len(residuals) - j - 1] for j in range(q)])
        if ma_matrix.shape[0] <= q or ma_matrix.shape[1] <= 0:
            return np.zeros(q)
        try:
            return np.linalg.lstsq(ma_matrix, y_centered[q:], rcond=None)[0]
        except np.linalg.LinAlgError:
            return np.zeros(q)

    @staticmethod
    def _compute_seasonal_pattern(views_sorted: np.ndarray, m: int) -> np.ndarray:
        """逐周期平均提取季节性模式

        参数:
            views_sorted: 排序后的播放量
            m: 周期长度

        返回:
            np.ndarray: 长度为 m 的季节模式数组

        方法:
            将序列按周期切分，每个周期位置取平均，减去总趋势均值
        """
        n = len(views_sorted)
        if m <= 0 or m >= n:
            return np.zeros(m) if m <= n else np.zeros(n)
        n_full = n // m  # 完整周期数
        if n_full < 1:
            return np.zeros(m)
        # 截取整周期部分，reshape 为 (n_full, m)
        seasonal_vals = views_sorted[: n_full * m].reshape(n_full, m)
        trend = float(np.mean(views_sorted))  # 总体趋势均值
        return np.mean(seasonal_vals, axis=0) - trend  # 每个位置偏离均值的量

    @staticmethod
    def _forecast(
        views_sorted: np.ndarray,
        ar_coeffs: np.ndarray,
        ma_coeffs: np.ndarray,
        seasonal_pattern: np.ndarray,
        p: int,
        q: int,
        m: int,
        days: int,
    ) -> list:
        """迭代多步预测

        参数:
            views_sorted: 原始播放量序列
            ar_coeffs: AR 系数
            ma_coeffs: MA 系数
            seasonal_pattern: 季节模式
            p, q, m: SARIMA 阶数
            days: 预测天数

        返回:
            list: 包含原始序列 + 预测值的完整列表

        预测公式:
            ŷ_t = AR_terms + MA_terms + seasonal_term + 0.1×growth_rate
        """
        growth_rate = float(np.mean(np.diff(views_sorted))) if len(views_sorted) > 1 else 0
        pred_values = list(views_sorted)
        last_residual = 0.0  # 最近预测误差

        for i in range(days):
            idx = len(pred_values)

            # AR 项: Σ φ_j × y_{t-j}
            ar_term = float(np.dot(ar_coeffs, pred_values[idx - p : idx])) if p > 0 and len(ar_coeffs) == p else 0.0

            # MA 项: Σ θ_j × ε_{t-j}
            ma_term = float(np.dot(ma_coeffs, [last_residual] * q)) if q > 0 and len(ma_coeffs) == q else 0.0

            # 季节项: 循环使用季节模式
            seas_term = float(seasonal_pattern[i % m]) if m > 0 else 0.0

            # 合成预测值
            next_val = ar_term + ma_term + seas_term + 0.1 * growth_rate
            # 确保不倒退（至少保持最低增长）
            if next_val < pred_values[-1]:
                next_val = pred_values[-1] + max(growth_rate * 0.3, 0)
            pred_values.append(next_val)

            # 更新残差（用于下一步 MA 项计算）
            if len(pred_values) > p + q:
                actual = float(views_sorted[-1]) if i == 0 else pred_values[-2]
                last_residual = actual - (ar_term + seas_term)

        return pred_values

    @staticmethod
    def _build_result(
        threshold: int,
        hours: float,
        conf: float,
        velocity: float,
        current_views: int,
        method: str = "sarima",
        notes: str = "",
        error: str = "",
    ) -> PredictionResult:
        """构造失败/回退结果

        参数:
            threshold: 目标阈值
            hours: 预计小时数
            conf: 置信度
            velocity: 当前速度
            current_views: 当前播放量
            method: 方法标识
            notes: 备注信息
            error: 错误信息

        返回:
            PredictionResult: 标准化预测结果
        """
        meta = {"method": method}
        if notes:
            meta["notes"] = notes
        if error:
            meta["error"] = error
        return PredictionResult(
            algorithm_name="SARIMA季节预测",
            algorithm_id="sarima_simple",
            target_threshold=threshold,
            predicted_hours=hours,
            confidence=conf,
            current_views=current_views,
            current_velocity=velocity,
            metadata=meta,
            timestamp=datetime.now(),
        )
