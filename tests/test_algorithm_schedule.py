"""重算法降频调度（ScheduleMixin）回归测试。

只验证调度判定与重投影数值语义，不加载 137 个真实算法（避免拖慢测试套件）：
把 ``AlgorithmRegistry._algorithms`` 换成假算法，用 algorithm_id 匹配重算法组。
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from algorithms.registry import AlgorithmRegistry as R
from algorithms.registry_parts import _schedule as sched_mod

_SHORT_HOURS = 75 / 3600.0


class _FakeAlgo:
    """最小算法替身：调度只依赖 algorithm_id / name。"""

    def __init__(self, algorithm_id: str, name: str = "") -> None:
        self.algorithm_id = algorithm_id
        self.name = name or algorithm_id


@pytest.fixture
def sched(monkeypatch):
    """隔离调度状态：假算法组 + 独立状态字典，退出时完整还原。"""
    saved: Dict[str, Any] = {
        "algorithms": R._algorithms,
        "state": R._sched_state,
        "heavy": R._sched_heavy_ids,
        "enabled": R._sched_enabled,
        "interval": R._sched_interval,
        "jump": R._sched_jump_ratio,
        "stats": R._sched_stats,
        "window": getattr(R, "_window_weight_history", None),
    }
    R._algorithms = {
        "heavyA": _FakeAlgo("heavy_a", "重算法A"),
        "heavyB": _FakeAlgo("heavy_b", "重算法B"),
        "cheapC": _FakeAlgo("cheap_c", "廉价C"),
    }
    R._sched_state = {}
    R._sched_stats = {}
    R._window_weight_history = {}
    R.configure_schedule(enabled=True, heavy_ids={"heavy_a", "heavy_b"}, interval_seconds=3600.0, jump_ratio=3.0)
    yield R
    R._algorithms = saved["algorithms"]
    R._sched_state = saved["state"]
    R._sched_heavy_ids = saved["heavy"]
    R._sched_enabled = saved["enabled"]
    R._sched_interval = saved["interval"]
    R._sched_jump_ratio = saved["jump"]
    R._sched_stats = saved["stats"]
    # 该属性原本可能**不存在**：不能用 None 覆盖，否则 getattr(cls, ..., {}) 会返回 None
    if saved["window"] is None:
        if hasattr(R, "_window_weight_history"):
            del R._window_weight_history
    else:
        R._window_weight_history = saved["window"]


def _heavy_entry(velocity: float = 480.0) -> Dict[str, Any]:
    return {
        "prediction": 100.0,
        "weight": 0.9,
        "confidence": 0.5,
        "predicted_hours": 2.0,
        "metadata": {"velocity": velocity},
    }


def _stored_state(anchor_idx: int = 0) -> Dict[str, Any]:
    return {"ts": sched_mod.time.monotonic(), "anchor_idx": anchor_idx, "cache": {"heavyA": _heavy_entry()}}


class TestScheduleDecision:
    def test_heavy_names_matched_by_algorithm_id(self, sched):
        assert sched._heavy_names() == {"heavyA", "heavyB"}

    def test_disabled_schedule_runs_all(self, sched):
        sched.configure_schedule(enabled=False)
        assert sched._should_run_heavy("BV1", 0, {}) == (True, "disabled")
        sched.configure_schedule(enabled=True)

    def test_cold_then_reuse(self, sched):
        assert sched._should_run_heavy("BV1", 0, {}) == (True, "cold")
        sched._sched_state["BV1"] = _stored_state(anchor_idx=0)
        run, reason = sched._should_run_heavy("BV1", 0, {})
        assert (run, reason) == (False, "reuse")

    def test_interval_forces_refresh(self, sched, monkeypatch):
        sched._sched_state["BV1"] = _stored_state(anchor_idx=0)
        base = sched_mod.time.monotonic()
        sched._sched_state["BV1"]["ts"] = base - 200.0  # 已超过 180s 间隔
        sched.configure_schedule(interval_seconds=180.0)
        monkeypatch.setattr(sched_mod.time, "monotonic", lambda: base)
        assert sched._should_run_heavy("BV1", 0, {}) == (True, "interval")

    def test_interval_not_reached_reuses(self, sched, monkeypatch):
        sched._sched_state["BV1"] = _stored_state(anchor_idx=0)
        base = sched_mod.time.monotonic()
        sched._sched_state["BV1"]["ts"] = base - 10.0
        sched.configure_schedule(interval_seconds=180.0)
        monkeypatch.setattr(sched_mod.time, "monotonic", lambda: base)
        assert sched._should_run_heavy("BV1", 0, {}) == (False, "reuse")

    def test_anchor_change_forces_refresh(self, sched):
        sched._sched_state["BV1"] = _stored_state(anchor_idx=0)
        assert sched._should_run_heavy("BV1", 1, {}) == (True, "anchor")

    def test_surge_forces_refresh(self, sched, monkeypatch):
        sched._sched_state["BV1"] = _stored_state(anchor_idx=0)
        monkeypatch.setattr(sched, "_detect_surge_from_cached", classmethod(lambda cls, d: {"is_surging": True}))
        assert sched._should_run_heavy("BV1", 0, {}) == (True, "surge")

    def test_store_and_reset(self, sched):
        sched._store_heavy("BV1", {"heavyA": _heavy_entry()}, anchor_idx=0)
        assert "BV1" in sched._sched_state
        sched.reset_schedule("BV1")
        assert "BV1" not in sched._sched_state


class TestHistoryJump:
    def test_back_jump_detected(self, sched):
        data = {"history_data": [{"view_count": 1000}, {"view_count": 900}], "derived_features": {}}
        assert sched._history_jump(data) is True

    def test_spike_detected(self, sched):
        data = {
            "history_data": [{"view_count": 1000}, {"view_count": 1100}],
            "derived_features": {"increment_75s": 10.0},
        }
        assert sched._history_jump(data) is True

    def test_normal_increment_not_jump(self, sched):
        data = {
            "history_data": [{"view_count": 1000}, {"view_count": 1012}],
            "derived_features": {"increment_75s": 10.0},
        }
        assert sched._history_jump(data) is False

    def test_single_point_not_jump(self, sched):
        assert sched._history_jump({"history_data": [{"view_count": 1000}]}) is False


class TestReprojection:
    def test_reproject_uses_current_value_and_cached_velocity(self, sched):
        """重投影 = 当前播放量 + 缓存速度×75s，与 _to_registry_result 同源。"""
        sched._store_heavy("BV1", {"heavyA": _heavy_entry(velocity=480.0)}, anchor_idx=0)
        results: Dict[str, Any] = {}
        injected = sched._inject_reused("BV1", results, 1000.0, [100000], ["10万"], 0)
        assert injected == ["heavyA"]
        r = results["heavyA"]
        assert r["prediction"] == pytest.approx(1000.0 + 480.0 * _SHORT_HOURS)
        assert r["predicted_hours"] == 2.0
        assert r["weight"] == 0.9
        assert r["confidence"] == 0.5
        assert r["metadata"]["scheduled_reuse"] is True
        assert "reuse_age_s" in r["metadata"]

    def test_reproject_scales_with_current_value(self, sched):
        sched._store_heavy("BV1", {"heavyA": _heavy_entry(velocity=3600.0)}, anchor_idx=0)
        results: Dict[str, Any] = {}
        sched._inject_reused("BV1", results, 5000.0, [100000], ["10万"], 0)
        assert results["heavyA"]["prediction"] == pytest.approx(5000.0 + 3600.0 * _SHORT_HOURS)

    def test_existing_result_not_overwritten(self, sched):
        sched._store_heavy("BV1", {"heavyA": _heavy_entry()}, anchor_idx=0)
        results = {"heavyA": {"prediction": 1.0, "weight": 1.0, "confidence": 1.0, "metadata": {}}}
        assert sched._inject_reused("BV1", results, 1000.0, [100000], ["10万"], 0) == []
        assert results["heavyA"]["prediction"] == 1.0

    def test_zero_velocity_falls_back_like_production(self, sched):
        """速度<=0 时走 _to_registry_result 的 1% 兜底分支（非重投影公式）。"""
        entry = _heavy_entry(velocity=0.0)
        entry["predicted_hours"] = float("inf")
        sched._store_heavy("BV1", {"heavyA": entry}, anchor_idx=0)
        results: Dict[str, Any] = {}
        sched._inject_reused("BV1", results, 1000.0, [100000], ["10万"], 0)
        assert results["heavyA"]["prediction"] == pytest.approx(1000.0 * 1.01)


class TestReusedWeightIsolation:
    def test_reused_excluded_from_window_history(self, sched):
        results = {
            "a": {"prediction": 1100.0, "weight": 1.0, "confidence": 0.5, "metadata": {"scheduled_reuse": True}},
            "b": {"prediction": 1005.0, "weight": 1.0, "confidence": 0.5, "metadata": {}},
            "c": {"prediction": 1010.0, "weight": 1.0, "confidence": 0.5, "metadata": {}},
        }
        valid = sched._get_valid_predictions(results)
        sched._apply_window_weights(results, valid, 1000.0)
        assert results["a"]["weight"] == 1.0  # 复用项权重保持缓存值
        assert "a" not in sched._window_weight_history  # 不计入「算法表现」历史
        assert "b" in sched._window_weight_history
        assert "c" in sched._window_weight_history

    def test_is_reused_flag(self, sched):
        assert sched._is_reused({"metadata": {"scheduled_reuse": True}}) is True
        assert sched._is_reused({"metadata": {}}) is False
        assert sched._is_reused(None) is False
