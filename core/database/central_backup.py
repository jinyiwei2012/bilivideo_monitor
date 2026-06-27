"""中央数据库备份同步模块"""

import logging
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class CentralBackup:
    """Backup and sync operations for central database (delegated from Database)"""

    def __init__(self, database):
        self.db = database

    def sync_to_central(self) -> dict:
        """将活跃库数据完整同步到中央备份库"""
        central_db = os.path.join(self.db._get_backup_dir(), "bilibili_monitor.db")
        if central_db == self.db.db_path or not os.path.exists(central_db):
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
        backup_conn = None
        try:
            backup_conn = sqlite3.connect(central_db)
            backup_conn.row_factory = sqlite3.Row
            backup_cur = backup_conn.cursor()
            self._ensure_central_tables(backup_cur)
            backup_conn.commit()
            with self.db._get_connection() as active_conn:
                active_cur = active_conn.cursor()
                self._sync_videos_to_central(active_cur, backup_cur, result)
                active_bvids, central_bvids = self._sync_monitor_records_to_central(active_cur, backup_cur, result)
                self._sync_per_video_details(active_bvids, central_bvids, backup_cur, result)
            backup_conn.commit()
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
        finally:
            if backup_conn:
                try:
                    backup_conn.close()
                except Exception:
                    pass
        return result

    def sync_per_video_dbs_to_backup(self):
        """关闭前将活跃库的所有视频独立库同步到备份目录"""
        backup_base = self.db._get_backup_dir()
        if backup_base == self.db.data_dir:
            return
        import shutil

        synced = 0
        for item in os.listdir(self.db.data_dir):
            src_dir = os.path.join(self.db.data_dir, item)
            if not os.path.isdir(src_dir) or not item.startswith("BV"):
                continue
            src_db = os.path.join(src_dir, f"{item}.db")
            if not os.path.exists(src_db):
                continue
            dst_dir = os.path.join(backup_base, item)
            dst_db = os.path.join(dst_dir, f"{item}.db")
            if os.path.exists(dst_db):
                try:
                    import sqlite3 as _sql

                    with _sql.connect(src_db) as _conn:
                        sc = _conn.execute("SELECT COUNT(*) FROM monitor_records").fetchone()[0]
                    with _sql.connect(dst_db) as _conn:
                        dc = _conn.execute("SELECT COUNT(*) FROM monitor_records").fetchone()[0]
                    if sc <= dc:
                        continue
                    shutil.rmtree(dst_dir)
                except Exception as e:
                    logger.debug("同步视频独立库跳过 %s: %s", item, e)
                    continue
            os.makedirs(dst_dir, exist_ok=True)
            shutil.copy2(src_db, dst_db)
            for ext in ("-wal", "-shm"):
                src_ext = src_db + ext
                if os.path.exists(src_ext):
                    shutil.copy2(src_ext, dst_db + ext)
            synced += 1
        if synced:
            logger.info("已同步 %d 个视频独立库到 %s", synced, backup_base)

    def check_backup_diffs(self) -> List[Dict]:
        """比较活跃库与备份库的差异，返回有差异的视频列表"""
        backup_base = self.db._get_backup_dir()
        if backup_base == self.db.data_dir:
            return []
        diffs = []
        import sqlite3 as _sql

        for item in os.listdir(self.db.data_dir):
            src_dir = os.path.join(self.db.data_dir, item)
            if not os.path.isdir(src_dir) or not item.startswith("BV"):
                continue
            src_db = os.path.join(src_dir, f"{item}.db")
            dst_db = os.path.join(backup_base, item, f"{item}.db")
            if not os.path.exists(src_db) or not os.path.exists(dst_db):
                continue
            try:
                with _sql.connect(src_db) as _conn:
                    sc = _conn.execute("SELECT COUNT(*) FROM monitor_records").fetchone()[0]
                with _sql.connect(dst_db) as _conn:
                    dc = _conn.execute("SELECT COUNT(*) FROM monitor_records").fetchone()[0]
                if sc != dc:
                    diffs.append({"bvid": item, "primary_records": sc, "backup_records": dc})
            except Exception:
                logger.exception("备份差异检查失败: %s", item)
                continue
        return diffs

    # ── 内部同步方法 ──────────────────────────────────────────────────

    def _sync_videos_to_central(self, active_cur, central_cur, result):
        """同步 videos 表到中央库（补全新记录和缺失字段）"""
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
        """同步 monitor_records 表到中央库（按时间戳去重增量同步）"""
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
        """同步每个视频的预测、周刊、年刊数据到中央库"""
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
        for base in (self.db.data_dir, self.db._get_backup_dir()):
            db_path = os.path.join(base, bvid, f"{bvid}.db")
            if os.path.exists(db_path):
                try:
                    uri = f"file:{db_path.replace(chr(92), '/')}?mode=ro"
                    conn = sqlite3.connect(uri, uri=True)
                    conn.row_factory = sqlite3.Row
                    return conn
                except Exception as e:
                    logger.debug("打开只读连接失败 %s: %s", db_path, e)
        return None

    @staticmethod
    def _sync_video_predictions(central_cur, bvid: str, vcur) -> int:
        """同步视频独立库的 predictions 到中央库"""
        try:
            vcur.execute("PRAGMA table_info(predictions)")
            if "algorithm" not in {r["name"] for r in vcur.fetchall()}:
                return 0
        except Exception:
            logger.exception("同步预测记录 PRAGMA 检查失败 %s", bvid)
            return 0
        try:
            vcur.execute("""
                SELECT algorithm, algorithm_id, target_threshold, predicted_seconds,
                       predicted_time, confidence, current_views, metadata,
                       predicted_hours, current_velocity, is_reached,
                       actual_time, error_rate, MAX(created_at) as created_at
                FROM predictions
                GROUP BY algorithm, predicted_time
            """)
        except Exception:
            logger.exception("同步预测记录查询失败 %s", bvid)
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
            logger.exception("同步周评分 LIMIT 1 检查失败 %s", bvid)
            return 0
        try:
            vcur.execute("SELECT * FROM weekly_scores ORDER BY timestamp ASC")
        except Exception:
            logger.exception("同步周评分查询失败 %s", bvid)
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
            logger.exception("同步年评分 LIMIT 1 检查失败 %s", bvid)
            return 0
        try:
            vcur.execute("SELECT * FROM yearly_scores ORDER BY timestamp ASC")
        except Exception:
            logger.exception("同步年评分查询失败 %s", bvid)
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
        cur.execute("""CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bvid TEXT NOT NULL,
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
        )""")
        CentralBackup._migrate_central_predictions(cur)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_predictions_bvid ON predictions(bvid)")
        try:
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_central_predict_unique "
                "ON predictions(bvid, algorithm, target_threshold)"
            )
        except Exception:
            logger.exception("中央库 UNIQUE INDEX 创建失败")
            pass

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
                except Exception as e:
                    logger.debug("迁移列 %s 失败: %s", col, e)
