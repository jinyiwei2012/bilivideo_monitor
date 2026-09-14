"""冷启动优化回归测试。

覆盖三件事：
1. ``_predict_single`` 中权重预热**晚于**首轮预测（消除并发争抢与首轮数值的时序依赖）
2. 回测预热走**批量**写权重（不再 40 次全量重算 + 40 次 JSON 落盘）
3. ``prewarm_algorithms`` 首触预热：调用每个算法一次且不触碰任何全局反馈状态
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Dict, List

import pytest

from algorithms.registry import AlgorithmRegistry as R


class _Recorder:
    """记录 predict 调用的算法替身。"""

    def __init__(self) -> None:
        self.calls: List[Any] = []

    def predict(self, video_data: Dict, threshold: int = 0) -> None:
        self.calls.append((video_data.get("bvid"), threshold))
        return None


@pytest.fixture
def registry_stub(monkeypatch):
    """把注册表换成假算法并标记已初始化，退出时还原。"""
    saved_algorithms = R._algorithms
    saved_initialized = R._initialized
    saved_warmed = getattr(R, "_backtest_warmed", None)
    saved_state = dict(R._sched_state)
    R._initialized = True
    R._backtest_warmed = set()
    R._sched_state.clear()
    yield R
    R._algorithms = saved_algorithms
    R._initialized = saved_initialized
    R._backtest_warmed = saved_warmed if saved_warmed is not None else set()
    R._sched_state.clear()
    R._sched_state.update(saved_state)


class TestWarmupOrdering:
    def test_warmup_scheduled_after_prediction(self, monkeypatch):
        """权重预热必须在 predict_all 之后：否则与首轮预测抢 CPU 且首轮权重不确定。"""
        import ui.monitor._prediction as pred

        order: List[str] = []
        monkeypatch.setattr(R, "predict_all", classmethod(lambda cls, *a, **k: (order.append("predict"), {})[1]))
        monkeypatch.setattr(pred, "_schedule_weight_warmup", lambda gui, bvid, history: order.append("warmup"))
        monkeypatch.setattr(pred, "_online_learning_feedback", lambda *a, **k: None)
        monkeypatch.setattr(pred, "_update_ensemble_accuracy", lambda *a, **k: None)
        monkeypatch.setattr(pred, "_save_prediction_outputs", lambda *a, **k: None)

        class _FakeGui:
            def __init__(self) -> None:
                self._data_lock = threading.Lock()
                self.history_data = {"BV1xx411c7mD": [(datetime(2026, 1, 1), 1000)]}
                self.monitored_videos = [{"bvid": "BV1xx411c7mD", "view_count": 1100}]
                self.video_dbs: Dict[str, Any] = {}
                self.prediction_results: Dict[str, Any] = {}

        pred._predict_single(_FakeGui(), "BV1xx411c7mD", {"bvid": "BV1xx411c7mD", "view_count": 1100})
        assert order == ["predict", "warmup"]


class TestWarmupBatching:
    def test_batched_weight_write(self, monkeypatch, registry_stub):
        """回测预热应整批写一次权重，且不再逐条 update_accuracy。"""
        import algorithms.rollout_backtest as rb
        import algorithms.registry_parts._warmup as wu

        class _FakeBacktester:
            def __init__(self, **kwargs) -> None:
                pass

            def backtest(self, series, predict_fn) -> Dict[str, Any]:
                return {"n_tests": 5, "mape": 0.2}

        class _FakeWeightManager:
            def __init__(self) -> None:
                self.batches: List[List[Any]] = []
                self.singles = 0

            def update_accuracy_batch(self, pairs) -> None:
                self.batches.append(list(pairs))

            def update_accuracy(self, *a, **k) -> None:
                self.singles += 1

        fake_wm = _FakeWeightManager()
        monkeypatch.setattr(rb, "RollingBacktester", _FakeBacktester)
        monkeypatch.setattr(wu, "get_weight_manager", lambda: fake_wm)

        registry_stub._algorithms = {f"algo{i}": _Recorder() for i in range(6)}
        history = [(datetime(2026, 1, 1), 1000 + i * 10) for i in range(20)]

        warmed = registry_stub.warmup_weights_from_backtest("BV1test", history)

        assert warmed == 6
        assert len(fake_wm.batches) == 1, "整批只应写一次权重"
        assert len(fake_wm.batches[0]) == 6
        assert fake_wm.singles == 0, "不应再逐条调用 update_accuracy"
        assert all(0.3 <= acc <= 0.9 for _, acc in fake_wm.batches[0])

    def test_skips_short_history(self, registry_stub):
        registry_stub._algorithms = {"a": _Recorder()}
        assert registry_stub.warmup_weights_from_backtest("BV1test", [(datetime(2026, 1, 1), 1)] * 5) == 0


class TestPrewarm:
    def test_prewarm_calls_each_algorithm_once(self, registry_stub):
        registry_stub._algorithms = {"a": _Recorder(), "b": _Recorder()}
        warmed = registry_stub.prewarm_algorithms("BV1xx411c7mD")
        assert warmed == 2
        for algo in registry_stub._algorithms.values():
            assert len(algo.calls) == 1
            assert algo.calls[0] == ("BV1xx411c7mD", 100000)

    def test_prewarm_does_not_touch_schedule_state(self, registry_stub):
        """首触预热不得写入降频缓存（否则等于凭空造了一轮"已实算"状态）。"""
        registry_stub._algorithms = {"a": _Recorder()}
        registry_stub.prewarm_algorithms("BV1xx411c7mD")
        assert registry_stub._sched_state == {}

    def test_prewarm_requires_bvid(self, registry_stub):
        registry_stub._algorithms = {"a": _Recorder()}
        assert registry_stub.prewarm_algorithms("") == 0
        assert registry_stub._algorithms["a"].calls == []

    def test_prewarm_survives_algorithm_exception(self, registry_stub):
        class _Boom:
            def predict(self, video_data, threshold=0):
                raise RuntimeError("boom")

        registry_stub._algorithms = {"boom": _Boom(), "ok": _Recorder()}
        assert registry_stub.prewarm_algorithms("BV1xx411c7mD") == 1
