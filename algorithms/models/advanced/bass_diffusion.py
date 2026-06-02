"""
Bass扩散模型 (Bass Diffusion Model)
=====================================

基于Frank M. Bass在1969年提出的创新扩散理论，模拟产品/内容在市场中的传播过程。
该模型将用户分为两类：
  - 创新者 (Innovators)：受外部因素（如推荐算法、首页推送）影响而观看视频
  - 模仿者 (Imitators)：受内部因素（如口碑传播、社交分享）影响而观看视频

核心数学公式：
    f(t) / (1 - F(t)) = p + q * F(t)
    其中:
      p (创新系数) : 外部影响力，控制初始增长速率
      q (模仿系数) : 内部口碑传播力，控制病毒式传播速率
      m (市场潜力) : 最大可能播放量，即理论上限
      F(t)         : 到时间 t 的累积采用者比例
      f(t)         : 在时间 t 的瞬时采用率

累积分布函数的解析解：
    F(t) = m * (1 - e^{-(p+q)t}) / (1 + (q/p) * e^{-(p+q)t})

适用场景：
  - 视频播放量的病毒式传播预测
  - 适用于有明确"爆款"潜力的视频
  - 需要至少 2 个历史数据点作为基础

参数自适应：
  - 根据粉丝数调整市场潜力 m (粉丝越多，潜在观众越多)
  - 根据互动率（点赞/播放比）调整模仿系数 q
  - 根据视频质量分数调整创新系数 p
"""

import numpy as np
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

# 时间戳格式化字符串，用于解析历史数据中的时间字段
_TS_FMT = "%Y-%m-%d %H:%M:%S"


class BassDiffusionAlgorithm(BaseAlgorithm):
    """
    Bass扩散模型预测算法

    使用Bass创新扩散模型对视频播放量进行预测。根据视频的当前播放量、
    历史增长数据和视频特征（粉丝数、互动率、质量分数），动态调整模型的
    三个核心参数（p, q, m），然后通过二分查找数值求解到达目标播放量所需的时间。

    模型假设播放量的增长遵循S型曲线：
      - 初期：增长缓慢（主要由创新者驱动）
      - 中期：加速增长（模仿者大量加入，口碑传播）
      - 后期：增长放缓并趋于饱和（市场潜力耗尽）

    类属性：
        name (str)          : 算法显示名称 "Bass扩散模型"
        algorithm_id (str)  : 算法唯一标识符 "bass_diffusion"
        description (str)   : 算法简要描述
        category (str)      : 算法分类 "扩散模型"
    """

    name = "Bass扩散模型"
    algorithm_id = "bass_diffusion"
    description = "基于创新扩散理论，模拟病毒式传播过程"
    category = "扩散模型"

    def __init__(self):
        """
        初始化Bass扩散模型算法

        设置模型的三个默认参数：
            p (创新系数) : 0.03 — 外部影响力，控制初始增长
            q (模仿系数) : 0.38 — 内部口碑传播力（社交媒体通常较高）
            m (市场潜力) : 10,000,000 — 默认最大播放量1000万
        这些参数会在预测过程中根据视频特征进行自适应调整。
        """
        super().__init__()
        self.p = 0.03  # 创新系数，代表外部推荐/曝光带来的初始增长
        self.q = 0.38  # 模仿系数，代表口碑传播/社交分享带来的增长（社交媒体通常较高）
        self.m = 10000000  # 市场潜力，代表理论上的最大播放量上限（默认1000万）

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        预测视频到达目标播放量所需的时间

        算法流程：
            1. 检查历史数据是否充足（至少需要2个数据点）
            2. 根据视频特征（粉丝数、互动率、质量分数）自适应调整模型参数
            3. 计算视频已发布的天数 t_days
            4. 检查当前播放量是否已达到目标阈值
            5. 使用Bass模型累积函数 + 二分查找求解到达目标所需天数
            6. 根据历史数据点数量和增长稳定性计算置信度

        Args:
            video_data (Dict[str, Any]): 包含视频数据的字典，期望的键包括：
                - view_count (int)           : 当前总播放量
                - history_data (list[dict])  : 历史数据点列表，每个点含 view 和 timestamp
                - follower (int, 可选)       : 粉丝数，用于调整市场潜力
                - like (int, 可选)          : 点赞数，用于计算互动率
                - view (int, 可选)          : 播放量（用于计算互动率时作为分母）
                - quality_score (float, 可选): 视频质量分数，用于调整创新系数
            threshold (int): 目标播放量阈值，默认为 100,000

        Returns:
            PredictionResult: 预测结果对象，包含：
                - predicted_hours (float) : 预测到达目标所需小时数
                - confidence (float)      : 预测置信度 (0.0 ~ 1.0)
                - metadata (dict)         : 包含模型参数 p, q, m 等元数据
        """
        current_views = video_data.get("view_count", 0)
        history_data = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # ── 数据不足时返回无效预测 ──
        if not history_data or len(history_data) < 2:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=float("inf"),  # 无穷大表示无法预测
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"error": "Insufficient data"},
                timestamp=datetime.now(),
            )

        try:
            # ── 根据视频特征自适应调整模型参数 ──
            self._adjust_parameters(video_data)

            # ── 计算视频已发布的天数 ──
            current_time = datetime.now()
            earliest_ts = history_data[0]["timestamp"]
            # 时间戳可能是数值（Unix时间戳）或字符串格式
            if isinstance(earliest_ts, (int, float)):
                earliest = datetime.fromtimestamp(earliest_ts)
            else:
                earliest = datetime.strptime(earliest_ts, _TS_FMT)
            t_days = (current_time - earliest).total_seconds() / 86400  # 转换为天数

            # ── 如果已达标，直接返回 ──
            if current_views >= threshold:
                return PredictionResult(
                    algorithm_name=self.name,
                    algorithm_id=self.algorithm_id,
                    target_threshold=threshold,
                    predicted_hours=0,
                    confidence=1.0,
                    current_views=current_views,
                    current_velocity=velocity,
                    metadata={"method": "bass_diffusion", "status": "already_reached"},
                    timestamp=datetime.now(),
                )

            # ── 使用Bass模型预测到达目标所需天数 ──
            days_needed = self._predict_days_to_target(current_views, threshold, t_days)

            # ── 预测时间过长（超过10年）视为无效 ──
            if days_needed is None or days_needed > 3650:
                return PredictionResult(
                    algorithm_name=self.name,
                    algorithm_id=self.algorithm_id,
                    target_threshold=threshold,
                    predicted_hours=float("inf"),
                    confidence=0.0,
                    current_views=current_views,
                    current_velocity=velocity,
                    metadata={"error": "Prediction too far in future"},
                    timestamp=datetime.now(),
                )

            predicted_hours = days_needed * 24  # 将天数转换为小时

            # ── 计算置信度：基于数据点数量和增长稳定性 ──
            confidence = self._calculate_confidence(history_data)

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "bass_diffusion", "p": self.p, "q": self.q, "m": self.m},
                timestamp=datetime.now(),
            )

        except Exception as e:
            # ── 异常回退：记录警告并返回无效预测 ──
            logger.warning(f"Bass扩散模型预测失败: {e}")
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=float("inf"),
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"error": str(e)},
                timestamp=datetime.now(),
            )

    def _adjust_parameters(self, video_info: Dict[str, Any]):
        """
        根据视频特征自适应调整Bass模型的三个核心参数

        调整规则：
            - 市场潜力 m : 基于粉丝数调整，粉丝数 × 3 作为潜力下限（至少100万）
            - 模仿系数 q : 基于点赞率（点赞数/播放量）调整，高互动率 → 高口碑传播
            - 创新系数 p : 基于视频质量分数调整，高质量 → 更高初始曝光概率

        Args:
            video_info (Dict[str, Any]): 视频信息字典，可包含 follower, like, view, quality_score
        """
        # ── 根据粉丝数调整市场潜力 ──
        if "follower" in video_info:
            follower = video_info["follower"]
            # 市场潜力与粉丝数正相关：每个粉丝平均带来3次播放
            self.m = max(follower * 3, 1000000)

        # ── 根据互动率调整模仿系数（口碑传播力） ──
        if "like" in video_info and "view" in video_info:
            like_rate = video_info["like"] / max(video_info["view"], 1)  # 点赞率
            # 高点赞率意味着更强的口碑传播：每10%点赞率增加1.0的模仿系数
            self.q = min(0.5, 0.3 + like_rate * 10)

        # ── 根据视频质量分数调整创新系数（外部曝光吸引力） ──
        if "quality_score" in video_info:
            quality = video_info["quality_score"]
            # 质量分数越高，视频越容易被推荐系统推送
            self.p = min(0.1, 0.02 + quality * 0.05)

    def _predict_days_to_target(self, current_views: int, target_views: int, current_t: float) -> Optional[float]:
        """
        使用Bass模型累积函数 + 二分查找求解到达目标播放量所需的天数

        算法：
            1. 构建Bass累积函数 F(t)，描述到时间 t 的累积播放量
            2. 如果目标超过市场潜力的95%，自动扩展市场潜力为目标值的1.2倍
            3. 使用二分查找在 [current_t, current_t + 3650] 天内搜索目标时间
            4. 最大迭代100次，精度为市场潜力的0.1%

        Args:
            current_views (int) : 当前播放量
            target_views (int)  : 目标播放量
            current_t (float)   : 当前已过去的天数

        Returns:
            Optional[float]: 到达目标还需的天数，如果无法求解则返回 None
        """

        # ── Bass模型累积函数：F(t) = m * (1 - e^{-(p+q)t}) / (1 + (q/p) * e^{-(p+q)t}) ──
        def bass_cumulative(t):
            if self.p + self.q == 0:
                return 0  # 避免除零
            exp_term = np.exp(-(self.p + self.q) * t)
            return self.m * (1 - exp_term) / (1 + (self.q / self.p) * exp_term)

        # ── 如果目标超过市场潜力的95%，扩展市场潜力以容纳目标 ──
        if target_views > self.m * 0.95:
            self.m = target_views * 1.2  # 设置市场潜力为目标值的120%

        # ── 二分查找：在 [current_t, current_t + 10年] 区间内搜索 ──
        t_low, t_high = current_t, current_t + 365 * 10  # 搜索范围为当前时间到10年后

        for _ in range(100):  # 最多迭代100次，每次将搜索区间缩小一半
            t_mid = (t_low + t_high) / 2  # 取中点
            views_mid = bass_cumulative(t_mid)

            # ── 达到目标精度（0.1%的市场潜力）则返回 ──
            if abs(views_mid - target_views) < self.m * 0.001:
                return t_mid - current_t  # 返回还需的天数

            # ── 中点值小于目标 → 搜索右半区间 ──
            if views_mid < target_views:
                t_low = t_mid
            else:
                t_high = t_mid  # 中点值大于目标 → 搜索左半区间

        return t_high - current_t  # 返回高边界对应的天数

    def _calculate_confidence(self, history_data: List[Dict[str, Any]]) -> float:
        """
        计算预测置信度

        置信度由两个因素共同决定：
            1. 数据点数量：数据点越多，基础置信度越高（每点+0.02，上限0.95）
            2. 增长稳定性：计算增长率的变异系数(CV)，CV越小越稳定，置信度越高

        综合公式：
            confidence = 0.6 * base_confidence + 0.4 * fit_quality
            fit_quality = max(0, 1 - CV)
            最终钳制在 [0, 0.95] 区间

        Args:
            history_data (List[Dict[str, Any]]): 历史数据点列表

        Returns:
            float: 置信度值 (0.0 ~ 0.95)
        """
        n_points = len(history_data)

        # ── 基础置信度：随数据点数量线性增长 ──
        base_confidence = min(0.95, 0.5 + n_points * 0.02)

        # ── 如果有足够的数据点，计算增长稳定性 ──
        if n_points >= 5:
            try:
                views = [d["view"] for d in history_data]
                # ── 计算逐期增长率 ──
                growth_rates = []
                for i in range(1, len(views)):
                    if views[i - 1] > 0:
                        rate = (views[i] - views[i - 1]) / views[i - 1]  # 环比增长率
                        growth_rates.append(rate)

                if growth_rates:
                    # ── 变异系数 CV = 标准差 / 均值，越小越稳定 ──
                    cv = np.std(growth_rates) / (np.mean(growth_rates) + 1e-10)  # 加1e-10避免除零
                    fit_quality = max(0, 1 - cv)  # CV→0时拟合质量→1
                    # 综合基础置信度和拟合质量
                    base_confidence = 0.6 * base_confidence + 0.4 * fit_quality

            except Exception as e:
                logger.debug("Bass扩散置信度计算失败: %s", e)

        return min(0.95, base_confidence)  # 上限0.95，不过度自信
