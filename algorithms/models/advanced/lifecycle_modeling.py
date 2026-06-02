"""
视频生命周期建模算法 (Video Lifecycle Modeling)
==============================================

将视频的播放量增长过程划分为不同的生命周期阶段，针对每个阶段
使用不同的预测策略。这种方法借鉴了产品生命周期理论（PLC），
将视频的生命周期类比为产品在市场中经历的不同阶段。

生命周期阶段定义：
    1. INTRODUCTION (导入期): 刚发布，播放量增长缓慢
       - 特征：播放量低，增长速度慢但有上升趋势
       - 策略：使用平均速度和趋势外推

    2. GROWTH (成长期): 开始获得推荐，播放量快速增长
       - 特征：增长速度超过阈值，且保持或加速增长
       - 策略：使用近期速度，考虑增长惯性

    3. VIRAL (病毒期): 突然爆火，增长速度极快
       - 特征：速度远超正常水平，可能是被热门推荐或热搜
       - 策略：加速期小幅放大，减速期大幅下调（热度消退风险高）

    4. MATURITY (成熟期): 增长放缓，趋于稳定
       - 特征：增长速度下降但维持在中等水平
       - 策略：使用指数衰减模型，估计衰减率

    5. DECLINE (衰退期): 播放量基本停止增长
       - 特征：速度极低，增长几乎停止
       - 策略：使用长期衰减趋势，保持最小速度底线

阶段判断依据：
    - 当前速度 (velocities[-1])
    - 平均速度 (avg_vel)
    - 加速度 (accel)
    - 速度稳定性 (vel_cv = 标准差/均值)
    - 视频年龄 (age_hours)
"""

import numpy as np
from typing import Dict, Any, List, Tuple
from datetime import datetime
from enum import Enum
from algorithms.base import BaseAlgorithm, PredictionResult


class LifecycleStage(Enum):
    """
    视频生命周期阶段枚举

    定义了视频播放量增长过程中可能经历的 5 个阶段：
        INTRODUCTION : 导入期 - 视频刚发布，播放量增长缓慢
        GROWTH       : 成长期 - 开始获得推荐，播放量快速增长
        MATURITY     : 成熟期 - 增长放缓，趋于稳定
        DECLINE      : 衰退期 - 播放量基本停止增长
        VIRAL        : 病毒期 - 突然爆火，增长速度极快
    """

    INTRODUCTION = "导入期"  # 刚发布，播放量增长缓慢
    GROWTH = "成长期"  # 开始获得推荐，播放量快速增长
    MATURITY = "成熟期"  # 增长放缓，趋于稳定
    DECLINE = "衰退期"  # 播放量基本停止增长
    VIRAL = "病毒期"  # 突然爆火，增长速度极快


class LifecycleModelAlgorithm(BaseAlgorithm):
    """
    视频生命周期建模算法

    主要功能：
        - 将视频播放量增长过程划分为 5 个生命周期阶段
        - 根据当前速度和加速度自动判断所处阶段
        - 针对不同阶段使用不同的预测策略
        - 综合考虑速度水平和变化趋势

    阶段判断的阈值配置：
        - velocity_threshold_growth (50): 进入成长期的最小速度（播放量/小时）
        - velocity_threshold_viral (500): 进入病毒期的最小速度
        - velocity_threshold_decline (10): 低于此速度进入衰退期
        - stable_period_hours (6): 判断稳定期需要的小时数

    类属性：
        name (str)            : "生命周期建模"
        algorithm_id (str)    : "lifecycle_modeling"
        category (str)        : "生命周期模型"
        default_weight (float): 1.5
    """

    name = "生命周期建模"
    algorithm_id = "lifecycle_modeling"
    description = "将视频划分为不同阶段，针对不同阶段使用不同预测策略"
    category = "生命周期模型"
    default_weight = 1.5

    def __init__(self):
        """
        初始化生命周期建模算法

        设置各阶段的判定阈值：
            velocity_threshold_growth (int) : 50 (成长期的速度下限)
            velocity_threshold_viral (int)  : 500 (病毒期的速度下限)
            velocity_threshold_decline (int): 10 (衰退期的速度上限)
            stable_period_hours (int)       : 6 (判断稳定期的最短时间)
        """
        super().__init__()
        self.velocity_threshold_growth = 50  # 播放量/小时，低于此值通常不算"增长期"
        self.velocity_threshold_viral = 500  # 播放量/小时，极高速度表示病毒传播
        self.velocity_threshold_decline = 10  # 播放量/小时，极低速度表示衰退
        self.stable_period_hours = 6  # 判断稳定期需要的最短时间（小时）

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行基于生命周期的预测

        算法流程：
            1. 检查历史数据是否充足（至少 3 个点）
            2. 提取播放量和时间序列
            3. 计算速度序列
            4. 判断当前所处的生命周期阶段
            5. 根据阶段选择对应的预测策略
            6. 综合阶段置信度和策略置信度

        Args:
            video_data (Dict[str, Any]): 视频数据字典
                - view_count (int)        : 当前总播放量
                - history_data (list[dict]): 历史数据点列表
            threshold (int): 目标播放量阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        # 数据太少（< 3 点）：无法判断阶段，使用简单预测
        if len(history) < 3:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.3, stage=LifecycleStage.INTRODUCTION, reason="insufficient_data",
            )

        # 提取播放量和时间序列
        views, timestamps = self._extract_series(history)

        if len(views) < 3:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.3, stage=LifecycleStage.INTRODUCTION, reason="short_series",
            )

        # 计算速度序列
        velocities, _ = self._calculate_velocity_series(views, timestamps)

        if len(velocities) < 2:
            velocity = velocities[-1] if len(velocities) > 0 else 0.0
            return self._make_result(
                current_views, threshold, velocity,
                confidence=0.4, stage=LifecycleStage.INTRODUCTION, reason="single_velocity",
            )

        # 判断当前生命周期阶段
        stage, reason, stage_confidence = self._determine_stage(views, velocities, timestamps, video_data)

        # 根据阶段选择预测策略
        predicted_velocity, confidence = self._predict_for_stage(stage, views, velocities, timestamps, video_data)

        # 综合置信度：不能超过阶段判断的置信度
        confidence = min(confidence, stage_confidence)

        return self._make_result(
            current_views, threshold, predicted_velocity, confidence=confidence, stage=stage, reason=reason
        )

    def _determine_stage(
        self, views: np.ndarray, velocities: np.ndarray, timestamps: np.ndarray, video_data: Dict
    ) -> Tuple[LifecycleStage, str, float]:
        """
        判断当前所处的生命周期阶段

        使用层次化的条件判断逻辑，按优先级从高到低检查：
            VIRAL > GROWTH > MATURITY > DECLINE > INTRODUCTION

        判断依据：
            - 当前速度 (current_vel): 速度的绝对水平
            - 加速度 (accel): 速度的变化趋势（正=上升，负=下降）
            - 速度稳定性 (vel_cv): 变异系数，越小越稳定
            - 视频年龄 (age_hours): 发布时间

        Args:
            views (np.ndarray)      : 播放量序列
            velocities (np.ndarray) : 速度序列
            timestamps (np.ndarray) : 时间戳序列
            video_data (Dict)       : 视频数据字典

        Returns:
            Tuple[LifecycleStage, str, float]: (阶段, 判断依据, 阶段置信度)
        """
        # 计算关键指标
        current_vel = velocities[-1]  # 最新速度
        avg_vel = np.mean(velocities)  # 平均速度
        np.max(velocities)  # 最大速度（预留）
        np.min(velocities)  # 最小速度（预留）

        # 计算加速度（最近 3 个速度值的变化趋势）
        accel = self._calculate_acceleration(velocities)

        # 视频年龄
        age_hours = self.get_video_age_hours(video_data)

        # 速度的标准差和变异系数（判断稳定性）
        vel_std = np.std(velocities)
        vel_cv = vel_std / (avg_vel + 1e-6)  # 变异系数 CV

        # ── 判断阶段（按优先级从高到低）─
        # 1. 病毒期：速度极快且仍在加速
        if current_vel >= self.velocity_threshold_viral and accel > 0:
            return LifecycleStage.VIRAL, "high_velocity_with_acceleration", 0.85

        # 2. 病毒期（减速）：速度极快但已开始减速（热度可能消退）
        if current_vel >= self.velocity_threshold_viral and accel <= 0:
            return LifecycleStage.VIRAL, "high_velocity_decelerating", 0.75

        # 3. 成长期：速度超过阈值且仍在加速
        if current_vel >= self.velocity_threshold_growth and accel > 0:
            return LifecycleStage.GROWTH, "velocity_above_threshold_accelerating", 0.8

        # 4. 成长期（稳定）：速度超过阈值但加速度接近 0
        if current_vel >= self.velocity_threshold_growth and abs(accel) < 0.1 * current_vel:
            return LifecycleStage.GROWTH, "velocity_above_threshold_stable", 0.75

        # 5. 成长期（减速）：速度超过阈值但开始减速，检查是否滑入成熟期
        if current_vel >= self.velocity_threshold_growth and accel < 0:
            # 减速到阈值一半以下 -> 可能进入成熟期
            if current_vel < self.velocity_threshold_growth * 0.5:
                return LifecycleStage.MATURITY, "velocity_declining_to_maturity", 0.7
            return LifecycleStage.GROWTH, "velocity_above_threshold_decelerating", 0.65

        # 6. 成熟期：速度在衰退阈值和增长阈值之间
        if current_vel < self.velocity_threshold_growth and current_vel >= self.velocity_threshold_decline:
            if vel_cv < 0.5:  # 速度稳定
                return LifecycleStage.MATURITY, "stable_low_velocity", 0.75
            else:
                return LifecycleStage.MATURITY, "unstable_low_velocity", 0.6

        # 7. 衰退期：速度极低
        if current_vel < self.velocity_threshold_decline:
            return LifecycleStage.DECLINE, "very_low_velocity", 0.8

        # 8. 导入期：默认阶段，如果是视频发布 24 小时内
        if age_hours < 24:
            return LifecycleStage.INTRODUCTION, "early_stage", 0.6

        # 默认：导入期
        return LifecycleStage.INTRODUCTION, "default", 0.5

    def _predict_for_stage(
        self, stage: LifecycleStage, views: np.ndarray, velocities: np.ndarray,
        timestamps: np.ndarray, video_data: Dict
    ) -> Tuple[float, float]:
        """
        根据生命周期阶段选择对应的预测策略

        各阶段策略：
            INTRODUCTION: 使用近期平均速度 + 趋势外推（2 小时外推）
            GROWTH:       使用近期速度，考虑增长惯性（加速时乘 1.1）
            MATURITY:     使用指数衰减模型，估计衰减率，保留最低 30%
            DECLINE:      使用长期衰减趋势，最低速度保持 1 播放/小时
            VIRAL:        加速期乘 1.2（继续走高），减速期乘 0.7（热度消退风险）

        Args:
            stage (LifecycleStage)  : 当前生命周期阶段
            views (np.ndarray)      : 播放量序列
            velocities (np.ndarray) : 速度序列
            timestamps (np.ndarray) : 时间戳序列
            video_data (Dict)       : 视频数据字典

        Returns:
            Tuple[float, float]: (预测速度, 置信度)
        """
        if stage == LifecycleStage.INTRODUCTION:
            # ── 导入期：使用近期平均速度 + 趋势外推 ──
            if len(velocities) >= 2:
                avg_vel = np.mean(velocities[-3:])  # 近期平均速度（最近 3 个点）
                # 考虑增长趋势：向外推 2 小时
                trend = self._calculate_acceleration(velocities)
                predicted_vel = avg_vel + trend * 2  # 外推 2 小时的预测速度
                confidence = 0.5
            else:
                predicted_vel = velocities[-1] if len(velocities) > 0 else 10.0
                confidence = 0.3

        elif stage == LifecycleStage.GROWTH:
            # ── 成长期：使用近期速度，考虑增长惯性 ──
            recent_vel = np.mean(velocities[-3:])  # 最近 3 个速度的均值
            accel = self._calculate_acceleration(velocities)

            if accel > 0:
                # 仍在加速中：预测速度略高于当前
                predicted_vel = recent_vel * 1.1  # 10% 惯性增长
                confidence = 0.75
            else:
                # 增速稳定或略有下降：直接用近期速度
                predicted_vel = recent_vel
                confidence = 0.7

        elif stage == LifecycleStage.MATURITY:
            # ── 成熟期：使用指数衰减模型 ──
            current_vel = velocities[-1]
            # 估计衰减率（基于近期速度下降）
            if len(velocities) >= 3:
                # 粗略估计：最近 3 个点的速度变化 / 时间
                decay_rate = (velocities[-3] - velocities[-1]) / (3 * 0.5)
                decay_rate = max(0, decay_rate)  # 衰减率不能为负（代表增长）
            else:
                decay_rate = current_vel * 0.1  # 默认 10%/周期的衰减率

            # 预测速度 = 当前速度 - 衰减率 * 2（线性衰减近似指数衰减）
            predicted_vel = current_vel - decay_rate * 2
            predicted_vel = max(predicted_vel, current_vel * 0.3)  # 最低保留 30%（不完全降为零）
            confidence = 0.7

        elif stage == LifecycleStage.DECLINE:
            # ── 衰退期：速度很低，使用长期趋势 ──
            if len(velocities) >= 3:
                # 计算长期衰减趋势（每个时间步的速度变化）
                long_term_slope = (velocities[-1] - velocities[0]) / len(velocities)
                predicted_vel = max(velocities[-1] + long_term_slope, 1.0)  # 最低保持 1 播放/小时
            else:
                predicted_vel = max(velocities[-1] * 0.8, 1.0)  # 20% 衰减
            confidence = 0.8  # 衰退期预测相对准确（因为没有大起大落）

        elif stage == LifecycleStage.VIRAL:
            # ── 病毒期：增长速度极快，但不确定性也极高 ──
            recent_vel = velocities[-1]
            accel = self._calculate_acceleration(velocities)

            if accel > 0:
                # 仍在加速（可能继续爆火）：预测速度乘 1.2
                predicted_vel = recent_vel * 1.2
                confidence = 0.6  # 病毒期不确定性高，置信度较低
            else:
                # 开始减速（热度消退风险高）：预测速度乘 0.7（大幅下调）
                predicted_vel = recent_vel * 0.7
                confidence = 0.65
        else:
            # ── 未知阶段：使用平均速度 ──
            predicted_vel = np.mean(velocities) if len(velocities) > 0 else 10.0
            confidence = 0.4

        return max(predicted_vel, 0.0), confidence

    def _calculate_acceleration(self, velocities: np.ndarray) -> float:
        """
        计算加速度：速度的变化率（二阶差分）

        使用最近 3 个速度值，通过简单差分计算：
            acceleration = (vel[-1] - vel[-3]) / 2

        Args:
            velocities (np.ndarray): 速度序列

        Returns:
            float: 加速度值（正数表示加速，负数表示减速）
        """
        if len(velocities) < 2:
            return 0.0

        # 使用最近 3 个点计算加速度
        recent = velocities[-min(3, len(velocities)) :]
        if len(recent) < 2:
            return 0.0

        # 简单差分
        accel = (recent[-1] - recent[0]) / (len(recent) - 1)
        return accel

    def _extract_series(self, history: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """
        从历史数据列表中提取播放量和时间戳序列

        处理多种时间戳格式（datetime 对象、字符串、数值），
        提取后按时间升序排序。

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
                t = t.timestamp()  # datetime 对象转为 Unix 时间戳
            elif isinstance(t, str):
                try:
                    from datetime import datetime as dt

                    t = dt.fromisoformat(t).timestamp()  # ISO 格式字符串解析
                except Exception:
                    continue  # 解析失败则跳过

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
        计算速度序列：相邻时间点的播放量增量除以时间增量（小时）

        Args:
            views (np.ndarray)      : 播放量数组
            timestamps (np.ndarray) : 时间戳数组

        Returns:
            Tuple[np.ndarray, np.ndarray]: (速度数组, 速度对应的时间戳数组)
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
        confidence: float, stage: LifecycleStage, reason: str
    ) -> PredictionResult:
        """
        构造预测结果对象

        Args:
            current_views (int)       : 当前播放量
            threshold (int)           : 目标播放量阈值
            velocity (float)          : 预测速度
            confidence (float)        : 置信度
            stage (LifecycleStage)    : 当前生命周期阶段
            reason (str)              : 阶段判断原因

        Returns:
            PredictionResult: 预测结果对象
        """

        if velocity <= 0:
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                predicted_hours = remaining / velocity

        metadata = {
            "stage": stage.value,  # 生命周期阶段名称（中文）
            "stage_reason": reason,  # 阶段判断依据
            "predicted_velocity": velocity,  # 预测速度
            "method": "lifecycle_based",  # 方法标识
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
