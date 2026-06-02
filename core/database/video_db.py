"""
单个视频的独立数据库 —— 每个 BV 号对应一个独立 SQLite 数据库文件
==============================================================

本模块实现了 VideoDatabase 类，为每个 Bilibili 视频提供独立的数据存储。
每个视频拥有独立的 SQLite 文件（data/<BV>/<BV>.db）。

数据库架构设计要点：
1. 一个视频一个库：避免单文件过大，方便备份和迁移
2. WAL 模式：启用 Write-Ahead Logging 提升并发读写性能
3. 线程安全：通过 _ConnectionCtx 持有可重入锁，保证多线程访问安全
4. Schema 迁移：通过 PRAGMA user_version 和预定义映射实现渐进式升级

支持的数据库表：
- video_info: 视频元数据（id 固定为 1，每库一条）
- monitor_records: 监控记录（按时间序列增长）
- predictions: 预测记录
- algorithm_performance: 算法性能跟踪（用于在线学习）
- weekly_scores: 周刊分数记录
- yearly_scores: 年刊分数记录
"""

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

# ── 模块级日志 ────────────────────────────────────────────────────
logger = logging.getLogger(__name__)


class VideoDatabase:
    """单个视频的独立数据库

    每个视频拥有独立的 SQLite 文件（data/<BV>/<BV>.db）。

    示例用法:
        db = VideoDatabase("BV1xx411c7mD")
        db.save_video_info({...})
        db.add_monitor_record(record)
        db.close()
    """

    def __init__(self, bvid: str, base_dir: str = None):
        """初始化视频独立数据库

        创建以 BV 号命名的目录和数据库文件，建立主连接，
        初始化表结构和索引。

        Args:
            bvid: BV 号（传入前应已通过 _validate_bvid 校验）
            base_dir: 数据库存放根目录（None 则使用 core/data/）
        """
        _validate_bvid(bvid)  # 安全校验，防止路径穿越
        self.bvid = bvid
        if base_dir is None:
            base_dir = project_path("core", "data")

        # ── 创建以 BV 号命名的文件夹 ─────────────────────────────
        self.video_dir = os.path.join(base_dir, bvid)
        os.makedirs(self.video_dir, exist_ok=True)

        # ── 数据库文件路径：data/<BV>/<BV>.db ────────────────────
        self.db_path = os.path.join(self.video_dir, f"{bvid}.db")
        self._lock = threading.RLock()  # 可重入线程锁
        # check_same_thread=False 允许跨线程使用同一连接（配合 _lock 保证安全）
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row  # 查询结果以字典式 Row 返回
        # WAL 模式：写操作不阻塞读操作，提升并发性能
        self._conn.execute("PRAGMA journal_mode=WAL")
        # synchronous=NORMAL：在关键安全点同步写入，平衡性能与安全性
        self._conn.execute("PRAGMA synchronous=NORMAL")

        # ── 镜像连接：同步写入 data/ 目录（退出时同步到 core/data/bilibili_monitor.db 的目标目录） ──
        self._mirror_conn = None
        mirror_base = project_path("data")
        if mirror_base != base_dir:
            mirror_dir = os.path.join(mirror_base, bvid)
            os.makedirs(mirror_dir, exist_ok=True)
            mirror_path = os.path.join(mirror_dir, f"{bvid}.db")
            try:
                self._mirror_conn = sqlite3.connect(mirror_path, check_same_thread=False)
                self._mirror_conn.execute("PRAGMA journal_mode=WAL")
                self._mirror_conn.execute("PRAGMA synchronous=NORMAL")
            except Exception as e:
                logger.warning("创建镜像数据库连接失败 %s: %s", bvid, e)
                self._mirror_conn = None

        try:
            self._init_db()  # 初始化表结构和索引
        except Exception:
            self._conn.close()  # 初始化失败则关闭连接
            raise

    def _get_connection(self):
        """返回线程安全的连接上下文管理器

        调用方使用 with self._get_connection() as conn: 获取连接，
        上下文内部自动获取锁并在退出时提交/回滚。

        Returns:
            _ConnectionCtx 透明连接上下文实例
        """
        return _ConnectionCtx(self._conn, self._lock)

    def _raw_connection(self):
        """返回原始连接（用于需要直接操作的场景）

        Returns:
            sqlite3.Connection 原始连接对象
        """
        return self._conn

    def _execute_on_all(self, sql: str, params: tuple = ()):
        """在主连接和镜像连接上同时执行 SQL

        确保主库和镜像库数据一致。镜像失败仅记录日志，不阻断主库写入。

        Args:
            sql: SQL 语句
            params: SQL 参数元组
        """
        def _exec(conn, label="main"):
            try:
                conn.execute(sql, params) if params else conn.execute(sql)
                conn.commit()
            except Exception as e:
                logger.error("数据库写入失败 [%s]: %s | SQL: %.200s", label, e, sql)

        with self._get_connection() as conn:
            _exec(conn, "main")
        if self._mirror_conn:
            with _ConnectionCtx(self._mirror_conn, self._lock) as conn:
                _exec(conn, "mirror")

    def _init_db(self):
        """初始化数据库：创建所需的表、索引，并执行 schema 迁移

        创建以下数据库对象：
        1. video_info — 视频元数据（id 固定为 1）
        2. monitor_records — 监控记录（时序数据）
        3. predictions — 预测记录
        4. algorithm_performance — 算法性能跟踪
        5. weekly_scores — 周刊分数
        6. yearly_scores — 年刊分数
        7. 相关索引 — 加速时间范围查询

        同时通过 PRAGMA user_version 执行渐进式 schema 迁移。
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # ── 1. 视频信息表（id 固定为 1，每库一条） ──────────
            cursor.execute("""
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
            """)

            # ── 2. 监控记录表（每次采集新增一条） ────────────────
            cursor.execute("""
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
            """)

            # ── 3. 预测记录表 ────────────────────────────────────
            cursor.execute("""
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
            """)

            # ── 4. 算法性能跟踪表（用于在线学习模块） ────────────
            cursor.execute("""
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
            """)
            # 算法性能索引：加速按算法名和 BV 号过滤
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_algo_perf_algorithm ON algorithm_performance(algorithm)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_algo_perf_bvid ON algorithm_performance(bvid)")

            # ── 5. 监控记录时间索引，加速时间范围查询 ────────────
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_monitor_timestamp ON monitor_records(timestamp)")

            # ── 6. 周刊分数记录表 ────────────────────────────────
            cursor.execute("""
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
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_weekly_timestamp ON weekly_scores(timestamp)")

            # ── 7. 年刊分数记录表 ────────────────────────────────
            cursor.execute("""
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
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_yearly_timestamp ON yearly_scores(timestamp)")

            # ── 数据库迁移：逐库检查 schema 版本 ────────────────
            cursor.execute("PRAGMA user_version")  # 读取当前 schema 版本号
            row = cursor.fetchone()
            db_version = row[0] if row else 0
            if db_version < 1:
                # 执行 v0→v1 迁移：补全缺失列 + 计算派生字段
                self._migrate_db(conn)
                cursor.execute("PRAGMA user_version = 1")  # 更新版本号，避免重复迁移

            conn.commit()

        # ── 同步初始化镜像数据库的表结构 ──────────────────────
        self._init_mirror_db()

    def _init_mirror_db(self):
        """同步初始化镜像数据库的表结构

        与主库保持相同的 schema，确保双写操作能在镜像库上执行。
        镜像库失败不影响主库正常运行。
        """
        if not self._mirror_conn:
            return
        try:
            with _ConnectionCtx(self._mirror_conn, self._lock) as mconn:
                mcur = mconn.cursor()
                mcur.execute("""
                    CREATE TABLE IF NOT EXISTS video_info (
                        id INTEGER PRIMARY KEY, title TEXT,
                        view_count INTEGER DEFAULT 0, like_count INTEGER DEFAULT 0,
                        coin_count INTEGER DEFAULT 0, share_count INTEGER DEFAULT 0,
                        favorite_count INTEGER DEFAULT 0, danmaku_count INTEGER DEFAULT 0,
                        reply_count INTEGER DEFAULT 0, viewers_app INTEGER DEFAULT 0,
                        viewers_web INTEGER DEFAULT 0, viewers_total INTEGER DEFAULT 0,
                        cover_path TEXT, like_view_ratio REAL DEFAULT 0,
                        owner_name TEXT, owner_id INTEGER, pubdate TEXT,
                        duration INTEGER, pic TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                mcur.execute("""
                    CREATE TABLE IF NOT EXISTS monitor_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TIMESTAMP,
                        view_count INTEGER DEFAULT 0, like_count INTEGER DEFAULT 0,
                        coin_count INTEGER DEFAULT 0, share_count INTEGER DEFAULT 0,
                        favorite_count INTEGER DEFAULT 0, danmaku_count INTEGER DEFAULT 0,
                        reply_count INTEGER DEFAULT 0, viewers_app INTEGER DEFAULT 0,
                        viewers_web INTEGER DEFAULT 0, viewers_total INTEGER DEFAULT 0,
                        like_view_ratio REAL DEFAULT 0
                    )
                """)
                mcur.execute("CREATE INDEX IF NOT EXISTS idx_mirror_monitor_ts ON monitor_records(timestamp)")
                mcur.execute("""
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
                """)
                mcur.execute("""
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
                """)
                mcur.execute("CREATE INDEX IF NOT EXISTS idx_algo_perf_algorithm ON algorithm_performance(algorithm)")
                mcur.execute("CREATE INDEX IF NOT EXISTS idx_algo_perf_bvid ON algorithm_performance(bvid)")
                mcur.execute("""
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
                """)
                mcur.execute("CREATE INDEX IF NOT EXISTS idx_weekly_timestamp ON weekly_scores(timestamp)")
                mcur.execute("""
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
                """)
                mcur.execute("CREATE INDEX IF NOT EXISTS idx_yearly_timestamp ON yearly_scores(timestamp)")
                mconn.commit()
        except Exception as e:
            logger.warning("初始化镜像数据库表失败 %s: %s", self.bvid, e)

    def _migrate_db(self, conn):
        """检查并迁移数据库：添加缺少的列、自动计算默认值

        分两步执行：
        1. _migrate_schema_upgrades: 补全缺失的列
        2. _migrate_compute_values: 计算缺失的派生字段值

        Args:
            conn: 数据库连接
        """
        cursor = conn.cursor()
        self._migrate_schema_upgrades(cursor)
        self._migrate_compute_values(cursor)

    def _migrate_schema_upgrades(self, cursor):
        """迁移数据库模式：添加缺少的列

        根据预定义的 schema_upgrades 字典，逐表检查并添加缺失的列。
        对表名和列名做正则校验防止 SQL 注入。

        支持的升级路径：
        - video_info: 添加 viewers_* 系、owner_* 系、like_view_ratio 等
        - monitor_records: 添加 viewers_* 系和 like_view_ratio
        - predictions: 添加 metadata、predicted_hours 等
        - weekly_scores: 添加 correction_d 和 base_view_score

        Args:
            cursor: 数据库游标
        """
        # ── 预定义各表需要确保的额外字段 ─────────────────────────
        schema_upgrades = {
            "video_info": [
                ("viewers_app", "INTEGER DEFAULT 0"),        # APP 观看人数
                ("viewers_web", "INTEGER DEFAULT 0"),         # 网页观看人数
                ("viewers_total", "INTEGER DEFAULT 0"),       # 总观看人数
                ("like_view_ratio", "REAL DEFAULT 0"),        # 播赞比
                ("owner_name", "TEXT"),                        # UP 主名称
                ("owner_id", "INTEGER"),                       # UP 主 UID
                ("pubdate", "TEXT"),                           # 发布时间
                ("duration", "INTEGER"),                       # 视频时长
                ("pic", "TEXT"),                               # 封面 URL
                ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ],
            "monitor_records": [
                ("viewers_app", "INTEGER DEFAULT 0"),
                ("viewers_web", "INTEGER DEFAULT 0"),
                ("viewers_total", "INTEGER DEFAULT 0"),
                ("like_view_ratio", "REAL DEFAULT 0"),
            ],
            "predictions": [
                ("metadata", "TEXT DEFAULT ''"),               # JSON 元数据
                ("predicted_hours", "REAL DEFAULT 0"),         # 预测小时数
                ("current_velocity", "REAL DEFAULT 0"),        # 当前播放速率
                ("is_reached", "BOOLEAN DEFAULT 0"),           # 是否已达标
                ("actual_time", "TIMESTAMP"),                  # 实际达标时间
                ("error_rate", "REAL DEFAULT 0"),              # 预测误差率
            ],
            "weekly_scores": [
                ("correction_d", "REAL"),                      # 第四项修正系数
                ("base_view_score", "REAL"),                   # 基础播放分数
            ],
        }

        for table, columns in schema_upgrades.items():
            # ── 正则校验表名，防止 SQL 注入 ──────────────────────
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table):
                continue
            cursor.execute(f"PRAGMA table_info({table})")
            existing = {row["name"] for row in cursor.fetchall()}
            if not existing:
                continue  # 表不存在则跳过
            for col_name, col_def in columns:
                # ── 正则校验列名，防止 SQL 注入 ──────────────────
                if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", col_name):
                    continue
                if col_name not in existing:
                    # ── 校验列定义格式，防止包含不安全 SQL 片段 ──
                    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*(\s+DEFAULT\s+[^\s;]+)?$", col_def):
                        logger.warning(f"迁移跳过: {table}.{col_name} 含不安全的列定义 {col_def}")
                        continue
                    try:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                    except Exception as e:
                        logger.warning(f"迁移失败 {table}.{col_name}: {e}")

    def _migrate_compute_values(self, cursor):
        """自动计算缺失的数值字段

        补充以下派生字段：
        1. monitor_records.like_view_ratio（播赞比）
        2. video_info.like_view_ratio（播赞比）
        3. predictions.predicted_hours（预测小时数，从 predicted_seconds 换算）

        使用 NULLIF 和 ROUND 确保除数不为零且结果精度合理。

        Args:
            cursor: 数据库游标
        """
        # ── 补全监控记录的播赞比 ────────────────────────────────
        try:
            cursor.execute("""
                UPDATE monitor_records
                SET like_view_ratio = ROUND(CAST(like_count AS REAL) / NULLIF(view_count, 0), 6)
                WHERE like_view_ratio IS NULL OR like_view_ratio = 0
            """)
        except Exception as e:
            logger.debug("更新 monitor_records like_view_ratio 失败: %s", e)

        # ── 补全视频信息的播赞比 ────────────────────────────────
        try:
            cursor.execute("""
                UPDATE video_info
                SET like_view_ratio = ROUND(CAST(like_count AS REAL) / NULLIF(view_count, 0), 6)
                WHERE like_view_ratio IS NULL OR like_view_ratio = 0
            """)
        except Exception as e:
            logger.debug("更新 video_info like_view_ratio 失败: %s", e)

        # ── 根据 predicted_seconds 自动计算 predicted_hours ─────
        try:
            cursor.execute("""
                UPDATE predictions
                SET predicted_hours = ROUND(CAST(predicted_seconds AS REAL) / 3600, 2)
                WHERE (predicted_hours IS NULL OR predicted_hours = 0)
                  AND (predicted_seconds IS NOT NULL AND predicted_seconds > 0)
            """)
        except Exception as e:
            logger.debug("更新 predictions predicted_hours 失败: %s", e)

    @staticmethod
    def _get_video_info_params(video_info: Dict):
        """返回 video_info 表 INSERT 的参数元组"""
        return (
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
        )

    @staticmethod
    def _get_monitor_record_params(record: MonitorRecord):
        """返回 monitor_records 表 INSERT 的参数元组"""
        return (
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
        )

    def save_video_info(self, video_info: Dict):
        """保存（插入或替换）视频信息到 video_info 表

        使用 INSERT OR REPLACE 语义，id 固定为 1。

        Args:
            video_info: 视频信息字典，键名应与 video_info 列对应
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
                    self._get_video_info_params(video_info),
                )
                conn.commit()
            # ── 同步写入镜像数据库 ─────────────────────────────
            self._mirror_save_video_info(video_info)
        except Exception as e:
            logger.warning("保存视频信息失败 %s: %s", self.bvid, e)

    def _mirror_save_video_info(self, video_info: Dict):
        """将视频信息同步写入镜像数据库

        镜像写入失败仅记录日志，不触发主库回滚。
        通过独立的 try/except 保证主库数据不受镜像故障影响。

        Args:
            video_info: 视频信息字典
        """
        if not self._mirror_conn:
            return
        try:
            self._mirror_conn.execute(
                """
                INSERT OR REPLACE INTO video_info
                (id, title, view_count, like_count, coin_count, share_count,
                 favorite_count, danmaku_count, reply_count, viewers_app,
                 viewers_web, viewers_total, cover_path, like_view_ratio,
                 owner_name, owner_id, pubdate, duration, pic, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                self._get_video_info_params(video_info),
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
                    self._get_monitor_record_params(record),
                )
                conn.commit()
            # ── 同步写入镜像数据库 ─────────────────────────────
            self._mirror_add_monitor_record(record)
            return True
        except Exception as e:
            logger.warning("添加监控记录失败 %s: %s", record.bvid, e)
            return False

    def _mirror_add_monitor_record(self, record: MonitorRecord):
        """将监控记录同步写入镜像数据库

        镜像写入失败仅记录日志，不触发主库回滚。

        Args:
            record: 监控记录数据对象
        """
        if not self._mirror_conn:
            return
        try:
            self._mirror_conn.execute(
                """
                INSERT INTO monitor_records
                (timestamp, view_count, like_count, coin_count, share_count,
                 favorite_count, danmaku_count, reply_count, viewers_app,
                 viewers_web, viewers_total, like_view_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                self._get_monitor_record_params(record),
            )
            self._mirror_conn.commit()
        except Exception as e:
            logger.debug("镜像添加监控记录失败 %s: %s", record.bvid, e)

    def get_all_records(self, limit: int = 5000) -> List[Dict]:
        """获取监控记录列表

        Args:
            limit: 限制返回条数（0 表示不限制）
                   有 limit 时取最后 N 条再反转，保证返回结果为升序

        Returns:
            记录字典列表，按时间升序排列
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if limit > 0:
                    # 倒序取最后 N 条再反转，保证返回结果为升序
                    # 这样既只取 N 条又能保持时间递增
                    cursor.execute("SELECT * FROM monitor_records ORDER BY timestamp DESC LIMIT ?", (limit,))
                    rows = list(reversed([dict(row) for row in cursor.fetchall()]))
                else:
                    cursor.execute("SELECT * FROM monitor_records ORDER BY timestamp ASC")
                    rows = [dict(row) for row in cursor.fetchall()]
                return rows
        except Exception as e:
            logger.warning("获取记录失败 %s: %s", self.bvid, e)
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
        except Exception:
            return None

    def add_prediction(self, prediction: PredictionRecord) -> bool:
        """添加一条预测记录

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
                    INSERT INTO predictions
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
                return True
        except Exception as e:
            logger.warning("添加预测记录失败 %s: %s", prediction.bvid, e)
            return False

    def get_predictions(self, limit: int = 100) -> List[Dict]:
        """获取预测记录列表，按时间倒序返回

        Args:
            limit: 返回条数限制（0 表示不限制）

        Returns:
            预测记录字典列表
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if limit > 0:
                    cursor.execute("SELECT * FROM predictions ORDER BY created_at DESC LIMIT ?", (limit,))
                else:
                    cursor.execute("SELECT * FROM predictions ORDER BY created_at DESC")
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning("获取预测记录失败: %s", e)
            return []

    def add_weekly_score(self, timestamp: str, score_data: dict) -> bool:
        """添加周刊分数记录

        Args:
            timestamp: 时间戳字符串（ISO 8601 格式）
            score_data: 包含分数数据的字典，键名与 weekly_scores 表字段对应：
                total_score, view_score, interaction_score, favorite_score,
                coin_score, like_score, correction_a~d, base_view_score

        Returns:
            是否写入成功
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO weekly_scores
                    (timestamp, total_score, view_score, interaction_score,
                     favorite_score, coin_score, like_score,
                     correction_a, correction_b, correction_c, correction_d,
                     base_view_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        timestamp,
                        score_data.get("total_score", 0),
                        score_data.get("view_score", 0),
                        score_data.get("interaction_score", 0),
                        score_data.get("favorite_score", 0),
                        score_data.get("coin_score", 0),
                        score_data.get("like_score", 0),
                        score_data.get("correction_a", 0),
                        score_data.get("correction_b", 0),
                        score_data.get("correction_c", 0),
                        score_data.get("correction_d", 0),
                        score_data.get("base_view_score", 0),
                    ),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("添加周刊分数记录失败 %s: %s", self.bvid, e)
            return False

    def get_weekly_scores(self, limit: int = 0) -> list:
        """获取周刊分数历史记录

        Args:
            limit: 限制返回条数（0 表示不限制）

        Returns:
            分数记录列表，按时间升序
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if limit > 0:
                    cursor.execute("SELECT * FROM weekly_scores ORDER BY timestamp ASC LIMIT ?", (limit,))
                else:
                    cursor.execute("SELECT * FROM weekly_scores ORDER BY timestamp ASC")
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning("获取周刊分数记录失败 %s: %s", self.bvid, e)
            return []

    def get_latest_weekly_score(self) -> Optional[Dict]:
        """获取最新一条周刊分数记录

        Returns:
            分数记录字典，无记录则返回 None
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM weekly_scores ORDER BY timestamp DESC LIMIT 1")
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception:
            return None

    def add_yearly_score(self, timestamp: str, score_data: dict) -> bool:
        """添加年刊分数记录

        Args:
            timestamp: 时间戳字符串（ISO 8601 格式）
            score_data: 包含分数数据的字典，键名与 yearly_scores 表字段对应：
                total_score, view_score, interaction_score, favorite_score,
                coin_score, like_score, correction_a~c

        Returns:
            是否写入成功
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO yearly_scores
                    (timestamp, total_score, view_score, interaction_score,
                     favorite_score, coin_score, like_score,
                     correction_a, correction_b, correction_c)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        timestamp,
                        score_data.get("total_score", 0),
                        score_data.get("view_score", 0),
                        score_data.get("interaction_score", 0),
                        score_data.get("favorite_score", 0),
                        score_data.get("coin_score", 0),
                        score_data.get("like_score", 0),
                        score_data.get("correction_a", 0),
                        score_data.get("correction_b", 0),
                        score_data.get("correction_c", 0),
                    ),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("添加年刊分数记录失败 %s: %s", self.bvid, e)
            return False

    def get_yearly_scores(self, limit: int = 0) -> list:
        """获取年刊分数历史记录

        Args:
            limit: 限制返回条数（0 表示不限制）

        Returns:
            分数记录列表，按时间升序
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if limit > 0:
                    cursor.execute("SELECT * FROM yearly_scores ORDER BY timestamp ASC LIMIT ?", (limit,))
                else:
                    cursor.execute("SELECT * FROM yearly_scores ORDER BY timestamp ASC")
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning("获取年刊分数记录失败 %s: %s", self.bvid, e)
            return []

    def get_latest_yearly_score(self) -> Optional[Dict]:
        """获取最新一条年刊分数记录

        Returns:
            分数记录字典，无记录则返回 None
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM yearly_scores ORDER BY timestamp DESC LIMIT 1")
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.debug("获取最新年刊分数失败: %s", e)
            return None

    def close(self):
        """关闭数据库连接，刷新 WAL

        关闭流程：
        1. 执行 TRUNCATE checkpoint 将 WAL 数据刷入主库文件
        2. 关闭主连接
        """
        self.wal_checkpoint()
        try:
            self._conn.close()
        except Exception as e:
            logger.debug("关闭数据库连接失败: %s", e)
        # ── 关闭镜像连接 ──────────────────────────────────────
        if self._mirror_conn:
            try:
                self._mirror_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._mirror_conn.close()
            except Exception as e:
                logger.debug("关闭镜像数据库连接失败: %s", e)

    def wal_checkpoint(self):
        """安全执行 WAL checkpoint，持有锁避免与写入冲突

        WAL 文件会随写入增长，定期执行 TRUNCATE checkpoint
        将日志清空并截断 WAL 文件到 0 字节。
        通过 _lock 确保与写入操作互斥，避免并发冲突。
        """
        try:
            with self._lock:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as e:
            logger.debug("WAL checkpoint 失败: %s", e)
