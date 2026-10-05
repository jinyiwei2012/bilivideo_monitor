"""Persistent repository for per-video online-viewer snapshots."""

import os
import sqlite3
import threading

from core.database import data_layout
from utils.time_utils import now_ts


class ViewerRepository:
    """Own cached per-video connections and thread-safe viewer snapshot access."""

    def __init__(self) -> None:
        self._cache: dict[str, sqlite3.Connection] = {}
        self._lock = threading.Lock()

    def write(self, bvid: str, total: int, web: int, app: int) -> None:
        """Append one online-viewer snapshot for a video."""
        with self._lock:
            connection = self._connection(bvid)
            connection.execute(
                "INSERT INTO viewers (timestamp, total, web, app) VALUES (?, ?, ?, ?)",
                (now_ts(), total, web, app),
            )
            connection.commit()

    def read_latest(self) -> dict[str, dict[str, int]]:
        """Return the latest snapshot for every video opened by this repository."""
        latest: dict[str, dict[str, int]] = {}
        with self._lock:
            for bvid, connection in list(self._cache.items()):
                row = connection.execute(
                    "SELECT total, web, app FROM viewers ORDER BY timestamp DESC LIMIT 1"
                ).fetchone()
                if row:
                    latest[bvid] = {"total": row[0], "web": row[1], "app": row[2]}
        return latest

    def close(self) -> None:
        """Close all owned connections and clear the cache."""
        with self._lock:
            for connection in self._cache.values():
                try:
                    connection.close()
                except sqlite3.Error:
                    pass
            self._cache.clear()

    def _connection(self, bvid: str) -> sqlite3.Connection:
        connection = self._cache.get(bvid)
        if connection is not None:
            return connection

        database_path = data_layout.viewer_db(bvid, data_layout.backup_root())
        os.makedirs(os.path.dirname(database_path), exist_ok=True)
        connection = sqlite3.connect(database_path, check_same_thread=False)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS viewers (timestamp TEXT, total INTEGER, web INTEGER, app INTEGER)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_viewers_ts ON viewers(timestamp DESC)")
        connection.commit()
        self._cache[bvid] = connection
        return connection
