"""总数据库管理类"""

import sqlite3
import os
import re
import threading
from datetime import datetime
from typing import List, Dict, Optional, Any

from .connection import _ConnectionCtx, _http_session
from .models import _validate_bvid, VideoInfo, MonitorRecord, PredictionRecord
from .video_db import VideoDatabase


class Database:
    """总数据库管理类"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, 'bilibili_monitor.db')

        self.db_path = db_path
        self.data_dir = os.path.dirname(db_path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self.init_database()

    def _get_connection(self):
        """返回线程安全的连接上下文管理器（兼容 with 语法）"""
        return _ConnectionCtx(self._conn, self._lock)

    def init_database(self):
        """初始化数据库表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 视频信息表
            cursor.execute('''
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
            ''')

            # 监控记录表
            cursor.execute('''
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
            ''')
            cursor.execute('''
                CREATE UNIQUE INDEX IF NOT EXISTS idx_monitor_bvid_ts
                ON monitor_records(bvid, timestamp)
            ''')

            # 预测记录表
            cursor.execute('''
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
            ''')

            # 投稿里程碑数据表
            cursor.execute('''
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
            ''')
            cursor.execute(
                'CREATE INDEX IF NOT EXISTS idx_milestones_bvid ON video_milestones(bvid)')
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
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table):
                continue
            cursor.execute(f"PRAGMA table_info({table})")
            existing = {row["name"] for row in cursor.fetchall()}
            if not existing:
                continue
            for col_name, col_def in columns:
                if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', col_name):
                    continue
                if col_name not in existing:
                    try:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                    except Exception:
                        pass

    def get_video_db(self, bvid: str) -> VideoDatabase:
        """获取单个视频的数据库实例"""
        return VideoDatabase(bvid, self.data_dir)

    def sync_from_video_db(self, bvid: str) -> bool:
        """从单个视频数据库同步到总数据库"""
        try:
            video_db = VideoDatabase(bvid, self.data_dir)

            # 获取视频信息
            video_info = video_db.get_video_info()
            if video_info:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT OR REPLACE INTO videos
                        (bvid, title, view_count, like_count, coin_count, share_count,
                         favorite_count, danmaku_count, reply_count, viewers_app,
                         viewers_web, viewers_total, cover_path, like_view_ratio,
                         owner_name, owner_id, pubdate, duration, pic, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        bvid, video_info.get('title', ''), video_info.get('view_count', 0),
                        video_info.get('like_count', 0), video_info.get('coin_count', 0),
                        video_info.get('share_count', 0), video_info.get('favorite_count', 0),
                        video_info.get('danmaku_count', 0), video_info.get('reply_count', 0),
                        video_info.get('viewers_app', 0), video_info.get('viewers_web', 0),
                        video_info.get('viewers_total', 0), video_info.get('cover_path', ''),
                        video_info.get('like_view_ratio', 0), video_info.get('owner_name', ''),
                        video_info.get('owner_id', 0), video_info.get('pubdate', ''),
                        video_info.get('duration', 0), video_info.get('pic', ''), datetime.now()
                    ))
                    conn.commit()

            # 获取所有监控记录并同步（使用 executemany 批量插入）
            records = video_db.get_all_records()
            if records:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    rows = [(
                        bvid, r['timestamp'], r['view_count'],
                        r['like_count'], r['coin_count'], r['share_count'],
                        r['favorite_count'], r['danmaku_count'], r['reply_count'],
                        r['viewers_app'], r['viewers_web'],
                        r['viewers_total'], r['like_view_ratio']
                    ) for r in records]
                    cursor.executemany('''
                        INSERT OR IGNORE INTO monitor_records
                        (bvid, timestamp, view_count, like_count, coin_count, share_count,
                         favorite_count, danmaku_count, reply_count, viewers_app,
                         viewers_web, viewers_total, like_view_ratio)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', rows)
                    conn.commit()

            return True
        except Exception as e:
            print(f"同步数据失败: {e}")
            return False

    def sync_all_video_dbs(self) -> Dict[str, bool]:
        """同步所有视频数据库到总数据库"""
        results = {}
        video_dirs = []

        # 遍历data目录下的所有BV号文件夹
        for item in os.listdir(self.data_dir):
            item_path = os.path.join(self.data_dir, item)
            if os.path.isdir(item_path) and item.startswith('BV'):
                video_dirs.append(item)

        for bvid in video_dirs:
            results[bvid] = self.sync_from_video_db(bvid)

        return results

    def add_video(self, video: VideoInfo) -> bool:
        """添加视频信息"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO videos
                    (bvid, title, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, cover_path, like_view_ratio,
                     owner_name, owner_id, pubdate, duration, pic, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    video.bvid, video.title, video.view_count, video.like_count,
                    video.coin_count, video.share_count, video.favorite_count,
                    video.danmaku_count, video.reply_count, video.viewers_app,
                    video.viewers_web, video.viewers_total, video.cover_path,
                    video.like_view_ratio, video.owner_name, video.owner_id,
                    video.pubdate, video.duration, video.pic, datetime.now()
                ))
                conn.commit()
                return True
        except Exception as e:
            print(f"添加视频失败: {e}")
            return False

    def get_video(self, bvid: str) -> Optional[VideoInfo]:
        """获取视频信息"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM videos WHERE bvid = ?', (bvid,))
                row = cursor.fetchone()
                if row:
                    return VideoInfo(**dict(row))
                return None
        except Exception as e:
            print(f"获取视频失败: {e}")
            return None

    def add_monitor_record(self, record: MonitorRecord) -> bool:
        """添加监控记录"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO monitor_records
                    (bvid, timestamp, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, like_view_ratio)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    record.bvid, record.timestamp, record.view_count, record.like_count,
                    record.coin_count, record.share_count, record.favorite_count,
                    record.danmaku_count, record.reply_count, record.viewers_app,
                    record.viewers_web, record.viewers_total, record.like_view_ratio
                ))
                conn.commit()
                return True
        except Exception as e:
            print(f"添加监控记录失败: {e}")
            return False

    def get_monitor_history(self, bvid: str, limit: int = 0) -> List[Dict]:
        """获取监控历史"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if limit and limit > 0:
                    cursor.execute('''
                        SELECT * FROM monitor_records
                        WHERE bvid = ?
                        ORDER BY timestamp ASC
                        LIMIT ?
                    ''', (bvid, limit))
                else:
                    cursor.execute('''
                        SELECT * FROM monitor_records
                        WHERE bvid = ?
                        ORDER BY timestamp ASC
                    ''', (bvid,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"获取监控历史失败: {e}")
            return []

    def add_prediction(self, prediction: PredictionRecord) -> bool:
        """添加预测记录"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO predictions
                    (bvid, algorithm, algorithm_id, target_threshold, predicted_seconds,
                     predicted_time, confidence, current_views)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    prediction.bvid, prediction.algorithm, prediction.algorithm_id,
                    prediction.target_threshold, prediction.predicted_seconds,
                    prediction.predicted_time, prediction.confidence,
                    prediction.current_views
                ))
                conn.commit()
                return True
        except Exception as e:
            print(f"添加预测记录失败: {e}")
            return False

    def download_cover(self, bvid: str, pic_url: str) -> str:
        """下载视频封面"""
        try:
            _validate_bvid(bvid)
            cover_dir = os.path.join(os.path.dirname(self.db_path), 'cover')
            os.makedirs(cover_dir, exist_ok=True)

            cover_path = os.path.join(cover_dir, f"{bvid}.jpg")

            if os.path.exists(cover_path):
                return cover_path

            response = _http_session.get(pic_url, timeout=10)
            if response.status_code == 200:
                with open(cover_path, 'wb') as f:
                    f.write(response.content)
                return cover_path
        except Exception as e:
            print(f"下载封面失败: {e}")
        return ""

    def export_video_to_csv(self, bvid: str, filepath: str = None) -> str:
        """导出视频数据到CSV"""
        _validate_bvid(bvid)
        import csv

        if filepath is None:
            exports_dir = os.path.join(os.path.dirname(self.db_path), 'exports')
            os.makedirs(exports_dir, exist_ok=True)
            filepath = os.path.join(exports_dir, f"{bvid}.csv")

        try:
            video = self.get_video(bvid)
            history = self.get_monitor_history(bvid)

            with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(['BV号', '标题', 'UP主', '播放量', '点赞数', '投币数',
                                '分享数', '收藏数', '弹幕数', '评论数', 'APP观看人数',
                                '网页观看人数', '总观看人数', '播赞比'])

                if video:
                    writer.writerow([
                        video.bvid, video.title, video.owner_name, video.view_count,
                        video.like_count, video.coin_count, video.share_count,
                        video.favorite_count, video.danmaku_count, video.reply_count,
                        video.viewers_app, video.viewers_web, video.viewers_total,
                        video.like_view_ratio
                    ])

            return filepath
        except Exception as e:
            print(f"导出失败: {e}")
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
                cursor.execute('''
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
                ''', (
                    bvid, period,
                    data.get('view_count', 0),
                    data.get('like_count', None),
                    data.get('coin_count', None),
                    data.get('share_count', None),
                    data.get('favorite_count', None),
                    data.get('danmaku_count', None),
                    data.get('reply_count', None),
                    data.get('note', None),
                    data.get('recorded_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                ))
                conn.commit()
                return True
        except Exception as e:
            print(f"里程碑写入失败: {e}")
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
                    cursor.execute(
                        'SELECT * FROM video_milestones WHERE bvid=? ORDER BY period',
                        (bvid,))
                else:
                    cursor.execute(
                        'SELECT * FROM video_milestones ORDER BY bvid, period')
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"里程碑查询失败: {e}")
            return []

    def get_all_milestones_grouped(self) -> dict:
        """返回以 bvid 为键的里程碑字典，值为 period→row 的子字典。"""
        rows = self.get_milestones()
        result = {}
        for row in rows:
            bv = row['bvid']
            if bv not in result:
                result[bv] = {}
            result[bv][row['period']] = row
        return result

    def delete_milestone(self, bvid: str, period: str) -> bool:
        """删除指定里程碑记录。"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'DELETE FROM video_milestones WHERE bvid=? AND period=?',
                    (bvid, period))
                conn.commit()
                return True
        except Exception as e:
            print(f"里程碑删除失败: {e}")
            return False

    def close(self):
        """关闭数据库连接，刷新 WAL。"""
        try:
            self._conn.commit()
            self._conn.close()
        except Exception as e:
            print(f"关闭数据库失败: {e}")


# 全局数据库实例
db = Database()
