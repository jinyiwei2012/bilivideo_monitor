"""中央数据库 CRUD 操作模块"""

import sqlite3
import logging
import os
from dataclasses import fields
from datetime import datetime
from typing import Any, Dict, List, Optional

from utils.time_utils import now_ts
from .models import VideoInfo, MonitorRecord, PredictionRecord

logger = logging.getLogger(__name__)


def _apply_ensemble_projection(conn: sqlite3.Connection, bvid: str, event: Any) -> None:
    """Apply one ensemble event, including timestamp-key legacy compatibility."""
    data = event.payload
    timestamp = data.get("timestamp") or event.entity_key
    interval = data.get("prediction_interval") or {}
    lower = interval.get("lower") if "prediction_interval" in data else data.get("interval_lower")
    upper = interval.get("upper") if "prediction_interval" in data else data.get("interval_upper")
    values = (
        bvid,
        event.source_row_id,
        timestamp,
        data.get("prediction", 0),
        data.get("confidence", 0),
        data.get("valid_algos", 0),
        data.get("total_algos", 0),
        lower,
        upper,
        interval.get("interval_width_ratio", data.get("interval_width_ratio")),
        int(bool(data.get("surge_correction_applied", False))),
        data.get("surge_magnitude"),
        data.get("surge_type", ""),
    )
    conflict_key = "bvid, timestamp" if event.source_row_id is None else "bvid, source_row_id"
    update = "prediction=excluded.prediction, confidence=excluded.confidence, valid_algos=excluded.valid_algos, total_algos=excluded.total_algos, interval_lower=excluded.interval_lower, interval_upper=excluded.interval_upper, interval_width_ratio=excluded.interval_width_ratio, surge_correction_applied=excluded.surge_correction_applied, surge_magnitude=excluded.surge_magnitude, surge_type=excluded.surge_type"
    if event.source_row_id is not None:
        update = "timestamp=excluded.timestamp, " + update
    conn.execute(
        f"""INSERT INTO prediction_ensemble (bvid, source_row_id, timestamp, prediction, confidence, valid_algos,
        total_algos, interval_lower, interval_upper, interval_width_ratio, surge_correction_applied,
        surge_magnitude, surge_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT({conflict_key}) DO UPDATE SET {update}""",
        values,
    )


def _apply_coherence_projection(conn: sqlite3.Connection, bvid: str, event: Any) -> None:
    """Apply one coherence event, including timestamp-algorithm legacy compatibility."""
    data = event.payload
    timestamp = data.get("timestamp") or event.entity_key.split(":", 1)[0]
    values = (bvid, event.source_row_id, timestamp, data.get("algorithm"), data.get("coherence", 0))
    conflict_key = "bvid, timestamp, algorithm" if event.source_row_id is None else "bvid, source_row_id"
    update = (
        "coherence=excluded.coherence"
        if event.source_row_id is None
        else "timestamp=excluded.timestamp, algorithm=excluded.algorithm, coherence=excluded.coherence"
    )
    conn.execute(
        f"""INSERT INTO algorithm_coherence (bvid, source_row_id, timestamp, algorithm, coherence)
        VALUES (?, ?, ?, ?, ?) ON CONFLICT({conflict_key}) DO UPDATE SET {update}""",
        values,
    )


def _apply_milestone_projection(conn: sqlite3.Connection, bvid: str, event: Any) -> None:
    """Apply one milestone event using its period as the stable logical key."""
    columns = (
        "view_count, like_count, coin_count, share_count, favorite_count, danmaku_count, reply_count, note, recorded_at"
    )
    conn.execute(
        f"""INSERT INTO video_milestones (bvid, period, {columns}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(bvid, period) DO UPDATE SET view_count=excluded.view_count, like_count=excluded.like_count,
        coin_count=excluded.coin_count, share_count=excluded.share_count, favorite_count=excluded.favorite_count,
        danmaku_count=excluded.danmaku_count, reply_count=excluded.reply_count, note=excluded.note,
        recorded_at=excluded.recorded_at""",
        (bvid, event.entity_key, *[event.payload.get(key) for key in columns.split(", ")]),
    )


def upsert_sync_cursor_on_connection(
    conn: sqlite3.Connection,
    *,
    scope: str,
    stream: str,
    partition_key: str,
    watermark: str,
    status: str,
    last_error: str | None = None,
) -> None:
    """Persist one cursor observation on an already-owned central connection."""
    conn.execute(
        """INSERT INTO sync_cursors
        (scope, stream, partition_key, watermark, updated_at, status, last_error)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(scope, stream, partition_key) DO UPDATE SET
        watermark=excluded.watermark, updated_at=excluded.updated_at,
        status=excluded.status, last_error=excluded.last_error""",
        (scope, stream, partition_key, watermark, now_ts(), status, last_error),
    )


class CentralCRUD:
    """CRUD operations for central database (delegated from Database)"""

    def __init__(self, database: Any) -> None:
        self.db = database

    def upsert_sync_cursor(
        self,
        *,
        scope: str,
        stream: str,
        partition_key: str,
        watermark: str,
        status: str,
        last_error: str | None = None,
    ) -> None:
        """Write an observational cursor without interrupting its primary flow."""
        try:
            with self.db._get_connection() as conn:
                upsert_sync_cursor_on_connection(
                    conn,
                    scope=scope,
                    stream=stream,
                    partition_key=partition_key,
                    watermark=watermark,
                    status=status,
                    last_error=last_error,
                )
                conn.commit()
        except Exception as error:
            logger.warning("同步游标观测写入失败 %s/%s/%s: %s", scope, stream, partition_key, error)

    def _sync_error_cursor(self, stream: str, bvid: str, error: Exception) -> None:
        """Record failure while retaining the last successfully observed watermark."""
        watermark = ""
        try:
            with self.db._get_connection() as conn:
                row = conn.execute(
                    "SELECT watermark FROM sync_cursors WHERE scope=? AND stream=? AND partition_key=?",
                    ("active_video", stream, bvid),
                ).fetchone()
                watermark = row[0] if row else ""
        except Exception:
            pass
        self.upsert_sync_cursor(
            scope="active_video",
            stream=stream,
            partition_key=bvid,
            watermark=watermark,
            status="error",
            last_error=str(error),
        )

    @staticmethod
    def apply_projection_batch(conn: sqlite3.Connection, bvid: str, events: list[Any]) -> None:
        """Apply outbox events using stable central UPSERT keys without committing."""
        for event in events:
            data = event.payload
            if event.stream == "monitor_records":
                conn.execute(
                    """INSERT INTO monitor_records (bvid, source_row_id, timestamp, view_count, like_count, coin_count, share_count,
                    favorite_count, danmaku_count, reply_count, viewers_app, viewers_web, viewers_total, like_view_ratio,
                    observed_at_us, request_start_us, rtt_us) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(bvid, source_row_id) DO UPDATE SET timestamp=excluded.timestamp, view_count=excluded.view_count,
                    like_count=excluded.like_count, coin_count=excluded.coin_count, share_count=excluded.share_count,
                    favorite_count=excluded.favorite_count, danmaku_count=excluded.danmaku_count, reply_count=excluded.reply_count,
                    viewers_app=excluded.viewers_app, viewers_web=excluded.viewers_web, viewers_total=excluded.viewers_total,
                    like_view_ratio=excluded.like_view_ratio, observed_at_us=excluded.observed_at_us,
                    request_start_us=excluded.request_start_us, rtt_us=excluded.rtt_us""",
                    (
                        bvid,
                        event.source_row_id,
                        data.get("timestamp"),
                        data.get("view_count", 0),
                        data.get("like_count", 0),
                        data.get("coin_count", 0),
                        data.get("share_count", 0),
                        data.get("favorite_count", 0),
                        data.get("danmaku_count", 0),
                        data.get("reply_count", 0),
                        data.get("viewers_app", 0),
                        data.get("viewers_web", 0),
                        data.get("viewers_total", 0),
                        data.get("like_view_ratio", 0),
                        data.get("observed_at_us"),
                        data.get("request_start_us"),
                        data.get("rtt_us"),
                    ),
                )
            elif event.stream == "predictions":
                conn.execute(
                    """INSERT INTO predictions (bvid, algorithm, algorithm_id, target_threshold, predicted_seconds, predicted_time, confidence, current_views, metadata, predicted_hours, current_velocity)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(bvid, algorithm, target_threshold) DO UPDATE SET algorithm_id=excluded.algorithm_id, predicted_seconds=excluded.predicted_seconds, predicted_time=excluded.predicted_time, confidence=excluded.confidence, current_views=excluded.current_views, metadata=excluded.metadata, predicted_hours=excluded.predicted_hours, current_velocity=excluded.current_velocity""",
                    (
                        bvid,
                        data.get("algorithm"),
                        data.get("algorithm_id"),
                        data.get("target_threshold", 0),
                        data.get("predicted_seconds", 0),
                        data.get("predicted_time"),
                        data.get("confidence", 0),
                        data.get("current_views", 0),
                        data.get("metadata", ""),
                        data.get("predicted_hours", 0),
                        data.get("current_velocity", 0),
                    ),
                )
                optional_columns = ("predicted_views", "is_reached", "actual_time", "error_rate")
                provided = [column for column in optional_columns if column in data]
                if provided:
                    assignments = ", ".join(f"{column}=?" for column in provided)
                    conn.execute(
                        f"UPDATE predictions SET {assignments} WHERE bvid=? AND algorithm=? AND target_threshold=?",
                        (
                            *[data[column] for column in provided],
                            bvid,
                            data.get("algorithm"),
                            data.get("target_threshold", 0),
                        ),
                    )
            elif event.stream in ("weekly_scores", "yearly_scores"):
                table = event.stream
                columns = "total_score, view_score, interaction_score, favorite_score, coin_score, like_score, correction_a, correction_b, correction_c"
                if table == "weekly_scores":
                    columns += ", correction_d, base_view_score"
                names = columns.split(", ")
                placeholders = ", ".join("?" for _ in range(len(names) + 2))
                assignments = ", ".join(f"{name}=excluded.{name}" for name in names)
                conn.execute(
                    f"INSERT INTO {table} (bvid, timestamp, {columns}) VALUES ({placeholders}) ON CONFLICT(bvid, timestamp) DO UPDATE SET {assignments}",
                    (bvid, event.entity_key, *[data.get(key, 0) for key in columns.split(", ")]),
                )
            elif event.stream == "prediction_ensemble":
                _apply_ensemble_projection(conn, bvid, event)
            elif event.stream == "algorithm_coherence":
                _apply_coherence_projection(conn, bvid, event)
            elif event.stream == "video_milestones":
                _apply_milestone_projection(conn, bvid, event)

    def _query_backup(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        """从备份库执行只读查询，返回行列表"""
        backup_db = os.path.join(self.db._get_backup_dir(), "bilibili_monitor.db")
        if backup_db == self.db.db_path or not os.path.exists(backup_db):
            return []
        conn = None
        try:
            conn = sqlite3.connect(f"file:{backup_db}?mode=ro", uri=True, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(sql, params)
            return cur.fetchall()
        except Exception as e:
            logger.debug("备份库查询失败: %s", e)
            return []
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

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
            logger.warning("获取视频失败 %s: %s", bvid, e, exc_info=True)

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
            logger.warning("添加视频失败 %s: %s", video.bvid, e, exc_info=True)
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
            logger.warning("删除视频失败 %s: %s", bvid, e, exc_info=True)
            return False

    def delete_monitor_records_before(self, cutoff: str) -> int:
        """删除中央库中 timestamp 早于 cutoff 的监控记录，返回删除行数。

        时间戳全库统一为 "YYYY-MM-DD HH:MM:SS"（见 utils.time_utils），
        可直接字典序比较并命中索引。
        """
        try:
            with self.db._get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM monitor_records WHERE timestamp < ?", (cutoff,))
                deleted = cur.rowcount
                conn.commit()
                return max(0, int(deleted))
        except Exception as e:
            logger.warning("清理中央库旧监控记录失败: %s", e)
            return 0

    @staticmethod
    def _read_video_info_light(bvid: str, data_dir: str) -> Optional[Dict]:
        """轻量只读读取单个视频库的 video_info 行（不建表、不迁移）。

        同步路径原先构造完整 VideoDatabase（建表 + 3 次 schema 迁移）仅为读一行，
        这里改为直接 SELECT；库/表不存在或出错时返回 None。
        """
        db_path = os.path.join(data_dir, bvid, f"{bvid}.db")
        if not os.path.exists(db_path):
            return None
        conn = None
        try:
            conn = sqlite3.connect(db_path, check_same_thread=False, timeout=5)
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM video_info WHERE id = 1")
            row = cur.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.debug("轻量读取 video_info 失败 %s: %s", bvid, e)
            return None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

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
                     viewers_web, viewers_total, like_view_ratio, observed_at_us,
                     request_start_us, rtt_us)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                        record.get("observed_at_us"),
                        record.get("request_start_us"),
                        record.get("rtt_us"),
                    ),
                )
                conn.commit()
            self.upsert_sync_cursor(
                scope="active_video",
                stream="monitor_records",
                partition_key=bvid,
                watermark=str(record.get("timestamp") or ""),
                status="success",
            )
            return True
        except Exception as e:
            logger.warning("同步监控记录失败 %s: %s", bvid, e, exc_info=True)
            self._sync_error_cursor("monitor_records", bvid, e)
            return False

    def add_monitor_record(self, record: MonitorRecord) -> bool:
        """添加监控记录到总库"""
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO monitor_records
                    (bvid, timestamp, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, like_view_ratio, observed_at_us,
                     request_start_us, rtt_us)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                        record.observed_at_us,
                        record.request_start_us,
                        record.rtt_us,
                    ),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("添加监控记录失败 %s: %s", record.bvid, e, exc_info=True)
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
            logger.warning("获取监控历史失败 %s: %s", bvid, e, exc_info=True)

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
            logger.warning("添加预测记录失败 %s: %s", prediction.bvid, e, exc_info=True)
            return False

    def get_predictions(self, bvid: str | None = None, algorithm: str | None = None, limit: int = 100) -> List[Dict]:
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
            logger.warning("获取预测记录失败: %s", e, exc_info=True)
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
                        data.get("recorded_at") or now_ts(),
                    ),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("里程碑写入失败: %s", e, exc_info=True)
            return False

    def get_milestones(self, bvid: str | None = None) -> list:
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
            logger.warning("里程碑查询失败: %s", e, exc_info=True)
            return []

    def get_all_milestones_grouped(self) -> dict:
        """返回以 bvid 为键的里程碑字典"""
        rows = self.get_milestones()
        result: dict[str, dict[str, dict[Any, Any]]] = {}
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
            logger.warning("里程碑删除失败: %s", e, exc_info=True)
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

        def _clamp_int(v: Any) -> int:
            """把数值夹到 SQLite 64 位有符号整数范围内。"""
            return min(max(int(v or 0), -_SQLITE_INT_MAX), _SQLITE_INT_MAX)

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
                        (
                            bvid,
                            r["algorithm"],
                            r["algorithm_id"],
                            _clamp_int(r.get("target_threshold", 0)),
                            _clamp_int(r.get("predicted_seconds", 0)),
                            r.get("predicted_time", ""),
                            r["confidence"],
                            _clamp_int(r.get("current_views", 0)),
                            _clamp_int(r.get("predicted_views", 0)),
                            r.get("metadata", ""),
                            r.get("predicted_hours", 0),
                            r.get("current_velocity", 0),
                        ),
                    )
                conn.commit()
            watermark = max((str(row.get("created_at") or "") for row in rows), default="")
            self.upsert_sync_cursor(
                scope="active_video",
                stream="predictions",
                partition_key=bvid,
                watermark=watermark or str(len(rows)),
                status="success",
            )
            return True
        except Exception as e:
            logger.warning("批量同步预测失败 %s: %s", bvid, e, exc_info=True)
            self._sync_error_cursor("predictions", bvid, e)
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
                    (
                        bvid,
                        timestamp,
                        int(data.get("prediction", 0)),
                        data.get("confidence", 0),
                        data.get("valid_algos", 0),
                        data.get("total_algos", 0),
                        interval.get("lower"),
                        interval.get("upper"),
                        interval.get("interval_width_ratio"),
                        int(data.get("surge_correction_applied", False)),
                        data.get("surge_magnitude"),
                        data.get("surge_type", ""),
                    ),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("同步集成预测失败 %s: %s", bvid, e, exc_info=True)
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
            logger.warning("同步共识度失败 %s: %s", bvid, e, exc_info=True)
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
                    (
                        bvid,
                        timestamp,
                        score_data.get("total_score", 0),
                        score_data.get("view_score", 0),
                        score_data.get("interaction_score", 0),
                        score_data.get("favorite_score", 0),
                        score_data.get("coin_score", 0),
                        score_data.get("like_score", 0),
                        score_data.get("correction_a", 0),
                        score_data.get("correction_b", 0),
                        score_data.get("correction_c", 0),
                        score_data.get("correction_d", 0),
                        score_data.get("base_view_score", 0),
                    ),
                )
                conn.commit()
            self.upsert_sync_cursor(
                scope="active_video", stream="weekly_scores", partition_key=bvid, watermark=timestamp, status="success"
            )
            return True
        except Exception as e:
            logger.warning("同步周刊分数失败 %s: %s", bvid, e, exc_info=True)
            self._sync_error_cursor("weekly_scores", bvid, e)
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
                    (
                        bvid,
                        timestamp,
                        score_data.get("total_score", 0),
                        score_data.get("view_score", 0),
                        score_data.get("interaction_score", 0),
                        score_data.get("favorite_score", 0),
                        score_data.get("coin_score", 0),
                        score_data.get("like_score", 0),
                        score_data.get("correction_a", 0),
                        score_data.get("correction_b", 0),
                        score_data.get("correction_c", 0),
                    ),
                )
                conn.commit()
            self.upsert_sync_cursor(
                scope="active_video", stream="yearly_scores", partition_key=bvid, watermark=timestamp, status="success"
            )
            return True
        except Exception as e:
            logger.warning("同步年刊分数失败 %s: %s", bvid, e, exc_info=True)
            self._sync_error_cursor("yearly_scores", bvid, e)
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
                        result["deleted"],
                        result["kept"],
                    )
        except Exception as e:
            logger.warning("中央库预测清理失败: %s", e, exc_info=True)
        return result
