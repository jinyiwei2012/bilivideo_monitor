import sqlite3

from core.database.central_db import Database
from core.database.models import MonitorRecord
from core.database.video_db import VideoDatabase


def test_monitor_timing_fields_roundtrip_through_video_and_central_databases(tmp_path) -> None:
    bvid = "BV1TEST12345"
    video_db = VideoDatabase(bvid, str(tmp_path / "videos"))
    central_db = Database(str(tmp_path / "central.db"))
    record = MonitorRecord(
        bvid=bvid,
        timestamp="2026-10-04 11:16:23",
        view_count=10_000_137,
        like_count=500_000,
        coin_count=1,
        share_count=2,
        favorite_count=3,
        danmaku_count=4,
        reply_count=5,
        observed_at_us=1_759_634_183_767_000,
        request_start_us=1_759_634_183_417_000,
        rtt_us=350_000,
    )

    try:
        assert video_db.add_monitor_record(record)
        with sqlite3.connect(video_db.db_path) as conn:
            stored = conn.execute("SELECT observed_at_us, request_start_us, rtt_us FROM monitor_records").fetchone()
        assert stored == (record.observed_at_us, record.request_start_us, record.rtt_us)

        assert central_db.add_monitor_record(record)
        with sqlite3.connect(central_db.db_path) as conn:
            mirrored = conn.execute(
                "SELECT observed_at_us, request_start_us, rtt_us FROM monitor_records WHERE bvid = ?",
                (bvid,),
            ).fetchone()
        assert mirrored == stored
    finally:
        video_db.close()
        central_db.close()


def test_existing_central_database_migrates_monitor_timing_columns(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE monitor_records (id INTEGER PRIMARY KEY, bvid TEXT, timestamp TIMESTAMP)")

    database = Database(str(path))
    try:
        with sqlite3.connect(path) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(monitor_records)")}
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert {"observed_at_us", "request_start_us", "rtt_us"} <= columns
        assert "sync_cursors" in tables
        assert version == 4
    finally:
        database.close()
