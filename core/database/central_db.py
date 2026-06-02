"""
中央总数据库管理类 —— 管理所有视频的汇总数据、里程碑及多库同步
==============================================================

Database 是面向外部调用的门面（Facade），
实际逻辑委托给 CentralCRUD / CentralQuery / CentralBackup 三个子模块。

本模块同时导出全局单例 get_db() 函数，确保整个应用共享同一个数据库连接。

架构要点：
1. 线程安全：所有数据库操作通过 _ConnectionCtx 持有互斥锁，保证多线程安全
2. WAL 模式：启用 SQLite WAL 日志，提升并发读写性能
3. 懒加载迁移：首次实例化时自动检查并迁移旧数据目录（core/data/ → data/）
4. 委托模式：CRUD/Query/Backup 三个子模块分别处理不同领域的数据库操作
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

# ── 模块级日志 ────────────────────────────────────────────────────
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

    通过委托模式将实际逻辑拆分为：
    - _crud (CentralCRUD): 增删改查操作
    - _query (CentralQuery): 复杂查询和导出
    - _backup (CentralBackup): 备份同步
    """

    # ── 数据目录配置（类级共享） ─────────────────────────────────
    _ACTIVE_DIR = project_path("core", "data")      # 活跃库目录
    _BACKUP_DIR = None                               # 备份目录（惰性初始化）

    @classmethod
    def _migrate_old_data(cls):
        """从旧的 core/data/ 迁移数据到 data/

        在项目重构过程中，数据目录可能从 core/data/ 变为 data/。
        此方法负责检测并执行一次性迁移，将旧目录中的数据库文件
        拷贝到新目录。已存在且数据更多的文件不会被覆盖。
        """
        old_dir = project_path("core", "data")
        new_dir = cls._ACTIVE_DIR
        if old_dir == new_dir or not os.path.exists(old_dir):
            return  # 新旧目录相同或旧目录不存在，无需迁移
        import shutil
        import sqlite3 as _sqlite3
        migrated = 0
        try:
            for item in os.listdir(old_dir):
                src = os.path.join(old_dir, item)
                dst = os.path.join(new_dir, item)
                if os.path.isdir(src):
                    # ── 目录级迁移（视频独立库目录） ─────────────
                    src_db = os.path.join(src, f"{item}.db")
                    dst_db = os.path.join(dst, f"{item}.db")
                    should_copy = not os.path.exists(dst)
                    if not should_copy and os.path.exists(src_db) and os.path.exists(dst_db):
                        try:
                            # 比较记录数：旧目录记录数远超新目录（>2倍）则覆盖
                            sc = _sqlite3.connect(src_db).execute("SELECT COUNT(*) FROM monitor_records").fetchone()[0]
                            dc = _sqlite3.connect(dst_db).execute("SELECT COUNT(*) FROM monitor_records").fetchone()[0]
                            if sc > dc * 2:
                                should_copy = True
                        except Exception as e:
                            logger.debug("迁移计数检查失败 %s: %s", item, e)
                    if should_copy:
                        if os.path.exists(dst):
                            try:
                                # 修改文件权限后删除旧目录
                                for f in os.listdir(dst):
                                    if f.endswith(".db") or f.endswith(".db-wal") or f.endswith(".db-shm"):
                                        os.chmod(os.path.join(dst, f), 0o600)
                            except Exception as e:
                                logger.debug("修改权限失败 %s: %s", f, e)
                            try:
                                shutil.rmtree(dst)
                            except PermissionError:
                                logger.warning("迁移跳过 %s: 文件被占用", item)
                                continue  # 文件被占用则跳过
                        shutil.copytree(src, dst)
                        migrated += 1
                else:
                    # ── 文件级迁移 ────────────────────────────────
                    if not os.path.exists(dst):
                        shutil.copy2(src, dst)
                        migrated += 1
            if migrated:
                logger.info("已从 %s 迁移 %d 项到 %s", old_dir, migrated, new_dir)
        except Exception as e:
            logger.warning("迁移旧数据失败: %s", e)

    @classmethod
    def _get_backup_dir(cls) -> str:
        """获取备份目录路径，优先从 config.DATA_DIR 读取

        若配置模块不可用，则回退到活跃目录。

        Returns:
            备份目录的绝对路径
        """
        if cls._BACKUP_DIR is None:
            try:
                from config import DATA_DIR
                cls._BACKUP_DIR = DATA_DIR
            except ImportError:
                cls._BACKUP_DIR = cls._ACTIVE_DIR  # 无法读取配置时回退
        return cls._BACKUP_DIR

    def __init__(self, db_path: str = None):
        """初始化中央总数据库

        创建或打开 bilibili_monitor.db 文件，启用 WAL 模式，
        初始化表结构和索引，创建三个委托子模块。

        Args:
            db_path: 数据库文件路径（None 则使用默认路径 core/data/bilibili_monitor.db）
        """
        if db_path is None:
            os.makedirs(self._ACTIVE_DIR, exist_ok=True)
            db_path = os.path.join(self._ACTIVE_DIR, "bilibili_monitor.db")

        # ── 执行旧数据迁移（在打开数据库之前） ──────────────────
        self._migrate_old_data()

        self.db_path = db_path
        self.data_dir = os.path.dirname(db_path)
        self._lock = threading.RLock()  # 可重入线程锁，保证数据库操作互斥
        # check_same_thread=False：允许跨线程使用同一连接（配合 _lock 保证安全）
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row  # 查询结果以字典式 Row 返回
        self._conn.execute("PRAGMA journal_mode=WAL")       # 启用 WAL 模式
        self._conn.execute("PRAGMA synchronous=NORMAL")     # 平衡性能与安全性
        try:
            self.init_database()
        except Exception:
            self._conn.close()  # 初始化失败则关闭连接
            raise

        # ── 创建委托子模块 ───────────────────────────────────────
        self._crud = CentralCRUD(self)        # CRUD 操作
        self._query = CentralQuery(self)      # 查询操作
        self._backup = CentralBackup(self)    # 备份同步

    def _get_connection(self):
        """返回线程安全的连接上下文管理器

        调用方使用 with self._get_connection() as conn: 获取连接，
        上下文内部自动获取锁并在退出时提交/回滚。

        Returns:
            _ConnectionCtx 透明连接上下文实例
        """
        return _ConnectionCtx(self._conn, self._lock)

    def init_database(self):
        """初始化总数据库表结构

        创建以下核心表及索引（使用 IF NOT EXISTS 避免重复创建）：
        - videos: 视频元数据
        - monitor_records: 监控记录（含外键引用 videos）
        - predictions: 预测记录
        - video_milestones: 里程碑数据
        同时执行 schema 迁移，补全缺失的列。
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # ── videos 表：视频元数据 ────────────────────────────
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
            # ── monitor_records 表：监控记录 ─────────────────────
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
            # ── 索引：唯一索引防重 + 复合索引加速查询 ────────────
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_monitor_bvid_ts
                ON monitor_records(bvid, timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_monitor_bvid_ts_view
                ON monitor_records(bvid, timestamp, view_count)
            """)
            # ── predictions 表：预测记录 ─────────────────────────
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
            # ── video_milestones 表：里程碑 ───────────────────────
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
            # ── 执行 schema 迁移 ─────────────────────────────────
            self._migrate_db(conn)
            conn.commit()

    def _migrate_db(self, conn):
        """总数据库迁移：检查并添加缺少的列

        对 videos、monitor_records、predictions 三张表，
        通过 PRAGMA table_info 检查现有列，使用 ALTER TABLE ADD COLUMN
        补全缺失字段。对表名和列名做正则校验防止 SQL 注入。

        Args:
            conn: 数据库连接
        """
        cursor = conn.cursor()
        # ── 预定义各表需要确保的额外字段 ─────────────────────────
        schema_upgrades = {
            "videos": [
                ("viewers_app", "INTEGER DEFAULT 0"),          # APP 观看人数
                ("viewers_web", "INTEGER DEFAULT 0"),           # 网页观看人数
                ("viewers_total", "INTEGER DEFAULT 0"),         # 总观看人数
                ("like_view_ratio", "REAL DEFAULT 0"),          # 播赞比
                ("owner_name", "TEXT"),                          # UP 主名称
                ("owner_id", "INTEGER"),                         # UP 主 UID
                ("pubdate", "TEXT"),                             # 发布时间
                ("duration", "INTEGER"),                         # 视频时长
                ("pic", "TEXT"),                                 # 封面 URL
            ],
            "monitor_records": [
                ("viewers_app", "INTEGER DEFAULT 0"),
                ("viewers_web", "INTEGER DEFAULT 0"),
                ("viewers_total", "INTEGER DEFAULT 0"),
                ("like_view_ratio", "REAL DEFAULT 0"),
            ],
            "predictions": [
                ("metadata", "TEXT DEFAULT ''"),                 # 额外元数据
                ("predicted_hours", "REAL DEFAULT 0"),           # 预测小时数
                ("current_velocity", "REAL DEFAULT 0"),          # 当前速率
            ],
        }
        for table, columns in schema_upgrades.items():
            # 正则校验表名（仅允许字母数字下划线）
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table):
                continue
            cursor.execute(f"PRAGMA table_info({table})")
            existing = {row["name"] for row in cursor.fetchall()}
            if not existing:
                continue  # 表不存在则跳过
            for col_name, col_def in columns:
                # 正则校验列名
                if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", col_name):
                    continue
                if col_name not in existing:
                    # 校验列定义格式
                    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*(\s+DEFAULT\s+[^\s;]+)?$", col_def):
                        logger.warning(f"迁移跳过: {table}.{col_name} 含不安全的列定义 {col_def}")
                        continue
                    try:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                    except Exception as e:
                        logger.warning(f"迁移失败 {table}.{col_name}: {e}")

    def get_video_db(self, bvid: str) -> VideoDatabase:
        """获取单个视频的独立数据库实例

        创建一个 VideoDatabase 对象，用于对该视频的独立 SQLite 文件
        （data/<BV>/<BV>.db）进行读写操作。

        Args:
            bvid: BV 号

        Returns:
            VideoDatabase 实例
        """
        return VideoDatabase(bvid, self.data_dir)

    def download_cover(self, bvid: str, pic_url: str) -> str:
        """下载视频封面到集中管理的 cover 目录

        优先检查本地是否已有有效封面，若无则通过 HTTP 下载。
        使用模块级共享的 _http_session 复用 TCP 连接。

        Args:
            bvid: BV 号
            pic_url: 封面图片 URL

        Returns:
            封面本地文件路径，下载失败返回空字符串
        """
        try:
            _validate_bvid(bvid)  # 先校验 BV 号合法性
            from utils.cover_manager import save_cover, get_valid_cover
            # 检查本地是否已有有效封面
            local = get_valid_cover(bvid)
            if local is not None:
                return local
            # 通过共享 Session 下载封面
            response = _http_session.get(pic_url, timeout=10)
            if response.status_code == 200:
                path = save_cover(bvid, response.content)
                return path or ""
        except Exception as e:
            logger.warning("下载封面失败 %s: %s", bvid, e)
        return ""

    def wal_checkpoint(self):
        """周期性 WAL checkpoint，控制 WAL 文件大小

        WAL 文件会随写入增长，定期执行 TRUNCATE checkpoint
        将日志清空并截断 WAL 文件到 0 字节。
        """
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as e:
            logger.debug("WAL checkpoint 失败: %s", e)

    def close(self):
        """关闭数据库连接，刷新 WAL

        执行 TRUNCATE checkpoint 将未写入的数据刷盘，
        然后提交并关闭连接。
        """
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.commit()
            self._conn.close()
        except Exception as e:
            logger.warning("关闭数据库失败: %s", e)

    # ════════════════════════════════════════════════════════════════
    # CRUD 委托（将调用转发给 CentralCRUD 子模块）
    # ════════════════════════════════════════════════════════════════

    def get_video(self, bvid: str) -> Optional[VideoInfo]:
        """获取视频信息（详见 CentralCRUD.get_video）"""
        return self._crud.get_video(bvid)

    def add_video(self, video: VideoInfo) -> bool:
        """添加视频信息（详见 CentralCRUD.add_video）"""
        return self._crud.add_video(video)

    def delete_video(self, bvid: str) -> bool:
        """删除视频及关联数据（详见 CentralCRUD.delete_video）"""
        return self._crud.delete_video(bvid)

    def sync_from_video_db(self, bvid: str) -> bool:
        """从视频独立库同步元数据（详见 CentralCRUD.sync_from_video_db）"""
        return self._crud.sync_from_video_db(bvid)

    def sync_video_info(self, bvid: str, video: dict) -> bool:
        """从内存字典同步视频信息（详见 CentralCRUD.sync_video_info）"""
        return self._crud.sync_video_info(bvid, video)

    def sync_monitor_record(self, bvid: str, record: dict) -> bool:
        """同步单条监控记录（详见 CentralCRUD.sync_monitor_record）"""
        return self._crud.sync_monitor_record(bvid, record)

    def sync_all_video_dbs(self) -> Dict[str, bool]:
        """同步所有视频独立库（详见 CentralCRUD.sync_all_video_dbs）"""
        return self._crud.sync_all_video_dbs()

    def add_monitor_record(self, record: MonitorRecord) -> bool:
        """添加监控记录（详见 CentralCRUD.add_monitor_record）"""
        return self._crud.add_monitor_record(record)

    def get_monitor_history(self, bvid: str, limit: int = 0) -> List[Dict]:
        """获取监控历史（详见 CentralCRUD.get_monitor_history）"""
        return self._crud.get_monitor_history(bvid, limit)

    def add_prediction(self, prediction: PredictionRecord) -> bool:
        """添加预测记录（详见 CentralCRUD.add_prediction）"""
        return self._crud.add_prediction(prediction)

    def get_predictions(self, bvid: str = None, algorithm: str = None, limit: int = 100) -> List[Dict]:
        """获取预测记录（详见 CentralCRUD.get_predictions）"""
        return self._crud.get_predictions(bvid, algorithm, limit)

    def upsert_milestone(self, bvid: str, period: str, data: dict) -> bool:
        """新增或更新里程碑（详见 CentralCRUD.upsert_milestone）"""
        return self._crud.upsert_milestone(bvid, period, data)

    def get_milestones(self, bvid: str = None) -> list:
        """查询里程碑（详见 CentralCRUD.get_milestones）"""
        return self._crud.get_milestones(bvid)

    def get_all_milestones_grouped(self) -> dict:
        """获取分组里程碑（详见 CentralCRUD.get_all_milestones_grouped）"""
        return self._crud.get_all_milestones_grouped()

    def delete_milestone(self, bvid: str, period: str) -> bool:
        """删除里程碑（详见 CentralCRUD.delete_milestone）"""
        return self._crud.delete_milestone(bvid, period)

    # ════════════════════════════════════════════════════════════════
    # 查询委托（将调用转发给 CentralQuery 子模块）
    # ════════════════════════════════════════════════════════════════

    def query_monitor_records(self, bvid: str, start_time: str = None, end_time: str = None, limit: int = 1000) -> List[Dict]:
        """按时间范围查询监控记录（详见 CentralQuery.query_monitor_records）"""
        return self._query.query_monitor_records(bvid, start_time, end_time, limit)

    def search_videos(self, keyword: str = "", field: str = "title", limit: int = 50) -> List[Dict]:
        """搜索视频（详见 CentralQuery.search_videos）"""
        return self._query.search_videos(keyword, field, limit)

    def get_video_list(self, sort_by: str = "updated_at", order: str = "DESC", limit: int = 100) -> List[Dict]:
        """获取视频列表（详见 CentralQuery.get_video_list）"""
        return self._query.get_video_list(sort_by, order, limit)

    def get_summary_stats(self) -> Dict:
        """获取汇总统计（详见 CentralQuery.get_summary_stats）"""
        return self._query.get_summary_stats()

    def export_video_to_csv(self, bvid: str, filepath: str = None) -> str:
        """导出视频 CSV（详见 CentralQuery.export_video_to_csv）"""
        return self._query.export_video_to_csv(bvid, filepath)

    # ════════════════════════════════════════════════════════════════
    # 备份同步委托（将调用转发给 CentralBackup 子模块）
    # ════════════════════════════════════════════════════════════════

    def sync_to_central(self) -> dict:
        """全量同步到中央备份库（详见 CentralBackup.sync_to_central）"""
        return self._backup.sync_to_central()

    def sync_per_video_dbs_to_backup(self):
        """文件级备份视频独立库（详见 CentralBackup.sync_per_video_dbs_to_backup）"""
        return self._backup.sync_per_video_dbs_to_backup()

    def check_backup_diffs(self) -> List[Dict]:
        """比较活跃库与备份库差异（详见 CentralBackup.check_backup_diffs）"""
        return self._backup.check_backup_diffs()


# ════════════════════════════════════════════════════════════════════
# 全局单例
# ════════════════════════════════════════════════════════════════════

_db = None  # 全局 Database 实例（惰性初始化）


def get_db():
    """获取全局 Database 单例（惰性初始化）

    首次调用时创建 Database 实例，后续调用返回同一实例。
    确保整个应用程序共享同一个数据库连接。

    Returns:
        Database 单例实例
    """
    global _db
    if _db is None:
        _db = Database()
    return _db
