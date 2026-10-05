"""Transactional migration regression coverage for video and central schemas."""

import sqlite3

import pytest

from core.database.central_schema import migrate_central_schema
from core.database.video_db import VIDEO_SCHEMA_VERSION, VideoDatabase


def test_video_v4_failure_rolls_back_version_and_schema(tmp_path, monkeypatch) -> None:
    bvid = "BV1xx411c7mD"
    database = VideoDatabase(bvid, str(tmp_path))
    database.close()
    path = tmp_path / bvid / f"{bvid}.db"
    with sqlite3.connect(path) as conn:
        conn.execute("DROP INDEX idx_weekly_ts")
        conn.execute("DROP INDEX idx_yearly_ts")
        conn.execute("PRAGMA user_version = 3")

    def fail_v4(self, conn):
        conn.execute("CREATE TABLE migration_failure_probe (id INTEGER)")
        raise RuntimeError("injected v4 failure")

    monkeypatch.setattr(VideoDatabase, "_migrate_scores_unique", fail_v4)
    with pytest.raises(RuntimeError, match="injected v4 failure"):
        VideoDatabase(bvid, str(tmp_path))

    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='migration_failure_probe'"
            ).fetchone()
            is None
        )
    monkeypatch.undo()

    database = VideoDatabase(bvid, str(tmp_path))
    try:
        assert database._conn.execute("PRAGMA user_version").fetchone()[0] == VIDEO_SCHEMA_VERSION
    finally:
        database.close()


def test_central_v3_failure_rolls_back_version_and_schema(monkeypatch) -> None:
    import core.database.central_schema as central_schema

    conn = sqlite3.connect(":memory:")
    try:
        central_schema._migrate_central_v1(conn)
        central_schema._migrate_central_v2(conn)
        conn.execute("PRAGMA user_version = 2")
        conn.commit()

        def fail_v3(connection):
            connection.execute("CREATE TABLE central_failure_probe (id INTEGER)")
            raise RuntimeError("injected v3 failure")

        monkeypatch.setattr(central_schema, "_migrate_central_v3", fail_v3)
        with pytest.raises(RuntimeError, match="injected v3 failure"):
            migrate_central_schema(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='central_failure_probe'"
            ).fetchone()
            is None
        )

        monkeypatch.undo()
        migrate_central_schema(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
        assert conn.execute("SELECT * FROM sync_cursors").fetchall() == []
    finally:
        conn.close()
