"""Read-only monitor-record queries for central and per-video databases."""

from typing import Any

from core.database.connection import readonly_connection


class MonitorRepository:
    """Execute the established monitor-record query modes without UI dependencies."""

    def __init__(self, database_path: str) -> None:
        self._database_path = database_path

    def query_central(
        self, mode: str, limit: int, threshold: int, filter_bvid: str | None, trend_bvid: str | None
    ) -> list[dict[str, Any]]:
        """Query central monitor records using the existing five UI modes."""
        with readonly_connection(self._database_path) as connection:
            if connection is None:
                return []
            return self._query(connection, mode, limit, threshold, filter_bvid, trend_bvid, central=True)

    def query_video(self, mode: str, limit: int, threshold: int) -> list[dict[str, Any]]:
        """Query a per-video monitor database using the existing five UI modes."""
        with readonly_connection(self._database_path) as connection:
            if connection is None:
                return []
            return self._query(connection, mode, limit, threshold, None, None, central=False)

    @staticmethod
    def _query(
        connection: Any,
        mode: str,
        limit: int,
        threshold: int,
        filter_bvid: str | None,
        trend_bvid: str | None,
        central: bool,
    ) -> list[dict[str, Any]]:
        if mode == "最新N条":
            if central and filter_bvid:
                rows = connection.execute(
                    "SELECT * FROM monitor_records WHERE bvid = ? ORDER BY timestamp DESC LIMIT ?", (filter_bvid, limit)
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM monitor_records ORDER BY timestamp DESC LIMIT ?", (limit,)
                ).fetchall()
        elif mode == "播放首次大于X":
            if central and filter_bvid:
                rows = connection.execute(
                    "SELECT * FROM monitor_records WHERE bvid = ? AND view_count > ? ORDER BY timestamp ASC LIMIT 1",
                    (filter_bvid, threshold),
                ).fetchall()
            elif central:
                rows = connection.execute(
                    """
                    WITH fa AS (
                        SELECT bvid, MIN(timestamp) AS ft FROM monitor_records WHERE view_count > ? GROUP BY bvid
                    )
                    SELECT m.* FROM monitor_records m
                    INNER JOIN fa f ON m.bvid = f.bvid AND m.timestamp = f.ft
                    ORDER BY m.timestamp DESC
                    """,
                    (threshold,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM monitor_records WHERE view_count > ? ORDER BY timestamp ASC LIMIT 1", (threshold,)
                ).fetchall()
        elif mode == "播放量大于X":
            if central and filter_bvid:
                rows = connection.execute(
                    "SELECT * FROM monitor_records WHERE bvid = ? AND view_count > ? ORDER BY timestamp DESC",
                    (filter_bvid, threshold),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM monitor_records WHERE view_count > ? ORDER BY timestamp DESC", (threshold,)
                ).fetchall()
        elif mode == "播放趋势":
            if central:
                rows = connection.execute(
                    "SELECT * FROM monitor_records WHERE bvid = ? ORDER BY timestamp ASC", (trend_bvid,)
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM monitor_records ORDER BY timestamp ASC").fetchall()
        elif mode == "全量数据":
            if central and filter_bvid:
                rows = connection.execute(
                    "SELECT * FROM monitor_records WHERE bvid = ? ORDER BY timestamp DESC", (filter_bvid,)
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM monitor_records ORDER BY timestamp DESC").fetchall()
        else:
            rows = []
        return [dict(row) for row in rows]
