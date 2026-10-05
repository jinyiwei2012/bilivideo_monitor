"""Read-only comparison of per-video detail against existing data copies."""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from . import data_layout

_STREAMS = {
    "monitor_records": ("timestamp", False),
    "predictions": ("created_at", True),
    "weekly_scores": ("timestamp", False),
    "yearly_scores": ("timestamp", False),
}


def _open_read_only(path: str) -> sqlite3.Connection | None:
    """Open an existing SQLite database without permitting any mutation."""
    if not os.path.isfile(path):
        return None
    uri = f"file:{path.replace(chr(92), '/')}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _has_table(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def read_sync_cursors(db_path: str) -> list[dict[str, Any]]:
    """Read central synchronization observations without changing data selection."""
    connection = _open_read_only(db_path)
    if connection is None:
        return []
    try:
        if not _has_table(connection, "sync_cursors"):
            return []
        columns = "scope, stream, partition_key, watermark, updated_at, status, last_error"
        rows = connection.execute(
            f"SELECT {columns} FROM sync_cursors ORDER BY scope, stream, partition_key"
        ).fetchall()
        return [dict(zip(columns.split(", "), row)) for row in rows]
    finally:
        connection.close()


def _stream_values(
    connection: sqlite3.Connection, table: str, watermark_column: str, logical_predictions: bool, bvid: str | None
) -> tuple[int | None, str | None, bool]:
    """Return count, watermark, and table availability for one stream."""
    if not _has_table(connection, table):
        return None, None, False
    where = " WHERE bvid=?" if bvid is not None else ""
    params: tuple[str, ...] = (bvid,) if bvid is not None else ()
    if logical_predictions:
        count_sql = f"SELECT COUNT(*) FROM (SELECT algorithm, target_threshold FROM {table}{where} GROUP BY algorithm, target_threshold)"
    else:
        count_sql = f"SELECT COUNT(*) FROM {table}{where}"
    count = connection.execute(count_sql, params).fetchone()[0]
    watermark = connection.execute(f"SELECT MAX({watermark_column}) FROM {table}{where}", params).fetchone()[0]
    return count, watermark, True


def _watermark_lag(source: str | None, target: str | None) -> str | None:
    """Describe ordering lag without imposing a timestamp format or timezone policy."""
    if source is None or target is None:
        return None
    return "target_behind" if target < source else "in_sync_or_ahead"


def _compare_flow(
    bvid: str,
    source_role: str,
    source_path: str,
    target_role: str,
    target_path: str,
    target_has_bvid: bool,
    checked_at: str,
) -> list[dict[str, Any]]:
    """Compare all audited streams for one source-to-target data flow."""
    source = _open_read_only(source_path)
    target = _open_read_only(target_path)
    try:
        source_version = source.execute("PRAGMA user_version").fetchone()[0] if source is not None else None
        entries: list[dict[str, Any]] = []
        for stream, (watermark_column, logical_predictions) in _STREAMS.items():
            source_values = (
                _stream_values(source, stream, watermark_column, logical_predictions, None)
                if source is not None
                else (None, None, False)
            )
            target_values = (
                _stream_values(target, stream, watermark_column, logical_predictions, bvid if target_has_bvid else None)
                if target is not None
                else (None, None, False)
            )
            source_count, source_watermark, source_table = source_values
            target_count, target_watermark, target_table = target_values
            entries.append(
                {
                    "bvid": bvid,
                    "source_role": source_role,
                    "target_role": target_role,
                    "stream": stream,
                    "source_row_count": source_count,
                    "target_row_count": target_count,
                    "count_delta": (
                        None if source_count is None or target_count is None else source_count - target_count
                    ),
                    "source_max_watermark": source_watermark,
                    "target_max_watermark": target_watermark,
                    "watermark_lag": _watermark_lag(source_watermark, target_watermark),
                    "missing_source_file": source is None,
                    "missing_target_file": target is None,
                    "missing_source_table": not source_table,
                    "missing_target_table": not target_table,
                    "schema_version": source_version,
                    "checked_at": checked_at,
                }
            )
        return entries
    finally:
        if source is not None:
            source.close()
        if target is not None:
            target.close()


def audit_video_consistency(
    bvid: str, active_root: str | None = None, backup_root: str | None = None
) -> dict[str, Any]:
    """Return a read-only consistency report for an existing BVID's data flows.

    The active video database is the source of each comparison.  Its central
    projection and its backup-root mirror are reported independently so callers
    can distinguish projection drift from mirror drift.
    """
    active_base = active_root or data_layout.active_root()
    backup_base = backup_root or data_layout.backup_root()
    source_path = os.path.join(active_base, bvid, f"{bvid}.db")
    checked_at = datetime.now(timezone.utc).isoformat()
    flows = [
        _compare_flow(
            bvid,
            "active_video",
            source_path,
            "active_central",
            os.path.join(active_base, data_layout.CENTRAL_DB_FILENAME),
            True,
            checked_at,
        ),
        _compare_flow(
            bvid,
            "active_video",
            source_path,
            "mirror_video",
            os.path.join(backup_base, bvid, f"{bvid}.db"),
            False,
            checked_at,
        ),
    ]
    return {
        "bvid": bvid,
        "checked_at": checked_at,
        "flows": flows,
        "entries": [entry for flow in flows for entry in flow],
        "sync_cursors": read_sync_cursors(os.path.join(active_base, data_layout.CENTRAL_DB_FILENAME)),
    }
