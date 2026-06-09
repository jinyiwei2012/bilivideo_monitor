"""
Theil-Sen 鲁棒回归 — Theil-Sen Robust Regression
==================================================

基于中位数的非参数回归方法，对异常值高度鲁棒。

核心原理：
  1. Theil-Sen 估计量：回归斜率为所有数据点对之间斜率的中位数
     斜率 = median{(y_j - y_i) / (x_j - x_i) | i < j}
     截距 = median{y_i - slope × x_i}
  2. 对异常值的"破坏点" (breakdown point) 高达 29.3%
     即需要超过 29.3% 的数据为异常值才能任意改变估计结果
     而 OLS 的破坏点仅为 0%（一个异常值就能严重偏移）
  3. 当数据点对过多时（> 2000），随机采样降低计算复杂度
  4. 分段评估趋势一致性：将序列分为多段，分别计算各段斜率，
     通过段间变异系数衡量趋势稳定性

参考: Theil (1950), Sen (1968)

适用场景：历史数据 >= 4 条，存在突发播放量高峰（异常值）
"""

import math
import random
import numpy as np
from typing import Dict, Any, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class TheilSenRegressionAlgorithm(BaseAlgorithm):
    """
    Theil-Sen 鲁棒回归预测算法

    计算所有数据点对之间斜率的中位数作为回归斜率，
    对异常值的容忍度高达 29.3%，远优于普通最小二乘。

    对于 B 站播放量数据中的突发高峰（异常值）有很强的鲁棒性，
    能更准确地估计真实趋势。

    属性:
        max_subpairs (int): 最大计算点对数，超过则随机采样，默认 2000
        default_weight (float): 默认集成权重 1.15
    """

    name = "Theil-Sen回归"
    algorithm_id = "theil_sen"
    description = "基于中位数斜率的非参数鲁棒回归"
    category = "统计模型"
    default_weight = 1.15

    def __init__(self):
        """初始化 Theil-Sen 回归模型"""
        super().__init__()
        self.max_subpairs = 2000  # 最大计算点对数（超过此数使用随机采样）

    def _theil_sen_slope(self, x: np.ndarray, y: np.ndarray) -> Tuple[float, float]:
        """
        计算 Theil-Sen 斜率和截距

        斜率估计:
          对于所有 i < j 且 x_j ≠ x_i 的点对：
          计算 (y_j - y_i) / (x_j - x_i)
          取所有斜率的中位数

        截距估计:
          intercept = median{y_i - slope × x_i}

        当点对总数 > max_subpairs 时，随机采样降低计算复杂度。

        参数:
            x (np.ndarray): 自变量（时间索引）
            y (np.ndarray): 因变量（播放量）

        返回:
            Tuple[float, float]: (斜率, 截距)
        """
        n = len(x)
        if n < 2:
            return 0.0, 0.0

        slopes = []  # 斜率列表
        n_pairs = n * (n - 1) // 2  # 总点对数

        if n_pairs <= self.max_subpairs:
            # 点对总数可控，计算所有点对
            for i in range(n):
                for j in range(i + 1, n):
                    if abs(x[j] - x[i]) > 1e-10:  # 跳过 x 相同的点对（除零）
                        slopes.append((y[j] - y[i]) / (x[j] - x[i]))
        else:
            # 点对过多，随机采样减少计算量
            indices = list(range(n))
            sampled = 0
            while sampled < self.max_subpairs:
                i, j = random.sample(indices, 2)  # 随机选两点
                if i > j:
                    i, j = j, i  # 确保 i < j
                if i != j and abs(x[j] - x[i]) > 1e-10:
                    slopes.append((y[j] - y[i]) / (x[j] - x[i]))
                    sampled += 1

        if not slopes:
            return 0.0, float(np.median(y))  # 无法计算斜率，用中位数代替

        # 斜率 = 所有点对斜率的中位数
        slope = float(np.median(slopes))
        # 截距 = 所有 {y_i - slope × x_i} 的中位数
        intercept = float(np.median(y - slope * x))

        return slope, intercept

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行 Theil-Sen 鲁棒回归预测

        流程:
          1. 检查数据是否充足（>= 4 条历史记录）
          2. 提取并排序播放量序列
          3. 用 Theil-Sen 估计趋势斜率
          4. 分段评估趋势一致性
          5. 模拟未来增长路径（带衰减）

        参数:
            video_data (Dict): 视频数据
            threshold (int): 目标播放量阈值

        返回:
            PredictionResult: 包含趋势一致性等元数据的预测结果
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        # 已达阈值
        if remaining <= 0:
            return self._make_result(0, 1.0, current_views, velocity, {"method": "theil_sen"}, threshold)

        # 数据不足
        if len(history) < 4 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return self._make_result(
                predicted_hours,
                0.3,
                current_views,
                velocity,
                {"method": "theil_sen", "notes": "insufficient_data"},
                threshold,
            )

        # 提取并排序播放量序列
        views_sorted = self._extract_views(history)
        if views_sorted is None or len(views_sorted) < 4:
            return self._make_result(
                remaining / velocity,
                0.3,
                current_views,
                velocity,
                {"method": "theil_sen_fallback"},
                threshold,
            )

        try:
            return self._predict_impl(views_sorted, current_views, velocity, remaining, threshold)
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
        """
        从历史记录中提取并排序播放量序列

        处理多种时间戳格式，按时间升序排列。

        参数:
            history (List[Dict]): 历史数据列表

        返回:
            np.ndarray 或 None: 排序后的播放量数组
        """
        timestamps, views_vals = [], []
        for h in history:
            ts = h.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()  # datetime 对象
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(str(ts)[:19].replace("T", " ")).timestamp()  # ISO 字符串
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))
        if len(views_vals) < 4:
            return None
        # 按时间升序排列
        order = np.argsort(timestamps)
        return np.array(views_vals, dtype=float)[order]

    def _predict_impl(self, views_arr, current_views, velocity, remaining, threshold):
        """
        执行 Theil-Sen 核心预测

        流程:
          1. 用 Theil-Sen 估计整体趋势斜率
          2. 分段评估趋势一致性（段间斜率变异系数）
          3. 若趋势斜率为负，回退到中位数日增量
          4. 将每数据点斜率转换为日增量（×24）
          5. 模拟未来增长路径（带指数衰减）

        参数:
            views_arr (np.ndarray): 排序后的播放量数组
            current_views (int): 当前播放量
            velocity (float): 当前速度
            remaining (int): 剩余播放量
            threshold (int): 目标阈值

        返回:
            PredictionResult
        """
        n = len(views_arr)
        x = np.arange(n, dtype=float)  # 时间轴：0, 1, 2, ...

        # ── Theil-Sen 斜率估计 ────────────────────
        slope, intercept = self._theil_sen_slope(x, views_arr)

        if slope <= 0:
            # 趋势斜率为负或零 → 用中位数日增量作为备选
            daily_increments = np.diff(views_arr)  # 逐日差分
            slope = float(np.median(daily_increments))  # 中位数增量
            float(views_arr[0])  # 初始值（为后续预留，未使用局部变量）

        # ── 基于时间序列分解评估趋势稳定性 ────────
        # 将序列分为 n_segments 段，计算各段 Theil-Sen 斜率，
        # 通过段间变异系数衡量趋势一致性
        n_segments = min(5, n // 3)  # 最多 5 段
        segment_slopes = []
        if n_segments >= 2:
            seg_size = n // n_segments
            for s in range(n_segments):
                start = s * seg_size
                end = start + seg_size if s < n_segments - 1 else n  # 最后一段取剩余
                if end - start >= 2:
                    xs = np.arange(end - start)
                    ys = views_arr[start:end]
                    s_slope, _ = self._theil_sen_slope(xs, ys)  # 该段斜率
                    segment_slopes.append(s_slope)

        # 趋势一致性：段间斜率越接近 → 一致性越高
        trend_consistency = 1.0
        if len(segment_slopes) >= 2:
            # 变异系数 CV = std / |mean|
            slope_cv = np.std(segment_slopes) / max(abs(np.mean(segment_slopes)), 1)
            # CV 越小 → 一致性越高
            trend_consistency = max(0.0, 1.0 - min(slope_cv, 3.0) * 0.3)

        # ── 预测 ─────────────────────────────────
        # 日增长量 = Theil-Sen slope（每数据点增量）× 24（假设每小时一个数据点）
        daily_growth = slope * 24  # 假设每小时一个数据点
        if daily_growth <= 0:
            daily_growth = velocity * 24  # 回退到当前速度的日增量

        # ── 模拟未来增长路径 ──────────────────
        forecast_days = min(365, max(10, int((threshold - current_views) / max(daily_growth, 1)) + 5))

        pred_views = float(current_views)
        target_day = None
        for day in range(1, forecast_days + 1):
            # 指数衰减因子（35 天衰减常数，比泊松/分位数的 28-30 天更长）
            decay = math.exp(-day / 35.0)
            # 衰减 0.4 + 0.6×(1-decay)：衰减后依然有一定基础增长
            pred_views += daily_growth * (0.4 + 0.6 * (1.0 - decay))
            if pred_views >= threshold:
                target_day = day
                break

        if target_day is not None and target_day <= 365:
            predicted_hours = target_day * 24
            # 置信度综合数据质量和趋势一致性
            data_qual = min(1.0, n / 15)
            conf = min(0.9, 0.35 + 0.25 * data_qual + 0.25 * trend_consistency)
        else:
            predicted_hours = remaining / velocity
            conf = 0.35

        return self._make_result(
            predicted_hours,
            conf,
            current_views,
            velocity,
            {
                "method": "theil_sen",
                "theil_slope": round(float(slope), 2),  # Theil-Sen 趋势斜率
                "daily_growth": round(float(daily_growth), 2),  # 日增长量
                "trend_consistency": round(float(trend_consistency), 3),  # 趋势一致性
                "segment_slopes": len(segment_slopes),  # 分段数
                "data_points": n,
            },
            threshold,
        )

    def _make_result(self, predicted_hours, confidence, current_views, velocity, metadata, threshold):
        """
        构造 PredictionResult

        参数:
            predicted_hours (float): 预测小时数
            confidence (float): 置信度
            current_views (int): 当前播放量
            velocity (float): 当前速度
            metadata (Dict): 元数据
            threshold (int): 目标阈值

        返回:
            PredictionResult
        """
        metadata.setdefault("method", "theil_sen")
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
