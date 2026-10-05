"""Fetch coalescing tests using Qt-free monitor owners."""

import threading

import ui.monitor._service as service
from ui.monitor._lifecycle import begin_stopping, drain_registered_tasks, has_registered_tasks
from ui.monitor._supervisor import TaskSupervisor


class _LogPanel:
    def add_log(self, *_args, **_kwargs):
        pass


class FakeGui:
    """Qt-free owner containing the monitor runtime's required fields."""

    def __init__(self, videos=()):
        self._data_lock = threading.RLock()
        self.monitored_videos = list(videos)
        self.log_panel = _LogPanel()
        self.video_dbs = {}

    def _sb(self, *_args, **_kwargs):
        pass


def test_same_bvid_fetches_coalesce_without_overlap():
    gui = FakeGui()
    supervisor = TaskSupervisor(gui)
    started = threading.Event()
    release = threading.Event()
    calls = 0
    active = 0
    max_active = 0
    lock = threading.Lock()

    def worker(_gui, _bvid, _video):
        nonlocal calls, active, max_active
        with lock:
            calls += 1
            active += 1
            max_active = max(max_active, active)
        started.set()
        assert release.wait(1)
        with lock:
            active -= 1

    first = supervisor.coalesce_fetch(gui, "BV1", {}, worker)
    assert first is not None and started.wait(1)
    shared = [supervisor.coalesce_fetch(gui, "BV1", {}, worker) for _ in range(3)]
    assert all(signal is first for signal in shared)
    release.set()
    first.result(timeout=1)
    assert calls == 1
    assert max_active == 1
    assert drain_registered_tasks(gui) == []


def test_manual_fetch_coalesces_with_active_batch_fetch(monkeypatch):
    video = {"bvid": "BV1"}
    gui = FakeGui((video,))
    started = threading.Event()
    release = threading.Event()
    calls = 0
    active = 0
    max_active = 0
    lock = threading.Lock()

    def worker(_gui, _bvid, _video):
        nonlocal calls, active, max_active
        with lock:
            calls += 1
            active += 1
            max_active = max(max_active, active)
        started.set()
        assert release.wait(1)
        with lock:
            active -= 1

    monkeypatch.setattr(service, "_fetch_one_video", worker)
    batch = threading.Thread(target=service._batch_fetch_all, args=(gui,))
    batch.start()
    assert started.wait(1)
    service.fetch_single_video_data(gui, "BV1")
    release.set()
    batch.join(1)
    assert not batch.is_alive()
    assert calls == 1
    assert max_active == 1
    assert drain_registered_tasks(gui) == []


def test_batch_keeps_distinct_bvids_bounded_and_waits(monkeypatch):
    gui = FakeGui(({"bvid": f"BV{i}"} for i in range(4)))
    started = threading.Event()
    release = threading.Event()
    active = 0
    max_active = 0
    completed = 0
    lock = threading.Lock()

    monkeypatch.setattr("utils.memory_guard.get_safe_workers", lambda: 2)

    def worker(_gui, _bvid, _video):
        nonlocal active, max_active, completed
        with lock:
            active += 1
            max_active = max(max_active, active)
            if active == 2:
                started.set()
        assert release.wait(1)
        with lock:
            active -= 1
            completed += 1

    monkeypatch.setattr(service, "_fetch_one_video", worker)
    batch = threading.Thread(target=service._batch_fetch_all, args=(gui,))
    batch.start()
    started.wait(1)
    assert batch.is_alive()
    release.set()
    batch.join(1)
    assert not batch.is_alive()
    assert completed == 4
    assert max_active == 2
    assert drain_registered_tasks(gui) == []


def test_fetch_exception_releases_lane_for_next_submission():
    gui = FakeGui()
    supervisor = TaskSupervisor(gui)
    calls = 0

    def worker(_gui, _bvid, _video):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("expected")

    first = supervisor.coalesce_fetch(gui, "BV1", {}, worker)
    assert first is not None
    try:
        first.result(timeout=1)
    except RuntimeError:
        pass
    else:
        raise AssertionError("first fetch should fail")
    second = supervisor.coalesce_fetch(gui, "BV1", {}, worker)
    assert second is not None
    second.result(timeout=1)
    assert calls == 2
    assert supervisor.active_fetch_lane_count() == 0
    assert drain_registered_tasks(gui) == []


def test_shutdown_rejects_new_fetch_and_active_fetch_drains():
    gui = FakeGui()
    supervisor = TaskSupervisor(gui)
    started = threading.Event()
    release = threading.Event()

    def worker(_gui, _bvid, _video):
        started.set()
        assert release.wait(1)

    active = supervisor.coalesce_fetch(gui, "BV1", {}, worker)
    assert active is not None and started.wait(1)
    begin_stopping(gui)
    assert supervisor.coalesce_fetch(gui, "BV2", {}, worker) is None
    release.set()
    active.result(timeout=1)
    assert drain_registered_tasks(gui) == []
    assert not has_registered_tasks(gui)
    assert supervisor.active_fetch_lane_count() == 0
