"""
Weibull增长模型预测算法模块

Weibull分布最初由Waloddi Weibull于1939年提出，用于描述材料强度的统计分布。
其累积分布函数的形态非常灵活，通过调整形状参数k可以模拟多种不同的增长模式，
因此被广泛应用于可靠性工程、生存分析和增长建模中。

核心公式：
    V(t) = K * (1 - exp(-(t/λ)^k))

其中：
    - K:  最大播放量（承载能力/渐近线）
    - λ:  尺度参数（Scale Parameter），控制曲线的时间刻度
    - k:  形状参数（Shape Parameter），控制曲线的增长形态
    - t:  时间（以天为单位）

形状参数k对增长模式的影响：
    k < 1:  递减增长率（初期快、后期慢）—— 适合短期爆红的视频
    k = 1:  指数增长（恒定的增长率）—— 等效于指数分布
    k > 1:  先增后减（S型曲线）—— 适合逐步积累热度的视频
    k ≈ 3.6: 接近正态分布对称S型

Weibull模型与其他模型的比较：
    - vs Logistic/Logistic: 可以描述初期极快的增长然后快速饱和
    - vs Gompertz:      Weibull更灵活，但缺少Gompertz的生物学解释
    - vs Richards:      两者都很灵活，但Weibull参数更少（3个 vs 4个）

算法流程：
    1. 从历史数据中提取时间序列（时间戳转天数）和播放量
    2. 使用 scipy.curve_fit 进行 Weibull 曲线非线性最小二乘拟合
    3. 数据点不足（<10条）时使用启发式参数估计
    4. 反解 Weibull 方程计算到达目标播放量所需时间
    5. 计算预测置信度（基于数据量和拟合质量 MAPE）

适用场景：
    - 需要灵活增长曲线形态的视频预测
    - 不确定增长属于哪种类型的探索性预测
    - 视频生命周期模式不明确时的通用拟合

局限性：参数物理含义不如Logistic直观

所属分类：扩散模型类（category = "扩散模型"）
"""

import numpy as np
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)


class WeibullGrowthAlgorithm(BaseAlgorithm):
    """
    Weibull Growth Model（Weibull增长模型）

    使用非线性最小二乘法拟合 Weibull 累积分布函数形式的增长曲线，
    预测视频播放量达到目标阈值所需的天数。

    公式: V(t) = K * (1 - exp(-(t/λ)^k))
    其中:
        - K: 最大播放量（承载能力/渐近线）
        - λ: 尺度参数（Scale），控制曲线时间刻度
        - k: 形状参数（Shape），控制增长形态
            k<1: 递减增长率（初期快后期慢）
            k=1: 恒定增长率（指数增长）
            k>1: S型增长（先增后减）

    类属性：
        name: 算法中文名称
        description: 算法简要描述
        category: 算法分类标签
    """

    name = "Weibull增长模型"
    description = "灵活的增长模型，适应不同生命周期"
    category = "扩散模型"
    algorithm_id = "weibull_growth"

    def __init__(self):
        """初始化Weibull增长模型参数

        设置默认的模型参数和拟合控制参数：
        - K=1000000: 默认最大播放量
        - lam=30: 默认尺度参数λ（天）
        - k=1.5: 默认形状参数（>1表示S型增长）
        - _maxfev=300: scipy curve_fit 的最大函数求值次数
        - _min_curvefit_points=10: 执行曲线拟合所需的最小数据点数量
        """
        super().__init__()
        self.K = 1000000  # 最大播放量（承载能力/渐近线）
        self.lam = 30  # 尺度参数λ（天），控制曲线沿时间轴的缩放
        self.k = 1.5  # 形状参数k（>1表示S型增长，1=指数，<1=递减）
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
        if not history_data or len(history_data) < 3:
            return None  # 数据不足

        try:
            # 预处理数据
            times, views = self._prepare_data(video_info)

            if len(times) < 3:
                return None

            # 拟合Weibull曲线（返回局部参数，避免单例竞态）
            K, lam, k = self._fit_curve(times, views, video_info)

            if current_views >= target_views:
                return (0, 1.0)  # 已达标

            # 检查目标是否可达
            if target_views >= K * 0.99:
                K = target_views * 1.2  # 临时上调承载能力

            current_t = times[-1]  # 当前时间点
            target_t = self._find_time_for_views(target_views, K, lam, k)

            if target_t is None:
                return None  # 目标不可达

            # 计算剩余天数并转换为秒
            days_needed = target_t - current_t

            # 合理性检查
            if days_needed < 0 or days_needed > 3650:
                return None

            seconds_needed = int(days_needed * 86400)  # 天转秒
            confidence = self._calculate_confidence(times, views, K, lam, k)

            return (seconds_needed, confidence)

        except Exception as e:
            logger.warning(f"Weibull模型预测失败: {e}")
            return None

    def _prepare_data(self, video_data):
        history = video_data.get("history_data", [])
        if len(history) < self._min_curvefit_points:
            raise ValueError("数据点不足")
        times_days, views, _ts_raw = self._prepare_timeseries_data(history)
        return times_days, views

    def _weibull(self, t, K, lam, k):
        """Weibull累积分布函数（作为增长曲线使用）

        计算Weibull增长曲线在时间t的值。

        公式: V(t) = K * (1 - exp(-(t/λ)^k))

        Args:
            t: 时间点（标量或数组）
            K: 承载能力参数（渐近线）
            lam: 尺度参数λ
            k: 形状参数k

        Returns:
            float/np.ndarray: Weibull函数值（预测播放量）
        """
        return K * (1 - np.exp(-np.power(t / lam, k)))

    def _fit_curve(self, times: np.ndarray, views: np.ndarray, video_info: Dict[str, Any]) -> Tuple[float, float, float]:
        """拟合Weibull曲线，返回 (K, lam, k)。

        使用 scipy.curve_fit 对历史数据进行非线性最小二乘拟合，
        估计模型参数 K、λ、k。数据点不足时使用启发式参数。
        参数作为局部值返回，不写入实例状态（避免单例共享可变状态）。

        Args:
            times: 时间数组（天）
            views: 播放量数组
            video_info: 视频信息，用于启发式参数估计（如粉丝数）

        Returns:
            (K, lam, k): 拟合得到的模型参数
        """
        # 数据点太少时跳过 curve_fit，直接使用启发式参数
        if len(times) < self._min_curvefit_points:
            K = max(views) * 3  # 承载能力 = 最大播放量的3倍
            lam = 30  # 默认尺度参数（30天）
            k = 1.5  # 默认形状参数（S型增长）
            if "follower" in video_info:
                K = max(K, video_info["follower"] * 2.5)
            return K, lam, k

        K_est = max(views) * 2.5
        lam_est = float(np.median(times)) if len(times) > 0 else 30
        k_est = 1.5

        p0 = [K_est, lam_est, k_est]
        bounds = ([max(views), 1, 0.1], [K_est * 10, times[-1] * 10, 5.0])

        popt, success = self._safe_curve_fit(self._weibull, times, views, p0, bounds, maxfev=5000)
        if success:
            return float(popt[0]), float(popt[1]), float(popt[2])
        else:
            K = max(views) * 3
            lam = 30
            k = 1.5
            if "follower" in video_info:
                K = max(K, video_info["follower"] * 2.5)
            return K, lam, k

    def _find_time_for_views(self, target_views: int, K: float, lam: float, k: float) -> Optional[float]:
        """找到达到目标播放量所需时间

        通过反解Weibull方程计算达到指定播放量所需的天数。

        反解推导：
            V = K * (1 - exp(-(t/λ)^k))
            1 - V/K = exp(-(t/λ)^k)
            -ln(1 - V/K) = (t/λ)^k
            t = λ * (-ln(1 - V/K))^(1/k)

        Args:
            target_views: 目标播放量
            K: 承载能力（渐近线）
            lam: 尺度参数 λ
            k: 形状参数 k

        Returns:
            Optional[float]: 到达目标所需天数，None表示目标不可达
        """
        try:
            # 目标播放量不能超过承载能力K
            if target_views >= K:
                return None

            # ratio = 1 - V/K（剩余比例，必须在0到1之间）
            ratio = 1 - target_views / K
            if ratio <= 0 or ratio >= 1:
                return None

            # t = λ * (-ln(ratio))^(1/k)
            t = lam * np.power(-np.log(ratio), 1.0 / k)
            return max(0, t)  # 确保非负
        except Exception:
            return None

    def _calculate_confidence(self, times: np.ndarray, views: np.ndarray, K: float, lam: float, k: float) -> float:
        n_points = len(times)
        predicted = self._weibull(times, K, lam, k)
        return self._growth_confidence(n_points, predicted, views, 0.02)

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """统一预测接口：从 video_data 提取参数, 委托 _predict_inner, 包装为 PredictionResult。"""
        current_views = video_data.get("view_count", 0)
        history_data = self._normalize_history(video_data.get("history_data", []))
        return self._to_prediction_result(
            self._predict_inner(current_views, threshold, history_data, video_data),
            current_views, video_data, threshold,
            method="weibull_growth", invalid_hours=float("inf"), invalid_velocity=0,
        )
