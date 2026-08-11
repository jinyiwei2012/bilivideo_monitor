"""
Richards曲线增长模型预测算法模块

Richards曲线（Richards Curve），又称广义Logistic模型（Generalized Logistic Model），
是F.J. Richards于1959年提出的增长曲线模型。它是对标准Logistic模型的推广，
引入了一个额外的形状参数ν（nu），用于控制曲线的非对称性。

核心公式：
    V(t) = K / (1 + ν * exp(-r * (t - t0)))^(1/ν)

其中：
    - K:  最大播放量（承载能力/渐近线）
    - r:  增长率参数
    - t0: 位移参数（与Logistic的拐点类似但不完全相同）
    - ν:  形状参数（控制曲线的非对称性和拐点位置）

形状参数ν的含义：
    ν → 1:  退化为标准Logistic模型（对称S型）
    ν < 1:  增长初期快于后期（左偏，早期加速更强）
    ν > 1:  增长后期快于初期（右偏，持续增长能力更强）
    ν → ∞:  退化为指数增长模型

与Logistic模型的对比：
    - Logistic是Richards在ν=1时的特例
    - Richards可以描述更丰富的增长模式
    - 代价是多一个参数，拟合难度增加
    - 对数据量要求更高（最少4条，推荐10条以上）

算法流程：
    1. 从历史数据中提取时间序列（时间戳转天数）和播放量
    2. 使用 scipy.curve_fit 进行 Richards 曲线非线性最小二乘拟合
    3. 数据点不足（<10条）时使用启发式参数估计（ν默认1.0）
    4. 反解 Richards 方程计算到达目标播放量所需时间
    5. 计算预测置信度（基于数据量和拟合质量 MAPE）

适用场景：增长模式复杂、需要更高灵活性的视频预测
局限性：参数多、对数据质量和数量要求高，小样本容易过拟合

所属分类：扩散模型类（category = "扩散模型"）
"""

import numpy as np
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)


class RichardsCurveAlgorithm(BaseAlgorithm):
    """
    Richards Curve Model (Generalized Logistic，广义Logistic模型)

    使用非线性最小二乘法拟合 Richards 增长曲线，预测视频播放量
    达到目标阈值所需的天数。

    公式: V(t) = K / (1 + ν * exp(-r * (t - t0)))^(1/ν)
    其中:
        - K: 最大播放量（承载能力）
        - r: 增长率
        - t0: 位移参数
        - ν: 形状参数（nu），控制曲线不对称性

    当ν→1时，Richards曲线退化为标准Logistic曲线。

    类属性：
        name: 算法中文名称
        description: 算法简要描述
        category: 算法分类标签
    """

    name = "Richards曲线模型"
    description = "广义Logistic模型，支持不对称增长"
    category = "扩散模型"
    algorithm_id = "richards_curve"

    def __init__(self):
        """初始化Richards曲线模型参数

        设置默认的模型参数和拟合控制参数：
        - K=1000000: 默认最大播放量（承载能力）
        - r=0.2: 默认增长率
        - t0=30: 默认位移参数（天）
        - nu=1.0: 默认形状参数（1.0等价于Logistic）
        - _maxfev=300: scipy curve_fit 的最大函数求值次数
        - _min_curvefit_points=10: 执行曲线拟合所需的最小数据点数量
        """
        super().__init__()
        self.K = 1000000  # 最大播放量（承载能力/渐近线）
        self.r = 0.2  # 增长率
        self.t0 = 30  # 位移参数（天）
        self.nu = 1.0  # 形状参数（1.0等价于标准Logistic）
        self._maxfev = 300  # 曲线拟合最大函数求值次数
        self._min_curvefit_points = 10  # 执行curve_fit的最小数据点数

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
        """
        if not history_data or len(history_data) < 4:
            return None  # Richards需要更多数据（4条以上）

        try:
            # 预处理数据
            times, views = self._prepare_data(video_info)

            if len(times) < 4:
                return None

            # 拟合Richards曲线
            self._fit_curve(times, views, video_info)

            if current_views >= target_views:
                return (0, 1.0)  # 已达标

            # 检查目标是否可达
            if target_views >= self.K * 0.99:
                self.K = target_views * 1.2  # 临时上调承载能力

            current_t = times[-1]  # 当前时间点
            target_t = self._find_time_for_views(target_views)

            if target_t is None:
                return None  # 目标不可达

            # 计算剩余天数并转换为秒
            days_needed = target_t - current_t

            # 合理性检查
            if days_needed < 0 or days_needed > 3650:
                return None

            seconds_needed = int(days_needed * 86400)  # 天转秒
            confidence = self._calculate_confidence(times, views)

            return (seconds_needed, confidence)

        except Exception as e:
            logger.warning(f"Richards模型预测失败: {e}")
            return None

    def _prepare_data(self, video_data):
        history = video_data.get("history_data", [])
        if len(history) < self._min_curvefit_points:
            raise ValueError("数据点不足")
        times_days, views, _ts_raw = self._prepare_timeseries_data(history)
        return times_days, views

    def _richards(self, t, K, r, t0, nu):
        """Richards曲线函数

        计算Richards增长曲线在时间t的值。

        公式: V(t) = K / (1 + ν * exp(-r * (t - t0)))^(1/ν)

        Args:
            t: 时间点（标量或数组）
            K: 承载能力参数
            r: 增长率参数
            t0: 位移参数
            nu: 形状参数（ν）

        Returns:
            float/np.ndarray: Richards函数值（预测播放量）
        """
        return K / np.power(1 + nu * np.exp(-r * (t - t0)), 1.0 / nu)

    def _fit_curve(self, times: np.ndarray, views: np.ndarray, video_info: Dict[str, Any]):
        """拟合Richards曲线

        使用 scipy.curve_fit 对历史数据进行非线性最小二乘拟合，
        估计模型参数 K、r、t0、ν。数据点不足时使用启发式参数。

        Args:
            times: 时间数组（天）
            views: 播放量数组
            video_info: 视频信息，用于启发式参数估计（如粉丝数）
        """
        # 数据点太少时跳过 curve_fit，直接使用启发式参数
        if len(times) < self._min_curvefit_points:
            self.K = max(views) * 3  # 承载能力 = 最大播放量的3倍
            self.r = 0.15
            self.t0 = np.median(times) if len(times) > 0 else 30
            self.nu = 1.0  # 默认对称（等价于Logistic）
            if "follower" in video_info:
                self.K = max(self.K, video_info["follower"] * 2.5)
            return

        K_est = max(views) * 2.5
        r_est = 0.2
        t0_est = np.median(times)
        nu_est = 1.0

        p0 = [K_est, r_est, t0_est, nu_est]
        bounds = ([max(views), 0.01, 0, 0.1], [K_est * 10, 2.0, times[-1] * 5, 5.0])

        popt, success = self._safe_curve_fit(self._richards, times, views, p0, bounds, maxfev=5000)
        if success:
            self.K, self.r, self.t0, self.nu = popt
        else:
            self.K = max(views) * 3
            self.r = 0.15
            self.t0 = np.median(times) if len(times) > 0 else 30
            self.nu = 1.0
            if "follower" in video_info:
                self.K = max(self.K, video_info["follower"] * 2.5)

    def _find_time_for_views(self, target_views: int) -> Optional[float]:
        """找到达到目标播放量所需时间

        通过反解Richards方程计算达到指定播放量所需的天数。

        反解推导：
            V = K / (1 + ν * exp(-r * (t - t0)))^(1/ν)
            (K/V)^ν = 1 + ν * exp(-r * (t - t0))
            (K/V)^ν - 1 = ν * exp(-r * (t - t0))
            ((K/V)^ν - 1) / ν = exp(-r * (t - t0))
            ln(((K/V)^ν - 1) / ν) = -r * (t - t0)
            t = t0 - ln(((K/V)^ν - 1) / ν) / r

        Args:
            target_views: 目标播放量

        Returns:
            Optional[float]: 到达目标所需天数，None表示目标不可达
        """
        try:
            if target_views >= self.K:
                return None  # 目标超过承载能力，不可达

            # 计算 (K/V)^ν - 1
            ratio = np.power(self.K / target_views, self.nu) - 1
            if ratio <= 0:
                return None

            # 计算内层：((K/V)^ν - 1) / ν
            inner = ratio / self.nu
            if inner <= 0:
                return None

            # t = t0 - ln(inner) / r
            t = self.t0 - np.log(inner) / self.r
            return max(0, t)  # 确保非负
        except Exception:
            return None

    def _calculate_confidence(self, times: np.ndarray, views: np.ndarray) -> float:
        n_points = len(times)
        predicted = self._richards(times, self.K, self.r, self.t0, self.nu)
        return self._growth_confidence(n_points, predicted, views, 0.02)

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """统一预测接口：从 video_data 提取参数, 委托 _predict_inner, 包装为 PredictionResult。"""
        current_views = video_data.get("view_count", 0)
        history_data = self._normalize_history(video_data.get("history_data", []))
        return self._to_prediction_result(
            self._predict_inner(current_views, threshold, history_data, video_data),
            current_views, video_data, threshold,
            method="richards_curve", invalid_hours=float("inf"), invalid_velocity=0,
        )
