"""Read models sourced from the legacy backup central database."""

from typing import Any

from core.database.connection import readonly_connection
from core.database.data_layout import backup_central


class ReadModelRepository:
    """Read central video metadata without changing its existing data source."""

    def __init__(self, database_path: str | None = None) -> None:
        self._database_path = database_path or backup_central()

    def load_videos(self) -> list[dict[str, Any]]:
        """Return central video summaries in their current UI ordering."""
        with readonly_connection(self._database_path) as connection:
            if connection is None:
                return []
            rows = connection.execute("SELECT bvid, title FROM videos ORDER BY updated_at DESC").fetchall()
        return [dict(row) for row in rows]

    def load_watch_bvids(self) -> list[str]:
        """Return the existing backup-central watch-list fallback ordering."""
        with readonly_connection(self._database_path) as connection:
            if connection is None:
                return []
            rows = connection.execute("SELECT bvid FROM videos ORDER BY updated_at DESC").fetchall()
        return [row["bvid"] for row in rows if row["bvid"]]
