"""Feature tests for monitor lifecycle ownership without a Qt application."""

import threading
import time

from ui.monitor._lifecycle import (
    AppState,
    MonitorRuntime,
    begin_stopping,
    close_video_dbs,
    drain_registered_tasks,
    get_app_state,
    has_registered_tasks,
    remove_video_db,
    set_video_db,
    use_video_db,
)


class FakeDb:
    def __init__(self):
        self.closed = False
        self.calls = 0

    def touch(self):
        if self.closed:
            raise RuntimeError("closed database")
        self.calls += 1

    def close(self):
        self.closed = True


class FakeGui:
    def __init__(self):
        self._data_lock = threading.RLock()
        self.video_dbs = {}
        self.monitored_videos = []


def test_stopping_rejects_new_tasks_and_drains_registered_work():
    runtime = MonitorRuntime()
    completed = threading.Event()
    assert runtime.start_thread(lambda: completed.set(), (), "work") is not None
    assert completed.wait(1)
    runtime.begin_stopping()
    assert runtime.state is AppState.STOPPING
    assert runtime.start_thread(lambda: None, (), "rejected") is None
    assert runtime.drain() == []
    runtime.mark_stopped()
    assert runtime.state is AppState.STOPPED


def test_db_access_and_close_are_serialized_without_closed_database_use():
    gui = FakeGui()
    db = FakeDb()
    assert set_video_db(gui, "BV1", db)
    started = threading.Event()
    release = threading.Event()

    def access_database():
        def operation(video_db):
            started.set()
            release.wait(1)
            video_db.touch()

        use_video_db(gui, "BV1", operation)

    worker = threading.Thread(target=access_database)
    worker.start()
    assert started.wait(1)
    closer = threading.Thread(target=lambda: close_video_dbs(gui))
    closer.start()
    time.sleep(0.02)
    release.set()
    worker.join(1)
    closer.join(1)
    assert db.closed
    assert db.calls == 1
    assert use_video_db(gui, "BV1", lambda video_db: video_db.touch()) is None


def test_concurrent_add_remove_does_not_corrupt_db_container():
    gui = FakeGui()

    def mutate(index):
        bvid = f"BV{index % 8}"
        for _ in range(100):
            set_video_db(gui, bvid, FakeDb())
            use_video_db(gui, bvid, lambda video_db: video_db.touch())
            remove_video_db(gui, bvid)

    workers = [threading.Thread(target=mutate, args=(index,)) for index in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(2)
    assert all(not worker.is_alive() for worker in workers)


def test_gui_state_rejects_tasks_after_shutdown_begins():
    gui = FakeGui()
    assert get_app_state(gui) is AppState.RUNNING
    begin_stopping(gui)
    assert get_app_state(gui) is AppState.STOPPING


def test_surviving_task_defers_resource_closure_until_it_releases():
    gui = FakeGui()
    db = FakeDb()
    assert set_video_db(gui, "BV1", db)
    started = threading.Event()
    release = threading.Event()

    def slow_resource_task():
        started.set()
        release.wait(1)
        use_video_db(gui, "BV1", lambda video_db: video_db.touch())

    from ui.monitor._lifecycle import start_registered_task

    assert start_registered_task(gui, slow_resource_task, name="periodic-sync") is not None
    assert started.wait(1)
    begin_stopping(gui)
    assert drain_registered_tasks(gui, timeout_per_thread=0.01) == ["periodic-sync"]
    assert has_registered_tasks(gui)
    assert not close_video_dbs(gui)
    assert not db.closed
    release.set()
    assert drain_registered_tasks(gui) == []
    assert close_video_dbs(gui)
    assert db.closed


def test_stopping_rejects_periodic_wal_and_preload_task_registration():
    gui = FakeGui()
    begin_stopping(gui)
    from ui.monitor._lifecycle import start_registered_task

    for task_name in ("periodic-sync", "wal-checkpoint", "algo-preload"):
        assert start_registered_task(gui, lambda: None, name=task_name) is None


def test_add_video_fetch_is_registered_and_defers_api_teardown(monkeypatch):
    """The add-video request participates in runtime drain before API closure."""
    import core
    import ui.main_gui_events_monitor as monitor_events

    gui = FakeGui()
    release = threading.Event()
    started = threading.Event()

    class _Api:
        closed = False

        def get_video_info(self, bvid):
            started.set()
            release.wait(1)
            return None

        def close(self):
            self.closed = True

    class _Dialog:
        _fetch_in_progress = False

    class _Label:
        def setText(self, value):
            pass

        def setStyleSheet(self, value):
            pass

    api = _Api()
    monkeypatch.setattr(core, "get_bilibili_api", lambda: api)
    monkeypatch.setattr(monitor_events, "invoke", lambda callback: None)

    monitor_events.fetch_video_info_and_add(gui, "BV1", _Dialog(), _Label())
    assert started.wait(1)
    begin_stopping(gui)
    assert drain_registered_tasks(gui, timeout_per_thread=0.01) == ["fetch-video"]
    if not has_registered_tasks(gui):
        api.close()
    assert not api.closed, "API must remain open while fetch-video is registered"

    release.set()
    assert drain_registered_tasks(gui) == []
    if not has_registered_tasks(gui):
        api.close()
    assert api.closed


class _PersistentThread:
    def __init__(self, name: str) -> None:
        self.name = name
        self.alive = True
        self.join_calls: list[float] = []

    def join(self, timeout: float = 0.0) -> None:
        self.join_calls.append(timeout)

    def is_alive(self) -> bool:
        return self.alive


class _PersistentPredictor:
    def __init__(self, bvid: str) -> None:
        self.bvid = bvid
        self._thread = _PersistentThread(f"Predictor-{bvid}")

    def stop(self, timeout: float = 0.0) -> None:
        self._thread.join(timeout)


class _PersistentPrecisionManager:
    def __init__(self) -> None:
        self.stop_calls = 0
        self.join_calls: list[float] = []
        self.alive = True

    def stop(self) -> None:
        self.stop_calls += 1

    def join(self, timeout: float = 0.0) -> list[str]:
        self.join_calls.append(timeout)
        return ["PrecisionWatch-BV1-100"] if self.alive else []


def test_repeated_stop_polls_retain_all_persistent_owners(monkeypatch):
    """A timeout must not discard owners that a later shutdown poll must drain."""
    import ui.monitor._service as service

    predictor = _PersistentPredictor("BV1")
    adhoc = _PersistentThread("adhoc")
    precision = _PersistentPrecisionManager()
    monkeypatch.setattr(service, "_predictors", {"BV1": predictor})
    monkeypatch.setattr(service, "_adhoc_threads", {adhoc})
    monkeypatch.setattr(service, "_precision_watch_manager", precision)
    monkeypatch.setattr(service, "_central_fetch_running", False)

    first = service._stop_all_workers()
    second = service._stop_all_workers()
    expected = {"Predictor-BV1", "adhoc", "PrecisionWatch-BV1-100"}
    assert expected.issubset(first)
    assert expected.issubset(second)
    assert service._predictors == {"BV1": predictor}
    assert service._adhoc_threads == {adhoc}
    assert service._precision_watch_manager is precision
    assert predictor._thread.join_calls == [0.0, 0.0]
    assert adhoc.join_calls == [0.0, 0.0]
    assert precision.join_calls == [0.0, 0.0]

    predictor._thread.alive = False
    adhoc.alive = False
    precision.alive = False
    assert service._stop_all_workers() == []
    assert service._predictors == {}
    assert service._adhoc_threads == set()
    assert service._precision_watch_manager is None


def test_queued_central_start_during_stopping_creates_no_runtime_state(monkeypatch):
    """A queued invoke callback arriving after STOPPING must be a no-op."""
    import ui.monitor._service as service

    gui = FakeGui()
    begin_stopping(gui)
    monkeypatch.setattr(service, "_central_fetch_running", False)
    monkeypatch.setattr(service, "_precision_watch_manager", None)
    created: list[str] = []
    monkeypatch.setattr(service, "_start_runtime_task", lambda *args, **kwargs: created.append("task"))

    service._start_central_fetcher(gui)
    assert created == []
    assert service._central_fetch_running is False
    assert service._precision_watch_manager is None
