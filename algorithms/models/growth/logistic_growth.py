"""
Logistic增长模型预测算法模块

Logistic增长模型（也称Verhulst模型）是经典的S型增长曲线，描述了在有限资源环境下的种群增长过程。
在B站视频播放量预测场景中，该模型模拟了视频播放量在"观众市场容量"约束下的增长轨迹。

核心公式：
    V(t) = K / (1 + exp(-r * (t - t0)))

其中：
    - K:  承载能力（Carrying Capacity），即视频的理论最大播放量
    - r:  增长率（Growth Rate），控制曲线的陡峭程度
    - t0: 拐点时间（Inflection Point），此时播放量达到 K/2，增长速度最快
    - t:  时间（以天为单位）

模型特点：
    1. 初期缓慢增长（t << t0）：播放量接近0
    2. 拐点附近加速增长（t ≈ t0）：播放量达到K/2，增长最快
    3. 后期趋于饱和（t >> t0）：播放量接近K，增长停滞
    4. 对称S型曲线：拐点前后的曲线形状对称

算法流程：
    1. 从历史数据中提取时间序列（时间戳转天数）和播放量
    2. 使用 scipy.curve_fit 进行 Logistic 曲线非线性最小二乘拟合
    3. 数据点不足（<10条）时使用启发式参数估计
    4. 反解 Logistic 方程计算到达目标播放量所需时间
    5. 计算预测置信度（基于数据量和拟合质量 MAPE）

适用场景：具有明确S型生长特征的视频，如稳定增长的系列内容
局限性：假设增长完全对称，对于非对称增长（如病毒式传播后快速衰退）不适用

与 gompertz_growth.py 的区别：
    - Logistic 是对称S型曲线，Gompertz 是非对称的
    - Logistic 的拐点始终在 K/2，Gompertz 的拐点在 K/e

所属分类：扩散模型类（category = "扩散模型"）
"""

import numpy as np
import logging
from typing import List, Dict, Any, Optional, Tuple
from algorithms.base import BaseAlgorithm

logger = logging.getLogger(__name__)


class LogisticGrowthAlgorithm(BaseAlgorithm):
    """
    Logistic Growth Model（Logistic增长模型）

    使用非线性最小二乘法拟合 Logistic 增长曲线，预测视频播放量
    达到目标阈值所需的天数。

    公式: V(t) = K / (1 + exp(-r * (t - t0)))
    其中:
        - K: 承载能力 (最大播放量)
        - r: 增长率
        - t0: 中点时间点（拐点）

    类属性：
        name: 算法中文名称
        description: 算法简要描述
        category: 算法分类标签
    """

    name = "Logistic增长模型"
    description = "经典的S型增长曲线，考虑资源限制"
    category = "扩散模型"

    def __init__(self):
        """初始化Logistic模型参数

        设置默认的模型参数和拟合控制参数：
        - K=1000000: 默认承载能力（100万播放量）
        - r=0.2: 默认增长率
        - t0=30: 默认拐点时间（天）
        - _maxfev=300: scipy curve_fit 的最大函数求值次数
        - _min_curvefit_points=10: 执行曲线拟合所需的最小数据点数量
        """
        super().__init__()
        self.K = 1000000  # 承载能力（理论最大播放量）
        self.r = 0.2  # 增长率
        self.t0 = 30  # 中点时间（拐点位置，天）
        self._maxfev = 300  # 曲线拟合最大迭代次数
        self._min_curvefit_points = 10  # 数据点少于该值时不跑curve_fit

    def predict(
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
            # 预处理：提取时间和播放量数组
            times, views = self._prepare_data(video_info)

            if len(times) < 3:
                return None

            # 拟合Logistic曲线
            self._fit_curve(times, views, video_info)

            # 如果已达到目标
            if current_views >= target_views:
                return (0, 1.0)

            # 检查目标是否可达：如果目标超过承载能力的99%，需要调整K
            if target_views >= self.K * 0.99:
                self.K = target_views * 1.2  # 临时上调承载能力

            # 预测时间
            current_t = times[-1]  # 当前数据对应的最后时间点
            target_t = self._find_time_for_views(target_views)

            if target_t is None:
                return None  # 目标不可达

            # 计算剩余天数并转为秒
            days_needed = target_t - current_t

            # 合理性检查：排除负值和超过10年的异常预测
            if days_needed < 0 or days_needed > 3650:
                return None

            seconds_needed = int(days_needed * 86400)  # 天转秒
            confidence = self._calculate_confidence(times, views)

            return (seconds_needed, confidence)

        except Exception as e:
            logger.warning(f"Logistic模型预测失败: {e}")
            return None

    def _prepare_data(self, video_data):
        history = video_data.get("history_data", [])
        if len(history) < self._min_curvefit_points:
            raise ValueError("数据点不足")
        times_days, views, _ts_raw = self._prepare_timeseries_data(history)
        return times_days, views

    def _logistic(self, t, K, r, t0):
        """Logistic函数

        计算Logistic增长曲线在时间t的值。

        公式: V(t) = K / (1 + exp(-r * (t - t0)))

        Args:
            t: 时间点（标量或数组）
            K: 承载能力参数
            r: 增长率参数
            t0: 拐点位置参数

        Returns:
            float/np.ndarray: Logistic函数值（预测播放量）
        """
        return K / (1 + np.exp(-r * (t - t0)))

    def _fit_curve(self, times: np.ndarray, views: np.ndarray, video_info: Dict[str, Any]):
        """拟合Logistic曲线

        使用 scipy.curve_fit 对历史数据进行非线性最小二乘拟合，
        估计模型参数 K、r、t0。数据点不足时使用启发式参数。

        Args:
            times: 时间数组（天）
            views: 播放量数组
            video_info: 视频信息，用于启发式参数估计（如粉丝数）
        """
        # 数据点太少时跳过 curve_fit，直接使用启发式参数
        if len(times) < self._min_curvefit_points:
            self.K = max(views) * 3  # 承载能力 = 最大播放量的3倍
            self.r = 0.15  # 默认增长率
            self.t0 = np.median(times) if len(times) > 0 else 30  # 拐点取时间中值
            if "follower" in video_info:
                self.K = max(self.K, video_info["follower"] * 2.5)
            return

        K_est = max(views) * 2.5
        r_est = 0.2
        t0_est = np.median(times)

        p0 = [K_est, r_est, t0_est]
        bounds = ([max(views), 0.01, 0], [K_est * 10, 2.0, times[-1] * 5])

        popt, success = self._safe_curve_fit(self._logistic, times, views, p0, bounds, maxfev=5000)
        if success:
            self.K, self.r, self.t0 = popt
        else:
            self.K = max(views) * 3
            self.r = 0.15
            self.t0 = np.median(times) if len(times) > 0 else 30
            if "follower" in video_info:
                self.K = max(self.K, video_info["follower"] * 2.5)

    def _find_time_for_views(self, target_views: int) -> Optional[float]:
        """找到达到目标播放量所需时间

        通过反解Logistic方程计算达到指定播放量所需的天数。

        反解推导：
            V = K / (1 + exp(-r * (t - t0)))
            1 + exp(-r * (t - t0)) = K / V
            exp(-r * (t - t0)) = K/V - 1
            -r * (t - t0) = ln(K/V - 1)
            t = t0 - ln(K/V - 1) / r

        Args:
            target_views: 目标播放量

        Returns:
            Optional[float]: 到达目标所需天数，None表示目标不可达
        """
        try:
            # 计算 K/V - 1
            ratio = self.K / target_views - 1
            if ratio <= 0:
                return None  # 目标超过承载能力，不可达
            # t = t0 - ln(ratio) / r
            t = self.t0 - np.log(ratio) / self.r
            return max(0, t)  # 确保非负
        except Exception:
            return None

    def _calculate_confidence(self, times: np.ndarray, views: np.ndarray) -> float:
        n_points = len(times)
        predicted = self._logistic(times, self.K, self.r, self.t0)
        return self._growth_confidence(n_points, predicted, views, 0.03)
