"""评论独立数据库 —— 评论抓取专用的 SQLite 文件（与视频库 / 中央库完全分离）。

设计要点（契约见 docs/bilibili_api_contract.md §8）：

- **独立文件**：``data/comments/comments.db``，不与 ``data/<BV>/<BV>.db``、
  ``data/bilibili_monitor.db`` 混用；不挂镜像连接（评论量大且可重新抓取）。
- **四张表**：``comment_tasks``（抓取任务）／``comments``（顶层评论与楼中楼统一存放）／
  ``comment_users``（用户去重）／``comment_pages``（每页游标，便于审计与断点续抓）。
- **尽量保留原始数据**：``comments.raw_json``、``comment_users.member_json`` 保存接口原文，
  规范化列只是便于查询的投影 —— 字段随版本变动时不会丢信息。
- **去重与增量**：``comments`` 以 ``rpid`` 唯一；重复抓取时更新点赞/回复数并累加 ``seen_count``，
  可据此观察评论热度增长。
"""

import json
import logging
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from utils import now_ts, project_path

from .connection import _ConnectionCtx

logger = logging.getLogger(__name__)

# comments 表列顺序（INSERT 与查询共用，单点维护）
_COMMENT_COLUMNS: List[str] = [
    "rpid",
    "rpid_str",
    "bvid",
    "aid",
    "oid",
    "type",
    "is_sub",
    "root",
    "parent",
    "dialog",
    "up_top",
    "message",
    "emote_json",
    "jump_url",
    "pictures_json",
    "content_json",
    "like_count",
    "rcount",
    "ctime",
    "mid",
    "uname",
    "sex",
    "sign",
    "level",
    "vip_json",
    "avatar",
    "medal_json",
    "official_json",
    "member_json",
    "location",
    "time_desc",
    "reply_control_json",
    "up_liked",
    "up_replied",
    "up_action_json",
    "invisible",
    "folded",
    "sort_mode",
    "task_id",
    "first_seen_at",
    "last_seen_at",
    "seen_count",
    "raw_json",
]

_USER_COLUMNS: List[str] = [
    "mid",
    "uname",
    "sex",
    "sign",
    "level",
    "vip_json",
    "avatar",
    "medal_json",
    "official_json",
    "member_json",
    "comment_count",
    "first_seen_at",
    "last_seen_at",
]

# 重复抓取时**需要刷新**的列（热度会随时间增长），其余列保持首次抓取的原样
_COMMENT_REFRESH_ON_CONFLICT = ("like_count", "rcount", "up_liked", "up_replied", "last_seen_at")

# 整数列（缺值时填 0；`seen_count` 例外，缺值填 1 —— 首见即计一次）
_COMMENT_INT_COLUMNS = frozenset(
    {
        "rpid",
        "aid",
        "oid",
        "type",
        "is_sub",
        "root",
        "parent",
        "dialog",
        "up_top",
        "like_count",
        "rcount",
        "ctime",
        "mid",
        "level",
        "up_liked",
        "up_replied",
        "invisible",
        "folded",
        "sort_mode",
        "task_id",
        "first_seen_at",
        "last_seen_at",
        "seen_count",
    }
)
_USER_INT_COLUMNS = frozenset({"mid", "level", "comment_count"})

SCHEMA_STATEMENTS: List[tuple[str, bool]] = [
    (
        """
        CREATE TABLE IF NOT EXISTS comment_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bvid TEXT DEFAULT '',
            aid INTEGER DEFAULT 0,
            mode INTEGER DEFAULT 3,
            status TEXT DEFAULT 'running',
            params_json TEXT DEFAULT '',
            started_at INTEGER DEFAULT 0,
            finished_at INTEGER DEFAULT 0,
            pages INTEGER DEFAULT 0,
            top_count INTEGER DEFAULT 0,
            sub_count INTEGER DEFAULT 0,
            total_count INTEGER DEFAULT 0,
            error TEXT DEFAULT ''
        )
        """,
        False,
    ),
    (
        """
        CREATE TABLE IF NOT EXISTS comments (
            rpid INTEGER PRIMARY KEY,
            rpid_str TEXT DEFAULT '',
            bvid TEXT DEFAULT '',
            aid INTEGER DEFAULT 0,
            oid INTEGER DEFAULT 0,
            type INTEGER DEFAULT 1,
            is_sub INTEGER DEFAULT 0,
            root INTEGER DEFAULT 0,
            parent INTEGER DEFAULT 0,
            dialog INTEGER DEFAULT 0,
            up_top INTEGER DEFAULT 0,
            message TEXT DEFAULT '',
            emote_json TEXT DEFAULT '',
            jump_url TEXT DEFAULT '',
            pictures_json TEXT DEFAULT '',
            content_json TEXT DEFAULT '',
            like_count INTEGER DEFAULT 0,
            rcount INTEGER DEFAULT 0,
            ctime INTEGER DEFAULT 0,
            mid INTEGER DEFAULT 0,
            uname TEXT DEFAULT '',
            sex TEXT DEFAULT '',
            sign TEXT DEFAULT '',
            level INTEGER DEFAULT 0,
            vip_json TEXT DEFAULT '',
            avatar TEXT DEFAULT '',
            medal_json TEXT DEFAULT '',
            official_json TEXT DEFAULT '',
            member_json TEXT DEFAULT '',
            location TEXT DEFAULT '',
            time_desc TEXT DEFAULT '',
            reply_control_json TEXT DEFAULT '',
            up_liked INTEGER DEFAULT 0,
            up_replied INTEGER DEFAULT 0,
            up_action_json TEXT DEFAULT '',
            invisible INTEGER DEFAULT 0,
            folded INTEGER DEFAULT 0,
            sort_mode INTEGER DEFAULT 0,
            task_id INTEGER DEFAULT 0,
            first_seen_at INTEGER DEFAULT 0,
            last_seen_at INTEGER DEFAULT 0,
            seen_count INTEGER DEFAULT 1,
            raw_json TEXT DEFAULT ''
        )
        """,
        False,
    ),
    (
        """
        CREATE TABLE IF NOT EXISTS comment_users (
            mid INTEGER PRIMARY KEY,
            uname TEXT DEFAULT '',
            sex TEXT DEFAULT '',
            sign TEXT DEFAULT '',
            level INTEGER DEFAULT 0,
            vip_json TEXT DEFAULT '',
            avatar TEXT DEFAULT '',
            medal_json TEXT DEFAULT '',
            official_json TEXT DEFAULT '',
            member_json TEXT DEFAULT '',
            comment_count INTEGER DEFAULT 1,
            first_seen_at INTEGER DEFAULT 0,
            last_seen_at INTEGER DEFAULT 0
        )
        """,
        False,
    ),
    (
        """
        CREATE TABLE IF NOT EXISTS comment_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER DEFAULT 0,
            page_index INTEGER DEFAULT 0,
            mode INTEGER DEFAULT 0,
            is_end INTEGER DEFAULT 0,
            all_count INTEGER DEFAULT 0,
            next_offset TEXT DEFAULT '',
            cursor_json TEXT DEFAULT '',
            created_at INTEGER DEFAULT 0
        )
        """,
        False,
    ),
    ("CREATE INDEX IF NOT EXISTS idx_comments_bvid ON comments(bvid)", True),
    ("CREATE INDEX IF NOT EXISTS idx_comments_root ON comments(root)", True),
    ("CREATE INDEX IF NOT EXISTS idx_comments_mid ON comments(mid)", True),
    ("CREATE INDEX IF NOT EXISTS idx_comments_ctime ON comments(ctime)", True),
    ("CREATE INDEX IF NOT EXISTS idx_comments_task ON comments(task_id)", True),
    ("CREATE INDEX IF NOT EXISTS idx_tasks_bvid ON comment_tasks(bvid)", True),
    ("CREATE UNIQUE INDEX IF NOT EXISTS uq_pages_task_page ON comment_pages(task_id, page_index)", True),
]


def _json(value: Any) -> str:
    """把任意值序列化为 JSON 文本（失败返回空串，绝不抛错）。"""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return ""


class CommentDatabase:
    """评论抓取独立库（线程安全，WAL 模式）。"""

    def __init__(self, base_dir: Optional[str] = None) -> None:
        """初始化独立评论库。

        Args:
            base_dir: 存放目录，默认 ``data/comments/``
        """
        if base_dir is None:
            base_dir = project_path("data", "comments")
        os.makedirs(base_dir, exist_ok=True)
        self.base_dir = base_dir
        self.db_path = os.path.join(base_dir, "comments.db")
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        try:
            self._init_db()
        except Exception:
            self._conn.close()
            raise

    # ── 基础设施 ────────────────────────────────────────
    def _get_connection(self) -> _ConnectionCtx:
        """返回线程安全连接上下文（兼容 ``with`` 语法）。"""
        return _ConnectionCtx(self._conn, self._lock)

    def _init_db(self) -> None:
        """建表与建索引（tolerant 项失败仅记 debug）。"""
        with self._get_connection() as conn:
            for sql, tolerant in SCHEMA_STATEMENTS:
                try:
                    conn.execute(sql)
                except sqlite3.Error as e:
                    if tolerant:
                        logger.debug("评论库可选 schema 跳过: %s", e)
                    else:
                        raise
        logger.info("评论独立库就绪: %s", self.db_path)

    def close(self) -> None:
        """关闭连接（应用退出时调用）。"""
        try:
            self._conn.close()
        except Exception as e:
            logger.debug("关闭评论库失败: %s", e)

    # ── 任务 ────────────────────────────────────────────
    def create_task(self, bvid: str, aid: int, mode: int, params: Optional[Dict[str, Any]] = None) -> int:
        """新建抓取任务，返回 task_id。"""
        with self._get_connection() as conn:
            cur = conn.execute(
                """INSERT INTO comment_tasks (bvid, aid, mode, status, params_json, started_at)
                   VALUES (?, ?, ?, 'running', ?, ?)""",
                (bvid, int(aid), int(mode), _json(params), now_ts()),
            )
            return int(cur.lastrowid or 0)

    def finish_task(
        self,
        task_id: int,
        *,
        status: str,
        pages: int = 0,
        top_count: int = 0,
        sub_count: int = 0,
        total_count: int = 0,
        error: str = "",
    ) -> None:
        """结束任务并写入统计与错误（error 截断到 500 字符防止异常文本膨胀）。"""
        with self._get_connection() as conn:
            conn.execute(
                """UPDATE comment_tasks
                   SET status=?, finished_at=?, pages=?, top_count=?, sub_count=?, total_count=?, error=?
                   WHERE id=?""",
                (
                    status,
                    now_ts(),
                    int(pages),
                    int(top_count),
                    int(sub_count),
                    int(total_count),
                    error[:500],
                    int(task_id),
                ),
            )

    def list_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        """按开始时间倒序列出抓取任务。"""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM comment_tasks ORDER BY started_at DESC, id DESC LIMIT ?", (int(limit),)
            ).fetchall()
            return [dict(r) for r in rows]

    def task_stats(self, task_id: int) -> Dict[str, Any]:
        """返回任务的评论分项统计（顶层 / 楼中楼 / 用户数）。"""
        with self._get_connection() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN is_sub=0 THEN 1 ELSE 0 END) AS top_count,
                          SUM(CASE WHEN is_sub=1 THEN 1 ELSE 0 END) AS sub_count,
                          COUNT(DISTINCT mid) AS user_count
                   FROM comments WHERE task_id=?""",
                (int(task_id),),
            ).fetchone()
        return dict(row) if row is not None else {}

    # ── 分页游标 ────────────────────────────────────────
    def save_page(
        self,
        task_id: int,
        page_index: int,
        mode: int,
        is_end: bool,
        all_count: int,
        cursor: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录一页的游标信息（审计 / 断点续抓用）。"""
        cursor = cursor or {}
        next_offset = ""
        pagination_reply = cursor.get("pagination_reply") or {}
        if isinstance(pagination_reply, dict):
            next_offset = str(pagination_reply.get("next_offset", "") or "")
        with self._get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO comment_pages
                   (task_id, page_index, mode, is_end, all_count, next_offset, cursor_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(task_id),
                    int(page_index),
                    int(mode),
                    1 if is_end else 0,
                    int(all_count),
                    next_offset,
                    _json(cursor),
                    now_ts(),
                ),
            )

    # ── 评论写入 ────────────────────────────────────────
    def save_comments(self, rows: List[Dict[str, Any]]) -> int:
        """批量 upsert 评论（返回写入条数）。

        冲突（同 rpid）时只刷新热度相关列并累加 ``seen_count``，其余列保留首次抓取值。
        """
        if not rows:
            return 0
        placeholders = ", ".join("?" for _ in _COMMENT_COLUMNS)
        updates = ", ".join(f"{c}=excluded.{c}" for c in _COMMENT_REFRESH_ON_CONFLICT)
        sql = (
            f"INSERT INTO comments ({', '.join(_COMMENT_COLUMNS)}) VALUES ({placeholders}) "
            f"ON CONFLICT(rpid) DO UPDATE SET {updates}, seen_count=comments.seen_count+1"
        )
        written = 0
        with self._get_connection() as conn:
            cur = conn.cursor()
            for row in rows:
                try:
                    cur.execute(sql, self._comment_values(row))
                    written += cur.rowcount
                except sqlite3.Error as e:
                    logger.debug("写入评论失败 rpid=%s: %s", row.get("rpid"), e)
        return written

    @staticmethod
    def _user_values(row: Dict[str, Any]) -> tuple[Any, ...]:
        """按 ``_USER_COLUMNS`` 顺序取值（缺列填类型安全默认值）。"""
        values = []
        for col in _USER_COLUMNS:
            if col in row:
                values.append(row[col])
            elif col == "comment_count":
                values.append(1)
            else:
                values.append(0 if col in _USER_INT_COLUMNS else "")
        return tuple(values)

    @staticmethod
    def _comment_values(row: Dict[str, Any]) -> tuple[Any, ...]:
        """按 ``_COMMENT_COLUMNS`` 顺序取值（缺列填类型安全默认值，保证列数与占位符一致）。"""
        values = []
        for col in _COMMENT_COLUMNS:
            if col in row:
                values.append(row[col])
            elif col == "seen_count":
                values.append(1)  # 首见即计一次；命中 rpid 冲突时由 SQL 累加
            else:
                values.append(0 if col in _COMMENT_INT_COLUMNS else "")
        return tuple(values)

    # ── 用户写入 ────────────────────────────────────────
    def save_users(self, rows: List[Dict[str, Any]]) -> int:
        """批量 upsert 用户并累加其评论数。"""
        if not rows:
            return 0
        placeholders = ", ".join("?" for _ in _USER_COLUMNS)
        sql = (
            f"INSERT INTO comment_users ({', '.join(_USER_COLUMNS)}) VALUES ({placeholders}) "
            "ON CONFLICT(mid) DO UPDATE SET uname=excluded.uname, level=excluded.level, "
            "avatar=excluded.avatar, medal_json=excluded.medal_json, official_json=excluded.official_json, "
            "member_json=excluded.member_json, last_seen_at=excluded.last_seen_at, "
            "comment_count=comment_users.comment_count+1"
        )
        written = 0
        with self._get_connection() as conn:
            cur = conn.cursor()
            for row in rows:
                try:
                    cur.execute(sql, self._user_values(row))
                    written += cur.rowcount
                except sqlite3.Error as e:
                    logger.debug("写入用户失败 mid=%s: %s", row.get("mid"), e)
        return written

    # ── 查询 ────────────────────────────────────────────
    def count_comments(self, bvid: Optional[str] = None, only_sub: Optional[bool] = None) -> int:
        """统计评论条数（可按视频 / 是否楼中楼过滤）。"""
        where, params = self._where(bvid, only_sub)
        with self._get_connection() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS n FROM comments{where}", params).fetchone()
        return int(row["n"]) if row is not None else 0

    def get_comments(
        self,
        bvid: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
        only_sub: Optional[bool] = None,
        order: str = "like",
    ) -> List[Dict[str, Any]]:
        """读取评论列表（order: like / ctime）。"""
        where, params = self._where(bvid, only_sub)
        order_col = "ctime" if order == "ctime" else "like_count"
        sql = f"SELECT * FROM comments{where} ORDER BY {order_col} DESC LIMIT ? OFFSET ?"
        with self._get_connection() as conn:
            rows = conn.execute(sql, (*params, int(limit), int(offset))).fetchall()
            return [dict(r) for r in rows]

    def get_user_stats(self, bvid: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """按评论数倒序返回活跃用户（可按视频限定）。"""
        if bvid:
            sql = """SELECT u.*, COUNT(c.rpid) AS comment_count_in_video
                   FROM comment_users u JOIN comments c ON c.mid = u.mid
                   WHERE c.bvid = ? GROUP BY u.mid ORDER BY comment_count_in_video DESC LIMIT ?"""
            params: tuple[Any, ...] = (bvid, int(limit))
        else:
            sql = "SELECT * FROM comment_users ORDER BY comment_count DESC LIMIT ?"
            params = (int(limit),)
        with self._get_connection() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def summary(self, bvid: Optional[str] = None) -> Dict[str, Any]:
        """汇总统计：条数、楼中楼数、用户数、IP 属地分布、时间范围。"""
        where, params = self._where(bvid, None)
        with self._get_connection() as conn:
            base = conn.execute(
                f"""SELECT COUNT(*) AS total,
                           SUM(CASE WHEN is_sub=1 THEN 1 ELSE 0 END) AS sub_count,
                           COUNT(DISTINCT mid) AS user_count,
                           MIN(ctime) AS first_ctime,
                           MAX(ctime) AS last_ctime
                    FROM comments{where}""",
                params,
            ).fetchone()
            locations = conn.execute(
                f"""SELECT location, COUNT(*) AS n FROM comments{where}
                    {'AND' if where else 'WHERE'} location <> '' GROUP BY location ORDER BY n DESC LIMIT 10""",
                params,
            ).fetchall()
        result = dict(base) if base is not None else {}
        result["locations"] = [dict(r) for r in locations]
        return result

    @staticmethod
    def _where(bvid: Optional[str], only_sub: Optional[bool]) -> tuple[str, tuple[Any, ...]]:
        """构造 WHERE 子句（参数化，杜绝字符串拼接注入）。"""
        clauses: List[str] = []
        params: List[Any] = []
        if bvid:
            clauses.append("bvid = ?")
            params.append(bvid)
        if only_sub is not None:
            clauses.append("is_sub = ?")
            params.append(1 if only_sub else 0)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, tuple(params)
