"""Transactional, versioned SQLite schema migration support."""

from collections.abc import Callable, Mapping
import sqlite3

MigrationStep = Callable[[sqlite3.Connection], None]
SchemaValidator = Callable[[sqlite3.Connection], None]


def run_migrations(
    conn: sqlite3.Connection,
    *,
    schema_name: str,
    latest_version: int,
    steps: Mapping[int, MigrationStep],
    validate: SchemaValidator,
) -> None:
    """Apply contiguous schema migrations atomically and validate the result."""
    if conn.in_transaction:
        raise RuntimeError(f"{schema_name} migration requires no active transaction")

    try:
        conn.execute("BEGIN IMMEDIATE")
        current_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if current_version > latest_version:
            raise RuntimeError(
                f"{schema_name} schema version {current_version} is newer than supported {latest_version}"
            )
        for version in range(current_version + 1, latest_version + 1):
            step = steps.get(version)
            if step is None:
                raise RuntimeError(f"{schema_name} has no migration step for version {version}")
            step(conn)
            conn.execute(f"PRAGMA user_version = {version}")
        validate(conn)
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
