"""
Hawkes 自激点过程预测算法 (Hawkes Self-Exciting Process)
=======================================================

基于自激点过程 (Self-Exciting Point Process) 模拟 B 站视频播放量的
级联扩散和病毒式传播效应。

核心原理：
    1. 自激励机制 - 视频的每次播放都可能触发推荐算法产生更多播放，
       形成正反馈循环（级联效应/虚拟传播）
    2. 强度函数 - 当前时刻的播放强度 = 基础强度 mu + 历史事件的自激贡献和
       lambda(t) = mu + sum(phi(t - t_i))
    3. 幂律衰减核 - 每个历史事件的影响力随时间按幂律衰减
       phi(tau) = kappa * (tau + c)^{-\theta}
    4. 分支比 - 衡量病毒性的关键指标
       branching_ratio = integral(phi(tau) dtau) = kappa / (theta * c^theta)
       分支比 > 1 表示超级临界（病毒式传播），新播放带来更多新播放

参数自适应：
    - mu (基础强度): 基于当前速度动态调整
    - kappa (激励强度): 基于视频质量分和互动率调整
    - theta (衰减指数): 网红视频（高互动率）衰减更慢
    - c (截止参数): 基于视频质量分调整

参考文献：
    Dong et al. (2022), "Universal scaling behavior and
    Hawkes process of videos' views on Bilibili.com"
"""

import math
import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class HawkesProcessAlgorithm(BaseAlgorithm):
    """
    Hawkes 自激点过程预测算法

    主要功能：
        - 使用幂律衰减核函数模拟历史播放对当前播放的激励效应
        - 基于视频特征（质量分、互动率）自适应调整模型参数
        - 计算分支比判断视频是否处于病毒性传播阶段
        - 对病毒性视频施加加速因子，对普通视频施加衰减因子

    强度函数的截断优化：
        由于幂律衰减核在 tau 很大时趋近于 0，对超过 168 小时（1 周）
        的历史事件进行截断，以加速计算，同时误差 < 1%。

    B 站视频播放量增长具有自激励特性：
        一个视频获得播放后，可能通过推荐算法触发更多播放（级联效应）。
    Hawkes 过程的强度函数：
        lambda(t) = mu + sum(phi(t - t_i))
        其中 mu 是基础强度，phi 是自激励核函数（通常为幂律衰减）
    """

    name = "Hawkes自激过程"
    algorithm_id = "hawkes_process"
    description = "自激点过程模拟播放量的级联扩散效应"
    category = "高级分析"
    default_weight = 1.35

    def __init__(self):
        """
        初始化 Hawkes 过程算法

        设置模型默认参数：
            mu (float)    : 0.1 (基础强度，每秒钟的基础播放概率)
            kappa (float) : 0.3 (激励强度，每次播放带来的额外播放)
            theta (float) : 1.2 (幂律衰减指数，控制记忆衰减速度)
            c (float)     : 1.0 (截止参数，确保核函数在 tau=0 时不发散)
        """
        super().__init__()
        self.mu = 0.1  # 基础强度因子
        self.kappa = 0.3  # 激励强度因子
        self.theta = 1.2  # 幂律衰减指数（theta 越大衰减越快）
        self.c = 1.0  # 截止参数（避免 tau=0 时分母为零）

    def _power_law_kernel(self, tau: float) -> float:
        """
        幂律衰减核函数

        公式：phi(tau) = kappa * (tau + c)^{-(1+theta)}
        参数：
            - kappa: 激励强度
            - (tau + c)^{-(1+theta)}: 幂律衰减因子，随时间推移贡献减小

        当 tau 为负时返回 0（未来时间不在核函数覆盖范围）。

        Args:
            tau (float): 当前时间与历史事件的时间差（秒）

        Returns:
            float: 该历史事件对当前强度的贡献
        """
        if tau < 0:
            return 0.0  # 负时间差无意义
        return self.kappa * (tau + self.c) ** (-(1 + self.theta))

    def _compute_intensity(self, events: np.ndarray, t_current: float) -> float:
        """
        计算给定时刻的 Hawkes 过程强度

        强度 = 基础强度 mu + 所有历史事件的自激贡献之和
        对超过 168 小时（1 周）的历史事件进行截断优化，
        因为此时核函数值已衰减到初始值的 1% 以下，贡献可忽略。

        Args:
            events (np.ndarray): 历史事件时间戳数组（秒）
            t_current (float)   : 当前评估时刻（秒）

        Returns:
            float: 当前时刻的 Hawkes 过程强度
        """
        base = self.mu  # 基础强度：即使没有任何历史事件也有的基础播放概率
        if len(events) == 0:
            return base  # 无历史事件，仅返回基础强度

        excitation = 0.0
        cutoff = 168 * 3600  # 截断时间 = 1 周（秒），核函数值 < 初始值的 1%
        for t in events:
            tau = t_current - t  # 时间差
            if tau > cutoff:
                continue  # 截断：足够旧的事件贡献可忽略
            if tau > 0:
                excitation += self._power_law_kernel(tau)  # 累加自激贡献
        return base + excitation  # 总强度 = 基础 + 自激贡献

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行 Hawkes 过程预测

        算法流程：
            1. 检查是否已达标（已达标则直接返回）
            2. 检查数据是否充足（< 4 个点或速度 <= 0 则回退）
            3. 提取并排序历史播放量和时间戳序列
            4. 构造"事件"列表（每达到一定增量记为一个事件）
            5. 基于视频特征自适应调整模型参数
            6. 计算当前强度和 Hawkes 预测速度
            7. 计算分支比判断病毒性
            8. 对未来的每个小时做递推预测，直到达到目标或超过 1 年

        Args:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            # 已达标，直接返回
            return self._make_result(0, 1.0, current_views, velocity, {"method": "hawkes"}, threshold)

        if len(history) < 4 or velocity <= 0:
            # 数据不足或速度非正，使用简单速度外推
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return self._make_result(
                predicted_hours, 0.3, current_views, velocity,
                {"method": "hawkes", "notes": "insufficient_data"}, threshold,
            )

        views_data = self._extract_views(history)
        if views_data is None:
            return self._make_result(
                remaining / velocity, 0.3, current_views, velocity,
                {"method": "hawkes_fallback"}, threshold,
            )

        views_arr, times = views_data
        try:
            return self._predict_impl(views_arr, times, current_views, velocity, remaining, threshold, video_data)
        except Exception as e:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return self._make_result(predicted_hours, 0.0, current_views, velocity, {"error": str(e)}, threshold)

    def _extract_views(self, history):
        """
        从历史记录中提取并排序播放量序列和时间戳

        处理多种时间戳格式，按时间升序排序。

        Args:
            history (list): 历史数据点列表

        Returns:
            tuple or None: (播放量数组, 时间戳数组) 或 None（数据不足时）
        """
        timestamps, views_vals = [], []
        for h in history:
            ts = h.get("timestamp", 0)
            # 处理多种时间戳格式
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(str(ts)[:19].replace("T", " ")).timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))
        if len(views_vals) < 4:
            return None  # 数据点不足
        # 按时间升序排序
        order = np.argsort(timestamps)
        return np.array(views_vals, dtype=float)[order], np.array(timestamps, dtype=float)[order]

    def _predict_impl(self, views_arr, times, current_views, velocity, remaining, threshold, video_data):
        """
        执行 Hawkes 过程核心预测逻辑

        步骤：
            1. 计算播放量增量的时间点作为"事件"
            2. 基于视频特征自适应调整参数
            3. 计算当前强度和 Hawkes 速度
            4. 计算分支比判断病毒性
            5. 逐小时递推预测，考虑自激强度衰减和病毒性加速/衰减

        Args:
            views_arr (np.ndarray): 播放量数组
            times (np.ndarray)    : 时间戳数组
            current_views (int)   : 当前播放量
            velocity (float)      : 当前速度
            remaining (int)       : 剩余播放量
            threshold (int)       : 目标阈值
            video_data (Dict)     : 视频数据字典

        Returns:
            PredictionResult: 预测结果对象
        """
        n = len(views_arr)
        start_time = times[0]
        (times[-1] - start_time) / 3600.0  # 视频年龄（小时，用于调试）
        now = times[-1]  # 当前时刻（Unix 时间戳）

        quality = self.get_quality_score(video_data)  # 视频质量分
        engagement = self.get_engagement_rate(video_data)  # 视频互动率

        # 将播放量增量的时间点作为"事件"
        # 增量较大时视为"子事件"（推荐带来的播放潮）
        increments = np.diff(views_arr)  # 相邻时间点的播放量增量
        np.diff(times)  # 相邻时间点的时间差（用于调试）

        # 构造事件列表：每达到一定增量记为一个事件
        events = []
        cumulative = 0
        event_threshold = max(50, current_views * 0.005)  # 事件阈值：至少 50 或 0.5% 的总播放量
        for i in range(len(increments)):
            cumulative += increments[i]
            if cumulative >= event_threshold:  # 累积增量超过阈值时记录一个事件
                events.append(times[i + 1])  # 记录事件发生的时间
                cumulative = 0  # 重置累积计数

        if len(events) < 2:
            events = times[1:]  # 如果没有足够事件，用所有时间点

        events = np.array(events)

        # 参数估计（基于数据自适应调整）
        self.mu = max(0.01, velocity / 3600.0 * 0.1)  # 基础强度 = 当前速度的 10%
        # 激励强度与视频质量分和互动率相关
        self.kappa = 0.2 + 0.4 * (quality * 0.6 + engagement * 0.4)
        # 网红视频（高互动率）衰减更慢：theta 更小意味着核函数拖尾更长
        self.theta = 1.5 - 0.5 * engagement
        # 质量分越高，截止参数越大（核函数在 tau=0 处值更小但衰减更慢）
        self.c = 1.0 + 2.0 * quality

        # 计算当前 Hawkes 强度并转换为小时播放速度
        current_intensity = self._compute_intensity(events, now)
        hawkes_velocity = current_intensity * event_threshold * 3600  # 转换为播放量/小时

        # 综合 Hawkes 速度（60%）与实测速度（40%）
        adjusted_velocity = velocity * 0.4 + hawkes_velocity * 0.6
        if adjusted_velocity <= 0:
            adjusted_velocity = velocity  # 速度过小时退化为当前速度

        # 分支比：衡量病毒性的关键指标
        # 分支比 = integral_0^inf phi(tau) dtau = kappa / (theta * c^theta)
        branching_ratio = self.kappa / (self.theta * (self.c ** self.theta))
        # 分支比 > 1 意味着超临界（病毒式传播），每次播放带来 > 1 次新播放
        is_viral = branching_ratio > 1.0

        # 预测：逐小时递推
        hourly_growth = adjusted_velocity
        forecast_hours_est = remaining / max(hourly_growth, 0.1)  # 粗略估计预测时间
        forecast_hours = min(8760, max(24, forecast_hours_est))  # 钳制在 [24h, 1年]

        pred_views = float(current_views)  # 初始化预测播放量
        target_hour = None

        for hour in range(1, min(int(forecast_hours) + 24, 8760)):
            t_future = now + hour * 3600  # 未来时刻

            # 计算该时刻的 Hawkes 强度（自激励强度随时间衰减）
            future_intensity = self._compute_intensity(events, t_future)
            future_hourly = future_intensity * event_threshold * 3600  # 未来小时播放速度

            # 病毒性传播的加速效应 vs 普通视频的衰减效应
            if is_viral:
                # 病毒性视频：初期加速（30%），随时间衰减
                acceleration = 1.0 + 0.3 * math.exp(-hour / 48.0)
            else:
                # 普通视频：初期保持，后期逐渐减速（最多 20%）
                acceleration = 1.0 - 0.2 * (1.0 - math.exp(-hour / 72.0))

            hour_growth = future_hourly * acceleration * (1.0 / 3600.0)  # 该小时的播放增量
            pred_views += max(0, hour_growth)  # 累加播放量

            if pred_views >= threshold:
                target_hour = hour  # 达到目标阈值
                break

        if target_hour is not None and target_hour <= 8760:
            predicted_hours = target_hour
            # 计算置信度：综合数据质量、事件数量、病毒性和视频质量分
            data_qual = min(1.0, n / 20)  # 数据质量指数
            event_qual = min(1.0, len(events) / 10)  # 事件质量指数
            viral_conf = min(1.0, abs(branching_ratio - 1.0) * 0.5) if is_viral else 0.1  # 病毒性置信度
            conf = min(0.9, 0.3 + 0.2 * data_qual + 0.15 * event_qual + 0.1 * viral_conf + 0.1 * quality)
        else:
            predicted_hours = remaining / velocity  # 超出预测范围，回退为速度外推
            conf = 0.3

        return self._make_result(
            predicted_hours, conf, current_views, adjusted_velocity,
            {
                "method": "hawkes",
                "branching_ratio": round(float(branching_ratio), 3),  # 分支比（关键指标）
                "is_viral": is_viral,  # 是否处于病毒传播状态
                "current_intensity": round(float(current_intensity), 4),  # 当前 Hawkes 强度
                "n_events": len(events),  # 事件数量
                "hawkes_velocity": round(float(hawkes_velocity), 2),  # Hawkes 预测速度
                "data_points": n,  # 数据点数量
            },
            threshold,
        )

    def _make_result(self, predicted_hours, confidence, current_views, velocity, metadata, threshold):
        """
        构造 PredictionResult 对象

        Args:
            predicted_hours (float): 预测到达目标所需小时数
            confidence (float)     : 置信度
            current_views (int)    : 当前播放量
            velocity (float)       : 当前速度
            metadata (dict)        : 元数据
            threshold (int)        : 目标阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        metadata.setdefault("method", "hawkes")
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
