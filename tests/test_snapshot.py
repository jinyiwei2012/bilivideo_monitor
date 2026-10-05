"""Consistent snapshot tests for the native SQLite backup path."""

import os
import sqlite3
import threading

from core.database.snapshot import SnapshotResult, snapshot_connection, snapshot_file


def _make_source(path) -> None:
    connection = sqlite3.connect(str(path))
    connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
    connection.executemany("INSERT INTO records (value) VALUES (?)", [(f"v{i}",) for i in range(5)])
    connection.commit()
    connection.close()


def _read_values(path) -> list[str]:
    connection = sqlite3.connect(str(path))
    try:
        return [row[0] for row in connection.execute("SELECT value FROM records ORDER BY id")]
    finally:
        connection.close()


def test_snapshot_file_produces_consistent_readable_copy(tmp_path) -> None:
    source = tmp_path / "source.db"
    destination = tmp_path / "backup" / "source.db"
    _make_source(source)

    result = snapshot_file(str(source), str(destination))

    assert result.ok
    assert result.delivered_at
    assert _read_values(destination) == ["v0", "v1", "v2", "v3", "v4"]
    connection = sqlite3.connect(str(destination))
    try:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def test_snapshot_file_includes_committed_wal_data(tmp_path) -> None:
    source = tmp_path / "wal_source.db"
    destination = tmp_path / "wal_source_snapshot.db"
    connection = sqlite3.connect(str(source))
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO records (value) VALUES ('uncheckpointed')")
        connection.commit()
        # Data is committed but not necessarily checkpointed out of the WAL yet.
        assert os.path.exists(str(source) + "-wal")
        result = snapshot_file(str(source), str(destination))
        assert result.ok
        assert _read_values(destination) == ["uncheckpointed"]
    finally:
        connection.close()


def test_snapshot_connection_copies_open_source(tmp_path) -> None:
    source = tmp_path / "live.db"
    destination = tmp_path / "live_snapshot.db"
    _make_source(source)
    connection = sqlite3.connect(str(source))
    try:
        result = snapshot_connection(connection, str(destination))
        assert result.ok
        assert _read_values(destination) == ["v0", "v1", "v2", "v3", "v4"]
    finally:
        connection.close()


def test_snapshot_failure_preserves_existing_destination(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.db"
    destination = tmp_path / "destination.db"
    _make_source(source)
    destination.write_text("old-valid-content", encoding="utf-8")

    import core.database.snapshot as snapshot

    def boom(_src: str, _dst: str) -> None:
        raise RuntimeError("injected replace failure")

    monkeypatch.setattr(snapshot.os, "replace", boom)

    result = snapshot_file(str(source), str(destination))

    assert not result.ok
    assert "injected replace failure" in (result.error or "")
    assert destination.read_text(encoding="utf-8") == "old-valid-content"
    # No temporary artifacts may remain next to the destination.
    leftovers = [name for name in os.listdir(tmp_path) if name.endswith(".snapshot-tmp")]
    assert leftovers == []


def test_snapshot_same_path_is_rejected(tmp_path) -> None:
    source = tmp_path / "same.db"
    _make_source(source)

    result = snapshot_file(str(source), str(source))

    assert not result.ok
    assert _read_values(source) == ["v0", "v1", "v2", "v3", "v4"]


def test_snapshot_missing_source_reports_error(tmp_path) -> None:
    result = snapshot_file(str(tmp_path / "missing.db"), str(tmp_path / "out.db"))
    assert not result.ok
    assert "not found" in (result.error or "")


def test_snapshot_single_flight_per_destination(tmp_path) -> None:
    source = tmp_path / "source.db"
    destination = tmp_path / "destination.db"
    _make_source(source)

    import core.database.snapshot as snapshot

    started = threading.Event()
    release = threading.Event()
    original = snapshot._backup_from_file

    def slow_backup(source_path, target, deadline):
        started.set()
        release.wait(2)
        return original(source_path, target, deadline)

    snapshot._backup_from_file = slow_backup
    try:
        first_result = {}

        def run_first() -> None:
            first_result["value"] = snapshot.snapshot_file(str(source), str(destination))

        worker = threading.Thread(target=run_first)
        worker.start()
        assert started.wait(2)
        second = snapshot.snapshot_file(str(source), str(destination))
        release.set()
        worker.join(3)
    finally:
        snapshot._backup_from_file = original

    assert isinstance(first_result["value"], SnapshotResult)
    assert first_result["value"].ok
    assert second.ok is False
    assert "already running" in (second.error or "")


def test_snapshot_deadline_aborts(tmp_path) -> None:
    source = tmp_path / "source.db"
    destination = tmp_path / "destination.db"
    _make_source(source)

    result = snapshot_file(str(source), str(destination), deadline=0.0)

    assert not result.ok
    leftovers = [name for name in os.listdir(tmp_path) if name.endswith(".snapshot-tmp")]
    assert leftovers == []
