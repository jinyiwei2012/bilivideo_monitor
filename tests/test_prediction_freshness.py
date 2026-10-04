"""并发预测结果新鲜度测试。"""

import threading

from ui.monitor import _prediction
from ui.monitor._lifecycle import drain_registered_tasks
from ui.monitor._supervisor import TaskSupervisor


class _FakeGui:
    def __init__(self):
        self._data_lock = threading.RLock()
        self.prediction_results = {}
        self.history_data = {}
        self.monitored_videos = []
        self.video_dbs = {}
        self.selected_bvid = "BV-freshness"
        self.prediction_done_calls = []

    def _prediction_done(self, *args):
        self.prediction_done_calls.append(args)


def _reset_cycles() -> None:
    with _prediction._prediction_cycle_lock:
        _prediction._prediction_cycle_counters.clear()
        _prediction._prediction_committed_cycles.clear()


def test_prediction_cycles_commit_in_normal_order():
    _reset_cycles()
    gui = _FakeGui()
    bvid = "BV-normal-order"
    seq1 = _prediction._begin_prediction_cycle(bvid)
    seq2 = _prediction._begin_prediction_cycle(bvid)

    assert _prediction._commit_prediction_result(gui, bvid, {"prediction": 101}, seq1)
    assert _prediction._commit_prediction_result(gui, bvid, {"prediction": 102}, seq2)
    assert gui.prediction_results[bvid] == {"prediction": 102}


def test_older_prediction_is_rejected_after_newer_commit():
    _reset_cycles()
    gui = _FakeGui()
    bvid = "BV-out-of-order"
    seq1 = _prediction._begin_prediction_cycle(bvid)
    seq2 = _prediction._begin_prediction_cycle(bvid)

    assert _prediction._commit_prediction_result(gui, bvid, {"prediction": 202}, seq2)
    assert not _prediction._commit_prediction_result(gui, bvid, {"prediction": 201}, seq1)
    assert gui.prediction_results[bvid] == {"prediction": 202}


def _result_for_view(view_count: int) -> dict:
    return {"_weighted": {"prediction": view_count + 10, "valid_algorithms": 1, "total_algorithms": 1}}


def _configure_prediction(monkeypatch, gui, prediction):
    monkeypatch.setattr(_prediction, "_merge_history", lambda *_args: [])
    monkeypatch.setattr(_prediction.AlgorithmRegistry, "predict_all", prediction)
    monkeypatch.setattr(_prediction, "_calc_surge_aware_growth_rate", lambda _history: 0.0)
    monkeypatch.setattr(_prediction, "_detect_surge_for_ui", lambda _history: {})
    monkeypatch.setattr(_prediction, "_maybe_release_memory", lambda _gui: None)
    monkeypatch.setattr(_prediction, "_online_learning_feedback", lambda *_args: None)
    monkeypatch.setattr(_prediction, "_update_ensemble_accuracy", lambda *_args: None)


def test_retired_bvid_discards_slow_prediction_state_save_and_ui(monkeypatch):
    gui = _FakeGui()
    supervisor = TaskSupervisor(gui)
    started = threading.Event()
    release = threading.Event()
    queued_ui = []
    scheduled_saves = []

    def slow_prediction(*_args, **_kwargs):
        started.set()
        assert release.wait(1)
        return _result_for_view(1)

    _configure_prediction(monkeypatch, gui, slow_prediction)
    monkeypatch.setattr(_prediction, "invoke", lambda callback, **_kwargs: queued_ui.append(callback))
    monkeypatch.setattr(
        _prediction,
        "start_registered_task",
        lambda _gui, _target, args=(), name=None: scheduled_saves.append(name) or object(),
    )

    assert supervisor.submit_prediction(gui, "BV-freshness", {"view_count": 1}, _prediction._predict_single) is not None
    assert started.wait(1)
    supervisor.retire_bvid("BV-freshness")
    release.set()
    assert drain_registered_tasks(gui) == []

    assert "BV-freshness" not in gui.prediction_results
    assert scheduled_saves == []
    assert queued_ui == []


def test_readded_bvid_uses_new_lane_without_old_result_pollution(monkeypatch):
    gui = _FakeGui()
    supervisor = TaskSupervisor(gui)
    old_started = threading.Event()
    release_old = threading.Event()
    new_finished = threading.Event()

    def prediction(_history, current_view, **_kwargs):
        if current_view == 1:
            old_started.set()
            assert release_old.wait(1)
        else:
            new_finished.set()
        return _result_for_view(current_view)

    _configure_prediction(monkeypatch, gui, prediction)
    monkeypatch.setattr(_prediction, "invoke", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(_prediction, "start_registered_task", lambda *_args, **_kwargs: object())

    assert supervisor.submit_prediction(gui, "BV-freshness", {"view_count": 1}, _prediction._predict_single) is not None
    assert old_started.wait(1)
    supervisor.retire_bvid("BV-freshness")
    assert supervisor.submit_prediction(gui, "BV-freshness", {"view_count": 2}, _prediction._predict_single) is not None
    assert new_finished.wait(1)
    release_old.set()
    assert drain_registered_tasks(gui) == []

    assert gui.prediction_results["BV-freshness"]["current_view"] == 2


def test_late_ui_callback_with_retired_token_cannot_overwrite_new_result(monkeypatch):
    gui = _FakeGui()
    supervisor = TaskSupervisor(gui)
    queued_ui = []
    release = threading.Event()

    monkeypatch.setattr(_prediction, "invoke", lambda callback, **_kwargs: queued_ui.append(callback))

    def wait_worker(_gui, _bvid, _video, _token):
        assert release.wait(1)
        return {}

    old_token = supervisor.submit_prediction(gui, "BV-freshness", {}, wait_worker)
    assert old_token is not None
    supervisor.retire_bvid("BV-freshness")
    new_token = supervisor.submit_prediction(gui, "BV-freshness", {}, wait_worker)
    assert new_token is not None
    new_result = {
        "bvid": "BV-freshness",
        "prediction": 200,
        "current_view": 2,
        "growth": 10,
        "rate_per_sec": 1.0,
        "success_list": [],
        "fail_list": [],
        "valid": 1,
        "total": 1,
    }
    old_result = {**new_result, "prediction": 100, "current_view": 1}

    _prediction._schedule_prediction_ui(gui, old_result, old_token)
    _prediction._schedule_prediction_ui(gui, new_result, new_token)
    queued_ui.pop(1)()
    supervisor.retire_bvid("BV-freshness")
    queued_ui.pop(0)()
    release.set()
    assert drain_registered_tasks(gui) == []

    assert [call[0] for call in gui.prediction_done_calls] == [200]
