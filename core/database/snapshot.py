"""Consistent SQLite snapshots via the native backup API.

This module only produces single-file, consistent database snapshots.  It does
not perform business synchronization, open the application's live connections,
or decide when snapshots run; callers own scheduling and source locking.
"""

import logging
import os
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from typing import Callable, Optional

from utils.time_utils import now_ts

logger = logging.getLogger(__name__)

_COPY_PAGES = 256
_COPY_SLEEP_SECONDS = 0.05

# One replacement in flight per destination: periodic and explicit triggers must
# not race to replace the same target file.
_destination_locks: dict[str, threading.Lock] = {}
_destination_locks_guard = threading.Lock()


@dataclass(frozen=True)
class SnapshotResult:
    """Outcome of one snapshot attempt."""

    source: str
    destination: str
    ok: bool
    error: Optional[str] = None
    delivered_at: Optional[str] = None


def _destination_lock(destination: str) -> threading.Lock:
    with _destination_locks_guard:
        lock = _destination_locks.get(destination)
        if lock is None:
            lock = threading.Lock()
            _destination_locks[destination] = lock
        return lock


def _normalized(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def snapshot_connection(
    source_connection: sqlite3.Connection,
    destination: str,
    *,
    deadline: Optional[float] = None,
) -> SnapshotResult:
    """Snapshot an already-open source connection into ``destination``.

    The caller owns the source lock.  Do not call this while the source still
    has an uncommitted write transaction: the backup would wait on the source
    and could block itself.  Never commit the caller's business transaction on
    its behalf.
    """
    source = getattr(source_connection, "path", None) or "<connection>"
    return _snapshot(
        source, destination, lambda target: _backup_from_connection(source_connection, target, deadline), deadline
    )


def snapshot_file(
    source_path: str,
    destination: str,
    *,
    deadline: Optional[float] = None,
) -> SnapshotResult:
    """Snapshot an existing source file read-only, without creating a source db.

    This opens the source with ``mode=ro`` so importing a live database class (and
    any migration side effects) is unnecessary for a pure file snapshot.
    """
    if not os.path.isfile(source_path):
        return SnapshotResult(source_path, destination, False, "source database not found")
    return _snapshot(
        source_path, destination, lambda target: _backup_from_file(source_path, target, deadline), deadline
    )


def _snapshot(
    source: str,
    destination: str,
    copy: Callable[[sqlite3.Connection], None],
    deadline: Optional[float],
) -> SnapshotResult:
    if _normalized(source) == _normalized(destination):
        return SnapshotResult(source, destination, False, "source and destination are the same path")

    lock = _destination_lock(destination)
    if not lock.acquire(blocking=False):
        return SnapshotResult(source, destination, False, "snapshot already running for destination")
    try:
        return _run_snapshot(source, destination, copy, deadline)
    finally:
        lock.release()


def _run_snapshot(
    source: str,
    destination: str,
    copy: Callable[[sqlite3.Connection], None],
    deadline: Optional[float],
) -> SnapshotResult:
    destination_dir = os.path.dirname(destination) or "."
    os.makedirs(destination_dir, exist_ok=True)
    temp_path = os.path.join(destination_dir, f".{os.path.basename(destination)}.{uuid.uuid4().hex}.snapshot-tmp")
    try:
        with closing(sqlite3.connect(temp_path)) as target:
            copy(target)
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError("snapshot deadline exceeded")
            check = target.execute("PRAGMA quick_check").fetchone()
        if check is None or check[0] != "ok":
            raise RuntimeError(f"snapshot quick_check failed: {check[0] if check else 'none'}")
        os.replace(temp_path, destination)
    except Exception as error:
        _cleanup_temp(temp_path)
        logger.warning("快照失败 %s -> %s: %s", source, destination, error)
        return SnapshotResult(source, destination, False, str(error))
    return SnapshotResult(source, destination, True, None, now_ts())


def _backup_from_connection(source: sqlite3.Connection, target: sqlite3.Connection, deadline: Optional[float]) -> None:
    def progress(_status: int, _remaining: int, _total: int) -> None:
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError("snapshot deadline exceeded")

    source.backup(target, pages=_COPY_PAGES, progress=progress, sleep=_COPY_SLEEP_SECONDS)


def _backup_from_file(source_path: str, target: sqlite3.Connection, deadline: Optional[float]) -> None:
    from .connection import open_readonly_connection

    source = open_readonly_connection(source_path)
    if source is None:
        raise FileNotFoundError(f"source database not found: {source_path}")
    try:
        _backup_from_connection(source, target, deadline)
    finally:
        source.close()


def _cleanup_temp(temp_path: str) -> None:
    for path in (temp_path, temp_path + "-wal", temp_path + "-shm"):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as error:
            logger.debug("清理快照临时文件失败 %s: %s", path, error)
