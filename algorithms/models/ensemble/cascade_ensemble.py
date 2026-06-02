"""
级联集成 (Cascade Ensemble) 预测模块
====================================

本模块实现了级联集成预测算法，多个预测器按顺序级联，
每个预测器的输出作为额外特征输入下一个预测器，逐级提升预测精度。

核心原理：
    Level 1 (线性趋势): 用首末点计算线性斜率，提供基础增长方向
    Level 2 (指数平滑): 对第一级输出用指数平滑修正，平滑短期波动
    Level 3 (季节性修正): 融入周季节性模式 + 前两级输出，给出最终预测

参考: Linardatos et al. (2024), "Regressor cascading for
      time series forecasting", Intelligent Decision Technologies

与传统并行集成的区别：
    - 并行：各预测器独立运行然后投票/平均
    - 级联：预测器按序执行，每组输出供下一级使用（类似残差修正链）

适用场景：数据量 ≥ 5 点的视频，能捕捉多时间尺度的趋势变化。
"""

import math
import numpy as np
from typing import Dict, Any, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class CascadeEnsembleAlgorithm(BaseAlgorithm):
    """
    级联集成 (Cascade Generalization / Regressor Cascading)

    与传统并行集成不同，级联集成将预测器按顺序排列，
    每个预测器的输出作为额外特征输入下一个预测器。
    能捕获不同模型间的互补信息，通常优于简单的投票/平均集成。

    三级级联结构：
        Level 1: 线性趋势 → 捕获长期方向
        Level 2: 指数平滑 + Level 1 输出 → 捕获近期波动
        Level 3: 季节性 + Level 1&2 输出 → 最终融合预测

    类属性：
        name (str): 算法名称 "Cascade级联集成"
        algorithm_id (str): 算法唯一标识 "cascade_ensemble"
        description (str): 算法简述
        category (str): 所属类别 "集成学习"
        default_weight (float): 默认集成权重 1.25（中高）
        cascade_levels (int): 级联层数，默认 3
    """

    name = "Cascade级联集成"
    algorithm_id = "cascade_ensemble"
    description = "预测器逐级级联，每个输出作为下一级输入"
    category = "集成学习"
    default_weight = 1.25

    def __init__(self):
        """初始化级联集成算法实例，设置 3 级级联。"""
        super().__init__()
        self.cascade_levels = 3  # 级联层数

    def _level1_prediction(self, views: np.ndarray) -> float:
        """
        第一级预测：简单线性趋势。

        使用首尾数据点计算斜率作为基础日增长量，
        提供最基础的长期趋势信号。

        Args:
            views (np.ndarray): 播放量序列

        Returns:
            float: 每日播放量增长估计（斜率）
        """
        n = len(views)
        if n < 2:
            return 0.0
        np.arange(n)  # 生成 x 轴索引（后续可能用于扩展）
        slope = (views[-1] - views[0]) / max(n - 1, 1)  # 首尾斜率
        return slope

    def _level2_prediction(self, views: np.ndarray, l1_output: float) -> Tuple[float, float]:
        """
        第二级预测：指数平滑 + 第一级输出修正。

        使用 α=0.3 的简单指数平滑捕获近期趋势，
        然后将平滑结果与 Level 1 的线性趋势按 6:4 加权融合。

        Args:
            views (np.ndarray): 播放量序列
            l1_output (float): 第一级输出的日增长量

        Returns:
            Tuple[float, float]:
                - adjusted (float): 修正后的日增长量
                - smoothed (float): 指数平滑的最终值（供第三级使用）
        """
        n = len(views)
        if n < 2:
            return 0.0, 0.0

        # 简单指数平滑：α=0.3 偏向近期但不过度敏感
        alpha = 0.3
        smoothed = views[0]
        for i in range(1, n):
            smoothed = alpha * views[i] + (1 - alpha) * smoothed  # 递推平滑

        growth = smoothed - views[-1]  # 平滑值与最新实际值的差距

        # 用第一级线性趋势修正指数平滑结果：60% 平滑 + 40% 线性
        adjusted = growth * 0.6 + l1_output * 0.4
        return adjusted, smoothed

    def _level3_prediction(self, views: np.ndarray, l2_output: float, l2_smoothed: float) -> float:
        """
        第三级预测：考虑周季节性 + 前两级输出融合。

        如果数据覆盖超过一周（≥ 7 点），计算周季节性效应
        （最近几天与 7 天前同一天的差额），然后将三级信息加权融合：
            - L2 输出 * 0.5（指数平滑趋势）
            - 季节性效应 * 0.3（周周期模式）
            - 平滑残差 * 0.2（原始偏差）

        Args:
            views (np.ndarray): 播放量序列
            l2_output (float): 第二级输出
            l2_smoothed (float): 第二级指数平滑终值

        Returns:
            float: 最终融合的日增长预测
        """
        n = len(views)
        if n < 7:
            return l2_output  # 数据不足以检测季节性

        # 周季节性：计算最近 7 天内每天的同比变化
        weekly_cycle = []
        for i in range(1, 8):
            if n >= i + 7:
                cycle_growth = (views[-i] - views[-i - 7]) / 7.0  # 7 天内的日均增长
                weekly_cycle.append(cycle_growth)

        seasonal_effect = np.mean(weekly_cycle) if weekly_cycle else 0  # 平均周季节性

        # 最终: 组合三级信息
        final = l2_output * 0.5 + seasonal_effect * 0.3 + (l2_smoothed - views[-1]) * 0.2
        return final

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行三级级联集成预测。

        预测流程：
            1. Level 1: 线性趋势 → l1_daily
            2. Level 2: 指数平滑 + l1_daily → l2_daily
            3. Level 3: 季节性 + l2_daily → l3_daily (最终日增长量)
            4. 用 l3_daily 逐日模拟播放量增长曲线
            5. 三级预测一致性作为置信度参考

        Args:
            video_data (Dict): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            # 已达标
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=0,
                confidence=1.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "cascade"},
                timestamp=datetime.now(),
            )

        # 数据不足 → 回退到匀速
        if len(history) < 5 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.3,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "cascade", "notes": "insufficient_data"},
                timestamp=datetime.now(),
            )

        # 提取并排序时间序列
        timestamps = []
        views_vals = []
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

        if len(views_vals) < 5:
            predicted_hours = remaining / velocity
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.3,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "cascade_fallback"},
                timestamp=datetime.now(),
            )

        try:
            order = np.argsort(timestamps)
            views_arr = np.array(views_vals, dtype=float)[order]
            n = len(views_arr)

            quality = self.get_quality_score(video_data)
            engagement = self.get_engagement_rate(video_data)

            # ── 级联预测流程 ──────────────────────────
            # Level 1: 线性趋势
            l1_slope = self._level1_prediction(views_arr)
            l1_daily = l1_slope * 24  # 转换为日增长（从每步增长转换为日增长）

            # Level 2: 指数平滑 + L1 修正
            l2_daily, l2_smoothed = self._level2_prediction(views_arr, l1_daily)

            # Level 3: 季节性 + L2 修正
            l3_daily = self._level3_prediction(views_arr, l2_daily, l2_smoothed)

            if l3_daily <= 0:
                l3_daily = l1_daily if l1_daily > 0 else velocity * 24  # 负增长回退

            daily_growth = l3_daily

            # ── 评估级间一致性作为置信度权重 ──────────
            predictions = [l1_daily, l2_daily, l3_daily]
            pred_mean = np.mean(predictions)
            pred_std = np.std(predictions)
            consistency = max(0.0, 1.0 - pred_std / max(abs(pred_mean), 1))  # 三级一致性

            # ── 逐日模拟预测 ─────────────────────────
            forecast_days = min(365, max(10, int((threshold - current_views) / max(daily_growth, 1)) + 5))

            pred_views = float(current_views)
            target_day = None
            for day in range(1, forecast_days + 1):
                # 级联预测：用各层级的融合结果，随时间衰减
                decay = math.exp(-day / 30.0)  # 30 天衰减常数
                growth = daily_growth * (0.6 + 0.4 * (1.0 - decay))
                pred_views += max(0, growth)
                if pred_views >= threshold:
                    target_day = day
                    break

            if target_day is not None and target_day <= 365:
                predicted_hours = target_day * 24
                data_qual = min(1.0, n / 15)  # 数据质量因子
                conf = min(0.9, 0.35 + 0.2 * data_qual + 0.2 * consistency + 0.1 * quality + 0.05 * engagement)
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
                    "method": "cascade",
                    "level1_l1": round(float(l1_daily), 2),
                    "level2_exp_smooth": round(float(l2_daily), 2),
                    "level3_cascade": round(float(l3_daily), 2),
                    "consistency": round(float(consistency), 3),
                    "data_points": n,
                },
                timestamp=datetime.now(),
            )
        except Exception as e:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"error": str(e)},
                timestamp=datetime.now(),
            )
