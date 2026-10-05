"""预测明细与集成数据持久化接线测试。"""

from ui.monitor import _prediction


class _FakeVideoDb:
    def __init__(self):
        self.rows = []
        self.cycles = []

    def save_prediction_cycle(self, timestamp, rows, ensemble, coherence):
        self.rows.extend(rows)
        self.cycles.append((timestamp, ensemble, coherence))
        return True


class _FakeLogPanel:
    def add_log(self, level, message):
        raise AssertionError(f"unexpected log: {level} {message}")


class _FakeGui:
    def __init__(self, bvid):
        self.video_dbs = {bvid: _FakeVideoDb()}
        self.log_panel = _FakeLogPanel()


def _make_results():
    return {
        "algo-ok": {
            "prediction": 150,
            "confidence": 0.8,
            "coherence": 0.75,
            "metadata": {"threshold_predictions": [{"threshold": 200, "minutes": 5, "name": "200"}]},
        },
        "algo-zero": {"prediction": 140, "confidence": 0.6, "coherence": 0, "metadata": {}},
        "algo-error": {"error": "failed", "coherence": 0.9},
        "_weighted": {
            "prediction": 160,
            "ensemble_confidence": 0.88,
            "valid_algorithms": 2,
            "total_algorithms": 3,
            "prediction_interval": {"lower": 145, "upper": 175, "interval_width_ratio": 0.2},
            "surge_correction_applied": True,
            "surge_magnitude": 1.5,
            "surge_type": "moderate",
        },
    }


def test_save_predictions_returns_ensemble_and_filtered_coherence():
    bvid = "BV-persistence"
    gui = _FakeGui(bvid)

    rows, ensemble, coherence = _prediction._save_predictions_to_db(gui, bvid, 100, _make_results())

    assert len(rows) == 1
    assert gui.video_dbs[bvid].rows == rows
    assert ensemble == {
        "prediction": 160,
        "confidence": 0.88,
        "valid_algos": 2,
        "total_algos": 3,
        "prediction_interval": {"lower": 145, "upper": 175, "interval_width_ratio": 0.2},
        "surge_correction_applied": True,
        "surge_magnitude": 1.5,
        "surge_type": "moderate",
    }
    assert coherence == [("algo-ok", 0.75)]
    assert len(gui.video_dbs[bvid].cycles) == 1
    timestamp, saved_ensemble, saved_coherence = gui.video_dbs[bvid].cycles[0]
    assert timestamp
    assert saved_ensemble == ensemble
    assert saved_coherence == coherence


def test_save_predictions_without_weighted_result_has_no_sync_payload():
    bvid = "BV-no-weighted"
    gui = _FakeGui(bvid)
    results = {"algo-ok": {"prediction": 150, "confidence": 0.8, "coherence": 0.75, "metadata": {}}}

    _, ensemble, coherence = _prediction._save_predictions_to_db(gui, bvid, 100, results)

    assert ensemble is None
    assert coherence == []
