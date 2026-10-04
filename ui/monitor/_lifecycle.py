"""Runtime ownership helpers for monitor workers and per-video databases."""

import logging
import threading
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")


class AppState(Enum):
    """The monitor runtime lifecycle."""

    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


class MonitorRuntime:
    """Owns monitor task registration and rejects work after shutdown starts."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = AppState.RUNNING
        self._threads: set[threading.Thread] = set()

    @property
    def state(self) -> AppState:
        with self._lock:
            return self._state

    def accepts_tasks(self) -> bool:
        return self.state is AppState.RUNNING

    def begin_stopping(self) -> None:
        with self._lock:
            if self._state is AppState.RUNNING:
                self._state = AppState.STOPPING

    def mark_stopped(self) -> None:
        with self._lock:
            self._state = AppState.STOPPED

    def start_thread(
        self, target: Callable[..., None], args: tuple[Any, ...], name: str | None = None
    ) -> Optional[threading.Thread]:
        """Start a registered task only while the application accepts work."""
        with self._lock:
            if self._state is not AppState.RUNNING:
                logger.debug("拒绝在 %s 状态启动任务 %s", self._state.value, name or target)
                return None

            thread: threading.Thread

            def runner() -> None:
                try:
                    # Admission above is atomic with registration.  A task admitted while
                    # RUNNING must drain even if shutdown begins before this thread runs.
                    target(*args)
                finally:
                    with self._lock:
                        self._threads.discard(thread)

            thread = threading.Thread(target=runner, daemon=True, name=name)
            self._threads.add(thread)
            thread.start()
            return thread

    def drain(self, timeout_per_thread: float = 2.0) -> list[str]:
        """Join all registered tasks with a bounded wait and return survivors."""
        with self._lock:
            threads = list(self._threads)
        alive: list[str] = []
        for thread in threads:
            thread.join(timeout=timeout_per_thread)
            if thread.is_alive():
                alive.append(thread.name)
        with self._lock:
            self._threads = {thread for thread in self._threads if thread.is_alive()}
        return alive

    def has_live_tasks(self) -> bool:
        """Return whether a registered task still owns runtime resources."""
        with self._lock:
            self._threads = {thread for thread in self._threads if thread.is_alive()}
            return bool(self._threads)


def _runtime(gui: Any) -> MonitorRuntime:
    runtime = getattr(gui, "_monitor_runtime", None)
    if runtime is None:
        runtime = MonitorRuntime()
        gui._monitor_runtime = runtime
    if not hasattr(gui, "_video_db_lock"):
        gui._video_db_lock = threading.RLock()
    if not hasattr(gui, "_video_dbs_closed"):
        gui._video_dbs_closed = False
    return runtime


def get_app_state(gui: Any) -> AppState:
    return _runtime(gui).state


def accepts_tasks(gui: Any) -> bool:
    return _runtime(gui).accepts_tasks()


def begin_stopping(gui: Any) -> None:
    _runtime(gui).begin_stopping()
    supervisor = getattr(gui, "_task_supervisor", None)
    if supervisor is not None:
        supervisor.shutdown()


def mark_stopped(gui: Any) -> None:
    _runtime(gui).mark_stopped()


def start_registered_task(
    gui: Any, target: Callable[..., Any], args: tuple[Any, ...] = (), name: str | None = None
) -> Optional[threading.Thread]:
    return _runtime(gui).start_thread(target, args, name)


def admit_runtime_creation(gui: Any, operation: Callable[[], T]) -> Optional[T]:
    """Atomically admit state mutation and thread creation while RUNNING.

    Creation paths use this instead of a separate state check so STOPPING cannot
    begin between the check and publishing an owned worker.  Do not acquire
    ``_data_lock`` from ``operation``; lifecycle admission precedes container
    locks, while DB users retain the documented ``_data_lock`` → DB-lock order.
    """
    runtime = _runtime(gui)
    with runtime._lock:
        if runtime._state is not AppState.RUNNING:
            return None
        return operation()


def drain_registered_tasks(gui: Any, timeout_per_thread: float = 2.0) -> list[str]:
    return _runtime(gui).drain(timeout_per_thread)


def has_registered_tasks(gui: Any) -> bool:
    return _runtime(gui).has_live_tasks()


# When both locks are required, always acquire ``_data_lock`` before ``_video_db_lock``.
# Database operations themselves acquire only ``_video_db_lock`` so closing a handle cannot
# race a worker which has already obtained it.
def set_video_db(gui: Any, bvid: str, video_db: Any) -> bool:
    _runtime(gui)
    with gui._video_db_lock:
        if gui._video_dbs_closed:
            logger.error("关闭视频库后仍尝试注册 %s", bvid)
            return False
        gui.video_dbs[bvid] = video_db
        return True


def remove_video_db(gui: Any, bvid: str) -> Any:
    _runtime(gui)
    with gui._video_db_lock:
        return gui.video_dbs.pop(bvid, None)


def use_video_db(gui: Any, bvid: str, operation: Callable[[Any], T]) -> Optional[T]:
    """Run an operation while its DB handle is protected from concurrent closure."""
    _runtime(gui)
    with gui._video_db_lock:
        if gui._video_dbs_closed:
            logger.error("关闭视频库后仍尝试访问 %s", bvid)
            return None
        video_db = gui.video_dbs.get(bvid)
        if video_db is None:
            return None
        return operation(video_db)


def video_db_ids(gui: Any) -> list[str]:
    """Return a stable DB-key snapshot without exposing the mutable container."""
    _runtime(gui)
    with gui._video_db_lock:
        if gui._video_dbs_closed:
            return []
        return list(gui.video_dbs)


def use_all_video_dbs(gui: Any, operation: Callable[[str, Any], T]) -> list[T]:
    """Use each current handle under its lease.

    The DB lock is intentionally held while each operation runs.  This is the
    lifetime lease: removal or shutdown cannot close a handle until its worker
    has completed.  Callers must not acquire ``_data_lock`` inside ``operation``;
    when both are needed, acquire ``_data_lock`` before this lease.
    """
    _runtime(gui)
    with gui._video_db_lock:
        if gui._video_dbs_closed:
            return []
        return [operation(bvid, video_db) for bvid, video_db in list(gui.video_dbs.items())]


def close_video_dbs(gui: Any) -> bool:
    """Close and detach every video DB after all resource users have drained."""
    runtime = _runtime(gui)
    if runtime.has_live_tasks():
        logger.warning("仍有登记任务运行，延后关闭视频数据库")
        return False
    with gui._video_db_lock:
        if gui._video_dbs_closed:
            return True
        gui._video_dbs_closed = True
        video_dbs = list(gui.video_dbs.items())
        gui.video_dbs.clear()
        for bvid, video_db in video_dbs:
            try:
                video_db.close()
            except Exception as exc:
                logger.debug("关闭视频数据库失败 %s: %s", bvid, exc)
    return True
