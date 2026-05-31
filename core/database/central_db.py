"""中央总数据库管理类 —— 管理所有视频的汇总数据、里程碑及多库同步

Database 是面向外部调用的门面（Facade），
实际逻辑委托给 CentralCRUD / CentralQuery / CentralBackup 三个子模块。
"""

import sqlite3
import os
import re
import threading
import logging
from typing import Dict, List, Optional

from utils import project_path

from .connection import _ConnectionCtx, _http_session
from .models import _validate_bvid, VideoInfo, MonitorRecord, PredictionRecord
from .video_db import VideoDatabase
from .central_crud import CentralCRUD
from .central_query import CentralQuery
from .central_backup import CentralBackup

logger = logging.getLogger(__name__)


class Database:
    """中央总数据库管理类

    管理 bilibili_monitor.db 总库，包含：
    - 所有视频的元数据（videos 表）
    - 汇总的监控记录（monitor_records 表）
    - 预测记录（predictions 表）
    - 里程碑数据（video_milestones 表）
    - 周刊/年刊分数（weekly_scores / yearly_scores 表）
    支持活跃库与备份库之间的双向同步。
    """

    _ACTIVE_DIR = project_path("core", "data")
    _BACKUP_DIR = None

    @classmethod
    def _migrate_old_data(cls):
        """从旧的 core/data/ 迁移数据到 data/"""
        old_dir = project_path("core", "data")
        new_dir = cls._ACTIVE_DIR
        if old_dir == new_dir or not os.path.exists(old_dir):
            return
        import shutil
        import sqlite3 as _sqlite3
        migrated = 0
        try:
            for item in os.listdir(old_dir):
                src = os.path.join(old_dir, item)
                dst = os.path.join(new_dir, item)
                if os.path.isdir(src):
                    src_db = os.path.join(src, f"{item}.db")
                    dst_db = os.path.join(dst, f"{item}.db")
                    should_copy = not os.path.exists(dst)
                    if not should_copy and os.path.exists(src_db) and os.path.exists(dst_db):
                        try:
                            sc = _sqlite3.connect(src_db).execute("SELECT COUNT(*) FROM monitor_records").fetchone()[0]
                            dc = _sqlite3.connect(dst_db).execute("SELECT COUNT(*) FROM monitor_records").fetchone()[0]
                            if sc > dc * 2:
                                should_copy = True
                        except Exception as e:
                            logger.debug("迁移计数检查失败 %s: %s", item, e)
                    if should_copy:
                        if os.path.exists(dst):
                            try:
                                for f in os.listdir(dst):
                                    if f.endswith(".db") or f.endswith(".db-wal") or f.endswith(".db-shm"):
                                        os.chmod(os.path.join(dst, f), 0o600)
                            except Exception as e:
                                logger.debug("修改权限失败 %s: %s", f, e)
                            try:
                                shutil.rmtree(dst)
                            except PermissionError:
                                logger.warning("迁移跳过 %s: 文件被占用", item)
                                continue
                        shutil.copytree(src, dst)
                        migrated += 1
                else:
                    if not os.path.exists(dst):
                        shutil.copy2(src, dst)
                        migrated += 1
            if migrated:
                logger.info("已从 %s 迁移 %d 项到 %s", old_dir, migrated, new_dir)
        except Exception as e:
            logger.warning("迁移旧数据失败: %s", e)

    @classmethod
    def _get_backup_dir(cls) -> str:
        """获取备份目录路径，优先从 config.DATA_DIR 读取"""
        if cls._BACKUP_DIR is None:
            try:
                from config import DATA_DIR
                cls._BACKUP_DIR = DATA_DIR
            except ImportError:
                cls._BACKUP_DIR = cls._ACTIVE_DIR
        return cls._BACKUP_DIR

    def __init__(self, db_path: str = None):
        if db_path is None:
            os.makedirs(self._ACTIVE_DIR, exist_ok=True)
            db_path = os.path.join(self._ACTIVE_DIR, "bilibili_monitor.db")

        self._migrate_old_data()

        self.db_path = db_path
        self.data_dir = os.path.dirname(db_path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        try:
            self.init_database()
        except Exception:
            self._conn.close()
            raise

        self._crud = CentralCRUD(self)
        self._query = CentralQuery(self)
        self._backup = CentralBackup(self)

    def _get_connection(self):
        """返回线程安全的连接上下文管理器（兼容 with 语法）"""
        return _ConnectionCtx(self._conn, self._lock)

    def init_database(self):
        """初始化总数据库表结构

        创建 videos、monitor_records、predictions、video_milestones 等核心表及索引
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    bvid TEXT PRIMARY KEY,
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS monitor_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bvid TEXT,
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
                    like_view_ratio REAL DEFAULT 0,
                    FOREIGN KEY (bvid) REFERENCES videos(bvid)
                )
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_monitor_bvid_ts
                ON monitor_records(bvid, timestamp)
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bvid TEXT,
                    algorithm TEXT,
                    algorithm_id TEXT,
                    target_threshold INTEGER,
                    predicted_seconds INTEGER,
                    predicted_time TIMESTAMP,
                    confidence REAL,
                    current_views INTEGER,
                    is_reached BOOLEAN DEFAULT 0,
                    actual_time TIMESTAMP,
                    error_rate REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (bvid) REFERENCES videos(bvid)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_predictions_bvid ON predictions(bvid)")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS video_milestones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bvid TEXT NOT NULL,
                    period TEXT NOT NULL,
                    view_count INTEGER NOT NULL,
                    like_count INTEGER,
                    coin_count INTEGER,
                    share_count INTEGER,
                    favorite_count INTEGER,
                    danmaku_count INTEGER,
                    reply_count INTEGER,
                    note TEXT,
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(bvid, period)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_milestones_bvid ON video_milestones(bvid)")
            self._migrate_db(conn)
            conn.commit()

    def _migrate_db(self, conn):
        """总数据库迁移：检查并添加缺少的列"""
        cursor = conn.cursor()
        schema_upgrades = {
            "videos": [
                ("viewers_app", "INTEGER DEFAULT 0"),
                ("viewers_web", "INTEGER DEFAULT 0"),
                ("viewers_total", "INTEGER DEFAULT 0"),
                ("like_view_ratio", "REAL DEFAULT 0"),
                ("owner_name", "TEXT"),
                ("owner_id", "INTEGER"),
                ("pubdate", "TEXT"),
                ("duration", "INTEGER"),
                ("pic", "TEXT"),
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
            ],
        }
        for table, columns in schema_upgrades.items():
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table):
                continue
            cursor.execute(f"PRAGMA table_info({table})")
            existing = {row["name"] for row in cursor.fetchall()}
            if not existing:
                continue
            for col_name, col_def in columns:
                if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", col_name):
                    continue
                if col_name not in existing:
                    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*(\s+DEFAULT\s+[^\s;]+)?$", col_def):
                        logger.warning(f"迁移跳过: {table}.{col_name} 含不安全的列定义 {col_def}")
                        continue
                    try:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                    except Exception as e:
                        logger.warning(f"迁移失败 {table}.{col_name}: {e}")

    def get_video_db(self, bvid: str) -> VideoDatabase:
        """获取单个视频的独立数据库实例"""
        return VideoDatabase(bvid, self.data_dir)

    def download_cover(self, bvid: str, pic_url: str) -> str:
        """下载视频封面到集中管理的 cover 目录"""
        try:
            _validate_bvid(bvid)
            from utils.cover_manager import save_cover, get_valid_cover
            local = get_valid_cover(bvid)
            if local is not None:
                return local
            response = _http_session.get(pic_url, timeout=10)
            if response.status_code == 200:
                path = save_cover(bvid, response.content)
                return path or ""
        except Exception as e:
            logger.warning("下载封面失败 %s: %s", bvid, e)
        return ""

    def wal_checkpoint(self):
        """周期性 WAL checkpoint，控制 WAL 文件大小"""
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as e:
            logger.debug("WAL checkpoint 失败: %s", e)

    def close(self):
        """关闭数据库连接，刷新 WAL"""
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.commit()
            self._conn.close()
        except Exception as e:
            logger.warning("关闭数据库失败: %s", e)

    # ── CRUD 委托 ─────────────────────────────────────────────────────

    def get_video(self, bvid: str) -> Optional[VideoInfo]:
        return self._crud.get_video(bvid)

    def add_video(self, video: VideoInfo) -> bool:
        return self._crud.add_video(video)

    def delete_video(self, bvid: str) -> bool:
        return self._crud.delete_video(bvid)

    def sync_from_video_db(self, bvid: str) -> bool:
        return self._crud.sync_from_video_db(bvid)

    def sync_video_info(self, bvid: str, video: dict) -> bool:
        return self._crud.sync_video_info(bvid, video)

    def sync_monitor_record(self, bvid: str, record: dict) -> bool:
        return self._crud.sync_monitor_record(bvid, record)

    def sync_all_video_dbs(self) -> Dict[str, bool]:
        return self._crud.sync_all_video_dbs()

    def add_monitor_record(self, record: MonitorRecord) -> bool:
        return self._crud.add_monitor_record(record)

    def get_monitor_history(self, bvid: str, limit: int = 0) -> List[Dict]:
        return self._crud.get_monitor_history(bvid, limit)

    def add_prediction(self, prediction: PredictionRecord) -> bool:
        return self._crud.add_prediction(prediction)

    def get_predictions(self, bvid: str = None, algorithm: str = None, limit: int = 100) -> List[Dict]:
        return self._crud.get_predictions(bvid, algorithm, limit)

    def upsert_milestone(self, bvid: str, period: str, data: dict) -> bool:
        return self._crud.upsert_milestone(bvid, period, data)

    def get_milestones(self, bvid: str = None) -> list:
        return self._crud.get_milestones(bvid)

    def get_all_milestones_grouped(self) -> dict:
        return self._crud.get_all_milestones_grouped()

    def delete_milestone(self, bvid: str, period: str) -> bool:
        return self._crud.delete_milestone(bvid, period)

    # ── 查询委托 ──────────────────────────────────────────────────────

    def query_monitor_records(self, bvid: str, start_time: str = None, end_time: str = None, limit: int = 1000) -> List[Dict]:
        return self._query.query_monitor_records(bvid, start_time, end_time, limit)

    def search_videos(self, keyword: str = "", field: str = "title", limit: int = 50) -> List[Dict]:
        return self._query.search_videos(keyword, field, limit)

    def get_video_list(self, sort_by: str = "updated_at", order: str = "DESC", limit: int = 100) -> List[Dict]:
        return self._query.get_video_list(sort_by, order, limit)

    def get_summary_stats(self) -> Dict:
        return self._query.get_summary_stats()

    def export_video_to_csv(self, bvid: str, filepath: str = None) -> str:
        return self._query.export_video_to_csv(bvid, filepath)

    # ── 备份同步委托 ──────────────────────────────────────────────────

    def sync_to_central(self) -> dict:
        return self._backup.sync_to_central()

    def sync_per_video_dbs_to_backup(self):
        return self._backup.sync_per_video_dbs_to_backup()

    def check_backup_diffs(self) -> List[Dict]:
        return self._backup.check_backup_diffs()


_db = None


def get_db():
    """获取全局 Database 单例（惰性初始化）"""
    global _db
    if _db is None:
        _db = Database()
    return _db
