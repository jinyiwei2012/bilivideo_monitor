"""
Hawkes过程（自激点过程）预测
通过自激励机制模拟B站视频播放量的级联扩散和病毒式传播
"""
import math
import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class HawkesProcessAlgorithm(BaseAlgorithm):
    """Hawkes 自激点过程 (Self-Exciting Point Process)

    B 站视频播放量的增长具有自激励特性：一个视频获得播放后，
    可能通过推荐算法触发更多播放（级联效应）。

    Hawkes 过程的强度函数：
    λ(t) = μ + Σ φ(t - t_i)
    其中 μ 是基础强度，φ 是自激励核函数（通常为幂律衰减）

    参考: Dong et al. (2022), "Universal scaling behavior and
          Hawkes process of videos' views on Bilibili.com"
    """

    name = "Hawkes自激过程"
    algorithm_id = "hawkes_process"
    description = "自激点过程模拟播放量的级联扩散效应"
    category = "高级分析"
    default_weight = 1.35

    def __init__(self):
        super().__init__()
        self.mu = 0.1          # 基础强度
        self.kappa = 0.3       # 激励强度
        self.theta = 1.2       # 幂律衰减指数
        self.c = 1.0           # 截止参数

    def _power_law_kernel(self, tau: float) -> float:
        """幂律衰减核函数: φ(τ) = κ * (τ + c)^{-(1+θ)}"""
        if tau < 0:
            return 0.0
        return self.kappa * (tau + self.c) ** (-(1 + self.theta))

    def _compute_intensity(self, events: np.ndarray,
                           t_current: float) -> float:
        """计算给定时刻的强度"""
        base = self.mu
        if len(events) == 0:
            return base

        excitation = 0.0
        for t in events:
            tau = t_current - t
            if tau > 0:
                excitation += self._power_law_kernel(tau)
        return base + excitation

    def predict(self, video_data: Dict[str, Any],
                threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get('view_count', 0)
        history = video_data.get('history_data', [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=0, confidence=1.0,
                current_views=current_views, current_velocity=velocity,
                metadata={'method': 'hawkes'}, timestamp=datetime.now()
            )

        if len(history) < 4 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float('inf')
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views,
                current_velocity=velocity,
                metadata={'method': 'hawkes', 'notes': 'insufficient_data'},
                timestamp=datetime.now()
            )

        # 提取时序
        timestamps = []
        views_vals = []
        for h in history:
            ts = h.get('timestamp', 0)
            if hasattr(ts, 'timestamp'):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S').timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get('view_count', 0)))

        if len(views_vals) < 4:
            predicted_hours = remaining / velocity
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views,
                current_velocity=velocity,
                metadata={'method': 'hawkes_fallback'}, timestamp=datetime.now()
            )

        try:
            order = np.argsort(timestamps)
            times = np.array(timestamps, dtype=float)[order]
            views_arr = np.array(views_vals, dtype=float)[order]

            n = len(views_arr)
            start_time = times[0]
            elapsed_hours = (times[-1] - start_time) / 3600.0
            now = times[-1]

            quality = self.get_quality_score(video_data)
            engagement = self.get_engagement_rate(video_data)

            # ── 将播放量增量的时间点作为"事件" ─────────
            # 增量较大时视为"子事件"（推荐带来的播放潮）
            increments = np.diff(views_arr)
            time_diffs = np.diff(times)

            # 构造事件列表：每达到一定增量记为一个事件
            events = []
            cumulative = 0
            event_threshold = max(50, current_views * 0.005)  # 事件阈值
            for i in range(len(increments)):
                cumulative += increments[i]
                if cumulative >= event_threshold:
                    events.append(times[i + 1])
                    cumulative = 0

            if len(events) < 2:
                events = times[1:]  # 如果没有足够事件，用所有时间点

            events = np.array(events)

            # ── 参数估计 (基于数据适配) ─────────────────
            self.mu = max(0.01, velocity / 3600.0 * 0.1)  # 基础强度
            # 激励强度参数与互动率相关
            self.kappa = 0.2 + 0.4 * (quality * 0.6 + engagement * 0.4)
            # 网红视频衰减更慢
            self.theta = 1.5 - 0.5 * engagement
            # 质量分越高，截止参数越大
            self.c = 1.0 + 2.0 * quality

            # ── 计算当前强度 ──────────────────────────
            current_intensity = self._compute_intensity(events, now)
            # 转换为小时播放速度
            hawkes_velocity = current_intensity * event_threshold * 3600

            # 综合 Hawkes 速度与实测速度
            adjusted_velocity = velocity * 0.4 + hawkes_velocity * 0.6
            if adjusted_velocity <= 0:
                adjusted_velocity = velocity

            # ── 分支比（衡量病毒性） ──────────────────
            # ∫_0^∞ φ(τ)dτ = κ / (θ * c^θ)
            branching_ratio = self.kappa / (self.theta * (self.c ** self.theta))
            # 分支比 > 1 => 超临界（病毒式传播）
            is_viral = branching_ratio > 1.0

            # ── 预测 ─────────────────────────────────
            hourly_growth = adjusted_velocity
            forecast_hours_est = remaining / max(hourly_growth, 0.1)
            forecast_hours = min(8760, max(24, forecast_hours_est))

            pred_views = float(current_views)
            target_hour = None

            for hour in range(1, min(int(forecast_hours) + 24, 8760)):
                t_future = now + hour * 3600

                # 自激励强度随时间衰减
                future_intensity = self._compute_intensity(events, t_future)
                future_hourly = future_intensity * event_threshold * 3600

                # 病毒式传播的加速效应
                if is_viral:
                    acceleration = 1.0 + 0.3 * math.exp(-hour / 48.0)
                else:
                    acceleration = 1.0 - 0.2 * (1.0 - math.exp(-hour / 72.0))

                hour_growth = future_hourly * acceleration * (1.0 / 3600.0)
                pred_views += max(0, hour_growth)

                if pred_views >= threshold:
                    target_hour = hour
                    break

            if target_hour is not None and target_hour <= 8760:
                predicted_hours = target_hour
                data_qual = min(1.0, n / 20)
                event_qual = min(1.0, len(events) / 10)
                viral_conf = min(1.0, abs(branching_ratio - 1.0) * 0.5) if is_viral else 0.1
                conf = min(0.9, 0.3 + 0.2 * data_qual + 0.15 * event_qual + 0.1 * viral_conf + 0.1 * quality)
            else:
                predicted_hours = remaining / velocity
                conf = 0.3

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=conf, current_views=current_views,
                current_velocity=adjusted_velocity,
                metadata={
                    'method': 'hawkes',
                    'branching_ratio': round(float(branching_ratio), 3),
                    'is_viral': is_viral,
                    'current_intensity': round(float(current_intensity), 4),
                    'n_events': len(events),
                    'hawkes_velocity': round(float(hawkes_velocity), 2),
                    'data_points': n,
                },
                timestamp=datetime.now()
            )
        except Exception as e:
            predicted_hours = remaining / velocity if velocity > 0 else float('inf')
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.0, current_views=current_views,
                current_velocity=velocity,
                metadata={'error': str(e)}, timestamp=datetime.now()
            )
