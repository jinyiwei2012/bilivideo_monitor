"""中央总数据库管理类 —— 管理所有视频的汇总数据、里程碑及多库同步

Database 是面向外部调用的门面（Facade），
实际逻辑委托给 CentralCRUD / CentralQuery / CentralBackup 三个子模块。
"""

import sqlite3
import os
import threading
import logging
from typing import ClassVar, Dict, List, Optional

from utils import project_path

from .connection import _ConnectionCtx, get_http_session
from .models import _validate_bvid, VideoInfo, MonitorRecord, PredictionRecord
from .video_db import VideoDatabase
from .central_crud import CentralCRUD
from .central_query import CentralQuery
from .central_backup import CentralBackup
from .central_schema import migrate_central_schema

logger = logging.getLogger(__name__)


class Database:
    """中央总数据库管理类

    管理 bilibili_monitor.db 总库，包含：
    - 所有视频的元数据（videos 表）
    - 汇总的监控记录（monitor_records 表）
    - 预测记录（predictions 表）
    - 里程碑数据（video_milestones 表）
    - 周刊/年刊分数（weekly_scores / yearly_scores 表）
    支持活跃库与备份库之间的双向同步。
    """

    MILESTONE_PERIODS = ["1周", "1月", "1年"]

    _ACTIVE_DIR = project_path("core", "data")
    _BACKUP_DIR: ClassVar[str | None] = None

    @classmethod
    def _get_backup_dir(cls) -> str:
        """获取备份目录路径，优先从 config.DATA_DIR 读取"""
        if cls._BACKUP_DIR is None:
            try:
                from config import DATA_DIR

                cls._BACKUP_DIR = DATA_DIR
            except ImportError:
                cls._BACKUP_DIR = cls._ACTIVE_DIR
        return cls._BACKUP_DIR

    def __init__(self, db_path: str | None = None) -> None:
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

        self._crud = CentralCRUD(self)
        self._query = CentralQuery(self)
        self._backup = CentralBackup(self)

    def _get_connection(self) -> _ConnectionCtx:
        """返回线程安全的连接上下文管理器（兼容 with 语法）"""
        return _ConnectionCtx(self._conn, self._lock)

    def init_database(self) -> None:
        """Initialize the central database through the versioned migrator."""
        with self._get_connection() as conn:
            migrate_central_schema(conn)

    def get_video_db(self, bvid: str) -> VideoDatabase:
        """获取单个视频的独立数据库实例，自动注入中央库引用用于写入兜底"""
        vdb = VideoDatabase(bvid, self.data_dir)
        vdb.set_central_db(self)
        return vdb

    def download_cover(self, bvid: str, pic_url: str) -> str:
        """下载视频封面到集中管理的 cover 目录"""
        try:
            _validate_bvid(bvid)
            from utils.cover_manager import save_cover, get_valid_cover

            local = get_valid_cover(bvid)
            if local is not None:
                return local
            response = get_http_session().get(pic_url, timeout=10)
            if response.status_code == 200:
                path = save_cover(bvid, response.content)
                return path or ""
        except Exception as e:
            logger.warning("下载封面失败 %s: %s", bvid, e)
        return ""

    def wal_checkpoint(self) -> None:
        """周期性 WAL checkpoint，控制 WAL 文件大小"""
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as e:
            logger.debug("WAL checkpoint 失败: %s", e)

    def close(self) -> None:
        """关闭数据库连接，刷新 WAL"""
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.commit()
            self._conn.close()
        except Exception as e:
            logger.warning("关闭数据库失败: %s", e)

    # ── CRUD 委托 ─────────────────────────────────────────────────────

    def get_video(self, bvid: str) -> Optional[VideoInfo]:
        return self._crud.get_video(bvid)

    def add_video(self, video: VideoInfo) -> bool:
        return self._crud.add_video(video)

    def delete_video(self, bvid: str) -> bool:
        return self._crud.delete_video(bvid)

    def sync_video_info(self, bvid: str, video: dict) -> bool:
        return self._crud.sync_video_info(bvid, video)

    def sync_monitor_record(self, bvid: str, record: dict) -> bool:
        return self._crud.sync_monitor_record(bvid, record)

    def sync_predictions(self, bvid: str, rows: list) -> bool:
        return self._crud.sync_predictions(bvid, rows)

    def sync_prediction_ensemble(self, bvid: str, timestamp: str, data: dict) -> bool:
        return self._crud.sync_prediction_ensemble(bvid, timestamp, data)

    def sync_algorithm_coherence(self, bvid: str, timestamp: str, rows: list) -> bool:
        return self._crud.sync_algorithm_coherence(bvid, timestamp, rows)

    def sync_weekly_score(self, bvid: str, timestamp: str, score_data: dict) -> bool:
        return self._crud.sync_weekly_score(bvid, timestamp, score_data)

    def sync_yearly_score(self, bvid: str, timestamp: str, score_data: dict) -> bool:
        return self._crud.sync_yearly_score(bvid, timestamp, score_data)

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
        """Persist a non-controlling synchronization observation."""
        self._crud.upsert_sync_cursor(
            scope=scope,
            stream=stream,
            partition_key=partition_key,
            watermark=watermark,
            status=status,
            last_error=last_error,
        )

    def apply_projection_batch(self, bvid: str, events: list) -> None:
        """Atomically apply decoded outbox events for one video."""
        with self._get_connection() as conn:
            self._crud.apply_projection_batch(conn, bvid, events)

    def delete_monitor_records_before(self, cutoff: str) -> int:
        """按时间清理中央库旧监控记录（委托 CRUD）。"""
        return self._crud.delete_monitor_records_before(cutoff)

    def add_monitor_record(self, record: MonitorRecord) -> bool:
        return self._crud.add_monitor_record(record)

    def get_monitor_history(self, bvid: str, limit: int = 0) -> List[Dict]:
        return self._crud.get_monitor_history(bvid, limit)

    def add_prediction(self, prediction: PredictionRecord) -> bool:
        return self._crud.add_prediction(prediction)

    def get_predictions(self, bvid: str | None = None, algorithm: str | None = None, limit: int = 100) -> List[Dict]:
        return self._crud.get_predictions(bvid, algorithm, limit)

    def upsert_milestone(self, bvid: str, period: str, data: dict) -> bool:
        return self._crud.upsert_milestone(bvid, period, data)

    def get_milestones(self, bvid: str | None = None) -> list:
        return self._crud.get_milestones(bvid)

    def get_all_milestones_grouped(self) -> dict:
        return self._crud.get_all_milestones_grouped()

    def delete_milestone(self, bvid: str, period: str) -> bool:
        return self._crud.delete_milestone(bvid, period)

    # ── 查询委托 ──────────────────────────────────────────────────────

    def query_monitor_records(
        self, bvid: str, start_time: str | None = None, end_time: str | None = None, limit: int = 1000
    ) -> List[Dict]:
        return self._query.query_monitor_records(bvid, start_time, end_time, limit)

    def search_videos(self, keyword: str = "", field: str = "title", limit: int = 50) -> List[Dict]:
        return self._query.search_videos(keyword, field, limit)

    def get_video_list(self, sort_by: str = "updated_at", order: str = "DESC", limit: int = 100) -> List[Dict]:
        return self._query.get_video_list(sort_by, order, limit)

    def get_summary_stats(self) -> Dict:
        return self._query.get_summary_stats()

    def export_video_to_csv(self, bvid: str, filepath: str | None = None) -> str:
        return self._query.export_video_to_csv(bvid, filepath)

    # ── 备份同步委托 ──────────────────────────────────────────────────

    def sync_to_central(self) -> dict:
        return self._backup.sync_to_central()

    def sync_per_video_dbs_to_backup(self) -> None:
        return self._backup.sync_per_video_dbs_to_backup()

    def check_backup_diffs(self) -> List[Dict]:
        return self._backup.check_backup_diffs()

    def cleanup_duplicate_predictions(self) -> dict:
        """清理中央库 predictions 表中的重复行（仅保留最新）"""
        return self._crud.cleanup_duplicate_predictions()


_db: Database | None = None


def get_db() -> Database:
    """获取全局 Database 单例（惰性初始化）"""
    global _db
    if _db is None:
        _db = Database()
    return _db
