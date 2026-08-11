"""
季节性分解预测算法 (Seasonal Decomposition Prediction Algorithm)

使用简化版STL（Seasonal-Trend decomposition using Loess-like approach）
将播放量增长序列分解为趋势、季节性和残差三个成分，
分别分析后再合成预测。

核心原理：
    时间序列 y_t 可以分解为：
    y_t = T_t + S_t + R_t
    其中:
    - T_t (Trend): 长期趋势，通过移动平均提取
    - S_t (Seasonal): 周期性波动，通过周期平均计算
    - R_t (Residual): 不可解释的随机噪声

    预测时：趋势使用线性外推，季节性使用周期循环，
    两者相加得到未来预测值。

适用场景：
    - 有明显周期性的播放量数据
    - 需要区分长期趋势和短期周期波动的分析
    - 数据量充足（≥14个点）的稳定监控

参考:
    Cleveland et al. (1990) "STL: A Seasonal-Trend Decomposition Procedure Based on Loess"
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
import logging

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)


class SeasonalDecompositionAlgorithm(BaseAlgorithm):
    """
    季节性分解预测 (Seasonal Decomposition for View Prediction)

    将播放量增长分解为:
    - 趋势成分 (Trend): 长期变化方向
    - 季节性成分 (Seasonal): 周期性波动模式
    - 残差成分 (Residual): 不可解释的随机噪声

    分解方法（简化版STL）:
        1. 移动平均 → 提取趋势
        2. 周期平均 → 提取季节性
        3. 原始序列 - 趋势 - 季节性 → 残差

    属性:
        name (str): 算法显示名称 "季节性分解"
        description (str): 算法描述
        category (str): 算法分类 "时间序列"
        period (int): 季节周期长度，默认 7（周周期）
        trend (list or None): 拟合后的趋势分量
        seasonal (list or None): 拟合后的季节分量
        residual (list or None): 拟合后的残差分量
    """

    name = "季节性分解"
    description = "分解趋势、季节性和残差成分"
    category = "时间序列"

    def __init__(self):
        """初始化季节性分解算法，设置周期为7天（周周期）"""
        super().__init__()
        self.period = 7  # 周季节性（B站播放量常见的周周期波动）
        self.trend = None  # 趋势分量
        self.seasonal = None  # 季节分量
        self.residual = None  # 残差分量

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """统一预测接口：从 video_data 提取参数, 委托 _predict_inner, 包装为 PredictionResult。"""
        current_views = video_data.get("view_count", 0)
        history_data = self._normalize_history(video_data.get("history_data", []))
        result = self._predict_inner(current_views, threshold, history_data, video_data)
        return self._to_prediction_result(result, current_views, video_data, threshold)

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

        算法步骤:
            1. 提取历史播放量，计算增长差分
            2. 调用 _decompose() 进行STL分解
            3. 对未来每天：趋势外推 + 季节循环 = 预测增长
            4. 累加增长直到达到目标，返回天数和置信度
        """
        if not history_data or len(history_data) < 14:
            return None

        try:
            views = [d["view"] for d in history_data]

            # 计算增长量（每期之间的变化）
            growth = [views[i] - views[i - 1] for i in range(1, len(views))]

            if len(growth) < 10:
                return None

            # 分解时间序列为趋势+季节+残差
            self._decompose(growth)

            if current_views >= target_views:
                return (0, 1.0)

            # 预测未来每天的增长量，累加到达到目标
            remaining = target_views - current_views
            predicted_total = 0
            days = 0
            max_days = 3650  # 最大预测天数

            while predicted_total < remaining and days < max_days:
                days += 1

                # 趋势预测 (使用趋势最后一个值做线性外推)
                trend_pred = self.trend[-1] if self.trend is not None else np.mean(growth[-5:])

                # 季节性预测（循环使用周期模式）
                season_idx = (len(growth) + days - 1) % self.period
                seasonal_pred = self.seasonal[season_idx] if self.seasonal is not None else 0

                # 组合预测 = 趋势 + 季节性
                forecast = trend_pred + seasonal_pred
                forecast = max(0, forecast)  # 增长不能为负

                predicted_total += forecast

            if days >= max_days:
                return None  # 超出最大预测天数，无法达标

            seconds_needed = days * 86400  # 天数转为秒数
            confidence = self._calculate_confidence(growth)

            return (seconds_needed, confidence)

        except Exception as e:
            logger.warning(f"季节性分解预测失败: {e}")
            return None

    def _decompose(self, series: List[float]):
        """
        执行季节性分解 (简化版STL)

        使用移动平均提取趋势，然后用周期平均计算季节性。

        参数:
            series (List[float]): 时间序列数据

        步骤:
            1. 中心化移动平均 → 提取趋势
            2. 去趋势 = 原始 - 趋势
            3. 周期平均 → 提取季节性模式
            4. 中心化季节性（去均值）
            5. 残差 = 原始 - 趋势 - 季节性
        """
        n = len(series)

        # 提取趋势 (中心化移动平均)
        # 窗口大小 = period 或 period+1（确保奇数）
        trend_window = self.period if self.period % 2 == 1 else self.period + 1
        half_window = trend_window // 2

        self.trend = []
        for i in range(n):
            if i < half_window or i >= n - half_window:
                # 边界处无法做完整窗口平均，使用原始值
                self.trend.append(series[i])
            else:
                # 中心化移动平均
                window = series[i - half_window : i + half_window + 1]
                self.trend.append(np.mean(window))

        # 去趋势: 原始序列 - 趋势
        detrended = [series[i] - self.trend[i] for i in range(n)]

        # 计算季节性 (周期平均)
        # 对每个周期位置（0~period-1），取所有同位置值的平均
        self.seasonal = []
        for i in range(self.period):
            season_values = [detrended[j] for j in range(i, n, self.period)]
            self.seasonal.append(np.mean(season_values) if season_values else 0)

        # 中心化季节性（减去均值，使季节性总和为0）
        season_mean = np.mean(self.seasonal)
        self.seasonal = [s - season_mean for s in self.seasonal]

        # 计算残差: 原始 - 趋势 - 季节性
        self.residual = []
        for i in range(n):
            season_idx = i % self.period
            fitted = self.trend[i] + self.seasonal[season_idx]
            self.residual.append(series[i] - fitted)

    def _calculate_confidence(self, growth: List[float]) -> float:
        """计算预测置信度

        基于残差和信号的大小比率（信噪比）评估模型拟合质量。

        参数:
            growth (List[float]): 增长量序列

        返回:
            float: 置信度 (0.0 ~ 0.9)

        置信度计算:
            - 基础置信度随数据量增加而提高
            - 信噪比（信号标准差 / 残差标准差）越大，置信度越高
        """
        n = len(growth)

        # 基础置信度：0.3 + 每点0.015，上限0.85
        base_conf = min(0.85, 0.3 + n * 0.015)

        # 残差大小评估：信噪比 = 信号标准差 / 残差标准差
        if self.residual is not None and len(self.residual) > 0:
            residual_std = np.std(self.residual)  # 残差标准差（噪声）
            signal_std = np.std(growth)  # 信号标准差

            if signal_std > 0:
                # 信噪比 = 信号 / 残差，越大越好
                snr = signal_std / (residual_std + 1)
                # 质量因子 = min(1.0, snr/5)
                quality = min(1.0, snr / 5)
                # 60%基础 + 40%质量因子
                base_conf = 0.6 * base_conf + 0.4 * quality

        return min(0.9, base_conf)
