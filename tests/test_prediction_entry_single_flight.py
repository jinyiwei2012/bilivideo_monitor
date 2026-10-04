"""Regression coverage for prediction entry points sharing one BVID lane."""

import threading

from ui.main_gui_events_runtime import run_post_training_predict
from ui.monitor import _prediction
from ui.monitor import _service
from ui.monitor._lifecycle import drain_registered_tasks
from ui.monitor._supervisor import TaskSupervisor


class _LogPanel:
    def add_log(self, _level, _message):
        pass


class _FakeGui:
    def __init__(self) -> None:
        self._data_lock = threading.RLock()
        self.video_dbs = {}
        self.monitored_videos = [{"bvid": "BV1single", "view_count": 1}]
        self.prediction_results = {}
        self.selected_bvid = ""
        self.log_panel = _LogPanel()

    def _sb(self, *_args, **_kwargs):
        pass


def test_prediction_entries_share_a_per_bvid_single_flight_lane(monkeypatch):
    gui = _FakeGui()
    first_started = threading.Event()
    release_first = threading.Event()
    completed = threading.Event()
    all_submitted = threading.Event()
    lock = threading.Lock()
    active = 0
    max_active = 0
    executions = 0
    submissions = 0

    def controlled_prediction(_gui, _bvid, _video):
        nonlocal active, max_active, executions
        with lock:
            active += 1
            max_active = max(max_active, active)
            executions += 1
            invocation = executions
        if invocation == 1:
            first_started.set()
            assert release_first.wait(1)
        with lock:
            active -= 1
        if invocation == 2:
            completed.set()
        return {}

    original_submit = TaskSupervisor.submit_prediction

    def count_submission(self, *args, **kwargs):
        nonlocal submissions
        token = original_submit(self, *args, **kwargs)
        with lock:
            submissions += 1
            if submissions == 3:
                all_submitted.set()
        return token

    monkeypatch.setattr(_prediction, "_predict_single", controlled_prediction)
    monkeypatch.setattr(TaskSupervisor, "submit_prediction", count_submission)

    video = gui.monitored_videos[0]
    _service._notify_predictor(gui, "BV1single", video)
    assert first_started.wait(1)
    _service.auto_predict_all(gui)
    run_post_training_predict(gui)
    assert all_submitted.wait(1)
    release_first.set()
    assert completed.wait(1)
    assert drain_registered_tasks(gui) == []
    assert max_active == 1
    assert executions <= 2
