"""Frozen process routing and authority-first central-write matrix."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import config
from config import runtime_mode
from core.database.video_db import VideoDatabase
from ui.monitor import _prediction, _service
from ui import main_gui_tick


@pytest.mark.parametrize(
    "configured,effective", [("legacy", "legacy"), ("shadow", "projector"), ("projector", "projector")]
)
def test_frozen_mode_matrix(configured, effective, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_mode, "_effective_mode", None)
    settings = {"projection": {"mode": configured}}
    monkeypatch.setattr(config, "load_config", lambda: settings)
    assert runtime_mode.effective_projection_mode() == effective
    settings["projection"]["mode"] = "legacy" if effective == "projector" else "projector"
    assert runtime_mode.effective_projection_mode() == effective
    central = Mock()
    monkeypatch.setattr(_prediction, "db", central)
    monkeypatch.setattr(_service, "db", central)
    _prediction._sync_predictions_to_central("BV1xx411c7mD", [{"algorithm": "a"}], {"prediction": 1}, [("a", 0.5)])
    video = {
        key: 1
        for key in (
            "view_count",
            "like_count",
            "coin_count",
            "share_count",
            "favorite_count",
            "danmaku_count",
            "reply_count",
        )
    }
    from datetime import datetime

    _service._sync_monitor_record(SimpleNamespace(), "BV1xx411c7mD", video, datetime(2026, 10, 5))
    _service._sync_video_info(SimpleNamespace(), "BV1xx411c7mD", video)
    expected = int(effective == "legacy")
    assert central.sync_predictions.call_count == expected
    assert central.sync_prediction_ensemble.call_count == expected
    assert central.sync_algorithm_coherence.call_count == expected
    assert central.sync_monitor_record.call_count == expected
    assert central.sync_video_info.call_count == 1
    database = VideoDatabase("BV1xx411c7mD", str(tmp_path))
    try:
        database.set_central_db(central)
        assert database.add_predictions_batch([{"algorithm": "a", "target_threshold": 100}])
        assert central.sync_predictions.call_count == 2 * expected
        assert database.upsert_milestone("1周", {"view_count": 100})
        assert database._conn.execute("SELECT COUNT(*) FROM projection_outbox").fetchone()[0] == 2
    finally:
        database.close()
    if effective == "legacy":
        gui = SimpleNamespace()
        main_gui_tick._run_projection_cycle(gui)
        assert not hasattr(gui, "_central_projector")


def test_default_saved_alias_invalid_and_restart(monkeypatch, caplog):
    assert config.DEFAULT_CONFIG["projection"]["mode"] == "projector"
    monkeypatch.setattr(runtime_mode, "_effective_mode", None)
    monkeypatch.setattr(config, "load_config", lambda: {"projection": {"mode": "legacy"}})
    assert runtime_mode.effective_projection_mode() == "legacy"
    monkeypatch.setattr(config, "load_config", lambda: {"projection": {"mode": "projector"}})
    assert runtime_mode.effective_projection_mode() == "legacy"
    monkeypatch.setattr(runtime_mode, "_effective_mode", None)
    assert runtime_mode.effective_projection_mode() == "projector"
    assert runtime_mode.resolve_projection_mode("shadow") == "projector"
    assert "independent shadow target" in caplog.text
    with pytest.raises(ValueError, match="Invalid projection.mode"):
        runtime_mode.resolve_projection_mode("invalid")


@pytest.mark.parametrize("mode", ["legacy", "shadow", "projector"])
@pytest.mark.parametrize("saved", [True, False])
def test_manual_observation_authority_first(mode, saved, monkeypatch):
    from ui import entry_tab

    monkeypatch.setattr(runtime_mode, "_effective_mode", None)
    monkeypatch.setattr(config, "load_config", lambda: {"projection": {"mode": mode}})
    central = Mock()
    monkeypatch.setattr(entry_tab, "get_db", lambda: central)
    video = Mock()
    video.add_monitor_record.return_value = saved
    panel = SimpleNamespace(_video_dbs={"BV1xx411c7mD": video})
    assert (
        entry_tab.EntryTab._save_snapshot_record(panel, "BV1xx411c7mD", "2026-10-05 12:00:00", {"view_count": 100})
        == saved
    )
    assert central.sync_monitor_record.call_count == int(saved and mode == "legacy")
