"""
Holt-Winters指数平滑预测算法 (Holt-Winters Exponential Smoothing)

经典的三重指数平滑方法（Holt-Winters Triple Exponential Smoothing），
同时考虑水平（Level）、趋势（Trend）和季节性（Seasonality）三个成分。

核心原理：
    将时间序列分解为三个可加成分：
    - 水平成分 (Level): 序列的当前基线水平
    - 趋势成分 (Trend): 序列的长期增长/下降方向
    - 季节成分 (Seasonality): 周期性波动模式（默认为周周期=7）

更新公式:
    Level_t   = α × (Y_t - Season_{t-m}) + (1-α) × (Level_{t-1} + Trend_{t-1})
    Trend_t   = β × (Level_t - Level_{t-1}) + (1-β) × Trend_{t-1}
    Season_t  = γ × (Y_t - Level_t) + (1-γ) × Season_{t-m}

参数说明:
    - α (alpha): 水平平滑系数，控制对新观测值的响应速度，默认 0.3
    - β (beta):  趋势平滑系数，控制趋势变化的响应速度，默认 0.1
    - γ (gamma): 季节平滑系数，控制季节性变化的响应速度，默认 0.1
    - m (season_length): 季节周期长度，默认 7（周周期）

适用场景:
    - 有明显周期性波动的视频（如周末 vs 工作日播放差异）
    - 数据量充足（≥14个数据点）的长周期监控
    - B站视频播放的周周期性特征分析

参考:
    Winters, P. R. (1960) "Forecasting Sales by Exponentially Weighted Moving Averages"
    Holt, C. C. (1957) "Forecasting seasonals and trends by exponentially weighted moving averages"
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import logging

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)


class HoltWintersAlgorithm(BaseAlgorithm):
    """
    Holt-Winters Triple Exponential Smoothing (三重指数平滑)

    考虑三个成分:
    - 水平 (Level): 去季节性后的序列基线
    - 趋势 (Trend): 序列的长期变化方向
    - 季节性 (Seasonality): 周期性的重复波动模式

    更新迭代:
        1. 更新水平: 当前值减去季节分量，与上一期水平+趋势做加权平均
        2. 更新趋势: 本期水平变化与上期趋势做加权平均
        3. 更新季节: 当前值减去水平，与上一周期同位置季节分量做加权平均

    属性:
        name (str): 算法显示名称 "Holt-Winters指数平滑"
        description (str): 算法描述
        category (str): 算法分类 "时间序列"
        alpha (float): 水平平滑参数，默认 0.3
        beta (float): 趋势平滑参数，默认 0.1
        gamma (float): 季节性平滑参数，默认 0.1
        season_length (int): 季节周期长度，默认 7（周周期）
    """

    name = "Holt-Winters指数平滑"
    description = "经典时间序列预测，考虑趋势和季节性"
    category = "时间序列"
    algorithm_id = "holt_winters"

    def __init__(self):
        """初始化Holt-Winters算法，设置平滑参数"""
        super().__init__()
        self.alpha = 0.3  # 水平平滑参数：新观测值在水平中的权重
        self.beta = 0.1  # 趋势平滑参数：新趋势变化在趋势中的权重
        self.gamma = 0.1  # 季节性平滑参数：新季节性在季节分量中的权重
        self.season_length = 7  # 假设周季节性（B站视频常见的周周期波动）

    def _predict_inner(
        self, current_views: int, target_views: int, history_data: List[Dict[str, Any]], video_info: Dict[str, Any]
    ) -> Optional[Tuple[int, float]]:
        """
        预测到达目标播放量所需时间

        参数:
            current_views (int): 当前播放量
            target_views (int): 目标播放量
            history_data (List[Dict]): 历史数据列表
            video_info (Dict): 视频信息字典

        返回:
            Optional[Tuple[int, float]]:
                - int: 预计所需秒数
                - float: 预测置信度 (0.0 ~ 1.0)
                - None: 预测失败

        算法步骤:
            1. 提取历史播放量，计算每期增长差分
            2. 使用 _fit() 拟合Holt-Winters模型
            3. 迭代预测未来每天的增长量（趋势 + 季节效应）
            4. 累加增长直到达到剩余播放量
            5. 返回所需天数和置信度
        """
        if not history_data or len(history_data) < 14:
            return None

        try:
            views = [d.get("view_count", d.get("view", 0)) for d in history_data]

            # 计算增长差分（每期之间的变化量）
            diffs = [views[i] - views[i - 1] for i in range(1, len(views))]

            if len(diffs) < 7:
                return None

            # 应用Holt-Winters拟合
            level, trend, seasons = self._fit(diffs)

            if current_views >= target_views:
                return (0, 1.0)

            remaining = target_views - current_views

            # 迭代预测未来增长量
            predicted_total = 0
            days = 0
            max_days = 3650  # 最大预测天数（约10年），防止无限循环

            while predicted_total < remaining and days < max_days:
                days += 1
                # 预测第days天的增长量：水平 + 趋势贡献 + 季节效应
                season_idx = (len(diffs) + days - 1) % self.season_length
                forecast = level + days * trend + seasons[season_idx]
                forecast = max(0, forecast)  # 增长不能为负
                predicted_total += forecast

            if days >= max_days:
                return None  # 预测天数超出上限，无法达标

            seconds_needed = days * 86400  # 天数转为秒数
            confidence = self._calculate_confidence(diffs, level, trend)

            return (seconds_needed, confidence)

        except Exception as e:
            logger.warning(f"Holt-Winters预测失败: {e}")
            return None

    def _fit(self, series: List[float]) -> Tuple[float, float, List[float]]:
        """
        拟合Holt-Winters模型参数

        参数:
            series (List[float]): 时间序列（播放量差分）

        返回:
            Tuple[float, float, List[float]]:
                - float: 当前水平值 (Level)
                - float: 当前趋势值 (Trend)
                - List[float]: 季节性因子列表（长度为 season_length）

        初始化方法:
            - 水平: 第一个完整周期的平均值
            - 趋势: 第二周期平均与第一周期平均的差值除以周期长度
            - 季节性: 每个周期位置的值减去水平的偏差
        """
        n = len(series)

        # 初始化水平（第一周期的平均值）
        level = np.mean(series[: self.season_length])

        # 初始化趋势（第二周期与第一周期的均值差，除以周期长度）
        trend = (
            np.mean(series[self.season_length : 2 * self.season_length]) - np.mean(series[: self.season_length])
        ) / self.season_length

        # 初始化季节性因子（每个周期位置的值与水平的偏差）
        seasons = []
        for i in range(self.season_length):
            season_values = [series[j] for j in range(i, n, self.season_length)]
            seasons.append(np.mean(season_values) - level)

        # 迭代更新三个成分
        for t in range(n):
            value = series[t]
            season_idx = t % self.season_length

            # 保存旧水平用于计算趋势变化
            old_level = level

            # 更新水平: Level_t = α(Y_t - Season_t) + (1-α)(Level_{t-1} + Trend_{t-1})
            level = self.alpha * (value - seasons[season_idx]) + (1 - self.alpha) * (level + trend)

            # 更新趋势: Trend_t = β(Level_t - Level_{t-1}) + (1-β)Trend_{t-1}
            trend = self.beta * (level - old_level) + (1 - self.beta) * trend

            # 更新季节性: Season_t = γ(Y_t - Level_t) + (1-γ)Season_{t-m}
            seasons[season_idx] = self.gamma * (value - level) + (1 - self.gamma) * seasons[season_idx]

        return level, trend, seasons

    def _calculate_confidence(self, diffs: List[float], level: float, trend: float) -> float:
        """计算预测置信度

        参数:
            diffs (List[float]): 增长差分序列
            level (float): 当前水平值
            trend (float): 当前趋势值

        返回:
            float: 置信度 (0.0 ~ 0.95)

        置信度计算:
            - 基础置信度随数据量增加（更多数据 → 更高置信度）
            - 正趋势加分（趋势向上 = 预测更可靠）
            - 趋势相对均值越大，稳定性越高
        """
        n = len(diffs)

        # 基础置信度：数据量越多越有信心（0.4 + 每点0.02，上限0.9）
        base_conf = min(0.9, 0.4 + n * 0.02)

        # 趋势稳定性：正趋势增加置信度
        if trend > 0:
            # 趋势稳定性 = 趋势相对于平均增长的比例（≤1.0）
            trend_stability = min(1.0, trend / (np.mean(diffs) + 1))
            # 70%基础置信度 + 30%趋势稳定性
            base_conf = 0.7 * base_conf + 0.3 * trend_stability

        return min(0.95, base_conf)

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """统一预测接口：从 video_data 提取参数, 委托 _predict_inner, 包装为 PredictionResult。"""
        current_views = video_data.get("view_count", 0)
        history_data = self._normalize_history(video_data.get("history_data", []))
        return self._to_prediction_result(
            self._predict_inner(current_views, threshold, history_data, video_data),
            current_views, video_data, threshold,
            method="holt_winters", invalid_hours=float("inf"), invalid_velocity=0,
        )
