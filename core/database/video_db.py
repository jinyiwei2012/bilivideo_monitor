"""单个视频的独立数据库 —— 每个 BV 号对应一个独立 SQLite 数据库文件"""

import sqlite3
import os
import re
import threading
import logging
import json
from dataclasses import asdict
from datetime import datetime
from utils import project_path
from utils.time_utils import now_ts
from typing import Any, Dict, List, Optional

from .connection import _ConnectionCtx
from .models import _validate_bvid, MonitorRecord, PredictionRecord
from .video_db_danmaku import _DanmakuMixin
from .video_db_scores import _ScoreOpsMixin
from .migrations import run_migrations

logger = logging.getLogger(__name__)

VIDEO_SCHEMA_VERSION = 6


class VideoDatabase(_DanmakuMixin, _ScoreOpsMixin):
    """单个视频的独立数据库
    每个视频拥有独立的 SQLite 文件（data/<BV>/<BV>.db），
    同时维护一个镜像连接同步写入 data/ 目录。
    """

    def __init__(self, bvid: str, base_dir: str | None = None) -> None:
        """初始化视频独立数据库

        Args:
            bvid: BV 号
            base_dir: 数据库存放目录，默认为 core/data/
        """
        _validate_bvid(bvid)
        self.bvid = bvid
        if base_dir is None:
            base_dir = project_path("core", "data")

        # 创建以BV号命名的文件夹
        self.video_dir = os.path.join(base_dir, bvid)
        os.makedirs(self.video_dir, exist_ok=True)

        # 数据库文件路径：/data/BV号/BV号.db
        self.db_path = os.path.join(self.video_dir, f"{bvid}.db")
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")  # 启用 WAL 模式提升并发读性能
        self._conn.execute("PRAGMA synchronous=NORMAL")  # 平衡写入安全与速度

        # 镜像连接：同步写入 data/ 目录（延迟初始化，首次写入时才创建以节省内存）
        self._mirror_conn: sqlite3.Connection | None = None
        self._mirror_path: str | None = None
        mirror_base = project_path("data")
        if mirror_base != base_dir:
            mirror_dir = os.path.join(mirror_base, bvid)
            os.makedirs(mirror_dir, exist_ok=True)
            self._mirror_path = os.path.join(mirror_dir, f"{bvid}.db")

        # 中央数据库引用（用于写入兜底，由调用方通过 set_central_db 注入）
        self._central_db: Any = None

        try:
            self._init_db()
        except Exception:
            self._conn.close()
            raise
        # 镜像库初始化：确保镜像连接可用（失败仅记 debug 日志，不影响主库）
        try:
            self._ensure_mirror()
        except Exception as e:
            logger.debug("初始化镜像数据库失败 %s: %s", self.bvid, e)

    def _get_connection(self) -> _ConnectionCtx:
        """返回线程安全的连接上下文管理器（兼容 with 语法）"""
        return _ConnectionCtx(self._conn, self._lock)

    def _ensure_mirror(self) -> None:
        """延迟创建镜像数据库连接（首次写入时调用，节省内存）。"""
        if self._mirror_conn is not None or self._mirror_path is None:
            return
        try:
            import sqlite3 as _sqlite3

            self._mirror_conn = _sqlite3.connect(self._mirror_path, check_same_thread=False)
            self._mirror_conn.row_factory = sqlite3.Row
            self._mirror_conn.execute("PRAGMA journal_mode=WAL")
            self._mirror_conn.execute("PRAGMA synchronous=NORMAL")
            self._init_mirror_tables()
        except Exception as e:
            logger.warning("创建镜像数据库连接失败 %s: %s", self.bvid, e, exc_info=True)
            self._mirror_conn = None

    def _execute_on_all(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        """在主连接和镜像连接上同时执行 SQL"""

        def _exec(conn: sqlite3.Connection, label: str = "main") -> None:
            try:
                conn.execute(sql, params) if params else conn.execute(sql)
                conn.commit()
            except Exception as e:
                logger.error("数据库写入失败 [%s]: %s | SQL: %.200s", label, e, sql)

        with self._get_connection() as conn:
            _exec(conn, "main")
        self._ensure_mirror()
        if self._mirror_conn:
            with _ConnectionCtx(self._mirror_conn, self._lock) as conn:
                _exec(conn, "mirror")

    def _raw_connection(self) -> sqlite3.Connection:
        """返回原始连接（用于需要直接操作的场景）"""
        return self._conn

    # ── 共享 schema 定义 (主库与镜像库单点维护) ──────────────────
    # 每项: (sql, tolerant); tolerant=True 时执行失败仅跳过 (如 UNIQUE 索引遇重复数据)
    SCHEMA_STATEMENTS = [
        (
            """
            CREATE TABLE IF NOT EXISTS video_info (
                id INTEGER PRIMARY KEY,
                title TEXT,
                view_count INTEGER DEFAULT 0,
                like_count INTEGER DEFAULT 0,
                coin_count INTEGER DEFAULT 0,
                share_count INTEGER DEFAULT 0,
                favorite_count INTEGER DEFAULT 0,
                danmaku_count INTEGER DEFAULT 0,
                reply_count INTEGER DEFAULT 0,
                viewers_app INTEGER DEFAULT 0,
                viewers_web INTEGER DEFAULT 0,
                viewers_total INTEGER DEFAULT 0,
                cover_path TEXT,
                like_view_ratio REAL DEFAULT 0,
                owner_name TEXT,
                owner_id INTEGER,
                pubdate TEXT,
                duration INTEGER,
                pic TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
            False,
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS monitor_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                view_count INTEGER,
                like_count INTEGER,
                coin_count INTEGER,
                share_count INTEGER,
                favorite_count INTEGER,
                danmaku_count INTEGER,
                reply_count INTEGER,
                viewers_app INTEGER DEFAULT 0,
                viewers_web INTEGER DEFAULT 0,
                viewers_total INTEGER DEFAULT 0,
                like_view_ratio REAL DEFAULT 0
            )
        """,
            False,
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                algorithm TEXT,
                algorithm_id TEXT,
                target_threshold INTEGER,
                predicted_seconds INTEGER,
                predicted_time TIMESTAMP,
                confidence REAL,
                current_views INTEGER,
                metadata TEXT DEFAULT '',
                predicted_hours REAL DEFAULT 0,
                current_velocity REAL DEFAULT 0,
                is_reached BOOLEAN DEFAULT 0,
                actual_time TIMESTAMP,
                error_rate REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
            False,
        ),
        # 已有重复数据时 UNIQUE 索引创建会失败（罕见），由后续清理修复
        ("CREATE UNIQUE INDEX IF NOT EXISTS idx_predict_unique ON predictions(algorithm, target_threshold)", True),
        # 预测历史按 created_at 排序查询的覆盖索引
        ("CREATE INDEX IF NOT EXISTS idx_predict_created_at ON predictions(created_at)", False),
        (
            """
            CREATE TABLE IF NOT EXISTS algorithm_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                algorithm TEXT NOT NULL,
                bvid TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                predicted_value REAL,
                actual_value REAL,
                error_rate REAL,
                weight REAL DEFAULT 1.0,
                confidence REAL DEFAULT 0.5
            )
        """,
            False,
        ),
        ("CREATE INDEX IF NOT EXISTS idx_algo_perf_algorithm ON algorithm_performance(algorithm)", False),
        ("CREATE INDEX IF NOT EXISTS idx_algo_perf_bvid ON algorithm_performance(bvid)", False),
        ("CREATE INDEX IF NOT EXISTS idx_monitor_timestamp ON monitor_records(timestamp)", False),
        (
            """
            CREATE TABLE IF NOT EXISTS crossing_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                threshold INTEGER NOT NULL,
                display_window_start TIMESTAMP NOT NULL,
                display_window_end TIMESTAMP NOT NULL,
                range_start TIMESTAMP NOT NULL,
                range_end TIMESTAMP NOT NULL,
                estimate TIMESTAMP NOT NULL,
                period_lo REAL,
                period_hi REAL,
                refined_start TIMESTAMP,
                refined_end TIMESTAMP,
                request_count INTEGER DEFAULT 0,
                rtt_median_us INTEGER,
                corrected_range_start TIMESTAMP,
                corrected_range_end TIMESTAMP,
                corrected_estimate TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(threshold)
            )
        """,
            False,
        ),
        ("CREATE INDEX IF NOT EXISTS idx_crossing_threshold ON crossing_events(threshold)", False),
        (
            """
            CREATE TABLE IF NOT EXISTS weekly_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_score REAL,
                view_score REAL,
                interaction_score REAL,
                favorite_score REAL,
                coin_score REAL,
                like_score REAL,
                correction_a REAL,
                correction_b REAL,
                correction_c REAL,
                correction_d REAL,
                base_view_score REAL
            )
        """,
            False,
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS yearly_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_score REAL,
                view_score REAL,
                interaction_score REAL,
                favorite_score REAL,
                coin_score REAL,
                like_score REAL,
                correction_a REAL,
                correction_b REAL,
                correction_c REAL
            )
        """,
            False,
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS danmaku_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bvid TEXT NOT NULL,
                oid INTEGER NOT NULL,
                segment_index INTEGER DEFAULT 0,
                content TEXT NOT NULL,
                video_ts REAL DEFAULT 0,
                mode INTEGER DEFAULT 1,
                font_size INTEGER DEFAULT 25,
                color INTEGER DEFAULT 16777215,
                send_time INTEGER DEFAULT 0,
                weight INTEGER DEFAULT 1,
                uid TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
            False,
        ),
        ("CREATE INDEX IF NOT EXISTS idx_danmaku_bvid ON danmaku_records(bvid)", False),
        ("CREATE INDEX IF NOT EXISTS idx_danmaku_segment ON danmaku_records(bvid, oid, segment_index)", False),
        # 弹幕按时间排序展示的覆盖索引
        ("CREATE INDEX IF NOT EXISTS idx_danmaku_video_ts ON danmaku_records(video_ts)", False),
    ]

    @staticmethod
    def _apply_schema(cursor: sqlite3.Cursor) -> None:
        """在指定 cursor 上执行共享 schema 定义 (主库/镜像库共用)。"""
        for sql, tolerant in VideoDatabase.SCHEMA_STATEMENTS:
            try:
                cursor.execute(sql)
            except Exception as e:
                if not tolerant:
                    raise
                logger.debug("schema 语句跳过(容忍): %.80s | %s", sql, e)

    def _init_db(self) -> None:
        """Initialize the database through the transactional versioned migrator."""
        with self._get_connection() as conn:
            self.migrate_video_schema(conn)

    def migrate_video_schema(self, conn: sqlite3.Connection) -> None:
        """Bring this video's database to the latest schema atomically."""
        run_migrations(
            conn,
            schema_name="video",
            latest_version=VIDEO_SCHEMA_VERSION,
            steps={
                1: self._migrate_video_v1,
                2: self._migrate_danmaku_dedup,
                3: self._migrate_danmaku_v3,
                4: self._migrate_scores_unique,
                5: self._migrate_precision_columns,
                6: self._migrate_projection_outbox,
            },
            validate=self._validate_video_schema,
        )

    def _validate_video_schema(self, conn: sqlite3.Connection) -> None:
        """Check lightweight structural invariants after migration."""
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {
            "video_info",
            "monitor_records",
            "predictions",
            "weekly_scores",
            "yearly_scores",
            "danmaku_records",
            "prediction_ensemble",
            "algorithm_coherence",
            "video_milestones",
            "projection_outbox",
        }
        if not required <= tables:
            raise RuntimeError("video schema lacks required tables")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(monitor_records)")}
        if not {"observed_at_us", "request_start_us", "rtt_us"} <= columns:
            raise RuntimeError("video monitor_records lacks precision columns")
        for table, index in (("weekly_scores", "idx_weekly_ts"), ("yearly_scores", "idx_yearly_ts")):
            indexes = {row[1] for row in conn.execute(f"PRAGMA index_list({table})")}
            if index not in indexes:
                raise RuntimeError(f"video schema lacks {index}")

    @staticmethod
    def _migrate_projection_outbox(conn: sqlite3.Connection) -> None:
        """v5→v6: add per-video projection authority tables and durable outbox."""
        statements = (
            """
            CREATE TABLE IF NOT EXISTS prediction_ensemble (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bvid TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                prediction INTEGER DEFAULT 0,
                confidence REAL DEFAULT 0,
                valid_algos INTEGER DEFAULT 0,
                total_algos INTEGER DEFAULT 0,
                interval_lower INTEGER,
                interval_upper INTEGER,
                interval_width_ratio REAL,
                surge_correction_applied BOOLEAN DEFAULT 0,
                surge_magnitude REAL,
                surge_type TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS algorithm_coherence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bvid TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                algorithm TEXT,
                coherence REAL DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS video_milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period TEXT NOT NULL UNIQUE,
                view_count INTEGER NOT NULL,
                like_count INTEGER,
                coin_count INTEGER,
                share_count INTEGER,
                favorite_count INTEGER,
                danmaku_count INTEGER,
                reply_count INTEGER,
                note TEXT,
                recorded_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS projection_outbox (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                stream TEXT NOT NULL,
                entity_key TEXT NOT NULL,
                operation TEXT NOT NULL,
                source_row_id INTEGER,
                payload TEXT,
                created_at TEXT NOT NULL,
                delivered_at TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_outbox_stream_entity ON projection_outbox(stream, entity_key)",
        )
        for statement in statements:
            conn.execute(statement)

    @staticmethod
    def _enqueue_outbox(
        cursor: sqlite3.Cursor,
        stream: str,
        entity_key: str,
        source_row_id: int | None,
        payload: dict[str, Any],
    ) -> None:
        """Append a projection event in the caller's active business transaction."""
        cursor.execute(
            """INSERT INTO projection_outbox
            (stream, entity_key, operation, source_row_id, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (stream, entity_key, "upsert", source_row_id, json.dumps(payload, ensure_ascii=False), now_ts()),
        )

    def save_prediction_cycle(
        self, timestamp: str, predictions: list[dict], ensemble: dict, coherence: list[tuple]
    ) -> bool:
        """Persist a prediction cycle and all projection events in one local transaction."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                for prediction in predictions:
                    sql, params = self._prediction_sql(prediction)
                    cursor.execute(sql, params)
                    provided = [key for key in ("is_reached", "actual_time", "error_rate") if key in prediction]
                    if provided:
                        assignments = ", ".join(f"{key}=?" for key in provided)
                        cursor.execute(
                            f"UPDATE predictions SET {assignments} WHERE algorithm=? AND target_threshold=?",
                            (
                                *[prediction[key] for key in provided],
                                prediction.get("algorithm"),
                                prediction.get("target_threshold"),
                            ),
                        )
                    source = cursor.execute(
                        "SELECT id FROM predictions WHERE algorithm=? AND target_threshold=?",
                        (prediction.get("algorithm"), prediction.get("target_threshold")),
                    ).fetchone()
                    self._enqueue_outbox(
                        cursor,
                        "predictions",
                        f"{prediction.get('algorithm')}:{prediction.get('target_threshold')}",
                        source[0],
                        prediction,
                    )
                interval = ensemble.get("prediction_interval", {}) or {}
                cursor.execute(
                    """INSERT INTO prediction_ensemble (bvid, timestamp, prediction, confidence, valid_algos, total_algos,
                    interval_lower, interval_upper, interval_width_ratio, surge_correction_applied, surge_magnitude, surge_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        self.bvid,
                        timestamp,
                        ensemble.get("prediction", 0),
                        ensemble.get("confidence", 0),
                        ensemble.get("valid_algos", 0),
                        ensemble.get("total_algos", 0),
                        interval.get("lower") if "prediction_interval" in ensemble else ensemble.get("interval_lower"),
                        interval.get("upper") if "prediction_interval" in ensemble else ensemble.get("interval_upper"),
                        interval.get("interval_width_ratio", ensemble.get("interval_width_ratio")),
                        int(ensemble.get("surge_correction_applied", False)),
                        ensemble.get("surge_magnitude"),
                        ensemble.get("surge_type", ""),
                    ),
                )
                ensemble_payload = dict(ensemble)
                ensemble_payload["timestamp"] = timestamp
                self._enqueue_outbox(cursor, "prediction_ensemble", timestamp, cursor.lastrowid, ensemble_payload)
                for algorithm, value in coherence:
                    cursor.execute(
                        "INSERT INTO algorithm_coherence (bvid, timestamp, algorithm, coherence) VALUES (?, ?, ?, ?)",
                        (self.bvid, timestamp, algorithm, round(value, 4)),
                    )
                    self._enqueue_outbox(
                        cursor,
                        "algorithm_coherence",
                        f"{timestamp}:{algorithm}",
                        cursor.lastrowid,
                        {"timestamp": timestamp, "algorithm": algorithm, "coherence": round(value, 4)},
                    )
                conn.commit()
            return True
        except Exception as error:
            logger.warning("保存预测周期失败 %s: %s", self.bvid, error, exc_info=True)
            return False

    def upsert_milestone(self, period: str, data: dict[str, Any]) -> bool:
        """Persist a per-video milestone and its outbox event atomically."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                recorded_at = data.get("recorded_at") or now_ts()
                cursor.execute(
                    """INSERT INTO video_milestones (period, view_count, like_count, coin_count, share_count, favorite_count,
                    danmaku_count, reply_count, note, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(period) DO UPDATE SET view_count=excluded.view_count, like_count=excluded.like_count,
                    coin_count=excluded.coin_count, share_count=excluded.share_count, favorite_count=excluded.favorite_count,
                    danmaku_count=excluded.danmaku_count, reply_count=excluded.reply_count, note=excluded.note, recorded_at=excluded.recorded_at""",
                    (
                        period,
                        data.get("view_count", 0),
                        data.get("like_count"),
                        data.get("coin_count"),
                        data.get("share_count"),
                        data.get("favorite_count"),
                        data.get("danmaku_count"),
                        data.get("reply_count"),
                        data.get("note"),
                        recorded_at,
                    ),
                )
                source = cursor.execute("SELECT id FROM video_milestones WHERE period=?", (period,)).fetchone()
                milestone_payload = dict(data)
                milestone_payload["recorded_at"] = recorded_at
                self._enqueue_outbox(cursor, "video_milestones", period, source[0], milestone_payload)
                conn.commit()
            return True
        except Exception as error:
            logger.warning("保存里程碑失败 %s: %s", self.bvid, error, exc_info=True)
            return False

    def _migrate_scores_unique(self, conn: sqlite3.Connection) -> None:
        """v3→v4 迁移：分数表按 timestamp 去重并建唯一索引。

        唯一索引让 `INSERT OR REPLACE` 按 timestamp 幂等（同一时刻只保留一行），
        是 M2.11「惰性物化 + 每小时桶」重写的前提。
        """
        cursor = conn.cursor()
        targets = (
            ("weekly_scores", "idx_weekly_timestamp", "idx_weekly_ts"),
            ("yearly_scores", "idx_yearly_timestamp", "idx_yearly_ts"),
        )
        for table, old_idx, new_idx in targets:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not cursor.fetchone():
                continue
            try:
                cursor.execute(f"DELETE FROM {table} WHERE id NOT IN (SELECT MAX(id) FROM {table} GROUP BY timestamp)")
            except sqlite3.Error as e:
                logger.debug("v3→v4 %s 去重失败: %s", table, e)
            cursor.execute(f"DROP INDEX IF EXISTS {old_idx}")
            try:
                cursor.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {new_idx} ON {table}(timestamp)")
            except sqlite3.OperationalError:
                logger.warning("v3→v4: %s 无法创建唯一索引", table)

    def set_central_db(self, central_db: Any) -> None:
        """注入中央数据库引用，用于写入时同步兜底

        Args:
            central_db: core.database.Database 实例
        """
        self._central_db = central_db

    def _init_mirror_tables(self) -> None:
        """在镜像连接上创建与主库相同的表结构（仅当镜像连接存在时）。

        schema 单点定义见 SCHEMA_STATEMENTS, 与主库共用。
        """
        if not self._mirror_conn:
            return
        try:
            self.migrate_video_schema(self._mirror_conn)
        except Exception as e:
            logger.warning("初始化镜像数据库表失败 %s: %s", self.bvid, e, exc_info=True)

    def _migrate_video_v1(self, conn: sqlite3.Connection) -> None:
        """检查并迁移数据库：添加缺少的列、自动计算默认值

        Args:
            conn: 数据库连接
        """
        cursor = conn.cursor()
        self._apply_schema(cursor)
        self._migrate_schema_upgrades(cursor)
        self._migrate_compute_values(cursor)

    def _migrate_schema_upgrades(self, cursor: sqlite3.Cursor) -> None:
        """迁移数据库模式：添加缺少的列

        根据预定义的 schema_upgrades 字典，逐表检查并添加缺失的列，
        对表名和列名做正则校验防止 SQL 注入
        """
        schema_upgrades = {
            "video_info": [
                ("viewers_app", "INTEGER DEFAULT 0"),
                ("viewers_web", "INTEGER DEFAULT 0"),
                ("viewers_total", "INTEGER DEFAULT 0"),
                ("like_view_ratio", "REAL DEFAULT 0"),
                ("owner_name", "TEXT"),
                ("owner_id", "INTEGER"),
                ("pubdate", "TEXT"),
                ("duration", "INTEGER"),
                ("pic", "TEXT"),
                ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ],
            "monitor_records": [
                ("viewers_app", "INTEGER DEFAULT 0"),
                ("viewers_web", "INTEGER DEFAULT 0"),
                ("viewers_total", "INTEGER DEFAULT 0"),
                ("like_view_ratio", "REAL DEFAULT 0"),
            ],
            "predictions": [
                ("metadata", "TEXT DEFAULT ''"),
                ("predicted_hours", "REAL DEFAULT 0"),
                ("current_velocity", "REAL DEFAULT 0"),
                ("is_reached", "BOOLEAN DEFAULT 0"),
                ("actual_time", "TIMESTAMP"),
                ("error_rate", "REAL DEFAULT 0"),
            ],
            "weekly_scores": [
                ("correction_d", "REAL"),
                ("base_view_score", "REAL"),
            ],
        }

        for table, columns in schema_upgrades.items():
            # 正则校验表名，防止 SQL 注入
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table):
                continue
            cursor.execute(f"PRAGMA table_info({table})")
            existing = {row["name"] for row in cursor.fetchall()}
            if not existing:
                continue
            for col_name, col_def in columns:
                # 正则校验列名，防止 SQL 注入
                if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", col_name):
                    continue
                if col_name not in existing:
                    # 校验列定义格式，防止包含不安全 SQL 片段
                    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*(\s+DEFAULT\s+[^\s;]+)?$", col_def):
                        logger.warning(f"迁移跳过: {table}.{col_name} 含不安全的列定义 {col_def}")
                        continue
                    try:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                    except Exception as e:
                        logger.warning(f"迁移失败 {table}.{col_name}: {e}")

    @staticmethod
    def _migrate_precision_columns(conn: sqlite3.Connection) -> None:
        """补充不改变既有字段语义的精确时间列。"""
        upgrades = {
            "monitor_records": (
                ("observed_at_us", "INTEGER"),
                ("request_start_us", "INTEGER"),
                ("rtt_us", "INTEGER"),
            ),
            "crossing_events": (
                ("rtt_median_us", "INTEGER"),
                ("corrected_range_start", "TIMESTAMP"),
                ("corrected_range_end", "TIMESTAMP"),
                ("corrected_estimate", "TIMESTAMP"),
            ),
        }
        cursor = conn.cursor()
        for table, columns in upgrades.items():
            cursor.execute(f"PRAGMA table_info({table})")
            existing = {row["name"] for row in cursor.fetchall()}
            if not existing:
                continue
            for column, definition in columns:
                if column not in existing:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _migrate_compute_values(self, cursor: sqlite3.Cursor) -> None:
        """自动计算缺失的数值字段

        补充 like_view_ratio（播赞比）和 predicted_hours 等派生字段
        """
        # 补全监控记录的播赞比
        try:
            cursor.execute("""
                UPDATE monitor_records
                SET like_view_ratio = ROUND(CAST(like_count AS REAL) / NULLIF(view_count, 0), 6)
                WHERE like_view_ratio IS NULL OR like_view_ratio = 0
            """)
        except Exception as e:
            logger.debug("更新 monitor_records like_view_ratio 失败: %s", e)

        # 补全视频信息的播赞比
        try:
            cursor.execute("""
                UPDATE video_info
                SET like_view_ratio = ROUND(CAST(like_count AS REAL) / NULLIF(view_count, 0), 6)
                WHERE like_view_ratio IS NULL OR like_view_ratio = 0
            """)
        except Exception as e:
            logger.debug("更新 video_info like_view_ratio 失败: %s", e)

        # 根据 predicted_seconds 自动计算 predicted_hours
        try:
            cursor.execute("""
                UPDATE predictions
                SET predicted_hours = ROUND(CAST(predicted_seconds AS REAL) / 3600, 2)
                WHERE (predicted_hours IS NULL OR predicted_hours = 0)
                  AND (predicted_seconds IS NOT NULL AND predicted_seconds > 0)
            """)
        except Exception as e:
            logger.debug("更新 predictions predicted_hours 失败: %s", e)

    def _exec_mirror(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        """在镜像连接上执行 SQL（若镜像已创建）。

        与主库写入共用同一 SQL/参数定义, 消除 _mirror_* 重复方法。
        """
        if not self._mirror_conn:
            return
        try:
            with self._lock:
                self._mirror_conn.execute(sql, params)
                self._mirror_conn.commit()
        except Exception as e:
            logger.debug("镜像写入失败 %s: %s", self.bvid, e)

    def save_video_info(self, video_info: Dict) -> None:
        """保存（插入或替换）视频信息到 video_info 表, 并同步镜像库。

        Args:
            video_info: 视频信息字典
        """
        sql = """
            INSERT OR REPLACE INTO video_info
            (id, title, view_count, like_count, coin_count, share_count,
             favorite_count, danmaku_count, reply_count, viewers_app,
             viewers_web, viewers_total, cover_path, like_view_ratio,
             owner_name, owner_id, pubdate, duration, pic, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            video_info.get("title", ""),
            video_info.get("view_count", 0),
            video_info.get("like_count", 0),
            video_info.get("coin_count", 0),
            video_info.get("share_count", 0),
            video_info.get("favorite_count", 0),
            video_info.get("danmaku_count", 0),
            video_info.get("reply_count", 0),
            video_info.get("viewers_app", 0),
            video_info.get("viewers_web", 0),
            video_info.get("viewers_total", 0),
            video_info.get("cover_path", ""),
            video_info.get("like_view_ratio", 0),
            video_info.get("author", ""),
            video_info.get("owner_id", 0),
            video_info.get("pubdate", ""),
            video_info.get("duration", 0),
            video_info.get("pic", ""),
            datetime.now(),
        )
        try:
            with self._get_connection() as conn:
                conn.cursor().execute(sql, params)
                conn.commit()
            self._exec_mirror(sql, params)
        except Exception as e:
            logger.warning("保存视频信息失败 %s: %s", self.bvid, e, exc_info=True)

    def add_monitor_record(self, record: MonitorRecord) -> bool:
        """添加一条监控记录, 并同步镜像库

        Args:
            record: 监控记录数据对象

        Returns:
            是否写入成功
        """
        sql = """
            INSERT INTO monitor_records
            (timestamp, view_count, like_count, coin_count, share_count,
             favorite_count, danmaku_count, reply_count, viewers_app,
             viewers_web, viewers_total, like_view_ratio, observed_at_us,
             request_start_us, rtt_us)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            record.timestamp,
            record.view_count,
            record.like_count,
            record.coin_count,
            record.share_count,
            record.favorite_count,
            record.danmaku_count,
            record.reply_count,
            record.viewers_app,
            record.viewers_web,
            record.viewers_total,
            record.like_view_ratio,
            record.observed_at_us,
            record.request_start_us,
            record.rtt_us,
        )
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                self._enqueue_outbox(
                    cursor,
                    "monitor_records",
                    record.timestamp,
                    cursor.lastrowid,
                    asdict(record),
                )
                conn.commit()
            self._exec_mirror(sql, params)
            return True
        except Exception as e:
            logger.warning("添加监控记录失败 %s: %s", record.bvid, e, exc_info=True)
            return False

    def delete_monitor_records_before(self, cutoff: str) -> int:
        """删除 timestamp 早于 cutoff 的监控记录（主库+镜像），返回删除行数。

        时间戳全库统一为 "YYYY-MM-DD HH:MM:SS"（见 utils.time_utils），
        因此可直接字典序比较并命中 timestamp 索引。返回 0 表示未删除或失败。
        """
        sql = "DELETE FROM monitor_records WHERE timestamp < ?"
        try:
            with self._get_connection() as conn:
                cur = conn.cursor()
                cur.execute(sql, (cutoff,))
                deleted = cur.rowcount
                conn.commit()
            self._exec_mirror(sql, (cutoff,))
            return max(0, int(deleted))
        except Exception as e:
            logger.warning("清理旧监控记录失败 %s: %s", self.bvid, e, exc_info=True)
            return 0

    def insert_crossing_event(self, event: dict[str, Any]) -> bool:
        """按阈值写入精确过线事件，重复阈值保持首条结果。"""
        sql = """
            INSERT OR IGNORE INTO crossing_events
            (threshold, display_window_start, display_window_end, range_start,
             range_end, estimate, period_lo, period_hi, refined_start,
             refined_end, request_count, rtt_median_us, corrected_range_start,
             corrected_range_end, corrected_estimate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            event.get("threshold", 0),
            event.get("display_window_start"),
            event.get("display_window_end"),
            event.get("range_start"),
            event.get("range_end"),
            event.get("estimate"),
            event.get("period_lo"),
            event.get("period_hi"),
            event.get("refined_start"),
            event.get("refined_end"),
            event.get("request_count", 0),
            event.get("rtt_median_us"),
            event.get("corrected_range_start"),
            event.get("corrected_range_end"),
            event.get("corrected_estimate"),
        )
        try:
            with self._get_connection() as conn:
                conn.execute(sql, params)
                conn.commit()
            self._exec_mirror(sql, params)
            return True
        except Exception as e:
            logger.warning("保存精确过线事件失败 %s: %s", self.bvid, e, exc_info=True)
            return False

    def get_crossing_event(self, threshold: int) -> dict[str, Any] | None:
        """返回指定阈值最近的精确过线事件。"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM crossing_events WHERE threshold = ? ORDER BY id DESC LIMIT 1", (threshold,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.debug("读取精确过线事件失败 %s/%s: %s", self.bvid, threshold, e)
            return None

    def _prediction_sql(self, row: dict) -> tuple:
        """构造 predictions 写入的 (SQL, params), 主库/镜像库共用。"""
        sql = """
            INSERT OR REPLACE INTO predictions
            (algorithm, algorithm_id, target_threshold, predicted_seconds,
             predicted_time, confidence, current_views,
             metadata, predicted_hours, current_velocity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            row.get("algorithm", ""),
            row.get("algorithm_id", ""),
            row.get("target_threshold", 0),
            row.get("predicted_seconds", 0),
            row.get("predicted_time", ""),
            row.get("confidence", 0),
            row.get("current_views", 0),
            row.get("metadata", ""),
            row.get("predicted_hours", 0),
            row.get("current_velocity", 0),
        )
        return sql, params

    # ═══ 分数操作已移入 _ScoreOpsMixin (video_db_scores.py) ═══

    def get_all_records(self, limit: int = 0) -> List[Dict]:
        """获取监控记录列表

        Args:
            limit: 限制返回条数，0 表示不限制

        Returns:
            记录字典列表，按时间升序排列
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if limit > 0:
                    # 倒序取最后 N 条再反转，保证返回结果为升序
                    cursor.execute("SELECT * FROM monitor_records ORDER BY timestamp DESC LIMIT ?", (limit,))
                    rows = list(reversed([dict(row) for row in cursor.fetchall()]))
                else:
                    cursor.execute("SELECT * FROM monitor_records ORDER BY timestamp ASC")
                    rows = [dict(row) for row in cursor.fetchall()]
                return rows
        except Exception as e:
            logger.warning("获取记录失败 %s: %s", self.bvid, e, exc_info=True)
            return []

    def get_video_info(self) -> Optional[Dict]:
        """获取视频信息（id=1 的单行记录）

        Returns:
            视频信息字典，未找到则返回 None
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM video_info WHERE id = 1")
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.debug("获取视频信息失败: %s", e)
            return None

    def add_prediction(self, prediction: PredictionRecord) -> bool:
        """添加或替换一条预测记录（按 algorithm + target_threshold 去重）

        Args:
            prediction: 预测记录数据对象

        Returns:
            是否写入成功
        """
        row = {
            "algorithm": prediction.algorithm,
            "algorithm_id": prediction.algorithm_id,
            "target_threshold": prediction.target_threshold,
            "predicted_seconds": prediction.predicted_seconds,
            "predicted_time": prediction.predicted_time,
            "confidence": prediction.confidence,
            "current_views": prediction.current_views,
            "metadata": prediction.metadata,
            "predicted_hours": prediction.predicted_hours,
            "current_velocity": prediction.current_velocity,
        }
        sql, params = self._prediction_sql(row)
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                source = cursor.execute(
                    "SELECT id FROM predictions WHERE algorithm=? AND target_threshold=?",
                    (prediction.algorithm, prediction.target_threshold),
                ).fetchone()
                self._enqueue_outbox(
                    cursor,
                    "predictions",
                    f"{prediction.algorithm}:{prediction.target_threshold}",
                    source[0] if source else None,
                    row,
                )
                conn.commit()
            self._exec_mirror(sql, params)
            # 中央库兜底同步
            if self._central_db:
                try:
                    self._central_db.sync_predictions(self.bvid, [row])
                except Exception as e:
                    logger.debug("同步预测到中央库失败 %s: %s", self.bvid, e)
            return True
        except Exception as e:
            logger.warning("添加预测记录失败 %s: %s", prediction.bvid, e, exc_info=True)
            return False

    def get_predictions(self, limit: int = 100) -> List[Dict]:
        """获取预测记录列表，按时间倒序返回"""

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if limit > 0:
                    cursor.execute("SELECT * FROM predictions ORDER BY created_at DESC LIMIT ?", (limit,))
                else:
                    cursor.execute("SELECT * FROM predictions ORDER BY created_at DESC")
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning("获取预测记录失败: %s", e, exc_info=True)
            return []

    def add_predictions_batch(self, rows: list) -> bool:
        """批量添加或替换预测记录（按 algorithm + target_threshold 去重）

        每条记录使用 INSERT OR REPLACE，同时同步写入镜像和中央库。

        Args:
            rows: 预测记录字典列表，每条需包含:
                algorithm, algorithm_id, target_threshold, predicted_seconds,
                predicted_time, confidence, current_views, metadata,
                predicted_hours, current_velocity

        Returns:
            是否写入成功
        """
        if not rows:
            return True
        # SQLite INTEGER 最大值 (64位带符号)
        _SQLITE_INT_MAX = 2**63 - 1

        def _clamp_int(v: Any) -> int:
            """把数值夹到 SQLite 64 位有符号整数范围内。"""
            return min(max(int(v or 0), -_SQLITE_INT_MAX), _SQLITE_INT_MAX)

        def _prediction_params(r: dict[str, Any]) -> tuple[Any, ...]:
            """构造 predictions 行参数，补全 is_reached / actual_time"""
            views = _clamp_int(r.get("current_views", 0))
            threshold = _clamp_int(r.get("target_threshold", 0))
            reached = views >= threshold
            return (
                r.get("algorithm", ""),
                r.get("algorithm_id", ""),
                threshold,
                _clamp_int(r.get("predicted_seconds", 0)),
                r.get("predicted_time", ""),
                r.get("confidence", 0),
                views,
                r.get("metadata", ""),
                r.get("predicted_hours", 0),
                r.get("current_velocity", 0),
                1 if reached else 0,
                now_ts() if reached else "",
            )

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.executemany(
                    """
                    INSERT OR REPLACE INTO predictions
                    (algorithm, algorithm_id, target_threshold, predicted_seconds,
                     predicted_time, confidence, current_views,
                     metadata, predicted_hours, current_velocity,
                     is_reached, actual_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    [_prediction_params(r) for r in rows],
                )
                for row in rows:
                    source = cursor.execute(
                        "SELECT id FROM predictions WHERE algorithm=? AND target_threshold=?",
                        (row.get("algorithm"), row.get("target_threshold")),
                    ).fetchone()
                    self._enqueue_outbox(
                        cursor,
                        "predictions",
                        f"{row.get('algorithm', '')}:{row.get('target_threshold', 0)}",
                        source[0] if source else None,
                        row,
                    )
                conn.commit()
            # 镜像批量同步（单事务批量写入，避免逐行 commit）
            if self._mirror_conn:
                try:
                    self._mirror_conn.executemany(
                        """INSERT OR REPLACE INTO predictions
                        (algorithm, algorithm_id, target_threshold, predicted_seconds,
                         predicted_time, confidence, current_views,
                         metadata, predicted_hours, current_velocity,
                         is_reached, actual_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        [_prediction_params(r) for r in rows],
                    )
                    self._mirror_conn.commit()
                except Exception as e:
                    logger.debug("镜像批量同步预测记录失败 %s: %s", self.bvid, e)
            # 中央库兜底同步
            if self._central_db:
                try:
                    self._central_db.sync_predictions(self.bvid, rows)
                except Exception as e:
                    logger.debug("批量同步预测到中央库失败 %s: %s", self.bvid, e)
            return True
        except Exception as e:
            logger.warning("批量添加预测记录失败 %s: %s", self.bvid, e, exc_info=True)
            return False

    # ═══ 周刊/年刊分数 → 已移入 _ScoreOpsMixin (video_db_scores.py) ═══

    def cleanup_duplicate_predictions(self) -> dict:
        """清理预测表中的重复行，每个 (algorithm, target_threshold) 仅保留最新一条

        已有的 UNIQUE 约束确保新写入不再产生重复，此方法用于清除历史遗留的重复数据。
        镜像库同步清理。

        Returns:
            {"deleted": int, "kept": int, "mirror_deleted": int}
        """
        result = {"deleted": 0, "kept": 0, "mirror_deleted": 0}
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # 先统计总数
                cursor.execute("SELECT COUNT(*) FROM predictions")
                before = cursor.fetchone()[0]
                # 删除每个 (algorithm, target_threshold) 分组中除最新 id 之外的行
                cursor.execute("""
                    DELETE FROM predictions
                    WHERE id NOT IN (
                        SELECT MAX(id) FROM predictions
                        GROUP BY algorithm, target_threshold
                    )
                """)
                result["deleted"] = before - (cursor.execute("SELECT COUNT(*) FROM predictions").fetchone()[0])
                result["kept"] = cursor.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
                conn.commit()
            # 镜像同步清理
            if self._mirror_conn:
                try:
                    mirror_cur = self._mirror_conn.cursor()
                    mirror_before = mirror_cur.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
                    mirror_cur.execute("""
                        DELETE FROM predictions
                        WHERE id NOT IN (
                            SELECT MAX(id) FROM predictions
                            GROUP BY algorithm, target_threshold
                        )
                    """)
                    self._mirror_conn.commit()
                    result["mirror_deleted"] = (
                        mirror_before - mirror_cur.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
                    )
                except Exception as e:
                    logger.debug("镜像清理预测重复失败 %s: %s", self.bvid, e)
            if result["deleted"] > 0 or result["mirror_deleted"] > 0:
                logger.info(
                    "预测清理完成 %s: 主库删除%d行(保留%d), 镜像删除%d行",
                    self.bvid,
                    result["deleted"],
                    result["kept"],
                    result["mirror_deleted"],
                )
        except Exception as e:
            logger.warning("清理预测重复失败 %s: %s", self.bvid, e, exc_info=True)
        return result

    def close(self) -> None:
        """关闭数据库连接，刷新 WAL

        依次 checkpoint、关闭主连接、关闭镜像连接
        """
        self.wal_checkpoint()
        try:
            self._conn.close()
        except Exception as e:
            logger.debug("关闭数据库连接失败: %s", e)
        if self._mirror_conn:
            try:
                self._mirror_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._mirror_conn.close()
            except Exception as e:
                logger.debug("关闭镜像数据库连接失败: %s", e)

    def wal_checkpoint(self) -> None:
        """安全执行 WAL checkpoint，持有锁避免与写入冲突"""
        try:
            with self._lock:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as e:
            logger.debug("WAL checkpoint 失败: %s", e)
