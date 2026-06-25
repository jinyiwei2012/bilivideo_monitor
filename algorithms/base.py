"""
预测算法基类

定义所有预测算法的统一抽象接口（BaseAlgorithm）和预测结果数据结构（PredictionResult）。
子类需实现 predict() 方法，并可复用基类提供的辅助方法计算播放速度、互动率等。
"""

import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple
from datetime import datetime
import time
from utils.time_utils import safe_timestamp

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PredictionResult:
    """预测结果 —— 存储单个算法对单个视频的预测产出。

    Attributes:
        algorithm_name: 算法可读名称
        algorithm_id:   算法唯一标识
        target_threshold: 目标播放量阈值（如 100000、1000000、10000000）
        predicted_hours:  预测达到目标阈值所需小时数
        confidence:       置信度，取值范围 [0, 1]
        current_views:    当前播放量
        current_velocity: 当前播放速度（播放量/小时）
        metadata:         额外元数据字典（如算法内部状态、特征值等）
        timestamp:        预测时间戳
    """

    algorithm_name: str
    algorithm_id: str
    target_threshold: int
    predicted_hours: float
    confidence: float
    current_views: int
    current_velocity: float
    metadata: Dict[str, Any]
    timestamp: datetime

    def to_dict(self) -> Dict[str, Any]:
        """将预测结果序列化为字典（timestamp 转为 ISO 格式字符串）。"""
        return {
            "algorithm_name": self.algorithm_name,
            "algorithm_id": self.algorithm_id,
            "target_threshold": self.target_threshold,
            "predicted_hours": self.predicted_hours,
            "confidence": self.confidence,
            "current_views": self.current_views,
            "current_velocity": self.current_velocity,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }


class BaseAlgorithm(ABC):
    """预测算法抽象基类

    所有具体预测算法必须继承此类并实现 predict() 方法。
    基类提供以下公共辅助方法：
        - calculate_velocity()   根据历史数据计算播放速度
        - get_engagement_rate()  计算综合互动率
        - get_quality_score()    计算内容质量评分
        - get_video_age_hours()  计算视频已发布时长
    """

    # 算法元信息 —— 子类应覆盖这些类属性
    name: str = "基类算法"
    description: str = "预测算法基类"
    category: str = "基础"

    def __init__(self):
        pass

    @abstractmethod
    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行预测 —— 子类必须实现此方法。

        Args:
            video_data: 包含视频所有数据的字典，包括：
                - view_count: 当前播放量
                - history_data: 历史数据列表（每项含 view_count 和 timestamp）
                - timestamp: 当前时间戳
                - 其他视频信息字段（like_count、coin_count 等）
            threshold: 目标播放量阈值（默认 10 万）

        Returns:
            PredictionResult 对象，包含算法名称、预测结果、置信度等
        """

    def _fallback(self, velocity: float, current_views: int, threshold: int,
                  method: str = "", metadata: dict = None) -> PredictionResult:
        """通用降级预测：当算法不可用或数据不足时，使用匀速外推。

        Args:
            velocity: 当前每小时播放速度
            current_views: 当前播放量
            threshold: 目标阈值
            method: 算法标识方法名
            metadata: 额外元数据（会合并到 metadata 中）

        Returns:
            PredictionResult 基于匀速外推的保守预测
        """
        meta = {"reason": "fallback"}
        if method:
            meta["method"] = method
        if metadata:
            meta.update(metadata)

        if velocity <= 0:
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=float("inf"),
                confidence=0.0, current_views=current_views, current_velocity=velocity,
                metadata=meta, timestamp=datetime.now(),
            )
        remaining = max(0, threshold - current_views)
        predicted_hours = remaining / velocity if remaining > 0 else 0
        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=0.3, current_views=current_views, current_velocity=velocity,
            metadata=meta, timestamp=datetime.now(),
        )

    # ── 质量评分权重常量 ───────────────────────────
    _W_ENGAGEMENT = 0.4   # 互动率权重
    _W_DANMAKU = 0.3      # 弹幕密度权重
    _W_COIN_LIKE = 0.3    # 投币/点赞比权重

    # ── 时间戳格式 ─────────────────────────────────
    _TS_FMT = "%Y-%m-%d %H:%M:%S"

    # ── 共享时间序列预处理 ─────────────────────────

    def _prepare_timeseries_data(self, history):
        """将历史数据的混合格式时间戳解析为以天为单位的相对时间及播放量数组。

        Args:
            history: 历史数据列表, 每项含 timestamp 和 view/view_count

        Returns:
            (times_days, views, ts_raw_list): times 以天为单位的浮点数组, views 播放量数组,
                                              ts_raw_list 原始时间戳列表(暂不使用)
        """
        import numpy as np

        n = len(history)
        times = np.empty(n, dtype=float)
        views = np.empty(n, dtype=float)

        first_ts = history[0]["timestamp"]
        if isinstance(first_ts, str):
            base_epoch = datetime.strptime(first_ts, self._TS_FMT).timestamp()
        elif isinstance(first_ts, datetime):
            base_epoch = first_ts.timestamp()
        else:
            base_epoch = float(first_ts)

        times[0] = 0.0
        views[0] = history[0].get("view", history[0].get("view_count", 0))

        for i in range(1, n):
            data = history[i]
            views[i] = data.get("view", data.get("view_count", 0))
            ts_raw = data["timestamp"]
            if isinstance(ts_raw, str):
                ts_epoch = datetime.strptime(ts_raw, self._TS_FMT).timestamp()
            elif isinstance(ts_raw, datetime):
                ts_epoch = ts_raw.timestamp()
            else:
                ts_epoch = float(ts_raw)
            times[i] = (ts_epoch - base_epoch) / 86400.0

        return times, views, None

    # ── 增长模型置信度计算 ─────────────────────────

    def _growth_confidence(self, n_points, predicted, actual, multiplier):
        """通用的增长模型置信度计算。

        基于数据点数量和 MAPE 拟合误差综合评估。
        """
        import numpy as np

        base_conf = min(0.9, 0.4 + n_points * multiplier)
        if n_points >= 5:
            try:
                predicted = np.asarray(predicted, dtype=float)
                actual = np.asarray(actual, dtype=float)
                mape = np.mean(np.abs((actual - predicted) / (actual + 1)))
                fit_quality = max(0.0, 1.0 - mape)
                base_conf = 0.5 * base_conf + 0.5 * fit_quality
            except Exception as e:
                logger.debug("置信度 MAPE 计算失败: %s", e)
        return min(0.95, base_conf)

    # ── 安全曲线拟合封装 ───────────────────────────

    def _safe_curve_fit(self, model_func, times, views, p0, bounds, maxfev=5000):
        """对 scipy curve_fit 的安全封装, 失败时回退到初始参数。

        Returns:
            (popt, success): popt 为拟合参数, success 为 True/False
        """
        from scipy.optimize import curve_fit

        try:
            popt, _ = curve_fit(model_func, times, views, p0=p0, bounds=bounds, maxfev=maxfev)
            return popt, True
        except Exception as e:
            logger.debug("curve_fit 失败，回退到初始参数: %s", e)
            return p0, False

    # ── 公共辅助方法 ───────────────────────────────

    @staticmethod
    def _timestamp_sort_key(item):
        ts = item.get("timestamp", 0)
        if isinstance(ts, (int, float)):
            return ts
        if hasattr(ts, "timestamp"):
            return ts.timestamp()
        try:
            return datetime.fromisoformat(str(ts)).timestamp()
        except Exception as e:
            logger.debug("时间戳解析失败: %s", e)
            return 0

    def calculate_velocity(self, video_data: Dict[str, Any]) -> float:
        """根据历史数据计算当前播放速度（播放量/小时）。

        优先使用 _prepare_video_data 预计算的速度（避免 100+ 算法重复计算），
        降级时不再排序（_prepare_video_data 已保证时间升序）。
        """
        # 优先使用预计算值
        pre = video_data.get("derived_features", {})
        if "velocity_polyfit" in pre:
            return pre["velocity_polyfit"]
        # 兼容 video_data 直接注入的 velocity 字段
        vel = video_data.get("velocity", 0)
        if vel > 0:
            return vel

        history = video_data.get("history_data", [])
        if len(history) < 2:
            return 0.0
        try:
            # _sorted 标记表示已按时间升序，跳过 sorted()
            if video_data.get("_sorted"):
                sorted_hist = history
            else:
                sorted_hist = sorted(history, key=self._timestamp_sort_key)

            if len(sorted_hist) >= 5:
                import numpy as np
                n_pts = min(10, len(sorted_hist))
                recent = sorted_hist[-n_pts:]
                t_arr = np.array([float(h.get("timestamp", 0)) for h in recent], dtype=np.float32)
                v_arr = np.array([float(h.get("view_count", 0)) for h in recent], dtype=np.float32)
                if np.max(t_arr) == np.min(t_arr):
                    return 0.0
                slope, _ = np.polyfit(t_arr, v_arr, 1)
                return max(0.0, slope / 3600.0)
            else:
                recent = sorted_hist[-2:]
                v0 = float(recent[0].get("view_count", 0))
                v1 = float(recent[-1].get("view_count", 0))
                t0 = recent[0].get("timestamp", 0)
                t1 = recent[-1].get("timestamp", 0)
                if hasattr(t0, "timestamp"):
                    t0 = t0.timestamp()
                elif not isinstance(t0, (int, float)):
                    t0 = 0
                if hasattr(t1, "timestamp"):
                    t1 = t1.timestamp()
                elif not isinstance(t1, (int, float)):
                    t1 = 0
                dt_hours = (t1 - t0) / 3600.0
                if dt_hours <= 0:
                    return 0.0
                return max(0.0, (v1 - v0) / dt_hours)
        except Exception as e:
            logger.debug("速率计算失败: %s", e)
            return 0.0

    def get_engagement_rate(self, video_data: Dict[str, Any]) -> float:
        """计算综合互动率。

        公式：(点赞 + 投币 + 收藏 + 分享) / 播放量，结果限制在 [0, 1]。
        """
        views = max(video_data.get("view_count", 0), 1)
        likes = video_data.get("like_count", 0) or 0
        coins = video_data.get("coin_count", 0) or 0
        favorites = video_data.get("favorite_count", 0) or 0
        shares = video_data.get("share_count", 0) or 0
        return min(1.0, (likes + coins + favorites + shares) / views)

    def get_quality_score(self, video_data: Dict[str, Any]) -> float:
        """计算内容质量评分，取值范围 [0, 1]。

        综合考虑三个维度：
            - 互动率（engagement）
            - 弹幕密度（每万播放弹幕数）
            - 投币/点赞比（硬币认可度）
        各维度通过预设权重加权求和。
        """
        engagement = self.get_engagement_rate(video_data)
        views = max(video_data.get("view_count", 0), 1)
        danmaku = video_data.get("danmaku_count", 0) or 0
        likes = video_data.get("like_count", 0) or 0
        coins = video_data.get("coin_count", 0) or 0

        # 弹幕密度：每万播放的弹幕数量，上限 1.0
        danmaku_density = min(1.0, danmaku / views * 10000)
        # 投币/点赞比：比值越高表示用户认可度越高
        coin_like_ratio = min(1.0, coins / max(likes, 1))
        score = self._W_ENGAGEMENT * engagement + self._W_DANMAKU * danmaku_density + self._W_COIN_LIKE * coin_like_ratio
        return min(1.0, max(0.0, score))

    def get_video_age_hours(self, video_data: Dict[str, Any]) -> float:
        """计算视频发布至今的小时数。

        优先级：
            1. 从 history_data 中最旧记录的 timestamp 推算
            2. 回退到 video_data['timestamp']（可为 datetime 或 Unix 时间戳）
            3. 均不可用时返回 0.0
        """
        history = video_data.get("history_data", [])
        now = datetime.now()

        if len(history) >= 1:
            sorted_history = sorted(history, key=self._timestamp_sort_key)
            t = sorted_history[0].get("timestamp", None)
            if t is not None:
                try:
                    ts_val = safe_timestamp(t)
                except Exception as e:
                    logger.debug("时间戳安全解析失败: %s", e)
                    ts_val = time.time()
                return max(0.0, (time.time() - ts_val) / 3600.0)
        # 回退：用 video_data 自身的 timestamp
        ts = video_data.get("timestamp")
        if ts is not None:
            if hasattr(ts, "timestamp"):
                return max(0.0, (now - ts).total_seconds() / 3600.0)
            if isinstance(ts, (int, float)):
                return max(0.0, (time.time() - ts) / 3600.0)
        return 0.0

    # ── 大推流检测与自适应速度 ─────────────────────

    @staticmethod
    def _extract_view_series(history: List[Dict]) -> Tuple[List[float], List[float]]:
        """从历史数据中提取排序后的播放量和时间戳序列。

        Returns:
            (views, timestamps) 均为按时间升序排列的 float 列表。
            时间戳统一转为 Unix 秒。
        """
        views: List[float] = []
        timestamps: List[float] = []
        for entry in history:
            v = entry.get("view_count", entry.get("view", 0))
            t = entry.get("timestamp", 0)
            if hasattr(t, "timestamp"):
                t = t.timestamp()
            elif isinstance(t, str):
                try:
                    t = datetime.fromisoformat(t).timestamp()
                except Exception as e:
                    logger.debug("ISO 时间解析失败: %s", e)
                    continue
            if v > 0 and isinstance(t, (int, float)) and t > 0:
                views.append(float(v))
                timestamps.append(float(t))
        if len(views) > 1:
            pairs = sorted(zip(timestamps, views), key=lambda x: x[0])
            timestamps, views = [p[0] for p in pairs], [p[1] for p in pairs]
        return views, timestamps

    @staticmethod
    def _calc_velocity_window(
        views: List[float], timestamps: List[float], start_idx: int, end_idx: int
    ) -> float:
        """计算指定索引窗口内的平均播放速度（播放量/小时）。

        窗口含头不含尾 [start_idx, end_idx)。
        """
        if end_idx - start_idx < 2:
            return 0.0
        try:
            dt = (timestamps[end_idx - 1] - timestamps[start_idx]) / 3600.0
            if dt <= 0:
                return 0.0
            dv = views[end_idx - 1] - views[start_idx]
            return max(0.0, dv / dt)
        except Exception as e:
            logger.debug("周期速率计算失败: %s", e)
            return 0.0

    @staticmethod
    def _find_period_window(
        timestamps: List[float], target_ts: float, window_sec: float
    ) -> Tuple[int, int]:
        """在历史时间戳中查找与 target_ts 相隔约 window_sec 之前的数据窗口。

        例如：window_sec=86400 (24h) 时，查找约 24 小时前、相同时间段的数据。
        通过时间范围匹配而非索引偏移，避免跨周期污染。

        Returns:
            (start_idx, end_idx)，若数据不足以覆盖该周期则返回 (-1, -1)。
        """
        if len(timestamps) < 4:
            return -1, -1

        lookback_ts = target_ts - window_sec
        # 宽松的时间窗口：±15% 的 window_sec 或至少 ±1 小时
        margin = max(3600, window_sec * 0.15)

        # 收集落在 [lookback_ts - margin, lookback_ts + margin] 范围内的索引
        indices = []
        for i, ts in enumerate(timestamps):
            if lookback_ts - margin <= ts <= lookback_ts + margin:
                indices.append(i)

        if len(indices) < 3:
            return -1, -1

        return indices[0], indices[-1]

    def detect_surge(self, video_data: Dict[str, Any]) -> Dict[str, Any]:
        """检测视频是否正在经历大推流（流量激增）。

        使用多窗口速度分析 + 周期对比（同日/同周）区分：
          - 有机增长（渐进、可持续）→ 不标记为推流
          - 平台推流（突发、临时、会衰减）→ 标记并预估衰减
          - 周期性波动（每日高峰）→ 不标记为推流

        推流判定需同时满足：
          1. 短窗口速度 >> 长期基线速度（近期速度比）
          2. 短窗口速度 >> 同日历史同期速度（排除周期性波动）

        Returns:
            dict with keys:
                is_surging, surge_magnitude, surge_confidence,
                baseline_velocity, surge_velocity,
                daily_baseline_velocity, weekly_baseline_velocity,
                decay_half_life_hours, surge_type, adjusted_velocity,
                velocity_history (各周期速度对比，供 UI 展示)
        """
        history = video_data.get("history_data", [])
        result: Dict[str, Any] = {
            "is_surging": False,
            "surge_magnitude": 1.0,
            "surge_confidence": 0.0,
            "baseline_velocity": 0.0,
            "surge_velocity": 0.0,
            "daily_baseline_velocity": 0.0,
            "weekly_baseline_velocity": 0.0,
            "decay_half_life_hours": 6.0,
            "surge_type": "none",
            "adjusted_velocity": 0.0,
            "velocity_history": {},
            "period_comparison": {},
        }

        if len(history) < 8:
            return result

        try:
            views, timestamps = self._extract_view_series(history)
            n = len(views)
            if n < 8:
                return result

            # ── 多窗口速度计算 ──────────────────────
            # W_current: 最近约 5-10 分钟的窗口
            current_size = min(3, n - 1)
            v_current = self._calc_velocity_window(views, timestamps, n - current_size - 1, n)

            # W_short: 最近约 15-30 分钟的窗口
            short_size = min(7, n - 1)
            v_short = self._calc_velocity_window(views, timestamps, n - short_size - 1, n)

            # W_baseline: 推流前的长期基线速度（所有早期数据）
            baseline_end = max(0, n - short_size - 2)
            if baseline_end >= 4:
                v_baseline = self._calc_velocity_window(views, timestamps, 0, baseline_end + 1)
            else:
                v_baseline = v_short

            # ── 周期对比：同日同时段速度 ──────────────
            now_ts = timestamps[-1]
            v_daily = 0.0
            v_weekly = 0.0
            daily_ratio = 1.0
            weekly_ratio = 1.0

            # 同日对比（24h 前相同时间段）
            d_start, d_end = self._find_period_window(timestamps, now_ts, 86400)
            if d_start >= 0:
                v_daily = self._calc_velocity_window(views, timestamps, d_start, d_end + 1)
                if v_daily > 0 and v_current > 0:
                    daily_ratio = v_current / v_daily

            # 同周对比（7 天前相同时间段）
            w_start, w_end = self._find_period_window(timestamps, now_ts, 604800)
            if w_start >= 0:
                v_weekly = self._calc_velocity_window(views, timestamps, w_start, w_end + 1)
                if v_weekly > 0 and v_current > 0:
                    weekly_ratio = v_current / v_weekly

            # ── 填充结果基础字段 ──────────────────────
            result["baseline_velocity"] = v_baseline
            result["surge_velocity"] = v_current
            result["daily_baseline_velocity"] = v_daily
            result["weekly_baseline_velocity"] = v_weekly
            result["velocity_history"] = {
                "current": round(v_current),
                "short_term": round(v_short),
                "long_baseline": round(v_baseline),
                "daily_same_period": round(v_daily) if v_daily > 0 else None,
                "weekly_same_period": round(v_weekly) if v_weekly > 0 else None,
            }
            result["period_comparison"] = {
                "daily_ratio": round(daily_ratio, 2) if v_daily > 0 else None,
                "weekly_ratio": round(weekly_ratio, 2) if v_weekly > 0 else None,
            }

            if v_baseline <= 0:
                result["adjusted_velocity"] = v_current
                return result

            # ── 推流强度判定（综合近期 + 周期对比）───
            surge_ratio = v_current / max(v_baseline, 0.01)
            result["surge_magnitude"] = round(surge_ratio, 2)

            # 周期性检查：如果同日同时段速度也高 → 可能是日常波动而非推流
            is_seasonal = False
            if v_daily > 0 and daily_ratio < 1.5:
                # 同日速度差异不大 → 这是每天都会出现的正常高峰
                is_seasonal = True

            if surge_ratio >= 3.0 and not is_seasonal:
                result["is_surging"] = True
                result["surge_confidence"] = min(0.95, 0.7 + (surge_ratio - 3.0) * 0.04)
                result["surge_type"] = "strong"
                result["decay_half_life_hours"] = max(2.0, 6.0 - surge_ratio * 0.5)
            elif surge_ratio >= 2.0 and not is_seasonal:
                result["is_surging"] = True
                result["surge_confidence"] = 0.6 + (surge_ratio - 2.0) * 0.2
                result["surge_type"] = "moderate"
                result["decay_half_life_hours"] = 8.0
            elif surge_ratio >= 1.5:
                # 轻度推流：需趋势一致性 + 排除周期性
                if not is_seasonal and n >= 5:
                    recent_vels: List[float] = []
                    for i in range(max(0, n - 5), n - 1):
                        v_i = self._calc_velocity_window(views, timestamps, i, i + 2)
                        if v_i > 0:
                            recent_vels.append(v_i)
                    if len(recent_vels) >= 3 and all(v > v_baseline * 1.3 for v in recent_vels[-3:]):
                        result["is_surging"] = True
                        result["surge_confidence"] = 0.5
                        result["surge_type"] = "mild"
                        result["decay_half_life_hours"] = 12.0

            # 如果被周期性排除了，但速度和周期比也异常高（同日 3x+），仍标记
            if is_seasonal and not result["is_surging"] and v_daily > 0 and daily_ratio >= 3.0:
                result["is_surging"] = True
                result["surge_confidence"] = 0.55
                result["surge_type"] = "strong"
                result["decay_half_life_hours"] = 4.0
                result["surge_magnitude"] = daily_ratio

            # ── 根据视频年龄调整半衰期 ──────────────────
            age_hours = self.get_video_age_hours(video_data)
            if age_hours > 336:
                result["decay_half_life_hours"] *= 0.6
            elif age_hours > 168:
                result["decay_half_life_hours"] *= 0.8
            elif age_hours < 24:
                result["decay_half_life_hours"] *= 1.3

            result["decay_half_life_hours"] = max(1.0, min(24.0, result["decay_half_life_hours"]))

            # ── 计算调整后的预测速度 ──────────────────
            result["adjusted_velocity"] = self._compute_surge_adjusted_velocity(
                result, v_current, v_short, v_baseline
            )

        except Exception as e:
            logger.warning("detect_surge 失败: %s", e)

        return result

    def _compute_surge_adjusted_velocity(
        self,
        surge_info: Dict[str, Any],
        v_short: float,
        v_medium: float,
        v_baseline: float,
    ) -> float:
        """根据推流信息计算衰减调整后的预测速度。

        核心思路：推流流量会随时间指数衰减，长期预测速度应介于
        当前峰值速度和基线速度之间。

        算法：
            1. 用指数衰减模型预测未来 1 小时后的速度
            2. 与当前短窗口速度做加权混合
            3. 推流越强 → 越倾向衰减后的保守估计
        """
        if not surge_info["is_surging"] or v_short <= 0:
            return v_short

        half_life = surge_info["decay_half_life_hours"]
        decay_lambda = math.log(2) / max(half_life, 0.5)

        # 预测未来 1 小时后的速度（指数衰减）
        predict_hours = 1.0
        surge_delta = v_short - v_baseline
        decayed_delta = surge_delta * math.exp(-decay_lambda * predict_hours)
        predicted_vel_1h = v_baseline + decayed_delta

        # 与中窗口速度做二次校验：取短期和中期的加权
        # 避免仅依赖衰减模型（模型可能有偏）
        vel_conservative = v_medium * 0.5 + predicted_vel_1h * 0.5

        # 根据推流强度选择混合比例
        surge_type = surge_info["surge_type"]
        if surge_type == "strong":
            blend = 0.35  # 65% 给保守估计
        elif surge_type == "moderate":
            blend = 0.50
        else:
            blend = 0.65

        adjusted = vel_conservative * blend + v_short * (1.0 - blend)

        # 不低于基线速度的 1.05 倍（允许少量增长）
        return max(v_baseline * 1.05, adjusted)

    def calculate_surge_aware_velocity(self, video_data: Dict[str, Any]) -> float:
        """计算考虑大推流衰减后的播放速度。

        常规情况下等价于 calculate_velocity()；
        检测到推流时自动应用衰减模型，返回更保守的长期预测速度。
        """
        surge_info = self.detect_surge(video_data)
        if surge_info["is_surging"]:
            return surge_info["adjusted_velocity"]
        return self.calculate_velocity(video_data)

    def get_surge_decay_factor(self, video_data: Dict[str, Any], hours_ahead: float = 1.0) -> float:
        """获取推流衰减因子，用于调整长期预测值。

        返回 [0.3, 1.0] 范围内的因子：
          1.0  = 无衰减（无推流或预测极短期）
          <0.5 = 强衰减（强推流 + 长时间预测）

        Args:
            video_data: 视频数据
            hours_ahead: 预测未来的小时数

        Returns:
            衰减因子（1.0 表示不调整，越小越保守）
        """
        surge_info = self.detect_surge(video_data)
        if not surge_info["is_surging"]:
            return 1.0

        half_life = surge_info["decay_half_life_hours"]
        decay_lambda = math.log(2) / max(half_life, 0.5)
        decay = math.exp(-decay_lambda * hours_ahead)

        # 推流越强，衰减对预测的影响越大
        mag = surge_info["surge_magnitude"]
        surge_weight = min(0.9, (mag - 1.0) / mag)
        factor = 1.0 - surge_weight * (1.0 - decay)
        return max(0.3, factor)

    # ── NPU 推理辅助 ──────────────────────────────

    def _npu_infer(self, model, input_array, algo_name: str = ""):
        """NPU 加速推理 — CUDA 不可用时自动降级到 NPU，否则用 PyTorch。

        用法：在 DL 算法的 predict() 中，将：
            model.to(self._device).eval()
            x = torch.from_numpy(x_arr).unsqueeze(0).to(self._device)
            output = model(x)
        替换为：
            output = self._npu_infer(model, x_arr, algo_name="MyAlgo")

        Args:
            model:       PyTorch nn.Module 实例（含已加载的权重）。
            input_array: numpy 数组，形状 (..., features)。
            algo_name:   算法名称，用于 NPU 模型缓存键。

        Returns:
            torch.Tensor: 推理输出张量（CPU, float32）。
        """
        import torch
        import numpy as np

        # 根据用户偏好和 CUDA 可用性决定是否尝试 NPU
        from algorithms.training.device import get_preferred_device
        prefer = get_preferred_device()
        cuda_available = torch.cuda.is_available()

        if prefer == "openvino_npu":
            try_npu = True   # 用户明确选择 NPU
        elif prefer == "cuda" and cuda_available:
            try_npu = False  # 用户选择 CUDA 且可用
        elif prefer in ("onnx_dml", "cpu"):
            try_npu = False  # 用户选择其他非 NPU 后端
        else:
            try_npu = not cuda_available  # auto 模式：有 CUDA 则用 CUDA，否则尝试 NPU

        if try_npu:
            try:
                from algorithms.training.npu_inference import get_npu_engine

                name = algo_name or self.__class__.__name__
                engine = get_npu_engine()
                if not engine.is_available:
                    raise RuntimeError("NPU 引擎不可用")

                x_np = np.asarray(input_array, dtype=np.float16)
                if x_np.ndim == 1:
                    x_np = x_np.reshape(1, -1)
                elif x_np.ndim == 2:
                    x_np = x_np[np.newaxis, :, :]
                elif x_np.ndim >= 3:
                    x_np = x_np[:1]

                x_sample = torch.from_numpy(x_np.astype(np.float32))
                engine.prepare_model(name, model, x_sample)
                result = engine.infer(name, x_np)
                result = np.atleast_2d(result)
                return torch.from_numpy(result.astype(np.float32))
            except Exception as e:
                logger.debug("NPU 推理回退 CPU: %s", e)

        # ── PyTorch 推理（CUDA 或 CPU）───────────────
        device = getattr(self, "_device", torch.device("cpu"))
        model.to(device).eval()
        x = torch.from_numpy(np.asarray(input_array, dtype=np.float32)).unsqueeze(0).to(device)
        with torch.no_grad():
            return model(x)
