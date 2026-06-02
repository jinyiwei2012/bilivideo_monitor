"""
中央数据库备份同步模块
======================
本模块负责将活跃（active）数据库与备份（backup）数据库之间的数据同步。
功能涵盖：
- 活跃库到中央备份库的完整同步（视频元数据 + 监控记录 + 预测/周刊/年刊数据）
- 关闭时将各视频独立数据库文件拷贝到备份目录
- 比较活跃库与备份库的差异，输出差异列表

所有同步操作遵循"活跃库优先，增量去重"的原则，避免重复写入。
"""
import logging
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

# ── 模块级日志 ────────────────────────────────────────────────────
logger = logging.getLogger(__name__)


class CentralBackup:
    """中央数据库备份与同步管理器

    作为 Database 的委托子模块，负责活跃库 → 备份库的数据同步。
    支持全量同步（sync_to_central）、文件级备份（sync_per_video_dbs_to_backup）
    和差异对比（check_backup_diffs）三种操作模式。
    """

    def __init__(self, database):
        """
        初始化备份管理器

        Args:
            database: Database 实例引用，用于访问活跃库连接和数据目录
        """
        self.db = database

    def sync_to_central(self) -> dict:
        """将活跃库数据完整同步到中央备份库

        同步范围包括：
        - videos 表（视频元数据，补全新记录和缺失字段）
        - monitor_records 表（监控记录，按时间戳去重增量同步）
        - 各视频独立库的 predictions / weekly_scores / yearly_scores

        Returns:
            同步结果字典，包含以下键：
            - synced_videos: 新增/更新的视频元数据数目
            - synced_records: 新增的监控记录数目
            - fixed_flaws: 修复的缺失字段数目
            - synced_predictions: 同步的预测记录数目
            - synced_weekly: 同步的周刊分数数目
            - synced_yearly: 同步的年刊分数数目
        """
        # ── 计算中央备份库路径 ──────────────────────────────────
        central_db = os.path.join(self.db._get_backup_dir(), "bilibili_monitor.db")
        # 如果备份库与活跃库相同或备份库不存在，跳过同步
        if central_db == self.db.db_path or not os.path.exists(central_db):
            logger.info("中央数据库不存在或与活跃库相同，跳过同步")
            return {
                "synced_videos": 0, "synced_records": 0, "fixed_flaws": 0,
                "synced_predictions": 0, "synced_weekly": 0, "synced_yearly": 0,
            }
        # ── 初始化返回结果 ──────────────────────────────────────
        result = {
            "synced_videos": 0, "synced_records": 0, "fixed_flaws": 0,
            "synced_predictions": 0, "synced_weekly": 0, "synced_yearly": 0,
        }
        try:
            # 连接备份库
            backup_conn = sqlite3.connect(central_db)
            backup_conn.row_factory = sqlite3.Row
            backup_cur = backup_conn.cursor()
            # 确保备份库表结构完备（兼容首次同步或 schema 升级）
            self._ensure_central_tables(backup_cur)
            backup_conn.commit()
            # 使用活跃库连接进行数据读取
            with self.db._get_connection() as active_conn:
                active_cur = active_conn.cursor()
                # 第一步：同步视频元数据
                self._sync_videos_to_central(active_cur, backup_cur, result)
                # 第二步：同步监控记录，同时获取两端已有的 BV 号集合
                active_bvids, central_bvids = self._sync_monitor_records_to_central(active_cur, backup_cur, result)
                # 第三步：同步各视频的预测/周刊/年刊数据
                self._sync_per_video_details(active_bvids, central_bvids, backup_cur, result)
            backup_conn.commit()
            backup_conn.close()
            logger.info(
                "中央库同步完成: %d视频 %d记录 %d瑕疵 | 预测%d 周刊%d 年刊%d",
                result["synced_videos"], result["synced_records"], result["fixed_flaws"],
                result["synced_predictions"], result["synced_weekly"], result["synced_yearly"],
            )
        except Exception as e:
            logger.warning("中央库同步失败: %s", e)
        return result

    def sync_per_video_dbs_to_backup(self):
        """关闭前将活跃库的所有视频独立库同步到备份目录

        将 data/<BV>/ 目录下的数据库文件（含 WAL/SHM）复制到备份目录。
        如果备份目录中已有记录且记录数不少于活跃库，则跳过该视频。
        """
        # ── 获取备份目录 ────────────────────────────────────────
        backup_base = self.db._get_backup_dir()
        # 如果备份目录与活跃目录相同，无需同步
        if backup_base == self.db.data_dir:
            return
        import shutil
        synced = 0
        # ── 遍历活跃目录下的所有 BV 号子目录 ────────────────────
        for item in os.listdir(self.db.data_dir):
            src_dir = os.path.join(self.db.data_dir, item)
            if not os.path.isdir(src_dir) or not item.startswith("BV"):
                continue  # 跳过非 BV 号目录
            src_db = os.path.join(src_dir, f"{item}.db")
            if not os.path.exists(src_db):
                continue  # 跳过无数据库文件的目录
            dst_dir = os.path.join(backup_base, item)
            dst_db = os.path.join(dst_dir, f"{item}.db")
            if os.path.exists(dst_db):
                try:
                    import sqlite3 as _sql
                    # 比较源和目标数据库的记录数，如果目标更多则跳过
                    with _sql.connect(src_db) as _conn:
                        sc = _conn.execute("SELECT COUNT(*) FROM monitor_records").fetchone()[0]
                    with _sql.connect(dst_db) as _conn:
                        dc = _conn.execute("SELECT COUNT(*) FROM monitor_records").fetchone()[0]
                    if sc <= dc:
                        continue  # 备份已有最新/等量数据
                    # 源有更多数据则删除旧备份目录重新拷贝
                    shutil.rmtree(dst_dir)
                except Exception:
                    continue
            # 创建目标目录并拷贝数据库文件
            os.makedirs(dst_dir, exist_ok=True)
            shutil.copy2(src_db, dst_db)
            # 同时拷贝 WAL 和 SHM 辅助文件
            for ext in ("-wal", "-shm"):
                src_ext = src_db + ext
                if os.path.exists(src_ext):
                    shutil.copy2(src_ext, dst_db + ext)
            synced += 1
        if synced:
            logger.info("已同步 %d 个视频独立库到 %s", synced, backup_base)

    def check_backup_diffs(self) -> List[Dict]:
        """比较活跃库与备份库的差异，返回有差异的视频列表

        Returns:
            差异列表，每项包含 bvid、primary_records（活跃库记录数）、
            backup_records（备份库记录数）
        """
        backup_base = self.db._get_backup_dir()
        if backup_base == self.db.data_dir:
            return []  # 同一目录无需比较
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
                # 比较两端监控记录数
                with _sql.connect(src_db) as _conn:
                    sc = _conn.execute("SELECT COUNT(*) FROM monitor_records").fetchone()[0]
                with _sql.connect(dst_db) as _conn:
                    dc = _conn.execute("SELECT COUNT(*) FROM monitor_records").fetchone()[0]
                if sc != dc:
                    diffs.append({"bvid": item, "primary_records": sc, "backup_records": dc})
            except Exception:
                continue
        return diffs

    # ════════════════════════════════════════════════════════════════
    # 内部同步方法
    # ════════════════════════════════════════════════════════════════

    def _sync_videos_to_central(self, active_cur, central_cur, result):
        """同步 videos 表到中央库（补全新记录和缺失字段）

        对活跃库的每条视频记录，检查备份库中是否存在：
        - 不存在则插入新记录
        - 存在但关键字段（播放/点赞/投币/分享）为空则修复

        Args:
            active_cur: 活跃库游标
            central_cur: 备份库游标
            result: 结果字典（原地修改 synced_videos 和 fixed_flaws）
        """
        active_cur.execute("SELECT * FROM videos")
        for av in (dict(r) for r in active_cur.fetchall()):
            central_cur.execute("SELECT * FROM videos WHERE bvid=?", (av["bvid"],))
            existing = central_cur.fetchone()
            should_update = False
            if not existing:
                # 新记录：备份库中不存在该视频
                should_update = True
                result["synced_videos"] += 1
            else:
                # 检查缺失字段（播放/点赞/投币/分享任意一项为空则需要修复）
                ed = dict(existing)
                for key in ("view_count", "like_count", "coin_count", "share_count"):
                    if not ed.get(key) and av.get(key):
                        should_update = True
                        result["fixed_flaws"] += 1
                        break  # 找到一处缺失即可，无需继续检查
            if should_update:
                central_cur.execute(
                    """INSERT OR REPLACE INTO videos
                    (bvid, title, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, cover_path, like_view_ratio,
                     owner_name, owner_id, pubdate, duration, pic, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        av["bvid"], av.get("title", ""), av.get("view_count", 0),
                        av.get("like_count", 0), av.get("coin_count", 0),
                        av.get("share_count", 0), av.get("favorite_count", 0),
                        av.get("danmaku_count", 0), av.get("reply_count", 0),
                        av.get("viewers_app", 0), av.get("viewers_web", 0),
                        av.get("viewers_total", 0), av.get("cover_path", ""),
                        av.get("like_view_ratio", 0), av.get("owner_name", ""),
                        av.get("owner_id", 0), av.get("pubdate", ""),
                        av.get("duration", 0), av.get("pic", ""),
                        datetime.now(),  # updated_at 设为当前时间
                    ),
                )

    def _sync_monitor_records_to_central(self, active_cur, central_cur, result):
        """同步 monitor_records 表到中央库（按时间戳去重增量同步）

        对活跃库的每条监控记录，仅当该 bvid+timestamp 组合在备份库中
        不存在时才插入，避免重复写入。同时自动计算缺失的播赞比。

        Args:
            active_cur: 活跃库游标
            central_cur: 备份库游标
            result: 结果字典（原地修改 synced_records）

        Returns:
            (active_bvids, central_bvids): 活跃库和备份库的 BV 号集合
        """
        # 获取两端已知的 BV 号集合
        central_cur.execute("SELECT DISTINCT bvid FROM monitor_records")
        central_bvids = {r["bvid"] for r in central_cur.fetchall()}
        active_cur.execute("SELECT DISTINCT bvid FROM monitor_records")
        active_bvids = {r["bvid"] for r in active_cur.fetchall()}

        for bvid in active_bvids:
            # 获取备份库中该视频已有的时间戳集合（用于去重）
            central_cur.execute("SELECT timestamp FROM monitor_records WHERE bvid=?", (bvid,))
            central_ts = {r["timestamp"] for r in central_cur.fetchall()}
            # 查询活跃库中该视频的所有记录（按时间升序）
            active_cur.execute("SELECT * FROM monitor_records WHERE bvid=? ORDER BY timestamp ASC", (bvid,))
            for row in active_cur.fetchall():
                rd = dict(row)
                if rd["timestamp"] not in central_ts:
                    # 自动计算播赞比（如果原数据缺失但有播放和点赞数）
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
                            rd["bvid"], rd["timestamp"],
                            rd.get("view_count", 0), rd.get("like_count", 0),
                            rd.get("coin_count", 0), rd.get("share_count", 0),
                            rd.get("favorite_count", 0), rd.get("danmaku_count", 0),
                            rd.get("reply_count", 0), rd.get("viewers_app", 0),
                            rd.get("viewers_web", 0), rd.get("viewers_total", 0),
                            lvr,
                        ),
                    )
                    central_ts.add(rd["timestamp"])  # 记录已同步的时间戳
                    result["synced_records"] += 1
        return active_bvids, central_bvids

    def _sync_per_video_details(self, active_bvids, central_bvids, central_cur, result):
        """同步每个视频的预测、周刊、年刊数据到中央库

        对活跃库和备份库中出现的所有 BV 号，分别检查并同步：
        - predictions（预测记录，按 algorithm+predicted_time 去重）
        - weekly_scores（周刊分数，按最新时间戳判断）
        - yearly_scores（年刊分数，按最新时间戳判断）

        Args:
            active_bvids: 活跃库中出现的 BV 号集合
            central_bvids: 备份库中出现的 BV 号集合
            central_cur: 备份库游标
            result: 结果字典（原地修改 synced_predictions / synced_weekly / synced_yearly）
        """
        # 合并两端 BV 号，确保不遗漏备份库独有的视频
        for bvid in active_bvids | central_bvids:
            video_db = self._open_video_db_ro(bvid)
            if video_db is None:
                continue  # 无法打开该视频的独立库则跳过
            try:
                vcur = video_db.cursor()
                # ── 同步预测记录 ────────────────────────────────
                # 用 COALESCE 处理空值（algorithm 或 predicted_time 为空时合并为 ''）
                v_count = vcur.execute(
                    "SELECT COUNT(DISTINCT COALESCE(algorithm,'') || COALESCE(predicted_time,'')) FROM predictions"
                ).fetchone()[0]
                c_count = central_cur.execute(
                    "SELECT COUNT(DISTINCT COALESCE(algorithm,'') || COALESCE(predicted_time,'')) FROM predictions WHERE bvid=?",
                    (bvid,),
                ).fetchone()[0]
                if v_count != c_count:
                    result["synced_predictions"] += self._sync_video_predictions(central_cur, bvid, vcur)
                # ── 同步周刊分数 ────────────────────────────────
                # 仅当独立库的最新时间戳大于备份库时才同步
                v_max = vcur.execute("SELECT MAX(timestamp) FROM weekly_scores").fetchone()[0]
                c_max = central_cur.execute(
                    "SELECT MAX(timestamp) FROM weekly_scores WHERE bvid=?", (bvid,)
                ).fetchone()[0]
                if v_max and (c_max is None or v_max > c_max):
                    result["synced_weekly"] += self._sync_video_weekly_scores(central_cur, bvid, vcur)
                # ── 同步年刊分数 ────────────────────────────────
                v_max = vcur.execute("SELECT MAX(timestamp) FROM yearly_scores").fetchone()[0]
                c_max = central_cur.execute(
                    "SELECT MAX(timestamp) FROM yearly_scores WHERE bvid=?", (bvid,)
                ).fetchone()[0]
                if v_max and (c_max is None or v_max > c_max):
                    result["synced_yearly"] += self._sync_video_yearly_scores(central_cur, bvid, vcur)
            finally:
                video_db.close()  # 确保独立库连接被释放

    def _open_video_db_ro(self, bvid: str) -> Optional[sqlite3.Connection]:
        """以只读方式打开视频独立库，优先活跃目录，回退备份目录

        Args:
            bvid: BV 号

        Returns:
            只读的 SQLite 连接，若两个目录都找不到则返回 None
        """
        # 先尝试活跃目录，再尝试备份目录
        for base in (self.db.data_dir, self.db._get_backup_dir()):
            db_path = os.path.join(base, bvid, f"{bvid}.db")
            if os.path.exists(db_path):
                try:
                    # 使用 URI 模式 + ?mode=ro 实现只读连接
                    uri = f"file:{db_path.replace(chr(92), '/')}?mode=ro"
                    conn = sqlite3.connect(uri, uri=True)
                    conn.row_factory = sqlite3.Row
                    return conn
                except Exception as e:
                    logger.debug("打开只读连接失败 %s: %s", db_path, e)
        return None

    @staticmethod
    def _sync_video_predictions(central_cur, bvid: str, vcur) -> int:
        """同步视频独立库的 predictions 到中央库

        按 algorithm + predicted_time 组合去重，仅同步中央库中不存在的记录。

        Args:
            central_cur: 中央库游标
            bvid: BV 号
            vcur: 视频独立库游标

        Returns:
            成功同步的记录数
        """
        # 检查视频独立库 predictions 表是否有 algorithm 列（兼容旧 schema）
        try:
            vcur.execute("PRAGMA table_info(predictions)")
            if "algorithm" not in {r["name"] for r in vcur.fetchall()}:
                return 0  # 旧 schema 无 algorithm 列，跳过
        except Exception:
            return 0
        try:
            # 按 algorithm + predicted_time 分组去重
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
        # 查询中央库已有记录，构建去重集合
        central_cur.execute("SELECT algorithm, predicted_time FROM predictions WHERE bvid=?", (bvid,))
        existing = {(r["algorithm"], r["predicted_time"]) for r in central_cur.fetchall()}
        batch = []  # 批量插入缓存
        for rd in rows:
            key = (rd.get("algorithm", ""), rd.get("predicted_time", ""))
            if key in existing:
                continue  # 已存在则跳过
            batch.append((
                bvid, rd.get("algorithm", ""), rd.get("algorithm_id", ""),
                rd.get("target_threshold", 0), rd.get("predicted_seconds", 0),
                rd.get("predicted_time", ""), rd.get("confidence", 0),
                rd.get("current_views", 0), rd.get("metadata", ""),
                rd.get("predicted_hours", 0), rd.get("current_velocity", 0),
                rd.get("is_reached", 0), rd.get("actual_time", ""),
                rd.get("error_rate", 0), rd.get("created_at"),
            ))
            existing.add(key)  # 标记为已处理
        if batch:
            central_cur.executemany(  # 批量插入
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
        """同步视频独立库的 weekly_scores 到中央库

        Args:
            central_cur: 中央库游标
            bvid: BV 号
            vcur: 视频独立库游标

        Returns:
            成功同步的记录数
        """
        # 检查表是否存在
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
        # 按时间戳去重
        central_cur.execute("SELECT timestamp FROM weekly_scores WHERE bvid=?", (bvid,))
        existing_ts = {r["timestamp"] for r in central_cur.fetchall()}
        batch = []
        for rd in rows:
            if rd.get("timestamp") in existing_ts:
                continue
            batch.append((
                bvid, rd.get("timestamp"), rd.get("total_score"),
                rd.get("view_score"), rd.get("interaction_score"),
                rd.get("favorite_score"), rd.get("coin_score"),
                rd.get("like_score"), rd.get("correction_a"),
                rd.get("correction_b"), rd.get("correction_c"),
                rd.get("correction_d"), rd.get("base_view_score"),
            ))
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
        """同步视频独立库的 yearly_scores 到中央库

        Args:
            central_cur: 中央库游标
            bvid: BV 号
            vcur: 视频独立库游标

        Returns:
            成功同步的记录数
        """
        # 检查表是否存在
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
        # 按时间戳去重
        central_cur.execute("SELECT timestamp FROM yearly_scores WHERE bvid=?", (bvid,))
        existing_ts = {r["timestamp"] for r in central_cur.fetchall()}
        batch = []
        for rd in rows:
            if rd.get("timestamp") in existing_ts:
                continue
            batch.append((
                bvid, rd.get("timestamp"), rd.get("total_score"),
                rd.get("view_score"), rd.get("interaction_score"),
                rd.get("favorite_score"), rd.get("coin_score"),
                rd.get("like_score"), rd.get("correction_a"),
                rd.get("correction_b"), rd.get("correction_c"),
            ))
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
        """确保中央库有完整的表结构（兼容首次同步）

        创建 videos、monitor_records、weekly_scores、yearly_scores、
        predictions 等核心表及索引。使用 IF NOT EXISTS 避免重复创建。

        Args:
            cur: 数据库游标
        """
        # ── videos 表：视频元数据 ────────────────────────────────
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
        # ── monitor_records 表：监控记录 ─────────────────────────
        cur.execute("""CREATE TABLE IF NOT EXISTS monitor_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, bvid TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            view_count INTEGER, like_count INTEGER, coin_count INTEGER,
            share_count INTEGER, favorite_count INTEGER, danmaku_count INTEGER,
            reply_count INTEGER, viewers_app INTEGER DEFAULT 0,
            viewers_web INTEGER DEFAULT 0, viewers_total INTEGER DEFAULT 0,
            like_view_ratio REAL DEFAULT 0)""")
        # 唯一索引：确保同一视频+时间戳不重复
        cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_monitor_bvid_ts
            ON monitor_records(bvid, timestamp)""")
        # ── weekly_scores 表：周刊分数 ───────────────────────────
        cur.execute("""CREATE TABLE IF NOT EXISTS weekly_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT, bvid TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_score REAL, view_score REAL, interaction_score REAL,
            favorite_score REAL, coin_score REAL, like_score REAL,
            correction_a REAL, correction_b REAL, correction_c REAL,
            correction_d REAL, base_view_score REAL)""")
        cur.execute("""CREATE INDEX IF NOT EXISTS idx_weekly_bvid
            ON weekly_scores(bvid, timestamp)""")
        # ── yearly_scores 表：年刊分数 ───────────────────────────
        cur.execute("""CREATE TABLE IF NOT EXISTS yearly_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT, bvid TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_score REAL, view_score REAL, interaction_score REAL,
            favorite_score REAL, coin_score REAL, like_score REAL,
            correction_a REAL, correction_b REAL, correction_c REAL)""")
        cur.execute("""CREATE INDEX IF NOT EXISTS idx_yearly_bvid
            ON yearly_scores(bvid, timestamp)""")
        # ── 兼容迁移 + predictions 索引 ─────────────────────────
        CentralBackup._migrate_central_predictions(cur)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_predictions_bvid ON predictions(bvid)")

    @staticmethod
    def _migrate_central_predictions(cur):
        """确保中央库 predictions 表包含独立库的全部字段

        通过 PRAGMA table_info 检查现有列，对缺失的字段
        执行 ALTER TABLE ADD COLUMN 补全。

        Args:
            cur: 数据库游标
        """
        cur.execute("PRAGMA table_info(predictions)")
        # 兼容 sqlite3.Row (字典式) 和 list/tuple (索引式) 两种访问方式
        existing = {r[1] if isinstance(r, (list, tuple)) else r["name"] for r in cur.fetchall()}
        if not existing:
            return  # predictions 表不存在，跳过迁移
        # 需要确保存在的额外字段及其定义
        for col, definition in [
            ("metadata", "TEXT DEFAULT ''"),         # JSON 格式的额外元数据
            ("predicted_hours", "REAL DEFAULT 0"),    # 预测所需小时数
            ("current_velocity", "REAL DEFAULT 0"),   # 当前播放速率
        ]:
            if col not in existing:
                try:
                    cur.execute(f"ALTER TABLE predictions ADD COLUMN {col} {definition}")
                except Exception as e:
                    logger.debug("迁移列 %s 失败: %s", col, e)
