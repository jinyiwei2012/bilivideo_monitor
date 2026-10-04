"""集成预测偏差反馈回路测试。"""

from algorithms.registry import AlgorithmRegistry


def _reset_feedback_state() -> None:
    with AlgorithmRegistry._prev_ensemble_lock:
        AlgorithmRegistry._prev_ensemble_pred.clear()


def test_ensemble_feedback_records_consecutive_growth_samples(monkeypatch):
    from algorithms import bias_correction

    recorded = []
    corrector = bias_correction.get_bias_corrector()
    monkeypatch.setattr(corrector, "record", lambda bvid, predicted, actual: recorded.append((bvid, predicted, actual)))
    _reset_feedback_state()

    bvid = "BV-feedback"
    AlgorithmRegistry._record_ensemble_feedback(bvid, 100.0)
    AlgorithmRegistry._store_ensemble_prediction(bvid, 130.0, 100.0)
    AlgorithmRegistry._record_ensemble_feedback(bvid, 115.0)

    assert recorded == [(bvid, 30.0, 15.0)]

    AlgorithmRegistry._store_ensemble_prediction(bvid, 145.0, 115.0)
    AlgorithmRegistry._record_ensemble_feedback(bvid, 125.0)

    assert recorded == [(bvid, 30.0, 15.0), (bvid, 30.0, 10.0)]


def test_ensemble_feedback_without_prediction_does_not_record(monkeypatch):
    from algorithms import bias_correction

    recorded = []
    corrector = bias_correction.get_bias_corrector()
    monkeypatch.setattr(corrector, "record", lambda *args: recorded.append(args))
    _reset_feedback_state()

    AlgorithmRegistry._record_ensemble_feedback("BV-no-fill", 100.0)
    AlgorithmRegistry._record_ensemble_feedback("BV-no-fill", 120.0)

    assert recorded == []


def test_ensemble_feedback_non_positive_predicted_growth_does_not_record(monkeypatch):
    from algorithms import bias_correction

    recorded = []
    corrector = bias_correction.get_bias_corrector()
    monkeypatch.setattr(corrector, "record", lambda *args: recorded.append(args))
    _reset_feedback_state()

    bvid = "BV-no-growth"
    AlgorithmRegistry._record_ensemble_feedback(bvid, 100.0)
    AlgorithmRegistry._store_ensemble_prediction(bvid, 100.0, 100.0)
    AlgorithmRegistry._record_ensemble_feedback(bvid, 120.0)

    assert recorded == []
