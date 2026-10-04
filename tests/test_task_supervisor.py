"""Concurrency feature tests for the dormant prediction task supervisor."""

import threading

from ui.monitor._lifecycle import MonitorRuntime, begin_stopping, drain_registered_tasks, has_registered_tasks
from ui.monitor._supervisor import TaskSupervisor


class FakeGui:
    """Qt-free owner with the monitor runtime's required containers."""

    def __init__(self) -> None:
        self._data_lock = threading.RLock()
        self.video_dbs = {}
        self.monitored_videos = []


def test_admitted_runtime_task_runs_when_stopping_begins_before_runner_check(monkeypatch):
    runtime = MonitorRuntime()
    executed = threading.Event()

    original_thread = threading.Thread

    class StoppingThread(original_thread):
        def start(self):
            runtime.begin_stopping()
            super().start()

    monkeypatch.setattr("ui.monitor._lifecycle.threading.Thread", StoppingThread)
    assert runtime.start_thread(executed.set, (), "admitted-work") is not None
    assert executed.wait(1)
    assert runtime.drain() == []


def test_supervisor_rejects_submissions_after_stopping():
    gui = FakeGui()
    supervisor = TaskSupervisor(gui)
    called = threading.Event()
    begin_stopping(gui)

    assert supervisor.submit_prediction(gui, "BV1", {"view_count": 1}, lambda *_: called.set()) is None
    assert not called.is_set()
    assert not has_registered_tasks(gui)


def test_same_key_runs_current_then_latest_pending_only():
    gui = FakeGui()
    supervisor = TaskSupervisor(gui)
    first_started = threading.Event()
    release_first = threading.Event()
    complete = threading.Event()
    payloads = []
    active = 0
    max_active = 0
    lock = threading.Lock()

    def worker(_gui, _bvid, video, _token):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            payloads.append(video["view_count"])
        if video["view_count"] == 1:
            first_started.set()
            assert release_first.wait(1)
        with lock:
            active -= 1
        if video["view_count"] == 2:
            complete.set()

    assert supervisor.submit_prediction(gui, "BV1", {"view_count": 1}, worker) is not None
    assert first_started.wait(1)
    assert supervisor.submit_prediction(gui, "BV1", {"view_count": 2}, worker) is not None
    release_first.set()
    assert complete.wait(1)
    assert drain_registered_tasks(gui) == []
    assert payloads == [1, 2]
    assert max_active == 1


def test_pending_requests_are_continuously_overwritten_by_latest_payload():
    gui = FakeGui()
    supervisor = TaskSupervisor(gui)
    first_started = threading.Event()
    release_first = threading.Event()
    complete = threading.Event()
    payloads = []

    def worker(_gui, _bvid, video, _token):
        payloads.append(video["view_count"])
        if video["view_count"] == 1:
            first_started.set()
            assert release_first.wait(1)
        if video["view_count"] == 3:
            complete.set()

    supervisor.submit_prediction(gui, "BV1", {"view_count": 1}, worker)
    assert first_started.wait(1)
    supervisor.submit_prediction(gui, "BV1", {"view_count": 2}, worker)
    supervisor.submit_prediction(gui, "BV1", {"view_count": 3}, worker)
    release_first.set()
    assert complete.wait(1)
    assert drain_registered_tasks(gui) == []
    assert payloads == [1, 3]


def test_different_bvids_can_run_concurrently():
    gui = FakeGui()
    supervisor = TaskSupervisor(gui)
    both_started = threading.Barrier(2)
    release = threading.Event()
    completed = threading.Event()
    completed_count = 0
    lock = threading.Lock()

    def worker(_gui, _bvid, _video, _token):
        nonlocal completed_count
        both_started.wait(1)
        assert release.wait(1)
        with lock:
            completed_count += 1
            if completed_count == 2:
                completed.set()

    supervisor.submit_prediction(gui, "BV1", {}, worker)
    supervisor.submit_prediction(gui, "BV2", {}, worker)
    release.set()
    assert completed.wait(1)
    assert drain_registered_tasks(gui) == []


def test_retire_discards_pending_and_invalidates_running_token():
    gui = FakeGui()
    supervisor = TaskSupervisor(gui)
    first_started = threading.Event()
    release_first = threading.Event()
    first_finished = threading.Event()
    payloads = []

    def worker(_gui, _bvid, video, _token):
        payloads.append(video["view_count"])
        if video["view_count"] == 1:
            first_started.set()
            assert release_first.wait(1)
            first_finished.set()

    current = supervisor.submit_prediction(gui, "BV1", {"view_count": 1}, worker)
    assert current is not None
    assert first_started.wait(1)
    supervisor.submit_prediction(gui, "BV1", {"view_count": 2}, worker)
    supervisor.retire_bvid("BV1")
    release_first.set()
    assert first_finished.wait(1)
    assert drain_registered_tasks(gui) == []
    assert payloads == [1]
    assert not supervisor.is_committed(current)


def test_supervisor_tasks_are_registered_with_runtime_drain():
    gui = FakeGui()
    supervisor = TaskSupervisor(gui)
    started = threading.Event()
    release = threading.Event()

    def worker(_gui, _bvid, _video, _token):
        started.set()
        assert release.wait(1)

    assert supervisor.submit_prediction(gui, "BV1", {}, worker) is not None
    assert started.wait(1)
    assert has_registered_tasks(gui)
    assert drain_registered_tasks(gui, timeout_per_thread=0.01) == ["prediction:BV1"]
    release.set()
    assert drain_registered_tasks(gui) == []
