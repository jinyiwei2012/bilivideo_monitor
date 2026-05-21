"""
UP主数据库管理模块 — 管理UP主信息与历史趋势数据
"""

import sqlite3
import os
from typing import List, Dict, Optional
from utils import project_path

_DATA_DIR = project_path("data")


class UpDatabase:
    """UP主数据库管理类

    使用中央数据库 data/bilibili_monitor.db 中的 up_info 和 up_history 表
    """

    def __init__(self):
        os.makedirs(_DATA_DIR, exist_ok=True)
        self._db_path = os.path.join(_DATA_DIR, "bilibili_monitor.db")
        self._init_tables()

    def _get_conn(self):
        return sqlite3.connect(self._db_path)

    def _init_tables(self):
        conn = self._get_conn()
        try:
            c = conn.cursor()
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS up_info (
                    uid           INTEGER PRIMARY KEY,
                    name          TEXT NOT NULL DEFAULT '',
                    face          TEXT DEFAULT '',
                    sign          TEXT DEFAULT '',
                    level         INTEGER DEFAULT 0,
                    follower_count INTEGER DEFAULT 0,
                    video_count   INTEGER DEFAULT 0,
                    total_views   INTEGER DEFAULT 0,
                    total_likes   INTEGER DEFAULT 0,
                    is_tracking   INTEGER DEFAULT 1,
                    created_at    TEXT DEFAULT (datetime('now','localtime')),
                    updated_at    TEXT DEFAULT (datetime('now','localtime'))
                )
            """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS up_history (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid           INTEGER NOT NULL,
                    timestamp     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                    follower_count INTEGER DEFAULT 0,
                    video_count   INTEGER DEFAULT 0,
                    total_views   INTEGER DEFAULT 0
                )
            """
            )
            c.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_up_history_uid
                ON up_history(uid)
            """
            )
            conn.commit()
        finally:
            conn.close()

    def upsert_up(self, info: Dict) -> bool:
        """插入或更新UP主信息

        Args:
            info: 包含 uid, name, face, sign, level, follower_count,
                  video_count, total_views, total_likes
        """
        conn = self._get_conn()
        try:
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO up_info (uid, name, face, sign, level,
                                     follower_count, video_count,
                                     total_views, total_likes)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(uid) DO UPDATE SET
                    name=excluded.name,
                    face=excluded.face,
                    sign=excluded.sign,
                    level=excluded.level,
                    follower_count=excluded.follower_count,
                    video_count=excluded.video_count,
                    total_views=excluded.total_views,
                    total_likes=excluded.total_likes,
                    updated_at=datetime('now','localtime')
            """,
                (
                    info.get("uid", 0),
                    info.get("name", ""),
                    info.get("face", ""),
                    info.get("sign", ""),
                    info.get("level", 0),
                    info.get("follower_count", 0),
                    info.get("video_count", 0),
                    info.get("total_views", 0),
                    info.get("total_likes", 0),
                ),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def add_history(self, uid: int, follower_count: int = 0, video_count: int = 0, total_views: int = 0) -> bool:
        """添加UP主历史记录点"""
        conn = self._get_conn()
        try:
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO up_history (uid, follower_count, video_count, total_views)
                VALUES (?,?,?,?)
            """,
                (uid, follower_count, video_count, total_views),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def get_up(self, uid: int) -> Optional[Dict]:
        """查询单个UP主信息"""
        conn = self._get_conn()
        try:
            c = conn.cursor()
            c.execute("SELECT * FROM up_info WHERE uid=?", (uid,))
            row = c.fetchone()
            if row:
                columns = [d[0] for d in c.description]
                return dict(zip(columns, row))
            return None
        finally:
            conn.close()

    def get_all_ups(self, only_tracking: bool = True) -> List[Dict]:
        """获取所有UP主列表"""
        conn = self._get_conn()
        try:
            c = conn.cursor()
            if only_tracking:
                c.execute("SELECT * FROM up_info WHERE is_tracking=1 ORDER BY updated_at DESC")
            else:
                c.execute("SELECT * FROM up_info ORDER BY updated_at DESC")
            rows = c.fetchall()
            columns = [d[0] for d in c.description]
            return [dict(zip(columns, r)) for r in rows]
        finally:
            conn.close()

    def get_history(self, uid: int, limit: int = 100) -> List[Dict]:
        """获取UP主历史趋势"""
        conn = self._get_conn()
        try:
            c = conn.cursor()
            c.execute(
                """
                SELECT * FROM up_history
                WHERE uid=?
                ORDER BY timestamp DESC
                LIMIT ?
            """,
                (uid, limit),
            )
            rows = c.fetchall()
            columns = [d[0] for d in c.description]
            return [dict(zip(columns, r)) for r in rows]
        finally:
            conn.close()

    def get_up_videos(self, uid: int) -> List[Dict]:
        """获取UP主在监控数据库中的视频列表"""
        conn = self._get_conn()
        try:
            c = conn.cursor()
            c.execute(
                """
                SELECT bvid, title, view_count, like_count, coin_count,
                       favorite_count, danmaku_count, reply_count
                FROM videos
                WHERE owner_id=?
                ORDER BY view_count DESC
            """,
                (uid,),
            )
            rows = c.fetchall()
            columns = [d[0] for d in c.description]
            return [dict(zip(columns, r)) for r in rows]
        finally:
            conn.close()

    def set_tracking(self, uid: int, tracking: bool) -> bool:
        """设置是否追踪该UP主"""
        conn = self._get_conn()
        try:
            c = conn.cursor()
            c.execute(
                "UPDATE up_info SET is_tracking=?, updated_at=datetime('now','localtime') WHERE uid=?",
                (1 if tracking else 0, uid),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def delete_up(self, uid: int) -> bool:
        """删除UP主数据"""
        conn = self._get_conn()
        try:
            c = conn.cursor()
            c.execute("DELETE FROM up_info WHERE uid=?", (uid,))
            c.execute("DELETE FROM up_history WHERE uid=?", (uid,))
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()
