"""Observational synchronization cursor tests without UI or network dependencies."""

import sqlite3

from core.database.central_db import Database
from core.database.consistency_audit import read_sync_cursors


def _cursor(database: Database, stream: str, bvid: str) -> sqlite3.Row:
    row = database._conn.execute(
        "SELECT watermark, status, last_error FROM sync_cursors WHERE scope=? AND stream=? AND partition_key=?",
        ("active_video", stream, bvid),
    ).fetchone()
    assert row is not None
    return row


def test_cursor_upsert_replaces_same_key(tmp_path) -> None:
    database = Database(str(tmp_path / "central.db"))
    try:
        database.upsert_sync_cursor(
            scope="active_video", stream="monitor_records", partition_key="BV1", watermark="first", status="success"
        )
        database.upsert_sync_cursor(
            scope="active_video",
            stream="monitor_records",
            partition_key="BV1",
            watermark="second",
            status="error",
            last_error="failed",
        )
        row = _cursor(database, "monitor_records", "BV1")
        assert tuple(row) == ("second", "error", "failed")
    finally:
        database.close()


def test_sync_observations_record_success_and_preserve_watermark_on_failure(tmp_path) -> None:
    database = Database(str(tmp_path / "central.db"))
    bvid = "BV1"
    timestamp = "2026-10-05 12:00:00"
    try:
        assert database.sync_monitor_record(bvid, {"timestamp": timestamp, "view_count": 1})
        assert tuple(_cursor(database, "monitor_records", bvid)) == (timestamp, "success", None)

        database._conn.execute("DROP TABLE monitor_records")
        database._conn.commit()
        assert not database.sync_monitor_record(bvid, {"timestamp": "2026-10-05 12:01:00"})
        assert tuple(_cursor(database, "monitor_records", bvid)) == (
            timestamp,
            "error",
            "no such table: monitor_records",
        )
    finally:
        database.close()


def test_cursor_report_reads_observations(tmp_path) -> None:
    path = tmp_path / "central.db"
    database = Database(str(path))
    try:
        database.upsert_sync_cursor(
            scope="active_video", stream="weekly_scores", partition_key="BV1", watermark="2026-10-05", status="success"
        )
        assert read_sync_cursors(str(path)) == [
            {
                "scope": "active_video",
                "stream": "weekly_scores",
                "partition_key": "BV1",
                "watermark": "2026-10-05",
                "updated_at": database._conn.execute("SELECT updated_at FROM sync_cursors").fetchone()[0],
                "status": "success",
                "last_error": None,
            }
        ]
    finally:
        database.close()


def test_backup_sync_result_is_unchanged_by_cursor_observation(tmp_path, monkeypatch) -> None:
    active_dir = tmp_path / "active"
    backup_dir = tmp_path / "backup"
    active_dir.mkdir()
    backup_dir.mkdir()
    active = Database(str(active_dir / "bilibili_monitor.db"))
    backup = Database(str(backup_dir / "bilibili_monitor.db"))
    backup.close()
    monkeypatch.setattr(Database, "_BACKUP_DIR", str(backup_dir))
    try:
        active._conn.execute(
            "INSERT INTO monitor_records (bvid, timestamp, view_count) VALUES (?, ?, ?)", ("BV1", "t1", 1)
        )
        active._conn.commit()
        first = active.sync_to_central()
        second = active.sync_to_central()
        assert first["synced_records"] == 1
        assert second["synced_records"] == 0
        cursors = read_sync_cursors(str(backup_dir / "bilibili_monitor.db"))
        assert any(cursor["stream"] == "monitor_records" and cursor["partition_key"] == "BV1" for cursor in cursors)
    finally:
        active.close()
