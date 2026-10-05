"""Read-only data consistency audit coverage."""

import hashlib
import os
import sqlite3

from core.database.consistency_audit import audit_video_consistency


def _hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest(), os.stat(path).st_mtime_ns


def _create_video_db(path):
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    connection.executescript("""
        PRAGMA user_version=7;
        CREATE TABLE monitor_records (timestamp TEXT);
        CREATE TABLE predictions (algorithm TEXT, target_threshold INTEGER, created_at TEXT);
        CREATE TABLE weekly_scores (timestamp TEXT);
        CREATE TABLE yearly_scores (timestamp TEXT);
        INSERT INTO monitor_records VALUES ('2026-01-02');
        INSERT INTO monitor_records VALUES ('2026-01-03');
        INSERT INTO predictions VALUES ('a', 1, '2026-01-03');
        INSERT INTO predictions VALUES ('a', 1, '2026-01-04');
        INSERT INTO weekly_scores VALUES ('2026-01-03');
        INSERT INTO yearly_scores VALUES ('2026-01-03');
        """)
    connection.commit()
    connection.close()


def _create_central_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE monitor_records (bvid TEXT, timestamp TEXT);
        CREATE TABLE predictions (bvid TEXT, algorithm TEXT, target_threshold INTEGER, created_at TEXT);
        CREATE TABLE weekly_scores (bvid TEXT, timestamp TEXT);
        INSERT INTO monitor_records VALUES ('BV1', '2026-01-02');
        INSERT INTO predictions VALUES ('BV1', 'a', 1, '2026-01-03');
        INSERT INTO weekly_scores VALUES ('BV1', '2026-01-02');
        """)
    connection.commit()
    connection.close()


def test_audit_reports_count_watermark_and_missing_table_without_writes(tmp_path):
    active_root = tmp_path / "active"
    backup_root = tmp_path / "backup"
    video_path = active_root / "BV1" / "BV1.db"
    central_path = active_root / "bilibili_monitor.db"
    _create_video_db(video_path)
    _create_central_db(central_path)
    before = {path: _hash_file(path) for path in (video_path, central_path)}

    report = audit_video_consistency("BV1", str(active_root), str(backup_root))

    after = {path: _hash_file(path) for path in (video_path, central_path)}
    assert before == after
    central_entries = {entry["stream"]: entry for entry in report["flows"][0]}
    assert central_entries["monitor_records"]["count_delta"] == 1
    assert central_entries["monitor_records"]["watermark_lag"] == "target_behind"
    assert central_entries["weekly_scores"]["watermark_lag"] == "target_behind"
    assert central_entries["yearly_scores"]["missing_target_table"]
    assert central_entries["monitor_records"]["schema_version"] == 7
    assert all(entry["missing_target_file"] for entry in report["flows"][1])
