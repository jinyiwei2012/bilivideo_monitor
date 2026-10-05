"""Versioned schema definition and migrations for the central database."""

import sqlite3

from .migrations import run_migrations

CENTRAL_SCHEMA_VERSION = 4

CENTRAL_V1_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS videos (
        bvid TEXT PRIMARY KEY, title TEXT, view_count INTEGER DEFAULT 0,
        like_count INTEGER DEFAULT 0, coin_count INTEGER DEFAULT 0,
        share_count INTEGER DEFAULT 0, favorite_count INTEGER DEFAULT 0,
        danmaku_count INTEGER DEFAULT 0, reply_count INTEGER DEFAULT 0,
        viewers_app INTEGER DEFAULT 0, viewers_web INTEGER DEFAULT 0,
        viewers_total INTEGER DEFAULT 0, cover_path TEXT, like_view_ratio REAL DEFAULT 0,
        owner_name TEXT, owner_id INTEGER, pubdate TEXT, duration INTEGER, pic TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    "CREATE INDEX IF NOT EXISTS idx_videos_owner_id ON videos(owner_id)",
    """CREATE TABLE IF NOT EXISTS monitor_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT, bvid TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        view_count INTEGER, like_count INTEGER, coin_count INTEGER, share_count INTEGER,
        favorite_count INTEGER, danmaku_count INTEGER, reply_count INTEGER,
        viewers_app INTEGER DEFAULT 0, viewers_web INTEGER DEFAULT 0, viewers_total INTEGER DEFAULT 0,
        like_view_ratio REAL DEFAULT 0, FOREIGN KEY (bvid) REFERENCES videos(bvid))""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_monitor_bvid_ts ON monitor_records(bvid, timestamp)",
    """CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, bvid TEXT, algorithm TEXT, algorithm_id TEXT,
        target_threshold INTEGER, predicted_seconds INTEGER, predicted_time TIMESTAMP,
        confidence REAL, current_views INTEGER, is_reached BOOLEAN DEFAULT 0,
        actual_time TIMESTAMP, error_rate REAL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (bvid) REFERENCES videos(bvid))""",
    "CREATE INDEX IF NOT EXISTS idx_predictions_bvid ON predictions(bvid)",
    "CREATE INDEX IF NOT EXISTS idx_predictions_created_at ON predictions(created_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_central_predict_unique ON predictions(bvid, algorithm, target_threshold)",
    """CREATE TABLE IF NOT EXISTS video_milestones (
        id INTEGER PRIMARY KEY AUTOINCREMENT, bvid TEXT NOT NULL, period TEXT NOT NULL,
        view_count INTEGER NOT NULL, like_count INTEGER, coin_count INTEGER, share_count INTEGER,
        favorite_count INTEGER, danmaku_count INTEGER, reply_count INTEGER, note TEXT,
        recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(bvid, period))""",
    "CREATE INDEX IF NOT EXISTS idx_milestones_bvid ON video_milestones(bvid)",
    """CREATE TABLE IF NOT EXISTS prediction_ensemble (
        id INTEGER PRIMARY KEY AUTOINCREMENT, bvid TEXT NOT NULL, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        prediction INTEGER DEFAULT 0, confidence REAL DEFAULT 0, valid_algos INTEGER DEFAULT 0,
        total_algos INTEGER DEFAULT 0, interval_lower INTEGER, interval_upper INTEGER,
        interval_width_ratio REAL, surge_correction_applied BOOLEAN DEFAULT 0,
        surge_magnitude REAL, surge_type TEXT)""",
    """CREATE TABLE IF NOT EXISTS algorithm_coherence (
        id INTEGER PRIMARY KEY AUTOINCREMENT, bvid TEXT NOT NULL, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        algorithm TEXT, coherence REAL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS weekly_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT, bvid TEXT NOT NULL, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        total_score REAL, view_score REAL, interaction_score REAL, favorite_score REAL,
        coin_score REAL, like_score REAL, correction_a REAL, correction_b REAL,
        correction_c REAL, correction_d REAL, base_view_score REAL)""",
    """CREATE TABLE IF NOT EXISTS yearly_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT, bvid TEXT NOT NULL, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        total_score REAL, view_score REAL, interaction_score REAL, favorite_score REAL,
        coin_score REAL, like_score REAL, correction_a REAL, correction_b REAL, correction_c REAL)""",
)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: tuple[tuple[str, str], ...]) -> None:
    existing = _columns(conn, table)
    for name, definition in columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _migrate_central_v1(conn: sqlite3.Connection) -> None:
    for statement in CENTRAL_V1_STATEMENTS:
        try:
            conn.execute(statement)
        except sqlite3.IntegrityError:
            if "idx_central_predict_unique" not in statement:
                raise
    _add_missing_columns(
        conn,
        "videos",
        (
            ("viewers_app", "INTEGER DEFAULT 0"),
            ("viewers_web", "INTEGER DEFAULT 0"),
            ("viewers_total", "INTEGER DEFAULT 0"),
            ("like_view_ratio", "REAL DEFAULT 0"),
            ("owner_name", "TEXT"),
            ("owner_id", "INTEGER"),
            ("pubdate", "TEXT"),
            ("duration", "INTEGER"),
            ("pic", "TEXT"),
        ),
    )
    _add_missing_columns(
        conn,
        "monitor_records",
        (
            ("viewers_app", "INTEGER DEFAULT 0"),
            ("viewers_web", "INTEGER DEFAULT 0"),
            ("viewers_total", "INTEGER DEFAULT 0"),
            ("like_view_ratio", "REAL DEFAULT 0"),
        ),
    )
    _add_missing_columns(
        conn,
        "predictions",
        (
            ("predicted_views", "INTEGER DEFAULT 0"),
            ("metadata", "TEXT DEFAULT ''"),
            ("predicted_hours", "REAL DEFAULT 0"),
            ("current_velocity", "REAL DEFAULT 0"),
        ),
    )


def _migrate_central_v2(conn: sqlite3.Connection) -> None:
    _add_missing_columns(
        conn,
        "monitor_records",
        (("observed_at_us", "INTEGER"), ("request_start_us", "INTEGER"), ("rtt_us", "INTEGER")),
    )


def _migrate_central_v3(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS sync_cursors (
        scope TEXT NOT NULL, stream TEXT NOT NULL, partition_key TEXT NOT NULL,
        watermark TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL, status TEXT NOT NULL,
        last_error TEXT, PRIMARY KEY (scope, stream, partition_key))""")


def _migrate_central_v4(conn: sqlite3.Connection) -> None:
    """v3→v4: add source row keys and future projection idempotency indexes."""
    for table in ("monitor_records", "prediction_ensemble", "algorithm_coherence"):
        _add_missing_columns(conn, table, (("source_row_id", "INTEGER"),))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_monitor_source_row ON monitor_records(bvid, source_row_id)")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_ensemble_source_row ON prediction_ensemble(bvid, source_row_id)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_coherence_source_row ON algorithm_coherence(bvid, source_row_id)"
    )


def validate_central_schema(conn: sqlite3.Connection) -> None:
    required_tables = {
        "videos",
        "monitor_records",
        "predictions",
        "video_milestones",
        "prediction_ensemble",
        "algorithm_coherence",
        "weekly_scores",
        "yearly_scores",
        "sync_cursors",
    }
    present = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = required_tables - present
    if missing:
        raise RuntimeError(f"central schema missing tables: {sorted(missing)}")
    required_columns = {"observed_at_us", "request_start_us", "rtt_us"}
    if not required_columns <= _columns(conn, "monitor_records"):
        raise RuntimeError("central monitor_records lacks precision columns")
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(monitor_records)")}
    if "idx_monitor_bvid_ts" not in indexes:
        raise RuntimeError("central monitor_records lacks timestamp index")
    for table, index in (
        ("monitor_records", "idx_monitor_source_row"),
        ("prediction_ensemble", "idx_ensemble_source_row"),
        ("algorithm_coherence", "idx_coherence_source_row"),
    ):
        indexes = {row[1] for row in conn.execute(f"PRAGMA index_list({table})")}
        if index not in indexes:
            raise RuntimeError(f"central schema lacks {index}")


def migrate_central_schema(conn: sqlite3.Connection) -> None:
    """Bring a central database to the latest supported schema atomically."""
    run_migrations(
        conn,
        schema_name="central",
        latest_version=CENTRAL_SCHEMA_VERSION,
        steps={1: _migrate_central_v1, 2: _migrate_central_v2, 3: _migrate_central_v3, 4: _migrate_central_v4},
        validate=validate_central_schema,
    )
