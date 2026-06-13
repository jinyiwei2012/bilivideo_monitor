"""中央数据库 CRUD 操作模块"""

import sqlite3
import logging
import os
from dataclasses import fields
from datetime import datetime
from typing import List, Dict, Optional

from .models import VideoInfo, MonitorRecord, PredictionRecord
from .video_db import VideoDatabase

logger = logging.getLogger(__name__)


class CentralCRUD:
    """CRUD operations for central database (delegated from Database)"""

    def __init__(self, database):
        self.db = database

    def _query_backup(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        """从备份库执行只读查询，返回行列表"""
        backup_db = os.path.join(self.db._get_backup_dir(), "bilibili_monitor.db")
        if backup_db == self.db.db_path or not os.path.exists(backup_db):
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
            with self.db._get_connection() as conn:
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

        backup_rows = self._query_backup("SELECT * FROM videos WHERE bvid = ?", (bvid,))
        if backup_rows:
            data = dict(backup_rows[0])
            valid_fields = {f.name for f in fields(VideoInfo)}
            filtered = {k: v for k, v in data.items() if k in valid_fields}
            return VideoInfo(**filtered)
        return None

    def add_video(self, video: VideoInfo) -> bool:
        """添加视频信息到总库"""
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT OR REPLACE INTO videos
                    (bvid, title, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, cover_path, like_view_ratio,
                     owner_name, owner_id, pubdate, duration, pic, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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

    def delete_video(self, bvid: str) -> bool:
        """删除视频及其所有关联记录"""
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM videos WHERE bvid = ?", (bvid,))
                cursor.execute("DELETE FROM monitor_records WHERE bvid = ?", (bvid,))
                cursor.execute("DELETE FROM predictions WHERE bvid = ?", (bvid,))
                cursor.execute("DELETE FROM video_milestones WHERE bvid = ?", (bvid,))
                conn.commit()
                return True
        except Exception as e:
            logger.warning("删除视频失败 %s: %s", bvid, e)
            return False

    def sync_from_video_db(self, bvid: str) -> bool:
        """从单个视频独立库同步视频信息到总数据库（仅同步元数据，不包含监控记录）"""
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                video_db = VideoDatabase(bvid, self.db.data_dir)
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
        """从内存字典直接同步视频信息到总数据库，避免重复读盘"""
        try:
            with self.db._get_connection() as conn:
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
        """从内存同步单条监控记录到中央数据库"""
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                like_view_ratio = record.get("like_view_ratio", 0)
                if not like_view_ratio:
                    vc = record.get("view_count", 0)
                    lc = record.get("like_count", 0)
                    if vc and lc:
                        like_view_ratio = round(lc / vc, 6)
                cursor.execute(
                    """INSERT OR IGNORE INTO monitor_records
                    (bvid, timestamp, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, like_view_ratio)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        """同步所有视频独立库到总数据库"""
        results = {}
        video_dirs = []
        for item in os.listdir(self.db.data_dir):
            item_path = os.path.join(self.db.data_dir, item)
            if os.path.isdir(item_path) and item.startswith("BV"):
                video_dirs.append(item)
        for bvid in video_dirs:
            results[bvid] = self.sync_from_video_db(bvid)
        return results

    def add_monitor_record(self, record: MonitorRecord) -> bool:
        """添加监控记录到总库"""
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO monitor_records
                    (bvid, timestamp, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, like_view_ratio)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        """获取监控历史数据（主库 + 备份库合并去重）"""
        rows = []
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                if limit and limit > 0:
                    cursor.execute(
                        """SELECT * FROM monitor_records
                        WHERE bvid = ? ORDER BY timestamp ASC LIMIT ?""",
                        (bvid, limit),
                    )
                else:
                    cursor.execute(
                        """SELECT * FROM monitor_records
                        WHERE bvid = ? ORDER BY timestamp ASC""",
                        (bvid,),
                    )
                rows = [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning("获取监控历史失败 %s: %s", bvid, e)

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
        """添加预测记录到总库"""
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO predictions
                    (bvid, algorithm, algorithm_id, target_threshold, predicted_seconds,
                     predicted_time, confidence, current_views)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
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

    def get_predictions(self, bvid: str = None, algorithm: str = None, limit: int = 100) -> List[Dict]:
        """获取预测记录，可按 bvid 和 algorithm 过滤"""
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                conditions = []
                params = []
                if bvid:
                    conditions.append("bvid = ?")
                    params.append(bvid)
                if algorithm:
                    conditions.append("algorithm = ?")
                    params.append(algorithm)
                where = "WHERE " + " AND ".join(conditions) if conditions else ""
                cursor.execute(
                    f"SELECT * FROM predictions {where} ORDER BY created_at DESC LIMIT ?",
                    params + [limit],
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning("获取预测记录失败: %s", e)
            return []

    def upsert_milestone(self, bvid: str, period: str, data: dict) -> bool:
        """新增或更新一条里程碑记录（同一 bvid+period 唯一）"""
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO video_milestones
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
                        recorded_at   = excluded.recorded_at""",
                    (
                        bvid,
                        period,
                        data.get("view_count", 0),
                        data.get("like_count"),
                        data.get("coin_count"),
                        data.get("share_count"),
                        data.get("favorite_count"),
                        data.get("danmaku_count"),
                        data.get("reply_count"),
                        data.get("note"),
                        data.get("recorded_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                    ),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("里程碑写入失败: %s", e)
            return False

    def get_milestones(self, bvid: str = None) -> list:
        """查询里程碑数据"""
        try:
            with self.db._get_connection() as conn:
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
        """返回以 bvid 为键的里程碑字典"""
        rows = self.get_milestones()
        result = {}
        for row in rows:
            bv = row["bvid"]
            if bv not in result:
                result[bv] = {}
            result[bv][row["period"]] = row
        return result

    def delete_milestone(self, bvid: str, period: str) -> bool:
        """删除指定里程碑记录"""
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM video_milestones WHERE bvid=? AND period=?", (bvid, period))
                conn.commit()
                return True
        except Exception as e:
            logger.warning("里程碑删除失败: %s", e)
            return False

    # ── 预测/分数/共识度 同步 ─────────────────────

    def sync_predictions(self, bvid: str, rows: list) -> bool:
        """批量同步预测记录到中央库（INSERT OR REPLACE 按 bvid+algorithm+threshold 去重）

        不再 DELETE 全表，改为逐行 upsert，保留历史预测记录不被清空。
        """
        if not rows:
            return True
        # SQLite INTEGER 最大值 (64位带符号)
        _SQLITE_INT_MAX = 2**63 - 1
        _clamp_int = lambda v: min(max(int(v or 0), -_SQLITE_INT_MAX), _SQLITE_INT_MAX)
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                # 确保 UNIQUE 索引存在
                cursor.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_central_predict_unique "
                    "ON predictions(bvid, algorithm, target_threshold)"
                )
                for r in rows:
                    cursor.execute(
                        """INSERT OR REPLACE INTO predictions
                        (bvid, algorithm, algorithm_id, target_threshold,
                         predicted_seconds, predicted_time, confidence, current_views,
                         predicted_views, metadata, predicted_hours, current_velocity)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (bvid, r["algorithm"], r["algorithm_id"],
                         _clamp_int(r.get("target_threshold", 0)),
                         _clamp_int(r.get("predicted_seconds", 0)),
                         r.get("predicted_time", ""), r["confidence"],
                         _clamp_int(r.get("current_views", 0)),
                         _clamp_int(r.get("predicted_views", 0)),
                         r.get("metadata", ""), r.get("predicted_hours", 0),
                         r.get("current_velocity", 0)),
                    )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("批量同步预测失败 %s: %s", bvid, e)
            return False

    def sync_prediction_ensemble(self, bvid: str, timestamp: str, data: dict) -> bool:
        """同步集成预测到中央库"""
        try:
            with self.db._get_connection() as conn:
                interval = data.get("prediction_interval", {}) or {}
                conn.execute(
                    """INSERT INTO prediction_ensemble
                    (bvid, timestamp, prediction, confidence, valid_algos, total_algos,
                     interval_lower, interval_upper, interval_width_ratio,
                     surge_correction_applied, surge_magnitude, surge_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (bvid, timestamp,
                     int(data.get("prediction", 0)), data.get("confidence", 0),
                     data.get("valid_algos", 0), data.get("total_algos", 0),
                     interval.get("lower"), interval.get("upper"),
                     interval.get("interval_width_ratio"),
                     int(data.get("surge_correction_applied", False)),
                     data.get("surge_magnitude"), data.get("surge_type", "")),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("同步集成预测失败 %s: %s", bvid, e)
            return False

    def sync_algorithm_coherence(self, bvid: str, timestamp: str, rows: list) -> bool:
        """批量同步算法共识度到中央库"""
        if not rows:
            return True
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                for algo, coh in rows:
                    cursor.execute(
                        "INSERT INTO algorithm_coherence (bvid, timestamp, algorithm, coherence) VALUES (?, ?, ?, ?)",
                        (bvid, timestamp, algo, round(coh, 4)),
                    )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("同步共识度失败 %s: %s", bvid, e)
            return False

    def sync_weekly_score(self, bvid: str, timestamp: str, score_data: dict) -> bool:
        """同步周刊分数到中央库"""
        try:
            with self.db._get_connection() as conn:
                conn.execute(
                    """INSERT INTO weekly_scores
                    (bvid, timestamp, total_score, view_score, interaction_score,
                     favorite_score, coin_score, like_score, correction_a, correction_b,
                     correction_c, correction_d, base_view_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (bvid, timestamp,
                     score_data.get("total_score", 0), score_data.get("view_score", 0),
                     score_data.get("interaction_score", 0), score_data.get("favorite_score", 0),
                     score_data.get("coin_score", 0), score_data.get("like_score", 0),
                     score_data.get("correction_a", 0), score_data.get("correction_b", 0),
                     score_data.get("correction_c", 0), score_data.get("correction_d", 0),
                     score_data.get("base_view_score", 0)),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("同步周刊分数失败 %s: %s", bvid, e)
            return False

    def sync_yearly_score(self, bvid: str, timestamp: str, score_data: dict) -> bool:
        """同步年刊分数到中央库"""
        try:
            with self.db._get_connection() as conn:
                conn.execute(
                    """INSERT INTO yearly_scores
                    (bvid, timestamp, total_score, view_score, interaction_score,
                     favorite_score, coin_score, like_score, correction_a, correction_b,
                     correction_c)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (bvid, timestamp,
                     score_data.get("total_score", 0), score_data.get("view_score", 0),
                     score_data.get("interaction_score", 0), score_data.get("favorite_score", 0),
                     score_data.get("coin_score", 0), score_data.get("like_score", 0),
                     score_data.get("correction_a", 0), score_data.get("correction_b", 0),
                     score_data.get("correction_c", 0)),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("同步年刊分数失败 %s: %s", bvid, e)
            return False

    def cleanup_duplicate_predictions(self) -> dict:
        """清理中央库 predictions 表中的重复行

        按 (bvid, algorithm, target_threshold) 分组，每组仅保留最新一条。
        prediction_ensemble 表（综合预测数据）不受影响。

        Returns:
            {"deleted": int, "kept": int}
        """
        result = {"deleted": 0, "kept": 0}
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM predictions")
                before = cursor.fetchone()[0]
                cursor.execute("""
                    DELETE FROM predictions
                    WHERE id NOT IN (
                        SELECT MAX(id) FROM predictions
                        GROUP BY bvid, algorithm, target_threshold
                    )
                """)
                conn.commit()
                cursor.execute("SELECT COUNT(*) FROM predictions")
                result["kept"] = cursor.fetchone()[0]
                result["deleted"] = before - result["kept"]
                if result["deleted"] > 0:
                    logger.info(
                        "中央库预测清理完成: 删除%d行, 保留%d行",
                        result["deleted"], result["kept"],
                    )
        except Exception as e:
            logger.warning("中央库预测清理失败: %s", e)
        return result
