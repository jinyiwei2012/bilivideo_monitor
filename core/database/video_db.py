"""单个视频的独立数据库 —— 每个 BV 号对应一个独立 SQLite 数据库文件"""

import sqlite3
import os
import re
import threading
import logging
from datetime import datetime
from utils import project_path
from typing import List, Dict, Optional

from .connection import _ConnectionCtx
from .models import _validate_bvid, MonitorRecord, PredictionRecord
from .video_db_danmaku import _DanmakuMixin
from .video_db_scores import _ScoreOpsMixin

logger = logging.getLogger(__name__)


class VideoDatabase(_DanmakuMixin, _ScoreOpsMixin):
    """单个视频的独立数据库
    每个视频拥有独立的 SQLite 文件（data/<BV>/<BV>.db），
    同时维护一个镜像连接同步写入 data/ 目录。
    """

    def __init__(self, bvid: str, base_dir: str = None):
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
        self._mirror_conn = None
        self._mirror_path = None
        mirror_base = project_path("data")
        if mirror_base != base_dir:
            mirror_dir = os.path.join(mirror_base, bvid)
            os.makedirs(mirror_dir, exist_ok=True)
            self._mirror_path = os.path.join(mirror_dir, f"{bvid}.db")

        # 中央数据库引用（用于写入兜底，由调用方通过 set_central_db 注入）
        self._central_db = None

        try:
            self._init_db()
            # 镜像表延迟初始化：首次 _execute_on_all() 写入时才创建连接
        except Exception:
            self._conn.close()
            raise

    def _get_connection(self):
        """返回线程安全的连接上下文管理器（兼容 with 语法）"""
        return _ConnectionCtx(self._conn, self._lock)

    def _ensure_mirror(self):
        """延迟创建镜像数据库连接（首次写入时调用，节省内存）。"""
        if self._mirror_conn is not None or self._mirror_path is None:
            return
        try:
            import sqlite3 as _sqlite3
            self._mirror_conn = _sqlite3.connect(self._mirror_path, check_same_thread=False)
            self._mirror_conn.execute("PRAGMA journal_mode=WAL")
            self._mirror_conn.execute("PRAGMA synchronous=NORMAL")
            self._init_mirror_tables()
        except Exception as e:
            logger.warning("创建镜像数据库连接失败 %s: %s", self.bvid, e, exc_info=True)
            self._mirror_conn = None

    def _execute_on_all(self, sql: str, params: tuple = ()):
        """在主连接和镜像连接上同时执行 SQL"""

        def _exec(conn, label="main"):
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

    def _raw_connection(self):
        """返回原始连接（用于需要直接操作的场景）"""
        return self._conn

    # ── 共享 schema 定义 (主库与镜像库单点维护) ──────────────────
    # 每项: (sql, tolerant); tolerant=True 时执行失败仅跳过 (如 UNIQUE 索引遇重复数据)
    SCHEMA_STATEMENTS = [
        ("""
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
        """, False),
        ("""
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
        """, False),
        ("""
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
        """, False),
        # 已有重复数据时 UNIQUE 索引创建会失败（罕见），由后续清理修复
        ("CREATE UNIQUE INDEX IF NOT EXISTS idx_predict_unique ON predictions(algorithm, target_threshold)", True),
        ("""
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
        """, False),
        ("CREATE INDEX IF NOT EXISTS idx_algo_perf_algorithm ON algorithm_performance(algorithm)", False),
        ("CREATE INDEX IF NOT EXISTS idx_algo_perf_bvid ON algorithm_performance(bvid)", False),
        ("CREATE INDEX IF NOT EXISTS idx_monitor_timestamp ON monitor_records(timestamp)", False),
        ("""
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
        """, False),
        ("CREATE INDEX IF NOT EXISTS idx_weekly_timestamp ON weekly_scores(timestamp)", False),
        ("""
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
        """, False),
        ("CREATE INDEX IF NOT EXISTS idx_yearly_timestamp ON yearly_scores(timestamp)", False),
        ("""
            CREATE TABLE IF NOT EXISTS danmaku_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bvid TEXT NOT NULL,
                oid INTEGER NOT NULL,
                segment_index INTEGER DEFAULT 0,
                dmid INTEGER DEFAULT 0,
                id_str TEXT DEFAULT '',
                content TEXT NOT NULL,
                video_ts REAL DEFAULT 0,
                mode INTEGER DEFAULT 1,
                font_size INTEGER DEFAULT 25,
                color INTEGER DEFAULT 16777215,
                send_time INTEGER DEFAULT 0,
                weight INTEGER DEFAULT 1,
                uid TEXT DEFAULT '',
                like_count INTEGER DEFAULT 0,
                pool INTEGER DEFAULT 0,
                dm_from INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """, False),
        ("CREATE INDEX IF NOT EXISTS idx_danmaku_bvid ON danmaku_records(bvid)", False),
        ("CREATE INDEX IF NOT EXISTS idx_danmaku_segment ON danmaku_records(bvid, oid, segment_index)", False),
        # dmid 列可能尚未迁移（将在下方 v3 迁移中处理）
        ("CREATE INDEX IF NOT EXISTS idx_danmaku_dmid ON danmaku_records(dmid) WHERE dmid > 0", True),
        # 去重：优先用 dmid（Proto 唯一弹幕ID），回退用内容指纹
        ("CREATE UNIQUE INDEX IF NOT EXISTS idx_danmaku_unique ON danmaku_records(bvid, oid, dmid)", True),
    ]

    @staticmethod
    def _apply_schema(cursor) -> None:
        """在指定 cursor 上执行共享 schema 定义 (主库/镜像库共用)。"""
        for sql, tolerant in VideoDatabase.SCHEMA_STATEMENTS:
            try:
                cursor.execute(sql)
            except Exception as e:  # noqa: BLE001
                if not tolerant:
                    raise
                logger.debug("schema 语句跳过(容忍): %.80s | %s", sql, e)

    def _init_db(self):
        """初始化数据库：创建所需的表、索引，并执行 schema 迁移"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 建表 + 索引 (schema 单点定义见 SCHEMA_STATEMENTS)
            self._apply_schema(cursor)

            # 数据库迁移：逐库检查 schema 版本（通过 PRAGMA user_version）
            cursor.execute("PRAGMA user_version")
            row = cursor.fetchone()
            db_version = row[0] if row else 0
            if db_version < 1:
                self._migrate_db(conn)
            if db_version < 2:
                # v1→v2: 去重弹幕 + 添加 UNIQUE 约束（修复 INSERT OR IGNORE 失效 bug）
                self._migrate_danmaku_dedup(conn)
            if db_version < 3:
                # v2→v3: 添加 Proto 弹幕新字段 (dmid/like_count/pool/dm_from) + 更新 UNIQUE 索引
                self._migrate_danmaku_v3(conn)
                cursor.execute("PRAGMA user_version = 3")

            conn.commit()

    def set_central_db(self, central_db):
        """注入中央数据库引用，用于写入时同步兜底

        Args:
            central_db: core.database.Database 实例
        """
        self._central_db = central_db

    def _init_mirror_tables(self):
        """在镜像连接上创建与主库相同的表结构（仅当镜像连接存在时）。

        schema 单点定义见 SCHEMA_STATEMENTS, 与主库共用。
        """
        if not self._mirror_conn:
            return
        try:
            mirror_cur = self._mirror_conn.cursor()
            self._apply_schema(mirror_cur)
            self._mirror_conn.commit()
        except Exception as e:
            logger.warning("初始化镜像数据库表失败 %s: %s", self.bvid, e, exc_info=True)

    def _migrate_db(self, conn):
        """检查并迁移数据库：添加缺少的列、自动计算默认值

        Args:
            conn: 数据库连接
        """
        cursor = conn.cursor()
        self._migrate_schema_upgrades(cursor)
        self._migrate_compute_values(cursor)

    def _migrate_schema_upgrades(self, cursor):
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

    def _migrate_compute_values(self, cursor):
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

    def save_video_info(self, video_info: Dict):
        """保存（插入或替换）视频信息到 video_info 表

        Args:
            video_info: 视频信息字典
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO video_info
                    (id, title, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, cover_path, like_view_ratio,
                     owner_name, owner_id, pubdate, duration, pic, updated_at)
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
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
                        video_info.get("owner_name", ""),
                        video_info.get("owner_id", 0),
                        video_info.get("pubdate", ""),
                        video_info.get("duration", 0),
                        video_info.get("pic", ""),
                        datetime.now(),
                    ),
                )
                conn.commit()
            # 同步写入镜像数据库
            self._mirror_save_video_info(video_info)
        except Exception as e:
            logger.warning("保存视频信息失败 %s: %s", self.bvid, e, exc_info=True)

    def _mirror_save_video_info(self, video_info: Dict):
        """将视频信息同步写入镜像数据库

        注意：双写模式存在一致性风险——若视频独立库写入成功但镜像库写入失败，
        两端数据将不一致。当前通过 try/except 仅记录日志，不触发回滚或重试。

        Args:
            video_info: 视频信息字典
        """
        if not self._mirror_conn:
            return
        try:
            with self._lock:
                self._mirror_conn.execute(
                """
                INSERT OR REPLACE INTO video_info
                (id, title, view_count, like_count, coin_count, share_count,
                 favorite_count, danmaku_count, reply_count, viewers_app,
                 viewers_web, viewers_total, cover_path, like_view_ratio,
                 owner_name, owner_id, pubdate, duration, pic, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
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
                    video_info.get("owner_name", ""),
                    video_info.get("owner_id", 0),
                    video_info.get("pubdate", ""),
                    video_info.get("duration", 0),
                    video_info.get("pic", ""),
                    datetime.now(),
                ),
            )
            self._mirror_conn.commit()
        except Exception as e:
            logger.debug("镜像保存视频信息失败 %s: %s", self.bvid, e)

    def add_monitor_record(self, record: MonitorRecord) -> bool:
        """添加一条监控记录

        Args:
            record: 监控记录数据对象

        Returns:
            是否写入成功
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO monitor_records
                    (timestamp, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, like_view_ratio)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
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
                    ),
                )
                conn.commit()
            self._mirror_add_monitor_record(record)
            return True
        except Exception as e:
            logger.warning("添加监控记录失败 %s: %s", record.bvid, e, exc_info=True)
            return False

    def _mirror_add_monitor_record(self, record: MonitorRecord):
        """将监控记录同步写入镜像数据库

        注意：双写模式存在一致性风险——若视频独立库写入成功但镜像库写入失败，
        两端数据将不一致。当前通过 try/except 仅记录日志，不触发回滚或重试。

        Args:
            record: 监控记录数据对象
        """
        if not self._mirror_conn:
            return
        try:
            with self._lock:
                self._mirror_conn.execute(
                    """
                    INSERT INTO monitor_records
                (timestamp, view_count, like_count, coin_count, share_count,
                 favorite_count, danmaku_count, reply_count, viewers_app,
                 viewers_web, viewers_total, like_view_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                    (
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
                    ),
                )
                self._mirror_conn.commit()
        except Exception as e:
            logger.debug("镜像添加监控记录失败 %s: %s", record.bvid, e)

    def _mirror_add_prediction(self, row: dict):
        """将预测记录同步写入镜像数据库"""
        if not self._mirror_conn:
            return
        try:
            with self._lock:
                self._mirror_conn.execute(
                    """
                    INSERT OR REPLACE INTO predictions
                    (algorithm, algorithm_id, target_threshold, predicted_seconds,
                     predicted_time, confidence, current_views,
                     metadata, predicted_hours, current_velocity)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
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
                    ),
                )
                self._mirror_conn.commit()
        except Exception as e:
            logger.debug("镜像添加预测记录失败 %s: %s", self.bvid, e)

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
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO predictions
                    (algorithm, algorithm_id, target_threshold, predicted_seconds,
                     predicted_time, confidence, current_views,
                     metadata, predicted_hours, current_velocity)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        prediction.algorithm,
                        prediction.algorithm_id,
                        prediction.target_threshold,
                        prediction.predicted_seconds,
                        prediction.predicted_time,
                        prediction.confidence,
                        prediction.current_views,
                        prediction.metadata,
                        prediction.predicted_hours,
                        prediction.current_velocity,
                    ),
                )
                conn.commit()
            self._mirror_add_prediction({
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
            })
            # 中央库兜底同步
            if self._central_db:
                try:
                    self._central_db.sync_predictions(self.bvid, [{
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
                    }])
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
        _clamp_int = lambda v: min(max(int(v or 0), -_SQLITE_INT_MAX), _SQLITE_INT_MAX)
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.executemany(
                    """
                    INSERT OR REPLACE INTO predictions
                    (algorithm, algorithm_id, target_threshold, predicted_seconds,
                     predicted_time, confidence, current_views,
                     metadata, predicted_hours, current_velocity)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    [
                        (
                            r.get("algorithm", ""),
                            r.get("algorithm_id", ""),
                            _clamp_int(r.get("target_threshold", 0)),
                            _clamp_int(r.get("predicted_seconds", 0)),
                            r.get("predicted_time", ""),
                            r.get("confidence", 0),
                            _clamp_int(r.get("current_views", 0)),
                            r.get("metadata", ""),
                            r.get("predicted_hours", 0),
                            r.get("current_velocity", 0),
                        )
                        for r in rows
                    ],
                )
                conn.commit()
            # 镜像批量同步（单事务批量写入，避免逐行 commit）
            if self._mirror_conn:
                try:
                    self._mirror_conn.executemany(
                        """INSERT OR REPLACE INTO predictions
                        (algorithm, algorithm_id, target_threshold, predicted_seconds,
                         predicted_time, confidence, current_views,
                         metadata, predicted_hours, current_velocity)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        [
                            (
                                r.get("algorithm", ""),
                                r.get("algorithm_id", ""),
                                r.get("target_threshold", 0),
                                r.get("predicted_seconds", 0),
                                r.get("predicted_time", ""),
                                r.get("confidence", 0),
                                r.get("current_views", 0),
                                r.get("metadata", ""),
                                r.get("predicted_hours", 0),
                                r.get("current_velocity", 0),
                            )
                            for r in rows
                        ],
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
                    self.bvid, result["deleted"], result["kept"], result["mirror_deleted"],
                )
        except Exception as e:
            logger.warning("清理预测重复失败 %s: %s", self.bvid, e, exc_info=True)
        return result

    def close(self):
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

    def wal_checkpoint(self):
        """安全执行 WAL checkpoint，持有锁避免与写入冲突"""
        try:
            with self._lock:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as e:
            logger.debug("WAL checkpoint 失败: %s", e)
