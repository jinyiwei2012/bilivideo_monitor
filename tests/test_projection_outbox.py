"""Authority-table and durable outbox schema and transaction tests."""

import sqlite3
import json

import pytest

from core.database.central_schema import migrate_central_schema
from core.database.central_db import Database
from core.database.models import MonitorRecord, PredictionRecord
from core.database.video_db import VideoDatabase
from core.database.projector import ProjectionEvent


def test_projection_cycle_reuses_projector_and_acquires_video_leases(monkeypatch) -> None:
    from types import SimpleNamespace
    from ui import main_gui_tick

    calls = []
    video_db = object()
    gui = SimpleNamespace()
    monkeypatch.setattr(main_gui_tick, "load_config", lambda: {"projection": {"mode": "shadow", "batch_size": 7}})
    monkeypatch.setattr(main_gui_tick, "projector_enabled", lambda: True)
    monkeypatch.setattr(main_gui_tick, "video_db_ids", lambda _gui: ["BV1xx411c7mD"])

    def lease(_gui, bvid, operation):
        calls.append(bvid)
        return operation(video_db)

    monkeypatch.setattr(main_gui_tick, "use_video_db", lease)
    import core
    from core.database.projector import CentralProjector, ProjectionRunResult

    monkeypatch.setattr(core, "get_db", lambda: object())
    monkeypatch.setattr(CentralProjector, "project_video", lambda self, db: ProjectionRunResult(delivered=1))
    main_gui_tick._run_projection_cycle(gui)
    projector = gui._central_projector
    assert projector._batch_size == 7
    main_gui_tick._run_projection_cycle(gui)
    assert gui._central_projector is projector
    assert calls == ["BV1xx411c7mD", "BV1xx411c7mD"]
    assert projector._run_lock.acquire(blocking=False)
    try:
        main_gui_tick._run_projection_cycle(gui)
        assert len(calls) == 2
    finally:
        projector._run_lock.release()


def test_monitor_payload_contains_full_record(tmp_path) -> None:
    database = VideoDatabase("BV1xx411c7mD", str(tmp_path))
    try:
        record = _record()
        assert database.add_monitor_record(record)
        payload = json.loads(database._conn.execute("SELECT payload FROM projection_outbox").fetchone()[0])
        assert set(record.__dataclass_fields__) <= payload.keys()
        assert payload["like_count"] == record.like_count
        assert "observed_at_us" in payload
    finally:
        database.close()


def test_nested_cycle_interval_survives_outbox_delivery(tmp_path) -> None:
    from core.database.projector import CentralProjector

    video = VideoDatabase("BV1xx411c7mD", str(tmp_path / "videos"))
    central = Database(str(tmp_path / "central.db"))
    try:
        assert video.save_prediction_cycle(
            "2026-10-05 12:00:00",
            [],
            {"prediction": 100, "prediction_interval": {"lower": 80, "upper": 120, "interval_width_ratio": 0.4}},
            [],
        )
        assert CentralProjector(central).project_video(video).delivered == 1
        row = central._conn.execute(
            "SELECT interval_lower, interval_upper, interval_width_ratio FROM prediction_ensemble"
        ).fetchone()
        assert tuple(row) == (80, 120, 0.4)
    finally:
        video.close()
        central.close()


def test_prediction_cycle_and_milestone_authority_are_atomic(tmp_path, monkeypatch) -> None:
    database = VideoDatabase("BV1xx411c7mD", str(tmp_path))
    prediction = {"algorithm": "linear", "algorithm_id": "linear", "target_threshold": 100, "is_reached": True}
    try:
        assert database.save_prediction_cycle(
            "2026-10-05 12:00:00", [prediction], {"prediction": 100}, [("linear", 0.5)]
        )
        assert database.upsert_milestone("1周", {"view_count": 100})
        for table in ("predictions", "prediction_ensemble", "algorithm_coherence", "video_milestones"):
            assert database._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1
        assert database._conn.execute("SELECT COUNT(*) FROM projection_outbox").fetchone()[0] == 4
        assert database._conn.execute("SELECT is_reached FROM predictions").fetchone()[0] == 1

        def fail_enqueue(*args, **kwargs):
            raise RuntimeError("atomicity probe")

        monkeypatch.setattr(database, "_enqueue_outbox", fail_enqueue)
        assert not database.save_prediction_cycle("2026-10-05 12:01:00", [], {"prediction": 200}, [])
        assert database._conn.execute("SELECT COUNT(*) FROM prediction_ensemble").fetchone()[0] == 1
        assert database._conn.execute("SELECT COUNT(*) FROM projection_outbox").fetchone()[0] == 4
    finally:
        database.close()


def test_projection_preserves_weekly_ensemble_and_prediction_fields(tmp_path) -> None:
    central = Database(str(tmp_path / "central.db"))
    try:
        events = [
            ProjectionEvent(
                1, "weekly_scores", "2026-10-05 12:00:00", 1, {"correction_d": 1.25, "base_view_score": 42}
            ),
            ProjectionEvent(
                2, "prediction_ensemble", "2026-10-05 12:00:00", 1, {"interval_lower": 10, "interval_upper": 20}
            ),
            ProjectionEvent(
                3, "prediction_ensemble", "2026-10-05 12:01:00", 2, {"prediction_interval": {"lower": 30, "upper": 40}}
            ),
            ProjectionEvent(
                4,
                "predictions",
                "linear:100",
                1,
                {
                    "algorithm": "linear",
                    "target_threshold": 100,
                    "is_reached": True,
                    "actual_time": "done",
                    "error_rate": 0.1,
                    "predicted_views": 99,
                },
            ),
        ]
        central.apply_projection_batch("BV1xx411c7mD", events)
        assert tuple(central._conn.execute("SELECT correction_d, base_view_score FROM weekly_scores").fetchone()) == (
            1.25,
            42,
        )
        assert [
            tuple(row)
            for row in central._conn.execute(
                "SELECT interval_lower, interval_upper FROM prediction_ensemble ORDER BY id"
            )
        ] == [(10, 20), (30, 40)]
        assert tuple(
            central._conn.execute(
                "SELECT is_reached, actual_time, error_rate, predicted_views FROM predictions"
            ).fetchone()
        ) == (1, "done", 0.1, 99)
    finally:
        central.close()


def _record() -> MonitorRecord:
    return MonitorRecord("BV1xx411c7mD", "2026-10-05 12:00:00", 1, 1, 1, 1, 1, 1, 1)


def test_video_schema_v6_adds_authority_tables_and_outbox(tmp_path) -> None:
    database = VideoDatabase("BV1xx411c7mD", str(tmp_path))
    try:
        tables = {row[0] for row in database._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"prediction_ensemble", "algorithm_coherence", "video_milestones", "projection_outbox"} <= tables
        assert database._conn.execute("PRAGMA user_version").fetchone()[0] == 6
    finally:
        database.close()


def test_video_v6_failure_rolls_back_schema_and_version(tmp_path, monkeypatch) -> None:
    bvid = "BV1xx411c7mD"
    database = VideoDatabase(bvid, str(tmp_path))
    database.close()
    path = tmp_path / bvid / f"{bvid}.db"
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE projection_outbox")
        connection.execute("DROP TABLE video_milestones")
        connection.execute("DROP TABLE algorithm_coherence")
        connection.execute("DROP TABLE prediction_ensemble")
        connection.execute("PRAGMA user_version = 5")

    def fail_v6(connection):
        connection.execute("CREATE TABLE outbox_failure_probe (id INTEGER)")
        raise RuntimeError("injected v6 failure")

    monkeypatch.setattr(VideoDatabase, "_migrate_projection_outbox", staticmethod(fail_v6))
    with pytest.raises(RuntimeError, match="injected v6 failure"):
        VideoDatabase(bvid, str(tmp_path))
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='outbox_failure_probe'"
            ).fetchone()
            is None
        )


def test_central_v4_failure_rolls_back_idempotency_indexes(monkeypatch) -> None:
    import core.database.central_schema as central_schema

    connection = sqlite3.connect(":memory:")
    try:
        central_schema._migrate_central_v1(connection)
        central_schema._migrate_central_v2(connection)
        central_schema._migrate_central_v3(connection)
        connection.execute("PRAGMA user_version = 3")
        connection.commit()

        def fail_v4(conn):
            conn.execute("CREATE INDEX central_failure_probe ON videos(title)")
            raise RuntimeError("injected v4 failure")

        monkeypatch.setattr(central_schema, "_migrate_central_v4", fail_v4)
        with pytest.raises(RuntimeError, match="injected v4 failure"):
            migrate_central_schema(connection)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE name='central_failure_probe'").fetchone() is None
        )
    finally:
        connection.close()


def test_central_v3_upgrades_to_v4_with_projection_indexes() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        import core.database.central_schema as central_schema

        central_schema._migrate_central_v1(connection)
        central_schema._migrate_central_v2(connection)
        central_schema._migrate_central_v3(connection)
        connection.execute("PRAGMA user_version = 3")
        connection.commit()
        migrate_central_schema(connection)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(monitor_records)")}
        assert "idx_monitor_source_row" in indexes
    finally:
        connection.close()


def test_monitor_write_and_outbox_are_atomic(tmp_path, monkeypatch) -> None:
    database = VideoDatabase("BV1xx411c7mD", str(tmp_path))
    try:
        original_enqueue = database._enqueue_outbox

        def fail_after_enqueue(*args, **kwargs):
            original_enqueue(*args, **kwargs)
            raise RuntimeError("injected post-outbox failure")

        monkeypatch.setattr(database, "_enqueue_outbox", fail_after_enqueue)
        assert not database.add_monitor_record(_record())
        assert database._conn.execute("SELECT COUNT(*) FROM monitor_records").fetchone()[0] == 0
        assert database._conn.execute("SELECT COUNT(*) FROM projection_outbox").fetchone()[0] == 0
    finally:
        database.close()


def test_outbox_content_and_legacy_central_sync_coexist(tmp_path) -> None:
    database = VideoDatabase("BV1xx411c7mD", str(tmp_path / "videos"), legacy_central_sync=True)
    central = Database(str(tmp_path / "central.db"))
    try:
        assert database.add_monitor_record(_record())
        row = database._conn.execute(
            "SELECT stream, entity_key, operation, created_at FROM projection_outbox"
        ).fetchone()
        assert tuple(row)[:3] == ("monitor_records", "2026-10-05 12:00:00", "upsert")
        assert row[3]
        database.set_central_db(central)
        assert database.add_prediction(
            PredictionRecord(
                database.bvid,
                "legacy",
                "legacy",
                10,
                1,
                "2026-10-05 12:00:00",
                1.0,
                1,
            )
        )
        assert central._conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 1
    finally:
        database.close()
        central.close()
