"""学习状态持久化可靠性回归测试。"""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from algorithms.online_learner import OnlineLearner
from algorithms.weight_manager import WeightManager


def _read_json(path):
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def test_weight_manager_concurrent_updates_flush_latest_state(tmp_path):
    manager = WeightManager(save_dir=str(tmp_path), save_update_threshold=10_000)

    def update(index):
        if index % 2:
            manager.update_accuracy(f"algo_{index % 5}", index / 100)
        else:
            manager.update_accuracy_batch([(f"algo_{index % 5}", index / 100)])

    with ThreadPoolExecutor(max_workers=30) as executor:
        list(executor.map(update, range(50)))

    manager.sync_save()
    data = _read_json(tmp_path / "default_weights.json")
    assert sum(len(records) for records in data["accuracy_records"].values()) == 50
    assert data["state_version"] == manager._state_version
    assert data["state_version"] >= manager._persisted_version


@pytest.mark.parametrize("failure", ["replace", "dump"])
def test_atomic_write_failure_preserves_old_file_and_cleans_temp(tmp_path, monkeypatch, failure):
    manager = WeightManager(save_dir=str(tmp_path))
    manager.set_user_weight("stable", 2.0)
    state_file = tmp_path / "default_weights.json"
    old_data = _read_json(state_file)

    if failure == "replace":
        monkeypatch.setattr(os, "replace", lambda *args: (_ for _ in ()).throw(OSError("replace failed")))
    else:
        monkeypatch.setattr(json, "dump", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("dump failed")))

    manager.set_user_weight("new", 3.0)

    assert _read_json(state_file) == old_data
    assert list(tmp_path.glob("*.tmp")) == []


def test_weight_manager_round_trip_preserves_records_and_weights(tmp_path):
    manager = WeightManager(save_dir=str(tmp_path))
    manager.set_user_weight("custom", 2.5)
    manager.update_accuracy_batch([("a", 0.8), ("b", 0.4)])
    manager.sync_save()

    restored = WeightManager(save_dir=str(tmp_path))
    assert restored.user_weights == manager.user_weights
    assert restored.ml_weights == pytest.approx(manager.ml_weights)
    assert restored.accuracy_records == manager.accuracy_records


def test_weight_manager_updates_are_throttled_but_sync_save_forces_flush(tmp_path, monkeypatch):
    replacements = []
    original_replace = os.replace

    def record_replace(source, destination):
        replacements.append((source, destination))
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", record_replace)
    manager = WeightManager(save_dir=str(tmp_path), save_interval_seconds=3600, save_update_threshold=20)
    for index in range(19):
        manager.update_accuracy("algo", index / 20)
    assert replacements == []

    manager.update_accuracy("algo", 0.95)
    assert len(replacements) == 1
    manager.update_accuracy("algo", 0.9)
    assert len(replacements) == 1

    manager.sync_save()
    assert len(replacements) == 2


def test_online_learner_round_trip_recreates_unregistered_trackers(tmp_path):
    state_file = tmp_path / "learner.json"
    learner = OnlineLearner(["a", "b"], warmup=1)
    learner.update("a", predicted=90, actual=100)
    learner.update("b", predicted=50, actual=100)
    learner.update_ogd("a", gradient=0.25)
    learner.save(str(state_file))

    restored = OnlineLearner(warmup=1)
    restored.load(str(state_file))

    assert set(restored.get_algorithm_stats()) == {"a", "b"}
    assert restored.get_algorithm_stats()["a"]["error_count"] == 2
    assert restored._trackers["a"].weight == pytest.approx(learner._trackers["a"].weight)
    assert restored.get_weights() == pytest.approx(learner.get_weights())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [("schema_version", 999, "schema"), ("algorithm_fingerprint", "invalid", "指纹")],
)
def test_online_learner_schema_or_fingerprint_mismatch_is_safe(tmp_path, caplog, field, value, message):
    state_file = tmp_path / "learner.json"
    learner = OnlineLearner(["a"])
    learner.update("a", predicted=90, actual=100)
    learner.save(str(state_file))
    data = _read_json(state_file)
    data[field] = value
    state_file.write_text(json.dumps(data), encoding="utf-8")

    restored = OnlineLearner()
    with caplog.at_level(logging.WARNING):
        restored.load(str(state_file))

    assert restored.get_algorithm_stats() == {}
    assert message in caplog.text


def test_online_learner_registered_set_mismatch_restores_intersection(tmp_path, caplog):
    state_file = tmp_path / "learner.json"
    learner = OnlineLearner(["a", "file_only"])
    learner.update("a", predicted=90, actual=100)
    learner.update("file_only", predicted=80, actual=100)
    learner.save(str(state_file))

    restored = OnlineLearner(["a", "runtime_only"])
    with caplog.at_level(logging.WARNING):
        restored.load(str(state_file))

    stats = restored.get_algorithm_stats()
    assert set(stats) == {"a", "runtime_only"}
    assert stats["a"]["error_count"] == 1
    assert stats["runtime_only"]["error_count"] == 0
    assert "算法集合" in caplog.text


def test_online_learner_atomic_failure_preserves_old_file(tmp_path, monkeypatch):
    state_file = tmp_path / "learner.json"
    learner = OnlineLearner(["a"])
    learner.save(str(state_file))
    old_data = _read_json(state_file)
    learner.update("a", predicted=50, actual=100)
    monkeypatch.setattr(os, "replace", lambda *args: (_ for _ in ()).throw(OSError("replace failed")))

    learner.save(str(state_file))

    assert _read_json(state_file) == old_data
    assert list(tmp_path.glob("*.tmp")) == []
