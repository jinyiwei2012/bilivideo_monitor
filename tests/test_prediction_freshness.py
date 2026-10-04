"""并发预测结果新鲜度测试。"""

import threading

from ui.monitor import _prediction


class _FakeGui:
    def __init__(self):
        self._data_lock = threading.Lock()
        self.prediction_results = {}


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
