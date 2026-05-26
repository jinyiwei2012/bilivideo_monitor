"""总数据库管理类"""

import sqlite3
import os
import re
import threading
import logging
from dataclasses import fields
from datetime import datetime
from typing import List, Dict, Optional
from utils import project_path

from .connection import _ConnectionCtx, _http_session
from .models import _validate_bvid, VideoInfo, MonitorRecord, PredictionRecord
from .video_db import VideoDatabase

logger = logging.getLogger(__name__)


class Database:
    """总数据库管理类"""

    # 双备份：active_dir = core/data/（活跃写入）, backup_dir = data/（config 定义）
    _ACTIVE_DIR = project_path("core", "data")
    _BACKUP_DIR = None  # 懒加载

    @classmethod
    def _get_backup_dir(cls) -> str:
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

    def _get_connection(self):
        """返回线程安全的连接上下文管理器（兼容 with 语法）"""
        return _ConnectionCtx(self._conn, self._lock)

    def init_database(self):
        """初始化数据库表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 视频信息表
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

            # 监控记录表
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

            # 预测记录表
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

            # 投稿里程碑数据表
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
            # 数据库迁移：检查并添加缺少的列
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
        """获取单个视频的数据库实例"""
        return VideoDatabase(bvid, self.data_dir)

    def sync_from_video_db(self, bvid: str) -> bool:
        """从单个视频数据库同步视频信息到总数据库（仅同步元数据，不包含监控记录）

        优化：优先使用内存数据（sync_video_info），避免新建 DB 连接 + 重复读盘。
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # 视频独立库中的 video_info 行 id=1
                video_db = VideoDatabase(bvid, self.data_dir)
                try:
                    video_info = video_db.get_video_info()
                finally:
                    video_db.close()
                if not video_info:
                    return True
                cursor.execute(
                    """INSERT OR REPLACE INTO videos
                    (bvid, title, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, cover_path, like_view_ratio,
                     owner_name, owner_id, pubdate, duration, pic, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        bvid,
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
            return True
        except Exception as e:
            logger.warning("同步数据失败 %s: %s", bvid, e)
            return False

    def sync_video_info(self, bvid: str, video: dict) -> bool:
        """从内存字典直接同步视频信息到总数据库，避免重复读盘

        Args:
            bvid: BV号
            video: 视频数据字典（key 与 videos 表字段对应）
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT OR REPLACE INTO videos
                    (bvid, title, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, cover_path, like_view_ratio,
                     owner_name, owner_id, pubdate, duration, pic, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        bvid,
                        video.get("title", ""),
                        video.get("view_count", 0),
                        video.get("like_count", 0),
                        video.get("coin_count", 0),
                        video.get("share_count", 0),
                        video.get("favorite_count", 0),
                        video.get("danmaku_count", 0),
                        video.get("reply_count", 0),
                        video.get("viewers_app", 0),
                        video.get("viewers_web", 0),
                        video.get("viewers_total", 0),
                        video.get("cover_path", ""),
                        video.get("like_view_ratio", 0),
                        video.get("author", ""),
                        video.get("owner_id", 0),
                        video.get("pubdate", ""),
                        video.get("duration", 0),
                        video.get("pic", ""),
                        datetime.now(),
                    ),
                )
                conn.commit()
            return True
        except Exception as e:
            logger.debug(f"同步视频信息失败 {bvid}: {e}")
            return False

    def sync_monitor_record(self, bvid: str, record: dict) -> bool:
        """从内存同步单条监控记录到中央数据库（避免全量读取）"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                like_view_ratio = record.get("like_view_ratio", 0)
                if not like_view_ratio:
                    vc = record.get("view_count", 0)
                    lc = record.get("like_count", 0)
                    if vc and lc:
                        like_view_ratio = round(lc / vc, 6)
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO monitor_records
                    (bvid, timestamp, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, like_view_ratio)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        bvid,
                        record.get("timestamp"),
                        record.get("view_count", 0),
                        record.get("like_count", 0),
                        record.get("coin_count", 0),
                        record.get("share_count", 0),
                        record.get("favorite_count", 0),
                        record.get("danmaku_count", 0),
                        record.get("reply_count", 0),
                        record.get("viewers_app", 0),
                        record.get("viewers_web", 0),
                        record.get("viewers_total", 0),
                        like_view_ratio,
                    ),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("同步监控记录失败 %s: %s", bvid, e)
            return False

    def sync_all_video_dbs(self) -> Dict[str, bool]:
        """同步所有视频数据库到总数据库"""
        results = {}
        video_dirs = []

        # 遍历data目录下的所有BV号文件夹
        for item in os.listdir(self.data_dir):
            item_path = os.path.join(self.data_dir, item)
            if os.path.isdir(item_path) and item.startswith("BV"):
                video_dirs.append(item)

        for bvid in video_dirs:
            results[bvid] = self.sync_from_video_db(bvid)

        return results

    def add_video(self, video: VideoInfo) -> bool:
        """添加视频信息"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO videos
                    (bvid, title, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, cover_path, like_view_ratio,
                     owner_name, owner_id, pubdate, duration, pic, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        video.bvid,
                        video.title,
                        video.view_count,
                        video.like_count,
                        video.coin_count,
                        video.share_count,
                        video.favorite_count,
                        video.danmaku_count,
                        video.reply_count,
                        video.viewers_app,
                        video.viewers_web,
                        video.viewers_total,
                        video.cover_path,
                        video.like_view_ratio,
                        video.owner_name,
                        video.owner_id,
                        video.pubdate,
                        video.duration,
                        video.pic,
                        datetime.now(),
                    ),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("添加视频失败 %s: %s", video.bvid, e)
            return False

    def _query_backup(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        """从备份库（data/）执行只读查询，返回行列表"""
        backup_db = os.path.join(self._get_backup_dir(), "bilibili_monitor.db")
        if backup_db == self.db_path or not os.path.exists(backup_db):
            return []
        try:
            conn = sqlite3.connect(f"file:{backup_db}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            conn.close()
            return rows
        except Exception as e:
            logger.debug("备份库查询失败: %s", e)
            return []

    def get_video(self, bvid: str) -> Optional[VideoInfo]:
        """获取视频信息（主库未命中则查备份库）"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM videos WHERE bvid = ?", (bvid,))
                row = cursor.fetchone()
                if row:
                    data = dict(row)
                    valid_fields = {f.name for f in fields(VideoInfo)}
                    filtered = {k: v for k, v in data.items() if k in valid_fields}
                    return VideoInfo(**filtered)
        except Exception as e:
            logger.warning("获取视频失败 %s: %s", bvid, e)

        # 互补：主库未命中，查备份库
        backup_rows = self._query_backup("SELECT * FROM videos WHERE bvid = ?", (bvid,))
        if backup_rows:
            data = dict(backup_rows[0])
            valid_fields = {f.name for f in fields(VideoInfo)}
            filtered = {k: v for k, v in data.items() if k in valid_fields}
            return VideoInfo(**filtered)
        return None

    def add_monitor_record(self, record: MonitorRecord) -> bool:
        """添加监控记录"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO monitor_records
                    (bvid, timestamp, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, like_view_ratio)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        record.bvid,
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
                return True
        except Exception as e:
            logger.warning("添加监控记录失败 %s: %s", record.bvid, e)
            return False

    def get_monitor_history(self, bvid: str, limit: int = 0) -> List[Dict]:
        """获取监控历史（双备份互补合并）"""
        rows = []
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if limit and limit > 0:
                    cursor.execute(
                        """
                        SELECT * FROM monitor_records
                        WHERE bvid = ?
                        ORDER BY timestamp ASC
                        LIMIT ?
                    """,
                        (bvid, limit),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT * FROM monitor_records
                        WHERE bvid = ?
                        ORDER BY timestamp ASC
                    """,
                        (bvid,),
                    )
                rows = [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning("获取监控历史失败 %s: %s", bvid, e)

        # 互补：从备份库补充缺失的记录
        backup_rows = self._query_backup("SELECT * FROM monitor_records WHERE bvid = ? ORDER BY timestamp ASC", (bvid,))
        if backup_rows:
            existing_ts = {r["timestamp"] for r in rows}
            for r in backup_rows:
                rd = dict(r)
                if rd["timestamp"] not in existing_ts:
                    rows.append(rd)
                    existing_ts.add(rd["timestamp"])
            rows.sort(key=lambda x: x["timestamp"])

        if limit > 0 and len(rows) > limit:
            rows = rows[:limit]
        return rows

    def add_prediction(self, prediction: PredictionRecord) -> bool:
        """添加预测记录"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO predictions
                    (bvid, algorithm, algorithm_id, target_threshold, predicted_seconds,
                     predicted_time, confidence, current_views)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        prediction.bvid,
                        prediction.algorithm,
                        prediction.algorithm_id,
                        prediction.target_threshold,
                        prediction.predicted_seconds,
                        prediction.predicted_time,
                        prediction.confidence,
                        prediction.current_views,
                    ),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("添加预测记录失败 %s: %s", prediction.bvid, e)
            return False

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

    def export_video_to_csv(self, bvid: str, filepath: str = None) -> str:
        """导出视频数据到CSV"""
        _validate_bvid(bvid)
        import csv

        if filepath is None:
            exports_dir = os.path.join(os.path.dirname(self.db_path), "exports")
            os.makedirs(exports_dir, exist_ok=True)
            filepath = os.path.join(exports_dir, f"{bvid}.csv")

        try:
            video = self.get_video(bvid)
            self.get_monitor_history(bvid)

            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "BV号",
                        "标题",
                        "UP主",
                        "播放量",
                        "点赞数",
                        "投币数",
                        "分享数",
                        "收藏数",
                        "弹幕数",
                        "评论数",
                        "APP观看人数",
                        "网页观看人数",
                        "总观看人数",
                        "播赞比",
                    ]
                )

                if video:
                    writer.writerow(
                        [
                            video.bvid,
                            video.title,
                            video.owner_name,
                            video.view_count,
                            video.like_count,
                            video.coin_count,
                            video.share_count,
                            video.favorite_count,
                            video.danmaku_count,
                            video.reply_count,
                            video.viewers_app,
                            video.viewers_web,
                            video.viewers_total,
                            video.like_view_ratio,
                        ]
                    )

            return filepath
        except Exception as e:
            logger.warning("导出失败: %s", e)
            return ""

    # ── 里程碑 CRUD ─────────────────────────────────────────────────────────

    MILESTONE_PERIODS = ["1周", "1月", "1年"]

    def upsert_milestone(self, bvid: str, period: str, data: dict) -> bool:
        """新增或更新一条里程碑记录（同一 bvid+period 唯一）。

        Args:
            bvid:   BV号
            period: 周期，取值 "1周" / "1月" / "1年"
            data:   字段字典，必须包含 view_count；其余字段可选
        Returns:
            成功返回 True
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO video_milestones
                        (bvid, period, view_count, like_count, coin_count,
                         share_count, favorite_count, danmaku_count, reply_count,
                         note, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(bvid, period) DO UPDATE SET
                        view_count    = excluded.view_count,
                        like_count    = excluded.like_count,
                        coin_count    = excluded.coin_count,
                        share_count   = excluded.share_count,
                        favorite_count= excluded.favorite_count,
                        danmaku_count = excluded.danmaku_count,
                        reply_count   = excluded.reply_count,
                        note          = excluded.note,
                        recorded_at   = excluded.recorded_at
                """,
                    (
                        bvid,
                        period,
                        data.get("view_count", 0),
                        data.get("like_count", None),
                        data.get("coin_count", None),
                        data.get("share_count", None),
                        data.get("favorite_count", None),
                        data.get("danmaku_count", None),
                        data.get("reply_count", None),
                        data.get("note", None),
                        data.get("recorded_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                    ),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("里程碑写入失败: %s", e)
            return False

    def get_milestones(self, bvid: str = None) -> list:
        """查询里程碑数据。

        Args:
            bvid: 指定 BV 号则只返回该视频，None 返回全部
        Returns:
            dict 列表，字段同 video_milestones 表
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if bvid:
                    cursor.execute("SELECT * FROM video_milestones WHERE bvid=? ORDER BY period", (bvid,))
                else:
                    cursor.execute("SELECT * FROM video_milestones ORDER BY bvid, period")
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning("里程碑查询失败: %s", e)
            return []

    def get_all_milestones_grouped(self) -> dict:
        """返回以 bvid 为键的里程碑字典，值为 period→row 的子字典。"""
        rows = self.get_milestones()
        result = {}
        for row in rows:
            bv = row["bvid"]
            if bv not in result:
                result[bv] = {}
            result[bv][row["period"]] = row
        return result

    def delete_milestone(self, bvid: str, period: str) -> bool:
        """删除指定里程碑记录。"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM video_milestones WHERE bvid=? AND period=?", (bvid, period))
                conn.commit()
                return True
        except Exception as e:
            logger.warning("里程碑删除失败: %s", e)
            return False

    # ── 关闭前同步：活跃库 → 中央库（兜底） ─────────────────────────

    def sync_to_central(self) -> dict:
        central_db = os.path.join(self._get_backup_dir(), "bilibili_monitor.db")
        if central_db == self.db_path or not os.path.exists(central_db):
            logger.info("中央数据库不存在或与活跃库相同，跳过同步")
            return {
                "synced_videos": 0,
                "synced_records": 0,
                "fixed_flaws": 0,
                "synced_predictions": 0,
                "synced_weekly": 0,
                "synced_yearly": 0,
            }

        result = {
            "synced_videos": 0,
            "synced_records": 0,
            "fixed_flaws": 0,
            "synced_predictions": 0,
            "synced_weekly": 0,
            "synced_yearly": 0,
        }
        try:
            central_conn = sqlite3.connect(central_db)
            central_conn.row_factory = sqlite3.Row
            central_cur = central_conn.cursor()
            self._ensure_central_tables(central_cur)
            central_conn.commit()

            active_cur = self._conn.cursor()
            self._sync_videos_to_central(active_cur, central_cur, result)
            active_bvids, central_bvids = self._sync_monitor_records_to_central(active_cur, central_cur, result)
            self._sync_per_video_details(active_bvids, central_bvids, central_cur, result)

            central_conn.commit()
            central_conn.close()
            logger.info(
                "中央库同步完成: %d视频 %d记录 %d瑕疵 | 预测%d 周刊%d 年刊%d",
                result["synced_videos"],
                result["synced_records"],
                result["fixed_flaws"],
                result["synced_predictions"],
                result["synced_weekly"],
                result["synced_yearly"],
            )
        except Exception as e:
            logger.warning("中央库同步失败: %s", e)
        return result

    def _sync_videos_to_central(self, active_cur, central_cur, result):
        active_cur.execute("SELECT * FROM videos")
        for av in (dict(r) for r in active_cur.fetchall()):
            central_cur.execute("SELECT * FROM videos WHERE bvid=?", (av["bvid"],))
            existing = central_cur.fetchone()
            should_update = False
            if not existing:
                should_update = True
                result["synced_videos"] += 1
            else:
                ed = dict(existing)
                for key in ("view_count", "like_count", "coin_count", "share_count"):
                    if not ed.get(key) and av.get(key):
                        should_update = True
                        result["fixed_flaws"] += 1
                        break
            if should_update:
                central_cur.execute(
                    """INSERT OR REPLACE INTO videos
                    (bvid, title, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, cover_path, like_view_ratio,
                     owner_name, owner_id, pubdate, duration, pic, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        av["bvid"],
                        av.get("title", ""),
                        av.get("view_count", 0),
                        av.get("like_count", 0),
                        av.get("coin_count", 0),
                        av.get("share_count", 0),
                        av.get("favorite_count", 0),
                        av.get("danmaku_count", 0),
                        av.get("reply_count", 0),
                        av.get("viewers_app", 0),
                        av.get("viewers_web", 0),
                        av.get("viewers_total", 0),
                        av.get("cover_path", ""),
                        av.get("like_view_ratio", 0),
                        av.get("owner_name", ""),
                        av.get("owner_id", 0),
                        av.get("pubdate", ""),
                        av.get("duration", 0),
                        av.get("pic", ""),
                        datetime.now(),
                    ),
                )

    def _sync_monitor_records_to_central(self, active_cur, central_cur, result):
        central_cur.execute("SELECT DISTINCT bvid FROM monitor_records")
        central_bvids = {r["bvid"] for r in central_cur.fetchall()}
        active_cur.execute("SELECT DISTINCT bvid FROM monitor_records")
        active_bvids = {r["bvid"] for r in active_cur.fetchall()}

        for bvid in active_bvids:
            central_cur.execute("SELECT timestamp FROM monitor_records WHERE bvid=?", (bvid,))
            central_ts = {r["timestamp"] for r in central_cur.fetchall()}
            active_cur.execute("SELECT * FROM monitor_records WHERE bvid=? ORDER BY timestamp ASC", (bvid,))
            for row in active_cur.fetchall():
                rd = dict(row)
                if rd["timestamp"] not in central_ts:
                    lvr = rd.get("like_view_ratio", 0)
                    if not lvr and rd.get("view_count") and rd.get("like_count"):
                        lvr = round(rd["like_count"] / rd["view_count"], 6)
                    central_cur.execute(
                        """INSERT INTO monitor_records
                        (bvid, timestamp, view_count, like_count, coin_count, share_count,
                         favorite_count, danmaku_count, reply_count, viewers_app,
                         viewers_web, viewers_total, like_view_ratio)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            rd["bvid"],
                            rd["timestamp"],
                            rd.get("view_count", 0),
                            rd.get("like_count", 0),
                            rd.get("coin_count", 0),
                            rd.get("share_count", 0),
                            rd.get("favorite_count", 0),
                            rd.get("danmaku_count", 0),
                            rd.get("reply_count", 0),
                            rd.get("viewers_app", 0),
                            rd.get("viewers_web", 0),
                            rd.get("viewers_total", 0),
                            lvr,
                        ),
                    )
                    central_ts.add(rd["timestamp"])
                    result["synced_records"] += 1
        return active_bvids, central_bvids

    def _sync_per_video_details(self, active_bvids, central_bvids, central_cur, result):
        for bvid in active_bvids | central_bvids:
            video_db = self._open_video_db_ro(bvid)
            if video_db is None:
                continue
            try:
                vcur = video_db.cursor()
                v_count = vcur.execute(
                    "SELECT COUNT(DISTINCT COALESCE(algorithm,'') || COALESCE(predicted_time,'')) FROM predictions"
                ).fetchone()[0]
                c_count = central_cur.execute(
                    "SELECT COUNT(DISTINCT COALESCE(algorithm,'') || COALESCE(predicted_time,'')) FROM predictions WHERE bvid=?",
                    (bvid,),
                ).fetchone()[0]
                if v_count != c_count:
                    result["synced_predictions"] += self._sync_video_predictions(central_cur, bvid, vcur)

                v_max = vcur.execute("SELECT MAX(timestamp) FROM weekly_scores").fetchone()[0]
                c_max = central_cur.execute(
                    "SELECT MAX(timestamp) FROM weekly_scores WHERE bvid=?", (bvid,)
                ).fetchone()[0]
                if v_max and (c_max is None or v_max > c_max):
                    result["synced_weekly"] += self._sync_video_weekly_scores(central_cur, bvid, vcur)

                v_max = vcur.execute("SELECT MAX(timestamp) FROM yearly_scores").fetchone()[0]
                c_max = central_cur.execute(
                    "SELECT MAX(timestamp) FROM yearly_scores WHERE bvid=?", (bvid,)
                ).fetchone()[0]
                if v_max and (c_max is None or v_max > c_max):
                    result["synced_yearly"] += self._sync_video_yearly_scores(central_cur, bvid, vcur)
            finally:
                video_db.close()

    def _open_video_db_ro(self, bvid: str) -> Optional[sqlite3.Connection]:
        """以只读方式打开视频独立库，优先活跃目录，回退备份目录"""
        for base in (self.data_dir, self._get_backup_dir()):
            db_path = os.path.join(base, bvid, f"{bvid}.db")
            if os.path.exists(db_path):
                try:
                    uri = f"file:{db_path.replace(chr(92), '/')}?mode=ro"
                    conn = sqlite3.connect(uri, uri=True)
                    conn.row_factory = sqlite3.Row
                    return conn
                except Exception:
                    pass
        return None

    @staticmethod
    def _sync_video_predictions(central_cur, bvid: str, vcur) -> int:
        """同步视频独立库的 predictions 到中央库"""
        try:
            vcur.execute("PRAGMA table_info(predictions)")
            if "algorithm" not in {r["name"] for r in vcur.fetchall()}:
                return 0
        except Exception:
            return 0
        try:
            # GROUP BY 只取每个 (algorithm, predicted_time) 组合的最新一条
            vcur.execute("""
                SELECT algorithm, algorithm_id, target_threshold, predicted_seconds,
                       predicted_time, confidence, current_views, metadata,
                       predicted_hours, current_velocity, is_reached,
                       actual_time, error_rate, MAX(created_at) as created_at
                FROM predictions
                GROUP BY algorithm, predicted_time
            """)
        except Exception:
            return 0
        rows = [dict(r) for r in vcur.fetchall()]
        if not rows:
            return 0

        central_cur.execute("SELECT algorithm, predicted_time FROM predictions WHERE bvid=?", (bvid,))
        existing = {(r["algorithm"], r["predicted_time"]) for r in central_cur.fetchall()}

        batch = []
        for rd in rows:
            key = (rd.get("algorithm", ""), rd.get("predicted_time", ""))
            if key in existing:
                continue
            batch.append(
                (
                    bvid,
                    rd.get("algorithm", ""),
                    rd.get("algorithm_id", ""),
                    rd.get("target_threshold", 0),
                    rd.get("predicted_seconds", 0),
                    rd.get("predicted_time", ""),
                    rd.get("confidence", 0),
                    rd.get("current_views", 0),
                    rd.get("metadata", ""),
                    rd.get("predicted_hours", 0),
                    rd.get("current_velocity", 0),
                    rd.get("is_reached", 0),
                    rd.get("actual_time", ""),
                    rd.get("error_rate", 0),
                    rd.get("created_at"),
                )
            )
            existing.add(key)
        if batch:
            central_cur.executemany(
                """INSERT INTO predictions (bvid, algorithm, algorithm_id,
                target_threshold, predicted_seconds, predicted_time, confidence,
                current_views, metadata, predicted_hours, current_velocity,
                is_reached, actual_time, error_rate, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                batch,
            )
        return len(batch)

    @staticmethod
    def _sync_video_weekly_scores(central_cur, bvid: str, vcur) -> int:
        """同步视频独立库的 weekly_scores 到中央库"""
        try:
            vcur.execute("SELECT timestamp FROM weekly_scores LIMIT 1")
        except Exception:
            return 0
        try:
            vcur.execute("SELECT * FROM weekly_scores ORDER BY timestamp ASC")
        except Exception:
            return 0
        rows = [dict(r) for r in vcur.fetchall()]
        if not rows:
            return 0

        central_cur.execute("SELECT timestamp FROM weekly_scores WHERE bvid=?", (bvid,))
        existing_ts = {r["timestamp"] for r in central_cur.fetchall()}

        batch = []
        for rd in rows:
            if rd.get("timestamp") in existing_ts:
                continue
            batch.append(
                (
                    bvid,
                    rd.get("timestamp"),
                    rd.get("total_score"),
                    rd.get("view_score"),
                    rd.get("interaction_score"),
                    rd.get("favorite_score"),
                    rd.get("coin_score"),
                    rd.get("like_score"),
                    rd.get("correction_a"),
                    rd.get("correction_b"),
                    rd.get("correction_c"),
                    rd.get("correction_d"),
                    rd.get("base_view_score"),
                )
            )
            existing_ts.add(rd["timestamp"])
        if batch:
            central_cur.executemany(
                """INSERT INTO weekly_scores (bvid, timestamp, total_score,
                view_score, interaction_score, favorite_score, coin_score,
                like_score, correction_a, correction_b, correction_c,
                correction_d, base_view_score)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                batch,
            )
        return len(batch)

    @staticmethod
    def _sync_video_yearly_scores(central_cur, bvid: str, vcur) -> int:
        """同步视频独立库的 yearly_scores 到中央库"""
        try:
            vcur.execute("SELECT timestamp FROM yearly_scores LIMIT 1")
        except Exception:
            return 0
        try:
            vcur.execute("SELECT * FROM yearly_scores ORDER BY timestamp ASC")
        except Exception:
            return 0
        rows = [dict(r) for r in vcur.fetchall()]
        if not rows:
            return 0

        central_cur.execute("SELECT timestamp FROM yearly_scores WHERE bvid=?", (bvid,))
        existing_ts = {r["timestamp"] for r in central_cur.fetchall()}

        batch = []
        for rd in rows:
            if rd.get("timestamp") in existing_ts:
                continue
            batch.append(
                (
                    bvid,
                    rd.get("timestamp"),
                    rd.get("total_score"),
                    rd.get("view_score"),
                    rd.get("interaction_score"),
                    rd.get("favorite_score"),
                    rd.get("coin_score"),
                    rd.get("like_score"),
                    rd.get("correction_a"),
                    rd.get("correction_b"),
                    rd.get("correction_c"),
                )
            )
            existing_ts.add(rd["timestamp"])
        if batch:
            central_cur.executemany(
                """INSERT INTO yearly_scores (bvid, timestamp, total_score,
                view_score, interaction_score, favorite_score, coin_score,
                like_score, correction_a, correction_b, correction_c)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                batch,
            )
        return len(batch)

    @staticmethod
    def _ensure_central_tables(cur):
        """确保中央库有完整的表结构（兼容首次同步）"""
        cur.execute("""CREATE TABLE IF NOT EXISTS videos (
            bvid TEXT PRIMARY KEY, title TEXT, view_count INTEGER DEFAULT 0,
            like_count INTEGER DEFAULT 0, coin_count INTEGER DEFAULT 0,
            share_count INTEGER DEFAULT 0, favorite_count INTEGER DEFAULT 0,
            danmaku_count INTEGER DEFAULT 0, reply_count INTEGER DEFAULT 0,
            viewers_app INTEGER DEFAULT 0, viewers_web INTEGER DEFAULT 0,
            viewers_total INTEGER DEFAULT 0, cover_path TEXT,
            like_view_ratio REAL DEFAULT 0, owner_name TEXT, owner_id INTEGER,
            pubdate TEXT, duration INTEGER, pic TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS monitor_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, bvid TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            view_count INTEGER, like_count INTEGER, coin_count INTEGER,
            share_count INTEGER, favorite_count INTEGER, danmaku_count INTEGER,
            reply_count INTEGER, viewers_app INTEGER DEFAULT 0,
            viewers_web INTEGER DEFAULT 0, viewers_total INTEGER DEFAULT 0,
            like_view_ratio REAL DEFAULT 0)""")
        cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_monitor_bvid_ts
            ON monitor_records(bvid, timestamp)""")
        # 独立库详细数据表（含 bvid 用于跨视频关联）
        cur.execute("""CREATE TABLE IF NOT EXISTS weekly_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT, bvid TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_score REAL, view_score REAL, interaction_score REAL,
            favorite_score REAL, coin_score REAL, like_score REAL,
            correction_a REAL, correction_b REAL, correction_c REAL,
            correction_d REAL, base_view_score REAL)""")
        cur.execute("""CREATE INDEX IF NOT EXISTS idx_weekly_bvid
            ON weekly_scores(bvid, timestamp)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS yearly_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT, bvid TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_score REAL, view_score REAL, interaction_score REAL,
            favorite_score REAL, coin_score REAL, like_score REAL,
            correction_a REAL, correction_b REAL, correction_c REAL)""")
        cur.execute("""CREATE INDEX IF NOT EXISTS idx_yearly_bvid
            ON yearly_scores(bvid, timestamp)""")
        # 迁移：确保 predictions 表有完整字段
        Database._migrate_central_predictions(cur)
        # 索引：加速 predictions 按 bvid 查询
        cur.execute("CREATE INDEX IF NOT EXISTS idx_predictions_bvid ON predictions(bvid)")

    @staticmethod
    def _migrate_central_predictions(cur):
        """确保中央库 predictions 表包含独立库的全部字段"""
        cur.execute("PRAGMA table_info(predictions)")
        existing = {r[1] if isinstance(r, (list, tuple)) else r["name"] for r in cur.fetchall()}
        if not existing:
            return
        for col, definition in [
            ("metadata", "TEXT DEFAULT ''"),
            ("predicted_hours", "REAL DEFAULT 0"),
            ("current_velocity", "REAL DEFAULT 0"),
        ]:
            if col not in existing:
                try:
                    cur.execute(f"ALTER TABLE predictions ADD COLUMN {col} {definition}")
                except Exception:
                    pass

    def wal_checkpoint(self):
        """周期性 WAL checkpoint，控制 WAL 文件大小。"""
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as e:
            logger.debug("WAL checkpoint 失败: %s", e)

    def close(self):
        """关闭数据库连接，刷新 WAL。"""
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.commit()
            self._conn.close()
        except Exception as e:
            logger.warning("关闭数据库失败: %s", e)


# 全局数据库实例（惰性初始化）
_db = None


def get_db():
    """获取全局 Database 单例（惰性初始化）"""
    global _db
    if _db is None:
        _db = Database()
    return _db
