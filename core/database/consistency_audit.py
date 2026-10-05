"""Read-only comparison of per-video detail against existing data copies."""

import os
import sqlite3
import json
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


_PROJECTION_TABLES = {
    "monitor_records": "monitor_records",
    "predictions": "predictions",
    "weekly_scores": "weekly_scores",
    "yearly_scores": "yearly_scores",
    "prediction_ensemble": "prediction_ensemble",
    "algorithm_coherence": "algorithm_coherence",
    "video_milestones": "video_milestones",
}


def _projection_key(event: sqlite3.Row | tuple[Any, ...]) -> tuple[str, tuple[Any, ...]]:
    """Return the central logical key for one decoded outbox event."""
    stream, entity_key, source_row_id, payload = event[1], event[2], event[3], json.loads(event[4] or "{}")
    if stream in ("monitor_records", "prediction_ensemble", "algorithm_coherence") and source_row_id is not None:
        return stream, ("source_row_id", source_row_id)
    if stream == "predictions":
        return stream, (payload.get("algorithm"), payload.get("target_threshold", 0))
    if stream in ("weekly_scores", "yearly_scores"):
        return stream, (entity_key,)
    if stream == "video_milestones":
        return stream, (entity_key,)
    if stream == "prediction_ensemble":
        return stream, ("timestamp", payload.get("timestamp") or entity_key)
    if stream == "algorithm_coherence":
        return stream, ("timestamp_algorithm", payload.get("timestamp"), payload.get("algorithm"))
    return stream, (entity_key,)


def _central_row_for_key(
    connection: sqlite3.Connection, bvid: str, stream: str, key: tuple[Any, ...]
) -> list[sqlite3.Row]:
    """Look up central rows under the projection stream's stable key."""
    table = _PROJECTION_TABLES[stream]
    if key[0] == "source_row_id":
        return connection.execute(f"SELECT * FROM {table} WHERE bvid=? AND source_row_id=?", (bvid, key[1])).fetchall()
    if key[0] == "timestamp":
        return connection.execute(f"SELECT * FROM {table} WHERE bvid=? AND timestamp=?", (bvid, key[1])).fetchall()
    if key[0] == "timestamp_algorithm":
        return connection.execute(
            f"SELECT * FROM {table} WHERE bvid=? AND timestamp=? AND algorithm=?", (bvid, key[1], key[2])
        ).fetchall()
    if stream == "predictions":
        return connection.execute(
            "SELECT * FROM predictions WHERE bvid=? AND algorithm=? AND target_threshold=?", (bvid, key[0], key[1])
        ).fetchall()
    if stream in ("weekly_scores", "yearly_scores"):
        return connection.execute(f"SELECT * FROM {table} WHERE bvid=? AND timestamp=?", (bvid, key[0])).fetchall()
    return connection.execute(f"SELECT * FROM {table} WHERE bvid=? AND period=?", (bvid, key[0])).fetchall()


def _normalized(value: Any, field: str) -> Any:
    """Normalize persisted values before projection-value comparisons."""
    if field == "metadata" and isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    if field == "coherence" and value is not None:
        return round(float(value), 4)
    return value


def _audit_projection_event(
    central: sqlite3.Connection, bvid: str, event: sqlite3.Row, report: dict[str, Any]
) -> tuple[str, tuple[Any, ...]] | None:
    """Compare one source outbox event to its central logical entity."""
    stream, key = _projection_key(event)
    if stream not in _PROJECTION_TABLES:
        return None
    identity = {"stream": stream, "key": key, "event_id": event[0]}
    rows = _central_row_for_key(central, bvid, stream, key)
    if not rows:
        report["missing_in_central"].append(identity)
        return stream, key
    if len(rows) > 1:
        report["duplicate_logical_keys"].append({**identity, "count": len(rows)})
        return stream, key
    payload = json.loads(event[4] or "{}")
    actual = dict(rows[0])
    for field, expected in payload.items():
        if field not in actual or field == "prediction_interval":
            continue
        expected_value = _normalized(expected, field)
        actual_value = _normalized(actual[field], field)
        if actual_value != expected_value:
            report["value_mismatch"].append(
                {**identity, "field": field, "expected": expected_value, "actual": actual_value}
            )
    return stream, key


def _central_logical_key(stream: str, row: sqlite3.Row) -> tuple[Any, ...]:
    """Derive one central row's projection key."""
    if stream in ("monitor_records", "prediction_ensemble", "algorithm_coherence") and row["source_row_id"] is not None:
        return "source_row_id", row["source_row_id"]
    if stream == "predictions":
        return row["algorithm"], row["target_threshold"]
    if stream in ("weekly_scores", "yearly_scores", "prediction_ensemble"):
        return "timestamp", row["timestamp"]
    if stream == "algorithm_coherence":
        return "timestamp_algorithm", row["timestamp"], row["algorithm"]
    return (row["period"],)


def _find_unexpected_projection_rows(
    central: sqlite3.Connection, bvid: str, expected_keys: set[tuple[str, tuple[Any, ...]]]
) -> list[dict[str, Any]]:
    """Find central rows that are not represented by audited events."""
    unexpected = []
    for stream, table in _PROJECTION_TABLES.items():
        for row in central.execute(f"SELECT * FROM {table} WHERE bvid=?", (bvid,)).fetchall():
            key = _central_logical_key(stream, row)
            if (stream, key) not in expected_keys:
                unexpected.append({"stream": stream, "key": key, "id": row["id"]})
    return unexpected


def audit_projection_entities(
    bvid: str, video_db_path: str, central_db_path: str, *, event_ids: list[int] | None = None
) -> dict[str, Any]:
    """Read-only audit of outbox entities against their central projections."""
    checked_at = datetime.now(timezone.utc).isoformat()
    report: dict[str, Any] = {
        "missing_in_central": [],
        "value_mismatch": [],
        "duplicate_logical_keys": [],
        "unexpected_central_rows": [],
        "checked_event_ids": [],
        "checked_at": checked_at,
    }
    source = _open_read_only(video_db_path)
    central = _open_read_only(central_db_path)
    if source is None or central is None or not _has_table(source, "projection_outbox"):
        if source is not None:
            source.close()
        if central is not None:
            central.close()
        return report
    try:
        sql = "SELECT event_id, stream, entity_key, source_row_id, payload FROM projection_outbox"
        params: tuple[Any, ...] = ()
        if event_ids is not None:
            if not event_ids:
                return report
            sql += f" WHERE event_id IN ({','.join('?' for _ in event_ids)})"
            params = tuple(event_ids)
        events = source.execute(sql + " ORDER BY event_id", params).fetchall()
        report["checked_event_ids"] = [row[0] for row in events]
        expected_keys = {
            result for event in events if (result := _audit_projection_event(central, bvid, event, report)) is not None
        }
        report["unexpected_central_rows"] = _find_unexpected_projection_rows(central, bvid, expected_keys)
        return report
    finally:
        source.close()
        central.close()
