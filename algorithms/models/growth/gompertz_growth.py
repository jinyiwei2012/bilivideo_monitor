"""
Gompertz增长曲线模型模块（精确拟合版）

Gompertz增长曲线是典型的S型（Sigmoid）增长模型，描述增长过程经历
"慢-快-慢"三个阶段的变化规律。与Logistic模型不同，Gompertz曲线是非对称的，
增长加速阶段和减速阶段的速率不同。

核心公式：
    V(t) = a * exp(-b * exp(-c * t))

其中：
    - a: 渐近线（理论最大播放量/市场容量上限）
    - b: 位移参数（控制曲线在时间轴上的左右平移）
    - c: 增长率参数（控制增长速度，c越大增长越快达到饱和）
    - t: 时间（以天为单位）

模型特点：
    1. 初期增长缓慢——视频刚发布，观众积累
    2. 中期加速增长——推荐算法触发，播放量爆发
    3. 后期趋于饱和——热度自然消退，接近容量上限
    4. 非对称S型曲线——加速和减速不对称

算法流程：
    1. 从历史数据中提取时间序列（时间戳转天数）和播放量
    2. 使用 scipy.curve_fit 进行 Gompertz 曲线非线性最小二乘拟合
    3. 数据点不足（<10条）时使用启发式参数估计
    4. 反解 Gompertz 方程计算到达目标播放量所需时间
    5. 计算预测置信度（基于数据量和拟合误差RMSE）

适用场景：具有明显S型增长特征、生命周期较长的视频
局限性：对数据点数量要求较高，拟合失败时需要回退方案

与 gompertz.py 的区别：
    本模块使用 scipy.curve_fit 进行精确的曲线拟合，
    而 gompertz.py 使用简化的增长率估计方法。

所属分类：扩散模型类（category = "扩散模型"）
"""

import numpy as np
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)


class GompertzGrowthAlgorithm(BaseAlgorithm):
    """
    Gompertz Growth Curve Model（Gompertz增长曲线模型）

    使用非线性最小二乘法拟合 Gompertz 增长曲线，预测视频播放量
    达到目标阈值所需的天数。

    公式: V(t) = a * exp(-b * exp(-c * t))
    其中:
        - a: 渐近线 (最大播放量)
        - b: 位移参数
        - c: 增长率参数
        - t: 时间（天）

    类属性：
        name: 算法中文名称
        description: 算法简要描述
        category: 算法分类标签
    """

    name = "Gompertz增长曲线"
    description = "S型增长模型，适用于长期增长预测"
    category = "扩散模型"
    algorithm_id = "gompertz_growth"

    def __init__(self):
        """初始化Gompertz模型参数

        设置默认的模型参数和拟合控制参数：
        - a=1000000: 默认渐近线（100万播放量）
        - b=5.0: 默认位移参数
        - c=0.1: 默认增长率
        - _maxfev=300: scipy curve_fit 的最大函数求值次数
        - _min_curvefit_points=10: 执行曲线拟合所需的最小数据点数量
        """
        super().__init__()
        self.a = 1000000  # 渐近线（最大播放量上限）
        self.b = 5.0  # 位移参数
        self.c = 0.1  # 增长率参数
        self._maxfev = 300  # scipy.optimize.curve_fit 最大迭代次数
        self._min_curvefit_points = 10  # 数据点阈值，低于此值不执行曲线拟合

    def _predict_inner(
        self, current_views: int, target_views: int, history_data: List[Dict[str, Any]], video_info: Dict[str, Any]
    ) -> Optional[Tuple[int, float]]:
        """
        预测视频播放量到达目标阈值所需的时间

        Args:
            current_views: 当前播放量
            target_views: 目标播放量阈值
            history_data: 历史数据列表，每条记录包含：
                - timestamp (str/datetime/float): 时间戳
                - view 或 view_count (int): 该时刻的播放量
            video_info: 视频信息字典，可选包含 follower（粉丝数）

        Returns:
            Optional[Tuple[int, float]]: 预测结果元组 (秒数, 置信度)
            - seconds: 到达目标所需秒数
            - confidence: 置信度 (0.0 ~ 0.95)
            - None: 数据不足或预测失败时返回

        预测步骤：
            1. 从历史数据准备时间序列
            2. 拟合Gompertz曲线
            3. 如果当前已达标则返回(0, 1.0)
            4. 反解方程求到达时间
            5. 计算置信度
        """
        if not history_data or len(history_data) < 3:
            return None  # 数据不足，无法预测

        try:
            # 预处理：提取时间和播放量数组
            times, views = self._prepare_data(video_info)

            if len(times) < 3:
                return None

            # 拟合Gompertz曲线，估计参数a、b、c
            self._fit_curve(times, views, video_info)

            # 如果已达到目标，直接返回预测时间0
            if current_views >= target_views:
                return (0, 1.0)

            # 反解方程找到达到目标播放量所需的时间点
            current_t = times[-1]  # 当前时间（天）
            target_t = self._find_time_for_views(target_views)

            if target_t is None:
                return None  # 目标不可达

            # 计算剩余天数并转为秒
            days_needed = target_t - current_t

            # 合理性检查：排除不合理的预测（负值或超过10年）
            if days_needed < 0 or days_needed > 3650:
                return None

            seconds_needed = int(days_needed * 86400)  # 天转秒
            confidence = self._calculate_confidence(times, views)

            return (seconds_needed, confidence)

        except Exception as e:
            logger.warning(f"Gompertz模型预测失败: {e}")
            return None

    def _prepare_data(self, video_data):
        history = video_data.get("history_data", [])
        if len(history) < self._min_curvefit_points:
            raise ValueError("数据点不足")
        times_days, views, _ts_raw = self._prepare_timeseries_data(history)
        return times_days, views

    def _gompertz(self, t, a, b, c):
        """Gompertz函数

        计算Gompertz增长曲线在时间t的值。

        公式: V(t) = a * exp(-b * exp(-c * t))

        Args:
            t: 时间点（标量或数组）
            a: 渐近线参数（最大播放量）
            b: 位移参数
            c: 增长率参数

        Returns:
            float/np.ndarray: Gompertz函数值（预测播放量）
        """
        return a * np.exp(-b * np.exp(-c * t))

    def _fit_curve(self, times: np.ndarray, views: np.ndarray, video_info: Dict[str, Any]):
        """拟合Gompertz曲线

        使用 scipy.curve_fit 对历史数据进行非线性最小二乘拟合，
        估计模型参数 a、b、c。数据点不足时使用启发式参数。

        Args:
            times: 时间数组（天）
            views: 播放量数组
            video_info: 视频信息，用于启发式参数估计（如粉丝数）
        """
        # 数据点不足：使用启发式参数估计
        if len(times) < self._min_curvefit_points:
            self.a = max(views) * 2.5  # 渐近线 = 最大播放量的2.5倍
            self.b = 4.0
            self.c = 0.15
            if "follower" in video_info:
                # 如果知道粉丝数，用它作为容量的下界
                self.a = max(self.a, video_info["follower"] * 2)
            return

        max_views = max(views) * 3
        p0 = [max_views, 5.0, 0.1]

        bounds = ([max(views), 0.1, 0.001], [max_views * 10, 20.0, 1.0])

        popt, success = self._safe_curve_fit(self._gompertz, times, views, p0, bounds, maxfev=5000)
        if success:
            self.a, self.b, self.c = popt
        else:
            self.a = max(views) * 2.5
            self.b = 4.0
            self.c = 0.15
            if "follower" in video_info:
                self.a = max(self.a, video_info["follower"] * 2)

    def _find_time_for_views(self, target_views: int) -> Optional[float]:
        """找到达到目标播放量所需时间

        通过反解Gompertz方程计算达到指定播放量所需的天数。

        反解推导：
            V = a * exp(-b * exp(-c * t))
            ln(V/a) = -b * exp(-c * t)
            -ln(V/a) / b = exp(-c * t)
            ln(-ln(V/a) / b) = -c * t
            t = -ln(-ln(V/a) / b) / c

        Args:
            target_views: 目标播放量

        Returns:
            Optional[float]: 到达目标所需天数，None表示目标不可达
            （例如目标超过了渐近线a的99%）
        """
        # 如果目标播放量达到渐近线的99%以上，认为不可达
        if target_views >= self.a * 0.99:
            return None

        try:
            # 反解公式：inner = -ln(V/a) / b
            inner = -np.log(target_views / self.a) / self.b
            if inner <= 0:
                return None  # ln值异常，目标不可达
            # t = -ln(inner) / c
            t = -np.log(inner) / self.c
            return max(0, t)
        except Exception:
            return None

    def _calculate_confidence(self, times: np.ndarray, views: np.ndarray) -> float:
        n_points = len(times)
        predicted = self._gompertz(times, self.a, self.b, self.c)
        return self._growth_confidence(n_points, predicted, views, 0.02)

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """统一预测接口：从 video_data 提取参数, 委托 _predict_inner, 包装为 PredictionResult。"""
        current_views = video_data.get("view_count", 0)
        history_data = self._normalize_history(video_data.get("history_data", []))
        return self._to_prediction_result(
            self._predict_inner(current_views, threshold, history_data, video_data),
            current_views, video_data, threshold,
            method="gompertz_growth", invalid_hours=float("inf"), invalid_velocity=0,
        )
