"""
生存分析算法 (Survival Analysis)
===============================

将生存分析（Survival Analysis）的方法应用于视频播放量增长预测。
在医学统计中，生存分析用于预测患者的生存时间；在本算法中，
"生存"被定义为"视频仍保持增长状态"，"死亡"（事件）被定义为
"播放量增长基本停止"。

核心原理：
    1. 事件定义 - 视频增长速度（播放量/小时）低于阈值时视为"停止增长"
    2. Kaplan-Meier 简化版 - 使用经验分布函数估计不同时间的生存概率
    3. 生存概率 - 视频在未来继续保持增长的概率
    4. 策略调整 - 根据生存概率调整预测速度和置信度

Kaplan-Meier 简化版估计：
    - 如果速度已经低于阈值：生存概率 = 0.1（已经"死亡"）
    - 如果速度高于阈值但在下降：根据衰减率预测何时低于阈值
    - 如果速度稳定或上升：生存概率高

生存概率与预测策略：
    - 生存概率 < 0.3：即将停止增长 -> 速度 ×0.5
    - 生存概率 < 0.5：可能即将停止 -> 速度 ×0.7
    - 生存概率 < 0.7：中等生存概率 -> 速度 ×0.85
    - 生存概率 >= 0.7：高生存概率 -> 保持当前速度

适用场景：
    - 需要预测视频"热度消退"的时间
    - 数据量 >= 5 个历史点
    - 适合结合其他算法进行长期预测调整
"""

import numpy as np
from typing import Dict, Any, List, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class SurvivalAnalysisAlgorithm(BaseAlgorithm):
    """
    生存分析算法

    主要功能：
        - 使用简化的 Kaplan-Meier 方法估计视频保持增长的"生存概率"
        - 预测视频"停止增长"的时间（播放量增长速度低于阈值）
        - 根据生存概率动态调整预测速度和置信度
        - 数据不足时回退为简单速度外推

    核心指标：
        - growth_threshold (float): 1.0 播放量/小时（低于此值视为停止增长）
        - survival_prob (float)   : 生存概率 [0, 1]（0=已停止, 1=稳定增长）
        - predicted_growth_stop_hours (float): 预测增长停止时间（小时）

    类属性：
        name (str)            : "生存分析"
        algorithm_id (str)    : "survival_analysis"
        category (str)        : "统计模型"
        default_weight (float): 1.2
    """

    name = "生存分析"
    algorithm_id = "survival_analysis"
    description = "预测视频停止增长的时间，调整长期预测策略"
    category = "统计模型"
    default_weight = 1.2

    def __init__(self):
        """
        初始化生存分析算法

        设置停止增长的判定阈值：
            growth_threshold (float): 1.0 播放量/小时（低于此值视为停止增长）
            min_data_points (int)   : 5（最少需要的数据点数）
        """
        super().__init__()
        self.growth_threshold = 1.0  # 播放量/小时，低于此值视为"停止增长"事件
        self.min_data_points = 5  # 最少需要的数据点数

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行生存分析预测

        算法流程：
            1. 检查数据是否充足（至少 min_data_points 个点）
            2. 提取播放量和时间序列
            3. 计算速度序列
            4. 使用简化的 Kaplan-Meier 方法估计生存概率和停止增长时间
            5. 根据生存概率调整预测速度
            6. 综合计算预测时间和置信度

        Args:
            video_data (Dict[str, Any]): 视频数据字典
                - view_count (int)        : 当前总播放量
                - history_data (list[dict]): 历史数据点列表
            threshold (int): 目标播放量阈值

        Returns:
            PredictionResult: 预测结果对象，metadata 中包含生存概率信息
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        # 数据不足：使用简单速度外推
        if len(history) < self.min_data_points:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.3, survival_prob=0.5,
                predicted_growth_stop_hours=float("inf"), reason="insufficient_data",
            )

        # 提取播放量和时间序列
        views, timestamps = self._extract_series(history)

        if len(views) < self.min_data_points:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.3, survival_prob=0.5,
                predicted_growth_stop_hours=float("inf"), reason="short_series",
            )

        # 计算速度序列
        velocities, vel_times = self._calculate_velocity_series(views, timestamps)

        if len(velocities) < 3:
            velocity = velocities[-1] if len(velocities) > 0 else 0.0
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.4, survival_prob=0.5,
                predicted_growth_stop_hours=float("inf"), reason="short_velocity_series",
            )

        # 使用简化的 Kaplan-Meier 方法估计生存函数
        survival_prob, growth_stop_hours = self._kaplan_meier_simplified(velocities, vel_times, current_views)

        # 根据生存概率调整预测
        adjusted_velocity, confidence = self._adjust_prediction(velocities, survival_prob, growth_stop_hours)

        return self._make_result(
            current_views, threshold, adjusted_velocity,
            confidence=confidence, survival_prob=survival_prob,
            predicted_growth_stop_hours=growth_stop_hours, reason="kaplan_meier",
        )

    def _kaplan_meier_simplified(
        self, velocities: np.ndarray, vel_times: np.ndarray, current_views: int
    ) -> Tuple[float, float]:
        """
        Kaplan-Meier 生存分析的简化版

        简化假设：
            1. 速度低于 growth_threshold 是"事件"（停止增长）
            2. 使用经验分布函数代替完整的 K-M 估计
            3. 通过速度衰减趋势外推预测停止增长时间

        判断逻辑：
            情况 1：已经发生"事件"（有速度点低于阈值）
                - 如果在过去：生存概率 0.1，停止时间 0
                - 如果在未来：生存概率 0.3，返回预测的停止时间
            情况 2：未发生"事件"但速度在下降
                - 根据衰减率外推停止时间
                - 生存概率根据预测时间长短调整
            情况 3：速度稳定或上升
                - 根据趋势判断生存概率
                - 趋势向上 -> 0.9；稳定 -> 0.7；否则 0.5

        Args:
            velocities (np.ndarray) : 速度序列
            vel_times (np.ndarray)  : 速度对应的时间戳
            current_views (int)     : 当前播放量

        Returns:
            Tuple[float, float]: (生存概率 [0, 1], 预测增长停止时间（小时）)
        """
        # 定义"事件"：速度低于阈值
        events = velocities < self.growth_threshold

        if np.any(events):
            # 找到第一个"事件"发生的位置
            first_event_idx = np.argmax(events)
            event_time = vel_times[first_event_idx]

            # 计算事件时间与当前时间的差距
            current_time = vel_times[-1]
            hours_to_event = (event_time - current_time) / 3600.0

            if hours_to_event > 0:
                # 增长还在继续，但预测会停止（距离事件还有 hours_to_event 小时）
                survival_prob = 0.3  # 接近事件，生存概率低
                return survival_prob, hours_to_event
            else:
                # 事件已发生：视频已经停止增长
                survival_prob = 0.1
                return survival_prob, 0.0

        # ── 未发生"事件"：所有速度都高于阈值 ──
        # 使用趋势外推预测何时会低于阈值
        if len(velocities) >= 3:
            # 计算速度衰减率（加速度）
            accel = self._calculate_acceleration(velocities)

            if accel < 0:
                # 速度在下降：预测何时低于阈值
                current_vel = velocities[-1]
                decay_rate = abs(accel)  # 衰减率 = |加速度|

                if decay_rate > 0:
                    # 外推：剩余速度 / 衰减率 = 到达阈值所需时间
                    hours_to_threshold = (current_vel - self.growth_threshold) / decay_rate
                    hours_to_threshold = max(0, hours_to_threshold)

                    # 根据预测时间长短计算生存概率
                    if hours_to_threshold > 168:  # 一周后
                        survival_prob = 0.8
                    elif hours_to_threshold > 48:  # 两天后
                        survival_prob = 0.6
                    elif hours_to_threshold > 12:  # 12 小时后
                        survival_prob = 0.4
                    else:  # 很快停止
                        survival_prob = 0.2

                    return survival_prob, hours_to_threshold

        # ── 速度稳定或上升：生存概率高 ──
        if len(velocities) >= 2:
            # 用一次多项式拟合判断趋势方向
            trend = np.polyfit(range(len(velocities)), velocities, 1)[0]  # 一次项系数即斜率

            if trend > 0:
                # 速度在上升：生存概率很高
                return 0.9, float("inf")  # 无限时间（不会停止）
            elif abs(trend) < 0.1 * np.mean(velocities):
                # 速度稳定：生存概率中等，预计一周后可能停止
                return 0.7, 168.0

        # 默认：生存概率中等，预计 3 天后可能停止增长
        return 0.5, 72.0

    def _adjust_prediction(
        self, velocities: np.ndarray, survival_prob: float, growth_stop_hours: float
    ) -> Tuple[float, float]:
        """
        根据生存概率调整预测速度

        调整规则（基于生存概率阈值）：
            - survival_prob < 0.3: 即将停止 -> 速度 ×0.5（大幅下调）
            - survival_prob < 0.5: 可能停止 -> 速度 ×0.7
            - survival_prob < 0.7: 中等概率 -> 速度 ×0.85
            - survival_prob >= 0.7: 高生存 -> 保持当前速度

        额外调整：如果预测停止时间 < 24 小时且 > 0，
        则进一步按时间比例下调速度。

        Args:
            velocities (np.ndarray)   : 速度序列
            survival_prob (float)     : 生存概率 [0, 1]
            growth_stop_hours (float): 预测停止时间（小时）

        Returns:
            Tuple[float, float]: (调整后的速度, 置信度)
        """
        current_vel = velocities[-1]

        # 根据生存概率阈值调整速度
        if survival_prob < 0.3:
            # 即将停止增长：大幅降低速度预测
            adjusted_vel = current_vel * 0.5
            confidence = 0.7
        elif survival_prob < 0.5:
            # 可能即将停止增长
            adjusted_vel = current_vel * 0.7
            confidence = 0.65
        elif survival_prob < 0.7:
            # 中等生存概率：小幅下调
            adjusted_vel = current_vel * 0.85
            confidence = 0.6
        else:
            # 生存概率高：保持当前速度
            adjusted_vel = current_vel
            confidence = 0.55

        # 额外调整：如果预测停止时间很短（< 24 小时），进一步降低速度
        if growth_stop_hours < 24 and growth_stop_hours > 0:
            time_factor = growth_stop_hours / 24.0  # 剩余时间比例
            adjusted_vel = adjusted_vel * (0.5 + 0.5 * time_factor)  # 线性插值下调

        return max(adjusted_vel, 0.0), confidence

    def _calculate_acceleration(self, velocities: np.ndarray) -> float:
        """
        计算加速度：速度的变化率

        使用最近 3 个速度值通过简单差分计算。

        Args:
            velocities (np.ndarray): 速度序列

        Returns:
            float: 加速度值
        """
        if len(velocities) < 2:
            return 0.0

        recent = velocities[-min(3, len(velocities)) :]
        accel = (recent[-1] - recent[0]) / (len(recent) - 1)
        return accel

    def _extract_series(self, history: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """
        从历史数据列表中提取播放量和时间戳序列

        处理多种时间戳格式并按时间排序。

        Args:
            history (List[Dict]): 历史数据点列表

        Returns:
            Tuple[np.ndarray, np.ndarray]: (播放量数组, 时间戳数组)
        """
        views = []
        timestamps = []

        for entry in history:
            v = entry.get("view_count", entry.get("view", 0))
            t = entry.get("timestamp", 0)

            # 处理多种时间戳格式
            if hasattr(t, "timestamp"):
                t = t.timestamp()
            elif isinstance(t, str):
                try:
                    from datetime import datetime as dt

                    t = dt.fromisoformat(t).timestamp()
                except Exception:
                    continue

            if v > 0 and t > 0:
                views.append(float(v))
                timestamps.append(float(t))

        # 按时间升序排序
        if len(views) > 1:
            sorted_indices = np.argsort(timestamps)
            views = [views[i] for i in sorted_indices]
            timestamps = [timestamps[i] for i in sorted_indices]

        return np.array(views), np.array(timestamps)

    def _calculate_velocity_series(self, views: np.ndarray, timestamps: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        计算速度序列：播放量增量 / 时间增量（小时）

        Args:
            views (np.ndarray)      : 播放量数组
            timestamps (np.ndarray) : 时间戳数组

        Returns:
            Tuple[np.ndarray, np.ndarray]: (速度数组, 速度时间戳数组)
        """
        if len(views) < 2:
            return np.array([]), np.array([])

        velocities = []
        vel_times = []

        for i in range(1, len(views)):
            dt = (timestamps[i] - timestamps[i - 1]) / 3600.0  # 时间差转小时
            if dt <= 0:
                continue  # 跳过非正时间差
            dv = views[i] - views[i - 1]  # 播放量增量
            velocity = dv / dt  # 每小时速度
            velocities.append(velocity)
            vel_times.append(timestamps[i])

        return np.array(velocities), np.array(vel_times)

    def _make_result(
        self, current_views: int, threshold: int, velocity: float,
        confidence: float, survival_prob: float,
        predicted_growth_stop_hours: float, reason: str,
    ) -> PredictionResult:
        """
        构造预测结果对象

        Args:
            current_views (int)            : 当前播放量
            threshold (int)                : 目标播放量阈值
            velocity (float)               : 预测速度
            confidence (float)             : 置信度
            survival_prob (float)          : 生存概率 [0, 1]
            predicted_growth_stop_hours (float): 预测停止增长时间
            reason (str)                   : 预测原因

        Returns:
            PredictionResult: 预测结果对象
        """

        if velocity <= 0:
            predicted_hours = float("inf")  # 速度非正，无法预测
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                predicted_hours = remaining / velocity

        # 构造元数据：包含生存分析特有的诊断信息
        metadata = {
            "survival_probability": survival_prob,  # 生存概率
            "predicted_growth_stop_hours": predicted_growth_stop_hours,  # 预测停止时间
            "growth_threshold": self.growth_threshold,  # 停止增长判定阈值
            "reason": reason,  # 预测原因
            "method": "survival_analysis",  # 方法标识
        }

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
