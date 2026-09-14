"""ScheduleMixin extracted from algorithms.registry — 重算法降频调度。

背景（实测，n=1000 历史，热态串行）：
  · 最重的 7 个算法占 **77.2%** 运行时长，但只占 **5.11%** 权重（权重≈数量占比，基础权重全 1.0）
  · 三场景反事实实测（平滑长历史 / 新视频短历史 / 推流爆发）：去掉这 7 个对集成
    `prediction` 的影响 ≤0.093%、对 log-ETA 中位数 ≤0.06%
因此让它们在「无事件」的轮次降频，用上一轮实算结果按**当前播放量重投影**，
既省掉大部分算力，又把数值漂移限制在实测的量级内。

强制刷新（任一命中即本轮对重算法全部实算）：
  1. ``interval`` —— 距上次实算 ≥ ``heavy_interval_seconds``（**固定时间强制重算**，纠正数据）
  2. ``surge``    —— ``detect_surge`` 命中推流
  3. ``anchor``   —— anchor 阈值索引变化（跨过 10万/100万/1000万）
  4. ``jump``     —— 历史末段增量相对稳健增量偏离 > ``jump_ratio`` 倍，或出现回跳
  5. ``cold``     —— 无缓存（首轮）

复用项的数值语义：``prediction`` 由缓存的速度按当前播放量重投影
（``current_value + velocity × 75/3600``，与 ``_to_registry_result`` 完全同源），
``predicted_hours`` / ``confidence`` 沿用上一轮实算值，并打上
``metadata.scheduled_reuse`` / ``metadata.reuse_age_s`` 以便观测；
复用项**不计入** ``_apply_window_weights`` 的「算法表现」历史（避免把缓存年龄
误当成算法连续表现），也**不重复**套 coherence 折扣（沿用缓存内的最终权重）。
"""

import logging
import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from ..base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

# 实测最重的 7 个（用 algorithm_id 匹配，比中文名稳定）
DEFAULT_HEAVY_IDS: Tuple[str, ...] = (
    "multi_task_simple",
    "quantile_regression",
    "moirai",
    "prophet",
    "sarima_simple",
    "bagging_simple",
    "arima_simple",
)
DEFAULT_HEAVY_INTERVAL_SECONDS = 180.0
DEFAULT_JUMP_RATIO = 3.0
_SHORT_TERM_SECONDS = 75
_REUSE_FLAG = "scheduled_reuse"


class ScheduleMixin:
    """重算法降频调度（被 AlgorithmRegistry 混入）。"""

    _algorithms: Dict[str, BaseAlgorithm]

    _sched_lock: threading.Lock
    _sched_state: Dict[str, Dict[str, Any]]
    _sched_enabled: bool
    _sched_heavy_ids: Set[str]
    _sched_interval: float
    _sched_jump_ratio: float
    _sched_stats: Dict[str, int]

    if TYPE_CHECKING:

        @classmethod
        def _to_registry_result(
            cls, prediction_result: Any, current_value: float, thresholds: List, threshold_names: List, weight: float
        ) -> Dict:
            raise NotImplementedError

        @classmethod
        def _detect_surge_from_cached(cls, cached_video_data: Dict) -> Dict:
            raise NotImplementedError

    # ── 配置 ────────────────────────────────────────────────

    @classmethod
    def configure_schedule(
        cls,
        enabled: Optional[bool] = None,
        heavy_ids: Optional[Any] = None,
        interval_seconds: Optional[float] = None,
        jump_ratio: Optional[float] = None,
    ) -> None:
        """运行期调整调度参数（测试与设置界面用）。"""
        if enabled is not None:
            cls._sched_enabled = bool(enabled)
        if heavy_ids is not None:
            cls._sched_heavy_ids = set(heavy_ids)
        if interval_seconds is not None:
            cls._sched_interval = max(0.0, float(interval_seconds))
        if jump_ratio is not None:
            cls._sched_jump_ratio = max(1.0, float(jump_ratio))

    @classmethod
    def reset_schedule(cls, bvid: Optional[str] = None) -> None:
        """清空调度状态（bvid 为空则全清）。删除监控时应传 bvid。"""
        with cls._sched_lock:
            if bvid:
                cls._sched_state.pop(bvid, None)
            else:
                cls._sched_state.clear()

    @classmethod
    def schedule_stats(cls) -> Dict[str, int]:
        """调度观测计数（实算/跳过/复用 轮数），供测试与状态面板使用。"""
        with cls._sched_lock:
            return dict(cls._sched_stats)

    # ── 判定 ────────────────────────────────────────────────

    @classmethod
    def _heavy_names(cls) -> Set[str]:
        """当前注册表中属于重算法组（按 algorithm_id 匹配）的 registry key 集合。"""
        if not cls._sched_heavy_ids:
            return set()
        return {
            name for name, algo in cls._algorithms.items() if getattr(algo, "algorithm_id", "") in cls._sched_heavy_ids
        }

    @classmethod
    def _history_jump(cls, cached_video_data: Dict) -> bool:
        """历史末段是否出现跳变（回跳或相对稳健增量的突增）。

        回跳 = API 抖动/纠正；突增 = 可能出现变化点，曲线型模型值得重算。
        """
        history = cached_video_data.get("history_data") or []
        if len(history) < 2:
            return False
        derived = cached_video_data.get("derived_features") or {}
        expected = float(derived.get("increment_75s", 0) or 0)
        try:
            last = float(history[-1].get("view_count", 0) or 0)
            prev = float(history[-2].get("view_count", 0) or 0)
        except (TypeError, ValueError):
            return False
        dv = last - prev
        if dv < 0:
            return True
        if expected > 0 and dv > expected * cls._sched_jump_ratio:
            return True
        return False

    @classmethod
    def _should_run_heavy(cls, bvid: str, anchor_idx: Optional[int], cached_video_data: Dict) -> Tuple[bool, str]:
        """本轮是否对重算法实算，返回 (是否实算, 原因)。"""
        if not cls._sched_enabled:
            return True, "disabled"
        if not cls._heavy_names():
            return True, "no-heavy"
        now = time.monotonic()
        with cls._sched_lock:
            state = cls._sched_state.get(bvid)
        if state is None or not state.get("cache"):
            return True, "cold"
        if (now - float(state.get("ts", 0.0))) >= cls._sched_interval:
            return True, "interval"
        if state.get("anchor_idx") != anchor_idx:
            return True, "anchor"
        if cls._history_jump(cached_video_data):
            return True, "jump"
        try:
            if cls._detect_surge_from_cached(cached_video_data).get("is_surging"):
                return True, "surge"
        except Exception as e:  # 推流检测失败不应影响预测主流程
            logger.debug("调度推流判定失败: %s", e)
        return False, "reuse"

    # ── 缓存存取 ────────────────────────────────────────────

    @classmethod
    def _store_heavy(cls, bvid: str, results: Dict, anchor_idx: Optional[int]) -> None:
        """把本轮重算法的最终结果存为下一轮的复用来源（在权重阶段之后调用）。"""
        if not cls._sched_enabled or not bvid:
            return
        cache: Dict[str, Dict[str, Any]] = {}
        for name in cls._heavy_names():
            r = results.get(name)
            if not isinstance(r, dict) or "error" in r:
                continue
            cache[name] = {
                "prediction": float(r.get("prediction", 0) or 0),
                "weight": float(r.get("weight", 0) or 0),
                "confidence": float(r.get("confidence", 0) or 0),
                "predicted_hours": float(r.get("predicted_hours", 0) or 0),
                "velocity": float((r.get("metadata") or {}).get("velocity", 0) or 0),
            }
        if not cache:
            return
        with cls._sched_lock:
            cls._sched_state[bvid] = {"ts": time.monotonic(), "anchor_idx": anchor_idx, "cache": cache}

    @classmethod
    def _inject_reused(
        cls,
        bvid: str,
        results: Dict,
        current_value: float,
        thresholds: List,
        threshold_names: List,
        anchor_idx: Optional[int],
    ) -> List[str]:
        """把上一轮重算法结果按当前播放量重投影后注入 results，返回被注入的算法名列表。

        重投影复用生产的 ``_to_registry_result``（与实算同源），仅把
        ``current_views`` 换成当前值，因此 ``prediction`` 与「重跑一次」的差异
        只来自速度本身的漂移，而非换算口径。
        """
        with cls._sched_lock:
            state = cls._sched_state.get(bvid)
            cache: Dict[str, Dict[str, Any]] = dict(state["cache"]) if state else {}
            age = (time.monotonic() - float(state["ts"])) if state else 0.0
        if not cache:
            return []
        anchor_threshold = thresholds[anchor_idx] if anchor_idx is not None else thresholds[-1]
        injected: List[str] = []
        for name, entry in cache.items():
            if name in results:
                continue
            algo = cls._algorithms.get(name)
            if algo is None:
                continue
            pr = PredictionResult(
                algorithm_name=getattr(algo, "name", name),
                algorithm_id=getattr(algo, "algorithm_id", name),
                target_threshold=anchor_threshold,
                predicted_hours=float(entry.get("predicted_hours", 0) or 0),
                confidence=float(entry.get("confidence", 0) or 0),
                current_views=int(current_value),
                current_velocity=float(entry.get("velocity", 0) or 0),
                metadata={},
                timestamp=datetime.now(),
            )
            res = cls._to_registry_result(
                pr, current_value, thresholds, threshold_names, weight=float(entry.get("weight", 0) or 0)
            )
            res["metadata"][_REUSE_FLAG] = True
            res["metadata"]["reuse_age_s"] = round(age, 1)
            results[name] = res
            injected.append(name)
        if injected:
            logger.debug("[%s] 重算法降频：复用 %d 个（年龄 %.0fs）", bvid, len(injected), age)
        return injected

    @staticmethod
    def _is_reused(result: Any) -> bool:
        """该结果是否为降频复用的（复用项不再计入算法表现历史/不重复套共识折扣）。"""
        if not isinstance(result, dict):
            return False
        return bool((result.get("metadata") or {}).get(_REUSE_FLAG))

    @classmethod
    def _record_sched_stat(cls, key: str) -> None:
        with cls._sched_lock:
            cls._sched_stats[key] = cls._sched_stats.get(key, 0) + 1
