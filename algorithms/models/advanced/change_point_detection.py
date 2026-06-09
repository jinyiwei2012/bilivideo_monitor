"""
变化点检测算法 (Change Point Detection)
======================================

基于CUSUM（Cumulative Sum，累积和）控制图方法检测视频播放量增速的突变点。

核心原理：
    1. CUSUM 正向检测 - 累积正向偏差，当超过阈值时检测到加速变化点
    2. CUSUM 负向检测 - 累积负向偏差，当超过阈值时检测到减速变化点
    3. 标准化预处理 - 对速度序列进行 z-score 标准化，使阈值具有通用性
    4. 策略自适应 - 根据最近变化点的类型（加速/减速）动态调整预测速度

变化点类型：
    - acceleration (加速) : 播放量增长速度突然提升，可能是被推荐算法推送
    - deceleration (减速) : 播放量增长速度突然下降，可能热度消退
    - stable (稳定)       : 未检测到明显变化点，增长速度保持稳定

适用场景：
    - 需要检测视频是否被"推流"或热度消退
    - 需要动态调整预测策略以应对增速突变
    - 最少需要 6 个数据点进行可靠的变化点检测
"""

import numpy as np
from typing import Dict, Any, List, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class ChangePointDetectionAlgorithm(BaseAlgorithm):
    """
    变化点检测算法

    主要功能：
        - 使用 CUSUM 算法检测播放量增速的突变点
        - 根据最近变化点的类型（加速/减速）动态调整预测速度
        - 数据不足时回退为简单速度外推

    检测流程：
        1. 从历史数据中提取播放量和时间戳序列
        2. 计算相邻时间点之间的速度序列（播放量/小时）
        3. 对速度序列进行 z-score 标准化
        4. 同时运行正向和负向 CUSUM 检测
        5. 分析最近变化点的类型，决定预测策略

    类属性：
        name (str)            : "变化点检测"
        algorithm_id (str)    : "change_point_detection"
        category (str)        : "统计模型"
        default_weight (float): 1.3
        cusum_threshold (float): 2.0 (CUSUM 检测阈值，标准差的倍数)
        min_data_points (int) : 6 (最少需要的数据点数)
    """

    name = "变化点检测"
    algorithm_id = "change_point_detection"
    description = "检测播放量增速突变点，动态调整预测策略"
    category = "统计模型"
    default_weight = 1.3

    def __init__(self):
        """
        初始化变化点检测算法

        设置 CUSUM 算法的检测参数：
            cusum_threshold : 2.0 (累积和超过此值，以标准差为单位，触发变化点检测)
            min_data_points  : 6 (最少数据点数，低于此值使用简单速度外推)
        """
        super().__init__()
        self.cusum_threshold = 2.0  # CUSUM 检测阈值（标准差的倍数）
        self.min_data_points = 6  # 最少需要的数据点数

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行变化点检测并生成预测

        算法流程：
            1. 检查历史数据是否充足（至少 min_data_points 个点）
            2. 提取播放量和时间戳序列（已排序）
            3. 计算速度序列（相邻时间点的播放量增量/时间增量）
            4. 使用 CUSUM 算法检测速度序列的变化点
            5. 根据最近变化点的类型调整预测速度和置信度
            6. 数据不足时回退为简单速度外推

        Args:
            video_data (Dict[str, Any]): 包含视频数据的字典，期望字段：
                - view_count (int)        : 当前总播放量
                - history_data (list[dict]): 历史数据点列表
                  每个点含 view_count 或 view、timestamp
            threshold (int): 目标播放量阈值，默认为 100,000

        Returns:
            PredictionResult: 预测结果对象，metadata 中包含检测到的变化点信息
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        # 数据不足：使用简单速度预测
        if len(history) < self.min_data_points:
            velocity = self._calculate_simple_velocity(history)
            return self._make_result(
                current_views, threshold, velocity, confidence=0.3, change_points=[], strategy="insufficient_data"
            )

        # 提取播放量和时间序列
        views, timestamps = self._extract_series(history)

        if len(views) < self.min_data_points:
            velocity = self._calculate_simple_velocity(history)
            return self._make_result(
                current_views, threshold, velocity, confidence=0.3, change_points=[], strategy="insufficient_data"
            )

        # 计算速度序列（相邻时间点的播放量增量/时间增量）
        velocities, vel_timestamps = self._calculate_velocity_series(views, timestamps)

        if len(velocities) < 4:
            # 速度点不足，使用最后一个速度值
            velocity = velocities[-1] if velocities else 0.0
            return self._make_result(
                current_views, threshold, velocity, confidence=0.4, change_points=[], strategy="short_series"
            )

        # 使用 CUSUM 检测变化点
        change_points = self._detect_cusum(velocities)

        # 根据变化点调整预测策略
        strategy, adjusted_velocity, confidence = self._adjust_prediction(velocities, change_points, video_data)

        return self._make_result(
            current_views,
            threshold,
            adjusted_velocity,
            confidence=confidence,
            change_points=change_points,
            strategy=strategy,
            velocities=velocities,
        )

    def _extract_series(self, history: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """
        从历史数据列表中提取播放量和时间戳序列

        处理多种时间戳格式：
            - datetime 对象：通过 .timestamp() 转换为 Unix 时间戳
            - 字符串       ：通过 fromisoformat 解析后转换
            - 数值         ：直接使用（视为 Unix 时间戳）

        提取后按时间升序排序，确保序列按时间先后排列。

        Args:
            history (List[Dict]): 历史数据点列表

        Returns:
            Tuple[np.ndarray, np.ndarray]: (播放量数组, 时间戳数组)，已按时间排序
        """
        views = []
        timestamps = []

        for entry in history:
            v = entry.get("view_count", entry.get("view", 0))
            t = entry.get("timestamp", 0)

            # 处理多种时间戳格式
            # datetime 对象：提取 Unix 时间戳
            if hasattr(t, "timestamp"):
                t = t.timestamp()
            elif isinstance(t, str):
                # ISO 格式字符串：解析后转换
                try:
                    from datetime import datetime as dt

                    t = dt.fromisoformat(t).timestamp()
                except Exception:
                    continue  # 解析失败则跳过该数据点

            # 只保留有效正值数据
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
        计算速度序列：相邻时间点的播放量增量除以时间增量

        公式：velocity_i = (views[i] - views[i-1]) / ((timestamps[i] - timestamps[i-1]) / 3600)

        Args:
            views (np.ndarray)      : 播放量数组（已按时间排序）
            timestamps (np.ndarray) : 时间戳数组（已按时间排序）

        Returns:
            Tuple[np.ndarray, np.ndarray]: (速度数组, 速度对应的时间戳数组)
        """
        if len(views) < 2:
            return np.array([]), np.array([])

        velocities = []
        vel_times = []

        for i in range(1, len(views)):
            dt = (timestamps[i] - timestamps[i - 1]) / 3600.0  # 时间差转换为小时
            if dt <= 0:
                continue  # 跳过非正时间差
            dv = views[i] - views[i - 1]  # 播放量变化量
            velocity = dv / dt  # 播放量/小时
            velocities.append(velocity)
            vel_times.append(timestamps[i])

        return np.array(velocities), np.array(vel_times)

    def _detect_cusum(self, series: np.ndarray) -> List[Dict]:
        """
        使用 CUSUM（累积和）算法检测速度序列中的变化点

        CUSUM 原理：
            标准化序列 z_i = (x_i - mean) / std
            正向 CUSUM: S+_i = max(0, S+_{i-1} + z_i - k)
            负向 CUSUM: S-_i = max(0, S-_{i-1} - z_i - k)
            其中 k 是松弛因子 (0.5)，避免微小波动触发检测

            当 S+_i > threshold 时，检测到正向变化点（加速）
            当 S-_i > threshold 时，检测到负向变化点（减速）
            检测到变化点后立即重置对应的累积和

        Args:
            series (np.ndarray): 速度序列

        Returns:
            List[Dict]: 检测到的变化点列表，每个变化点包含：
                - index (int)       : 在速度序列中的位置索引
                - type (str)        : "acceleration"（加速）或 "deceleration"（减速）
                - magnitude (float) : 变化幅度（与均值的偏差）
                - cusum_value (float): 触发检测时的累积和值
        """
        if len(series) < 4:
            return []

        # z-score 标准化：使序列均值为 0、标准差为 1
        mean = np.mean(series)
        std = np.std(series)

        if std == 0:
            return []  # 方差为零，不存在变化

        normalized = (series - mean) / std  # 标准化后的序列

        # 初始化正向和负向 CUSUM
        cusum_pos = np.zeros(len(normalized))  # 正向 CUSUM（检测加速）
        cusum_neg = np.zeros(len(normalized))  # 负向 CUSUM（检测减速）

        change_points = []

        for i in range(1, len(normalized)):
            # 正向 CUSUM：累积正向偏差（减 0.5 作为松弛因子）
            cusum_pos[i] = max(0, cusum_pos[i - 1] + normalized[i] - 0.5)
            # 负向 CUSUM：累积负向偏差
            cusum_neg[i] = max(0, cusum_neg[i - 1] - normalized[i] - 0.5)

            # 检测到加速变化点
            if cusum_pos[i] > self.cusum_threshold:
                change_points.append(
                    {
                        "index": i,
                        "type": "acceleration",  # 增速突变（加速）
                        "magnitude": float(series[i] - mean),  # 当前速度与均值的偏差
                        "cusum_value": float(cusum_pos[i]),  # 累积和值
                    }
                )
                cusum_pos[i] = 0  # 检测后重置，继续检测后续变化点

            # 检测到减速变化点
            elif cusum_neg[i] > self.cusum_threshold:
                change_points.append(
                    {
                        "index": i,
                        "type": "deceleration",  # 增速突变（减速）
                        "magnitude": float(mean - series[i]),  # 均值与当前速度的偏差
                        "cusum_value": float(cusum_neg[i]),  # 累积和值
                    }
                )
                cusum_neg[i] = 0  # 检测后重置

        return change_points

    def _adjust_prediction(
        self, velocities: np.ndarray, change_points: List[Dict], video_data: Dict
    ) -> Tuple[str, float, float]:
        """
        根据检测到的变化点调整预测策略

        策略分类：
            - stable (稳定)           : 无变化点，使用近期平均速度，置信度 0.7
            - post_change_stable (变化后稳定) : 变化点较旧，影响减弱，置信度 0.65
            - accelerating (加速中)   : 近期加速，速度乘 1.2（预留惯性增长），置信度 0.75
            - post_acceleration (加速后) : 加速后趋于稳定，速度乘 1.1，置信度 0.7
            - decelerating (减速中)   : 近期减速，速度乘 0.8（保守下调），置信度 0.6

        Args:
            velocities (np.ndarray)      : 速度序列
            change_points (List[Dict])   : 检测到的变化点列表
            video_data (Dict)            : 视频数据字典

        Returns:
            Tuple[str, float, float]: (策略名称, 调整后的速度, 置信度)
        """
        if not change_points:
            # 无变化点：使用近期平均速度
            recent_vel = np.mean(velocities[-3:]) if len(velocities) >= 3 else velocities[-1]
            return "stable", max(0, recent_vel), 0.7

        # 检查最近的变化点（最近 3 个数据点内）
        recent_window = min(3, len(velocities))
        recent_change = None

        for cp in reversed(change_points):
            if cp["index"] >= len(velocities) - recent_window:
                recent_change = cp
                break

        if recent_change is None:
            # 变化点较旧，影响已减弱
            recent_vel = np.mean(velocities[-3:])
            return "post_change_stable", max(0, recent_vel), 0.65

        # 根据最近变化点类型调整预测
        if recent_change["type"] == "acceleration":
            # 近期在加速：使用基类推流检测获取更精确的衰减因子
            current_vel = velocities[-1]
            acceleration = self._estimate_acceleration(velocities)

            # 尝试使用基类推流检测来修正
            surge_info = self.detect_surge(video_data)
            if surge_info.get("is_surging"):
                # 检测到推流 → 使用衰减模型而非简单乘数
                surge_mag = surge_info["surge_magnitude"]
                decay_factor = self.get_surge_decay_factor(video_data, hours_ahead=2.0)

                if surge_info["surge_type"] == "strong":
                    # 强推流：大幅衰减，快速回归基线
                    base_vel = surge_info.get("baseline_velocity", current_vel * 0.3)
                    adjusted_vel = base_vel + (current_vel - base_vel) * decay_factor
                    strategy = "surge_strong_decaying"
                    confidence = 0.70
                elif surge_info["surge_type"] == "moderate":
                    adjusted_vel = current_vel * (0.5 + 0.5 * decay_factor)
                    strategy = "surge_moderate_decaying"
                    confidence = 0.72
                else:
                    adjusted_vel = current_vel * (0.6 + 0.4 * decay_factor)
                    strategy = "surge_mild_decaying"
                    confidence = 0.74
            elif acceleration > 0:
                # 有机加速（非推流）：适度上调
                adjusted_vel = current_vel * 1.2
                strategy = "accelerating"
                confidence = 0.75
            else:
                # 加速后趋于稳定
                adjusted_vel = current_vel * 1.1
                strategy = "post_acceleration"
                confidence = 0.7

        elif recent_change["type"] == "deceleration":
            # 近期在减速：降低速度预测
            current_vel = velocities[-1]
            adjusted_vel = current_vel * 0.8  # 减速因子 0.8
            strategy = "decelerating"
            confidence = 0.6
        else:
            adjusted_vel = velocities[-1]
            strategy = "unknown_change"
            confidence = 0.5

        return strategy, max(0, adjusted_vel), confidence

    def _estimate_acceleration(self, velocities: np.ndarray) -> float:
        """
        估算加速度：速度的变化率（即速度的差分/二阶差分）

        使用最近 3 个速度值，通过简单差分计算：
            acceleration = (vel[-1] - vel[-3]) / 2
        正值表示加速，负值表示减速。

        Args:
            velocities (np.ndarray): 速度序列（至少 3 个值）

        Returns:
            float: 加速度值（正数表示加速，负数表示减速）
        """
        if len(velocities) < 3:
            return 0.0

        # 使用最近 3 个速度值计算差分
        recent = velocities[-3:]
        accel = (recent[-1] - recent[0]) / (len(recent) - 1)  # 简单差分
        return accel

    def _calculate_simple_velocity(self, history: List[Dict]) -> float:
        """
        计算简单速度（数据不足时使用）

        使用最近两个数据点计算速度：
            速度 = (播放量差) / (时间差，小时)

        Args:
            history (List[Dict]): 历史数据点列表

        Returns:
            float: 简单速度值（播放量/小时）
        """
        if len(history) < 2:
            return 0.0

        try:
            recent = history[-2:]
            v0 = float(recent[0].get("view_count", 0))
            v1 = float(recent[-1].get("view_count", 0))

            t0 = recent[0].get("timestamp", 0)
            t1 = recent[-1].get("timestamp", 0)

            # 处理多种时间戳格式
            if hasattr(t0, "timestamp"):
                t0 = t0.timestamp()
            elif isinstance(t0, str):
                from datetime import datetime as dt

                t0 = dt.fromisoformat(t0).timestamp()

            if hasattr(t1, "timestamp"):
                t1 = t1.timestamp()
            elif isinstance(t1, str):
                from datetime import datetime as dt

                t1 = dt.fromisoformat(t1).timestamp()

            dt_hours = (t1 - t0) / 3600.0  # 时间差转换为小时
            if dt_hours <= 0:
                return 0.0

            return max(0.0, (v1 - v0) / dt_hours)
        except Exception:
            return 0.0

    def _make_result(
        self,
        current_views: int,
        threshold: int,
        velocity: float,
        confidence: float,
        change_points: List[Dict],
        strategy: str,
        velocities: np.ndarray = None,
    ) -> PredictionResult:
        """
        构造预测结果对象

        根据速度和剩余播放量计算预测时间。如果速度为非正值或已达标，
        则相应调整预测时间和置信度。同时将检测到的变化点信息写入 metadata。

        Args:
            current_views (int)         : 当前播放量
            threshold (int)             : 目标播放量阈值
            velocity (float)            : 预测速度（播放量/小时）
            confidence (float)          : 置信度
            change_points (List[Dict])  : 检测到的变化点列表
            strategy (str)              : 预测策略名称
            velocities (np.ndarray, optional): 速度序列（用于 metadata）

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

        # 构造元数据：包含变化点检测的完整诊断信息
        metadata = {
            "strategy": strategy,
            "change_points": change_points,
            "change_point_count": len(change_points),
            "recent_velocity": float(velocities[-1]) if velocities is not None and len(velocities) > 0 else velocity,
            "velocity_trend": self._get_velocity_trend(velocities) if velocities is not None else "unknown",
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

    def _get_velocity_trend(self, velocities: np.ndarray) -> str:
        """
        判断速度序列的总体趋势

        使用 np.polyfit 对速度序列做一次多项式（线性）拟合，根据斜率判断趋势：
            - accelerating (加速) : 斜率 > 10% 的平均速度
            - decelerating (减速) : 斜率 < -10% 的平均速度
            - stable (稳定)       : 斜率在 -10% ~ 10% 之间
            - insufficient_data   : 数据点不足 3 个

        Args:
            velocities (np.ndarray): 速度序列

        Returns:
            str: 趋势描述字符串
        """
        if len(velocities) < 3:
            return "insufficient_data"

        # 使用简单线性回归判断趋势
        x = np.arange(len(velocities), dtype=np.float64)
        y = np.asarray(velocities, dtype=np.float64)

        # 用 np.polyfit 拟合一次多项式，避免大数溢出
        slope = np.polyfit(x, y, 1)[0]  # 一次项系数即斜率

        # 根据斜率相对值判断趋势
        if slope > 0.1 * np.mean(velocities):
            return "accelerating"
        elif slope < -0.1 * np.mean(velocities):
            return "decelerating"
        else:
            return "stable"
