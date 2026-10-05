"""Authority-table and durable outbox schema and transaction tests."""

import sqlite3

import pytest

from core.database.central_schema import migrate_central_schema
from core.database.central_db import Database
from core.database.models import MonitorRecord, PredictionRecord
from core.database.video_db import VideoDatabase


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
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
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
    database = VideoDatabase("BV1xx411c7mD", str(tmp_path / "videos"))
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
