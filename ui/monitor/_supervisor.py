"""Dormant single-flight task supervisor for per-video prediction work."""

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, NamedTuple, Optional

from ui.monitor._lifecycle import accepts_tasks, start_registered_task

logger = logging.getLogger(__name__)

PredictionWorker = Callable[[Any, str, dict[str, Any]], Any]


class TaskKey(NamedTuple):
    """Identity of one serialized unit of work."""

    kind: str
    bvid: str


@dataclass(eq=False)
class _Lane:
    """Mutable state for one single-flight lane."""

    running: bool = False
    next_seq: int = 0
    current: Optional["TaskToken"] = None
    pending: Optional[tuple["TaskToken", dict[str, Any], PredictionWorker]] = None
    retired: bool = False


@dataclass(frozen=True)
class TaskToken:
    """In-memory validity token for a specific lane execution."""

    lane: _Lane
    seq: int


class TaskSupervisor:
    """Serialize prediction work per BVID while allowing different BVIDs to run."""

    def __init__(self, gui: Any) -> None:
        self._gui = gui
        self._lock = threading.RLock()
        self._lanes: dict[TaskKey, _Lane] = {}
        self._committed: set[TaskToken] = set()
        gui._task_supervisor = self

    def submit_prediction(
        self, gui: Any, bvid: str, video: dict[str, Any], target: PredictionWorker
    ) -> Optional[TaskToken]:
        """Submit one prediction, retaining only the newest request while busy."""
        if not accepts_tasks(gui):
            return None
        key = TaskKey("prediction", bvid)
        with self._lock:
            if not accepts_tasks(gui):
                return None
            lane = self._lanes.get(key)
            if lane is None:
                lane = _Lane()
                self._lanes[key] = lane
            if lane.retired:
                return None
            token = self._new_token(lane)
            payload = video.copy()
            if lane.running:
                lane.pending = (token, payload, target)
                return token
            lane.running = True
            lane.current = token
            thread = start_registered_task(
                gui, self._run_lane, args=(key, lane, payload, target), name=f"prediction:{bvid}"
            )
            if thread is None:
                lane.running = False
                lane.current = None
                if self._lanes.get(key) is lane:
                    self._lanes.pop(key)
                return None
            return token

    def retire_bvid(self, bvid: str) -> None:
        """Invalidate and detach a BVID lane, dropping work that has not started."""
        key = TaskKey("prediction", bvid)
        with self._lock:
            lane = self._lanes.pop(key, None)
            if lane is not None:
                lane.retired = True
                lane.pending = None
                self._committed = {token for token in self._committed if token.lane is not lane}

    def shutdown(self) -> None:
        """Reject deferred work after shutdown begins; running work drains naturally."""
        with self._lock:
            for lane in self._lanes.values():
                lane.pending = None

    def is_committed(self, token: TaskToken) -> bool:
        """Return whether an execution finished while its lane remained valid."""
        with self._lock:
            return token in self._committed

    def is_current(self, token: TaskToken) -> bool:
        """Return whether a token may still publish results for its active lane."""
        with self._lock:
            return any(
                lane is token.lane and not lane.retired and lane.current == token for lane in self._lanes.values()
            )

    def active_lane_count(self) -> int:
        """Return the number of non-retired lanes currently owned by this supervisor."""
        with self._lock:
            return sum(not lane.retired for lane in self._lanes.values())

    @staticmethod
    def _new_token(lane: _Lane) -> TaskToken:
        lane.next_seq += 1
        return TaskToken(lane, lane.next_seq)

    def _run_lane(self, key: TaskKey, lane: _Lane, video: dict[str, Any], target: PredictionWorker) -> None:
        current_video = video
        current_target = target
        while True:
            completed_without_error = False
            try:
                current_target(self._gui, key.bvid, current_video)
                completed_without_error = True
            except Exception:
                logger.exception("预测任务失败 %s", key.bvid)
            with self._lock:
                if lane.retired or self._lanes.get(key) is not lane or not accepts_tasks(self._gui):
                    lane.pending = None
                    lane.running = False
                    lane.current = None
                    return
                if completed_without_error and lane.current is not None:
                    self._committed.add(lane.current)
                pending = lane.pending
                if pending is None:
                    lane.running = False
                    lane.current = None
                    return
                lane.pending = None
                lane.current, current_video, current_target = pending


def get_task_supervisor(gui: Any) -> TaskSupervisor:
    """Return the GUI-owned supervisor without a process-global test contaminant."""
    supervisor = getattr(gui, "_task_supervisor", None)
    if supervisor is None:
        supervisor = TaskSupervisor(gui)
    return supervisor
