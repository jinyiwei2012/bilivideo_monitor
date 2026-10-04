"""目标附近的高频播放量采样服务，不依赖 Qt，可离线测试。"""

from __future__ import annotations

import logging
import statistics
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping

from utils.ntp_time import calibrated_now

logger = logging.getLogger(__name__)

Fetch = Callable[[str], Any]
Clock = Callable[[], datetime]
Sleep = Callable[[float], None]
Monotonic = Callable[[], float]
Persist = Callable[[str, Mapping[str, Any]], Any]
Notify = Callable[[str, Mapping[str, Any]], Any]


def _extract_views(value: Any) -> int:
    if isinstance(value, Mapping):
        stat = value.get("stat", value)
        if isinstance(stat, Mapping):
            value = stat.get("view", stat.get("view_count", 0))
    return int(value or 0)


class PrecisionWatchManager:
    """为接近阈值的视频启动有界高频采样线程。

    每次请求以响应接收时刻作为原始观测时间，并用单调钟测得 RTT。校正结果采用
    对称网络延迟假设 ``t_server ≈ t_receive - RTT / 2``；该假设不能消除上下行
    不对称、服务端排队或缓存刷新延迟，因此原始与校正区间会一并持久化。
    """

    def __init__(
        self,
        fetch: Fetch,
        persist: Persist,
        notify: Notify | None = None,
        *,
        clock: Clock | None = None,
        monotonic: Monotonic | None = None,
        sleep: Sleep | None = None,
        enabled: bool = True,
        near_remaining: int = 10_000,
        close_remaining: int = 1_000,
        interval_near_s: float = 5,
        interval_close_s: float = 1,
        max_duration_s: float = 5_400,
        max_requests: int = 4_000,
        max_active: int = 3,
        stop_margin_s: float = 180,
    ) -> None:
        self.fetch = fetch
        self.persist = persist
        self.notify = notify or (lambda _bvid, _event: None)
        self.clock = clock or calibrated_now
        self.monotonic = monotonic or time.monotonic
        self.sleep = sleep or time.sleep
        self.enabled = enabled
        self.near_remaining = near_remaining
        self.close_remaining = close_remaining
        self.interval_near_s = interval_near_s
        self.interval_close_s = interval_close_s
        self.max_duration_s = max_duration_s
        self.max_requests = max_requests
        self.max_active = max_active
        self.stop_margin_s = stop_margin_s
        self._lock = threading.Lock()
        self._active: dict[tuple[str, int], threading.Thread] = {}
        self._completed: set[tuple[str, int]] = set()
        self._stop = threading.Event()

    def offer(self, bvid: str, current_views: int, threshold: int) -> bool:
        """接收常规拉取结果；仅在目标附近且容量允许时启动监视。"""
        key = (bvid, int(threshold))
        remaining = threshold - current_views
        if not self.enabled or not bvid or remaining <= 0 or remaining > self.near_remaining:
            return False
        with self._lock:
            if self._stop.is_set() or key in self._active or key in self._completed:
                return False
            if len(self._active) >= self.max_active:
                return False
            thread = threading.Thread(
                target=self._run_guarded,
                args=(bvid, int(current_views), int(threshold)),
                daemon=True,
                name=f"PrecisionWatch-{bvid}-{threshold}",
            )
            self._active[key] = thread
            thread.start()
        return True

    def _run_guarded(self, bvid: str, current_views: int, threshold: int) -> None:
        key = (bvid, threshold)
        try:
            completed = self.run_watch(bvid, current_views, threshold)
            if completed:
                with self._lock:
                    self._completed.add(key)
        except Exception as exc:
            logger.warning("精确过线监视失败 %s/%s: %s", bvid, threshold, exc)
        finally:
            with self._lock:
                self._active.pop(key, None)

    def run_watch(self, bvid: str, current_views: int, threshold: int) -> bool:
        """同步执行一次监视，供工作线程与离线测试共同调用。"""
        from core.crossing_precision import StepBracket, estimate_crossing, fit_rigid_grid, refine_crossing

        started_at = self.clock()
        started_mono = self.monotonic()
        previous_time = started_at
        previous_corrected_time = started_at
        previous_views = current_views
        brackets: list[StepBracket] = []
        corrected_brackets: list[StepBracket] = []
        rtts: list[float] = []
        crossing_seen_at: datetime | None = None
        requests = 0

        while not self._stop.is_set() and requests < self.max_requests:
            elapsed = self.monotonic() - started_mono
            if elapsed >= self.max_duration_s:
                break
            if crossing_seen_at is not None and (self.clock() - crossing_seen_at).total_seconds() >= self.stop_margin_s:
                break
            remaining = threshold - previous_views
            self.sleep(self.interval_close_s if remaining <= self.close_remaining else self.interval_near_s)
            request_started = self.monotonic()
            fetched = self.fetch(bvid)
            request_finished = self.monotonic()
            observed_at = self.clock()
            rtt_s = max(0.0, request_finished - request_started)
            corrected_at = observed_at - timedelta(seconds=rtt_s / 2)
            observed_views = _extract_views(fetched)
            requests += 1
            rtts.append(rtt_s)
            if observed_views <= 0:
                continue
            if observed_views > previous_views:
                brackets.append(
                    StepBracket(len(brackets) + 1, previous_time, observed_at, previous_views, observed_views)
                )
                corrected_brackets.append(
                    StepBracket(
                        len(corrected_brackets) + 1,
                        previous_corrected_time,
                        corrected_at,
                        previous_views,
                        observed_views,
                    )
                )
                if previous_views < threshold <= observed_views and crossing_seen_at is None:
                    crossing_seen_at = observed_at
            previous_time = observed_at
            previous_corrected_time = corrected_at
            previous_views = max(previous_views, observed_views)

        estimate = estimate_crossing(brackets, threshold)
        if estimate is None:
            return False
        corrected_estimate = estimate_crossing(corrected_brackets, threshold)
        refined = None
        fit = fit_rigid_grid(brackets)
        if fit is not None:
            refined = refine_crossing(estimate, fit)
        event: dict[str, Any] = {
            "threshold": threshold,
            "display_window_start": estimate.display_window_start,
            "display_window_end": estimate.display_window_end,
            "range_start": estimate.range_start,
            "range_end": estimate.range_end,
            "estimate": estimate.estimate,
            "period_lo": fit.period_lo if fit else None,
            "period_hi": fit.period_hi if fit else None,
            "refined_start": refined[0] if refined else None,
            "refined_end": refined[1] if refined else None,
            "request_count": requests,
            "rtt_median_us": round(statistics.median(rtts) * 1_000_000) if rtts else None,
            "corrected_range_start": corrected_estimate.range_start if corrected_estimate else None,
            "corrected_range_end": corrected_estimate.range_end if corrected_estimate else None,
            "corrected_estimate": corrected_estimate.estimate if corrected_estimate else None,
        }
        self.persist(bvid, event)
        self.notify(bvid, event)
        return True

    def stop(self) -> None:
        """阻止新任务并请求现有任务尽快停止。"""
        self._stop.set()

    def join(self, timeout: float = 2) -> list[str]:
        """Join active watches and return names that still own resources."""
        with self._lock:
            threads = list(self._active.values())
        alive: list[str] = []
        for thread in threads:
            thread.join(timeout=timeout)
            if thread.is_alive():
                alive.append(thread.name)
        return alive
