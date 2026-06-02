"""
UP 主数据库管理模块 (UpDatabase)
=================================

本模块管理 UP 主（视频创作者）的信息存储和历史趋势数据。

数据库设计：
  使用中央数据库 data/bilibili_monitor.db 中的两张表：

  1. up_info 表 — UP 主当前信息快照
     - uid (PRIMARY KEY): UP 主唯一 ID
     - name: UP 主名称
     - face: 头像 URL
     - sign: 个性签名
     - level: 用户等级
     - follower_count: 粉丝数
     - video_count: 投稿视频数
     - total_views: 总播放量（汇总）
     - total_likes: 总点赞数（汇总）
     - is_tracking: 是否正在追踪 (0/1)
     - created_at / updated_at: 创建/更新时间

  2. up_history 表 — UP 主历史趋势数据
     - id (PRIMARY KEY AUTOINCREMENT): 记录 ID
     - uid: UP 主 ID（索引列，加速按 UID 查询）
     - timestamp: 记录时间
     - follower_count: 当时粉丝数
     - video_count: 当时投稿数
     - total_views: 当时总播放量
"""
import sqlite3
import os
from typing import List, Dict, Optional
from utils import project_path

_DATA_DIR = project_path("data")


class UpDatabase:
    """UP 主数据库管理类

    封装对 up_info 和 up_history 两张表的 CRUD 操作。
    使用 UPSERT 语法确保 UP 主信息无重复。

    使用示例:
      db = UpDatabase()
      db.upsert_up({"uid": 123456, "name": "某某UP主", ...})
      db.add_history(123456, follower_count=10000, video_count=50, total_views=500000)
    """

    def __init__(self):
        """初始化数据库连接

        确保 data 目录存在，创建所需的表结构和索引。
        """
        os.makedirs(_DATA_DIR, exist_ok=True)
        self._db_path = os.path.join(_DATA_DIR, "bilibili_monitor.db")
        self._init_tables()

    def _get_conn(self):
        """获取数据库连接

        每次操作创建独立的连接，避免跨线程共享连接导致的问题。
        SQLite 的简单连接开销很小，适合多线程场景。

        Returns:
            sqlite3.Connection 对象
        """
        return sqlite3.connect(self._db_path)

    def _init_tables(self):
        """初始化 UP 主信息表和趋势历史表

        创建以下对象：
          1. up_info 表（UP 主基本信息快照，uid 为主键）
          2. up_history 表（历史趋势记录，带自增 ID）
          3. idx_up_history_uid 索引（加速按 UID 查询历史记录）
        """
        conn = self._get_conn()
        try:
            c = conn.cursor()
            # UP 主信息表（每个 UP 主一条记录，通过 UPSERT 更新）
            c.execute("""
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
            """)
            # UP 主历史趋势表（每次采集追加一条记录）
            c.execute("""
                CREATE TABLE IF NOT EXISTS up_history (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid           INTEGER NOT NULL,
                    timestamp     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                    follower_count INTEGER DEFAULT 0,
                    video_count   INTEGER DEFAULT 0,
                    total_views   INTEGER DEFAULT 0
                )
            """)
            # 为 up_history 表的 uid 列创建索引，加速按 UP 主查询历史趋势
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_up_history_uid
                ON up_history(uid)
            """)
            conn.commit()
        finally:
            conn.close()

    def upsert_up(self, info: Dict) -> bool:
        """插入或更新 UP 主信息

        使用 SQLite UPSERT (ON CONFLICT DO UPDATE) 语法：
        - uid 不存在：插入新记录
        - uid 已存在：更新除 uid 和 created_at 外的所有字段，自动刷新 updated_at

        Args:
            info: 包含 uid, name, face, sign, level, follower_count,
                  video_count, total_views, total_likes 的字典

        Returns:
            True=操作成功, False=操作失败
        """
        conn = self._get_conn()
        try:
            c = conn.cursor()
            # 使用 UPSERT 语法一次性完成插入或更新
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
        """添加一条 UP 主历史记录点

        每次定时采集 UP 主数据时调用，记录当时的关键指标。
        时间戳由数据库自动生成。

        Args:
            uid: UP 主 UID
            follower_count: 当前粉丝数
            video_count: 当前投稿数
            total_views: 当前总播放量

        Returns:
            True=插入成功, False=操作失败
        """
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
        """查询单个 UP 主的最新信息

        Args:
            uid: UP 主 UID

        Returns:
            包含所有列的 UP 主信息字典，不存在返回 None
        """
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
        """获取所有 UP 主列表

        Args:
            only_tracking: True=仅返回正在追踪的 UP 主，False=返回全部

        Returns:
            UP 主信息字典列表，按更新时间降序排列
        """
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
        """获取 UP 主历史趋势数据（按时间倒序）

        Args:
            uid: UP 主 UID
            limit: 返回的最大记录数

        Returns:
            历史记录列表，按时间戳降序排列
        """
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
        """获取 UP 主在监控数据库中的视频列表（从 videos 表查询）

        Args:
            uid: UP 主 UID

        Returns:
            视频信息列表（含 bvid, title, view_count 等），按播放量降序排列
        """
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
        """设置是否追踪该 UP 主

        Args:
            uid: UP 主 UID
            tracking: True=开始追踪, False=停止追踪

        Returns:
            True=操作成功, False=操作失败
        """
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
        """删除 UP 主数据（同时清理信息表和历史表）

        此操作不可逆，会同时删除 up_info 和 up_history 中与该 UID 相关的记录。

        Args:
            uid: UP 主 UID

        Returns:
            True=操作成功, False=操作失败
        """
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
