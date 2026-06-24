"""弹幕记录 Mixin — 提供 danmaku_records 表的所有操作方法。

作为 VideoDatabase 的 Mixin 类使用，不独立实例化。
"""
import logging
import sqlite3
from typing import List, Dict

logger = logging.getLogger(__name__)


class _DanmakuMixin:
    """弹幕记录表操作 Mixin — 需 mixin 到 VideoDatabase 类上。"""

    # ── 迁移 ────────────────────────────────────

    def _migrate_danmaku_dedup(self, conn):
        """v1→v2 迁移：去重弹幕记录并添加 UNIQUE 约束。"""
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='danmaku_records'"
            )
            if not cursor.fetchone():
                return
            cursor.execute("""
                DELETE FROM danmaku_records
                WHERE id NOT IN (
                    SELECT MIN(id) FROM danmaku_records
                    WHERE bvid = ?
                    GROUP BY bvid, oid, segment_index, content, video_ts, uid
                ) AND bvid = ?
            """, (self.bvid, self.bvid))
            deleted = cursor.rowcount
            if deleted > 0:
                logger.info("v1→v2 去重 %s: 清理 %d 条重复弹幕", self.bvid, deleted)
            try:
                cursor.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_danmaku_unique "
                    "ON danmaku_records(bvid, oid, segment_index, content, video_ts, uid)"
                )
            except sqlite3.OperationalError:
                logger.warning("v1→v2: %s 无法创建弹幕 UNIQUE 索引", self.bvid)
            conn.commit()
        except sqlite3.Error as e:
            logger.debug("v1→v2 弹幕迁移失败 %s: %s", self.bvid, e)

    def _migrate_danmaku_v3(self, conn):
        """v2→v3 迁移：添加 Proto 弹幕新字段 + 更新 UNIQUE 索引为 dmid 方案。"""
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='danmaku_records'"
            )
            if not cursor.fetchone():
                return
            new_columns = {
                "dmid": "INTEGER DEFAULT 0",
                "id_str": "TEXT DEFAULT ''",
                "like_count": "INTEGER DEFAULT 0",
                "pool": "INTEGER DEFAULT 0",
                "dm_from": "INTEGER DEFAULT 0",
            }
            existing = {row[1] for row in cursor.execute("PRAGMA table_info(danmaku_records)")}
            for col_name, col_def in new_columns.items():
                if col_name not in existing:
                    try:
                        cursor.execute(
                            f"ALTER TABLE danmaku_records ADD COLUMN {col_name} {col_def}"
                        )
                    except sqlite3.OperationalError:
                        pass
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_danmaku_dmid ON danmaku_records(dmid) WHERE dmid > 0"
            )
            try:
                cursor.execute("DROP INDEX IF EXISTS idx_danmaku_unique")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_danmaku_unique "
                    "ON danmaku_records(bvid, oid, dmid)"
                )
            except sqlite3.OperationalError:
                try:
                    cursor.execute(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_danmaku_unique "
                        "ON danmaku_records(bvid, oid, segment_index, content, video_ts)"
                    )
                except sqlite3.OperationalError:
                    logger.warning("v2→v3: %s 无法创建弹幕 UNIQUE 索引", self.bvid)
            conn.commit()
            logger.info("v2→v3 弹幕 schema 升级完成: %s", self.bvid)
        except sqlite3.Error as e:
            logger.debug("v2→v3 弹幕迁移失败 %s: %s", self.bvid, e)

    # ── CRUD ────────────────────────────────────

    def add_danmaku_batch(self, rows: list) -> int:
        """批量插入弹幕记录（跳过重复）。"""
        inserted = 0
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN")
                for r in rows:
                    try:
                        cursor.execute(
                            """INSERT OR IGNORE INTO danmaku_records
                               (bvid, oid, segment_index, dmid, id_str, content, video_ts,
                                mode, font_size, color, send_time, weight, uid,
                                like_count, pool, dm_from)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                r.get("bvid", self.bvid), r.get("oid", 0),
                                r.get("segment_index", 0),
                                r.get("dmid", 0), str(r.get("id_str", "")),
                                r.get("content", ""), r.get("video_ts", 0),
                                r.get("mode", 1), r.get("font_size", 25),
                                r.get("color", 16777215), r.get("send_time", 0),
                                r.get("weight", 1), str(r.get("uid", "")),
                                r.get("like_count", 0), r.get("pool", 0),
                                r.get("dm_from", 0),
                            ),
                        )
                        if cursor.rowcount > 0:
                            inserted += 1
                    except Exception:
                        pass
                conn.commit()
        except Exception as e:
            logger.debug("批量插入弹幕失败 %s: %s", self.bvid, e)
        return inserted

    def get_danmaku_records(self, limit: int = 5000) -> List[Dict]:
        """获取弹幕记录列表（按 video_ts 排序）。"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if limit and limit > 0:
                    cursor.execute(
                        "SELECT * FROM danmaku_records WHERE bvid=? ORDER BY video_ts ASC LIMIT ?",
                        (self.bvid, limit),
                    )
                else:
                    cursor.execute(
                        "SELECT * FROM danmaku_records WHERE bvid=? ORDER BY video_ts ASC",
                        (self.bvid,),
                    )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.debug("查询弹幕记录失败 %s: %s", self.bvid, e)
            return []

    def count_danmaku(self) -> int:
        """统计弹幕总数。"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM danmaku_records WHERE bvid=?", (self.bvid,))
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception:
            return 0

    def get_danmaku_segment_count(self) -> int:
        """获取已拉取的弹幕段数。"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(DISTINCT segment_index) FROM danmaku_records WHERE bvid=?",
                    (self.bvid,),
                )
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception:
            return 0

    def get_max_danmaku_segment(self) -> int:
        """获取已拉取的最大弹幕段号。"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COALESCE(MAX(segment_index), 0) FROM danmaku_records WHERE bvid=?",
                    (self.bvid,),
                )
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception:
            return 0

    def dedup_danmaku(self) -> int:
        """清理重复弹幕记录，保留每组首条。"""
        deleted = 0
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM danmaku_records
                    WHERE id NOT IN (
                        SELECT MIN(id) FROM danmaku_records
                        WHERE bvid = ?
                        GROUP BY bvid, oid, segment_index, content, video_ts, uid
                    ) AND bvid = ?
                """, (self.bvid, self.bvid))
                deleted = cursor.rowcount
                conn.commit()
                if deleted > 0:
                    logger.info("已清理 %s 的 %d 条重复弹幕", self.bvid, deleted)
        except sqlite3.Error as e:
            logger.debug("清理重复弹幕失败 %s: %s", self.bvid, e)
        return deleted
