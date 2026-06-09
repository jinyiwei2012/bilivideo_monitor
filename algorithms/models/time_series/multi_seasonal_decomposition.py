"""
多季节性分解预测算法 (Multi-Seasonal Decomposition Prediction Algorithm)

同时考虑日周期和周周期模式，将播放量序列分解为：
趋势 + 日周期 + 周周期 + 残差，分别建模后再合成预测。

核心原理：
    B站视频播放量呈现多种周期性：
    - 日周期: 一天内不同时段播放量不同（如晚上18-24点是高峰）
    - 周周期: 工作日 vs 周末播放模式不同（周末通常更高）

    将时间序列分解为三个可加成分：
    y_t = T_t + D_t + W_t + R_t
    其中:
    - T_t: 长期趋势（双边移动平均）
    - D_t: 日周期分量（以24小时为周期）
    - W_t: 周周期分量（以7天为周期）
    - R_t: 不可解释的残差

    预测时：趋势使用线性外推（加入衰减），
    日和周期分量使用正弦/余弦波模拟，合成最终预测。

适用场景：
    - 有多天/多周数据的视频
    - 需要区分日间和周末周期效应的场景
    - 数据量充足（≥10点）的预测

参考:
    Cleveland et al. (1990), "STL: A Seasonal-Trend Decomposition Procedure Based on Loess"
"""

import math
import numpy as np
from typing import Dict, Any, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class MultiSeasonalDecompositionAlgorithm(BaseAlgorithm):
    """多季节性分解 (Multi-Seasonal Decomposition)

    B 站视频播放量呈现多种周期性：
    - 日周期: 一天内不同时段播放量不同
    - 周周期: 工作日 vs 周末播放模式不同

    将时间序列分解为: 趋势 + 日周期 + 周周期 + 残差
    分别建模后再合成预测，能更准确地捕捉复合周期模式。

    参考: Cleveland et al. (1990), "STL: A Seasonal-Trend
          Decomposition Procedure Based on Loess"

    属性:
        name (str): 算法显示名称 "多季节分解"
        algorithm_id (str): 算法唯一标识 "multi_seasonal"
        description (str): 算法描述
        category (str): 算法分类 "时间序列"
        default_weight (float): 集成预测中的默认权重 1.2
    """

    name = "多季节分解"
    algorithm_id = "multi_seasonal"
    description = "分解为趋势+日周期+周周期，分别预测再合成"
    category = "时间序列"
    default_weight = 1.2

    def _decompose(
        self, views: np.ndarray, hours_per_point: float
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """STL-like分解: 趋势 + 日周期 + 周周期 + 残差

        将播放量序列分解为四个分量，使用双边移动平均提取趋势，
        周期平均提取日周期和周周期模式。

        参数:
            views (np.ndarray): 播放量序列
            hours_per_point (float): 每个数据点代表的小时数

        返回:
            Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
                (trend, daily_cycle, weekly_cycle, residual)
                四个分量数组，长度均等于输入序列长度
        """
        n = len(views)
        if n < 2:
            return views, np.zeros(n), np.zeros(n), np.zeros(n)

        # 周期长度（以数据点计）
        daily_period = max(1, int(24 / max(hours_per_point, 0.1)))  # 日周期点数
        weekly_period = daily_period * 7  # 周周期点数

        # 1. 趋势分量 (双边移动平均)
        # 窗口大小 = max(7, 日周期×2)，确保为奇数
        trend_window = min(n, max(7, daily_period * 2))
        if trend_window % 2 == 0:
            trend_window += 1

        trend = np.zeros(n)
        half_w = trend_window // 2
        for i in range(n):
            start = max(0, i - half_w)
            end = min(n, i + half_w + 1)
            trend[i] = np.mean(views[start:end])  # 双边移动平均

        detrended = views - trend  # 去趋势后的序列

        # 2. 日周期分量
        # 对每个"小时位置"（模 daily_period），取所有同位置去趋势值的平均
        daily_cycle = np.zeros(n)
        if daily_period >= 2 and n >= daily_period * 2:
            daily_pattern = np.zeros(daily_period)
            daily_counts = np.zeros(daily_period)
            for i in range(n):
                p = i % daily_period
                daily_pattern[p] += detrended[i]
                daily_counts[p] += 1
            daily_pattern = daily_pattern / np.maximum(daily_counts, 1)  # 平均
            # 去均值（使日周期总和为零）
            daily_pattern = daily_pattern - np.mean(daily_pattern)

            for i in range(n):
                daily_cycle[i] = daily_pattern[i % daily_period]

        residual_1 = detrended - daily_cycle  # 去日周期后的残差

        # 3. 周周期分量
        # 对每个周位置，取所有同位置去除趋势和日周期后值的平均
        weekly_cycle = np.zeros(n)
        if weekly_period >= 2 and n >= weekly_period:
            weekly_pattern = np.zeros(weekly_period)
            weekly_counts = np.zeros(weekly_period)
            for i in range(n):
                p = i % weekly_period
                weekly_pattern[p] += residual_1[i]
                weekly_counts[p] += 1
            weekly_pattern = weekly_pattern / np.maximum(weekly_counts, 1)
            weekly_pattern = weekly_pattern - np.mean(weekly_pattern)  # 去均值

            for i in range(n):
                weekly_cycle[i] = weekly_pattern[i % weekly_period]

        # 4. 残差 = 去趋势 - 日周期 - 周周期
        residual = detrended - daily_cycle - weekly_cycle

        return trend, daily_cycle, weekly_cycle, residual

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行多季节性分解预测

        参数:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 预测结果对象

        算法步骤:
            1. 提取按时间排序的播放量序列
            2. 分解为趋势+日周期+周周期+残差
            3. 对趋势做线性外推
            4. 评估日和周期的季节性强度
            5. 用正弦/余弦波模拟未来季节效应
            6. 趋势（含衰减）+ 季节效应 = 每日预测增长
            7. 累加直至达到目标
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        # 已达标
        if remaining <= 0:
            return self._make_result(0, 1.0, current_views, velocity, {"method": "multi_seasonal"}, threshold)

        # 数据不足
        if len(history) < 10 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return self._make_result(
                predicted_hours,
                0.3,
                current_views,
                velocity,
                {"method": "multi_seasonal", "notes": "insufficient_data"},
                threshold,
            )

        views_data = self._extract_views(history)
        if views_data is None:
            return self._make_result(
                remaining / velocity,
                0.3,
                current_views,
                velocity,
                {"method": "multi_seasonal_fallback"},
                threshold,
            )

        views_arr, hours_per_point = views_data
        try:
            return self._predict_impl(
                views_arr, hours_per_point, current_views, velocity, remaining, threshold, video_data
            )
        except Exception as e:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return self._make_result(
                predicted_hours,
                0.0,
                current_views,
                velocity,
                {"error": str(e)},
                threshold,
            )

    def _extract_views(self, history):
        """从历史记录中提取并排序播放量序列，计算数据点间隔

        参数:
            history: 历史数据列表

        返回:
            Tuple[np.ndarray, float]: (播放量数组, 每点小时间隔) 或 None
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
        if len(views_vals) < 10:
            return None
        order = np.argsort(timestamps)
        views_arr = np.array(views_vals, dtype=float)[order]
        n = len(views_arr)
        # 估计数据点间的小时数（总跨度 / 点数间隔）
        if n >= 2:
            hours_per_point = (timestamps[order[-1]] - timestamps[order[0]]) / (3600.0 * max(n - 1, 1))
        else:
            hours_per_point = 1.0
        # 限制在 0.1~24 小时之间
        hours_per_point = max(0.1, min(24.0, hours_per_point))
        return views_arr, hours_per_point

    def _predict_impl(self, views_arr, hours_per_point, current_views, velocity, remaining, threshold, video_data):
        """执行多季节性分解核心预测

        参数:
            views_arr: 播放量数组
            hours_per_point: 每点小时间隔
            current_views: 当前播放量
            velocity: 当前速度
            remaining: 剩余播放量
            threshold: 目标阈值
            video_data: 视频数据字典

        返回:
            PredictionResult: 预测结果对象
        """
        n = len(views_arr)

        # 获取视频质量得分和互动率
        quality = self.get_quality_score(video_data)
        engagement = self.get_engagement_rate(video_data)

        # ── 分解 ─────────────────────────────────
        trend, daily_cycle, weekly_cycle, residual = self._decompose(views_arr, hours_per_point)

        # ── 趋势预测 (线性外推) ──────────────────
        if n >= 3:
            t = np.arange(n, dtype=float)
            # 用 polyfit 做一阶线性回归得到趋势的斜率和截距
            trend_slope, trend_intercept = np.polyfit(t, trend, 1)
        else:
            trend_slope = 0
            trend[-1] if len(trend) > 0 else current_views

        # ── 季节性强度评估 ───────────────────────
        # 日周期强度 = 日周期标准差 / 总标准差 × 2（归一化到0~1）
        daily_strength = 0.0
        if len(daily_cycle) > 0 and np.std(daily_cycle) > 0:
            daily_strength = min(1.0, np.std(daily_cycle) / max(np.std(views_arr), 1) * 2)

        # 周周期强度
        weekly_strength = 0.0
        if len(weekly_cycle) > 0 and np.std(weekly_cycle) > 0:
            weekly_strength = min(1.0, np.std(weekly_cycle) / max(np.std(views_arr), 1) * 2)

        # ── 综合预测 ─────────────────────────────
        # 趋势日增长量
        trend_daily_growth = trend_slope * 24 / max(hours_per_point, 0.1)
        if trend_daily_growth <= 0:
            trend_daily_growth = velocity * 24

        forecast_days = min(365, max(14, int((threshold - current_views) / max(trend_daily_growth, 1)) + 7))

        # 日周期长度（数据点）
        daily_period = max(1, int(24 / max(hours_per_point, 0.1)))
        daily_period * 7  # 周周期长度 = 日周期 × 7

        pred_views = float(current_views)
        target_day = None

        # 逐日迭代预测
        for day in range(1, forecast_days + 1):
            # 趋势成分（含指数衰减，45天半衰期）
            trend_contrib = trend_daily_growth * math.exp(-day / 45.0)

            # 日周期：用正弦波模拟（周期=1天）
            point_in_day = (day * 24) % 24
            int(point_in_day / max(hours_per_point, 0.1)) % max(daily_period, 1)
            daily_contrib = daily_cycle[-1] * daily_strength * math.sin(2 * math.pi * day)

            # 周周期：用余弦波模拟（周期=7天）
            weekly_contrib = weekly_cycle[-1] * weekly_strength * math.cos(2 * math.pi * day / 7)

            total_growth = trend_contrib + daily_contrib + weekly_contrib
            pred_views += max(0, total_growth)

            if pred_views >= threshold:
                target_day = day
                break

        if target_day is not None and target_day <= 365:
            predicted_hours = target_day * 24
            # 综合置信度 = 数据质量 + 季节强度 + 视频质量 + 互动率
            data_qual = min(1.0, n / 25)  # 25点 = 满分
            seasonal_strength = max(daily_strength, weekly_strength)
            conf = min(0.9, 0.3 + 0.2 * data_qual + 0.2 * seasonal_strength + 0.15 * quality + 0.05 * engagement)
        else:
            # 预测期内无法达标，回退速度估计
            predicted_hours = remaining / velocity
            conf = 0.35

        return self._make_result(
            predicted_hours,
            conf,
            current_views,
            velocity,
            {
                "method": "multi_seasonal",
                "daily_strength": round(float(daily_strength), 3),
                "weekly_strength": round(float(weekly_strength), 3),
                "trend_daily_growth": round(float(trend_daily_growth), 2),
                "residual_std": round(float(np.std(residual)), 2),
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
        metadata.setdefault("method", "multi_seasonal")
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
