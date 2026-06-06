"""中央数据库查询模块"""

import csv
import logging
import os
from typing import List, Dict

from .models import _validate_bvid

logger = logging.getLogger(__name__)


class CentralQuery:
    """Query operations for central database (delegated from Database)"""

    def __init__(self, database):
        self.db = database

    def _run_query(self, sql: str, params: tuple = ()) -> List[Dict]:
        """执行查询并返回字典列表"""
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning("查询失败: %s", e)
            return []

    def _run_video_query(self, bvid: str, sql: str, params: tuple = ()) -> List[Dict]:
        """执行指定视频的查询"""
        return self._run_query(sql, (bvid,) + params)

    def query_monitor_records(
        self, bvid: str, start_time: str = None, end_time: str = None, limit: int = 1000
    ) -> List[Dict]:
        """按时间范围查询监控记录"""
        conditions = ["bvid = ?"]
        params = [bvid]
        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time)
        if end_time:
            conditions.append("timestamp <= ?")
            params.append(end_time)
        where = " AND ".join(conditions)
        return self._run_query(
            f"SELECT * FROM monitor_records WHERE {where} ORDER BY timestamp ASC LIMIT ?",
            params + [limit],
        )

    def search_videos(self, keyword: str = "", field: str = "title", limit: int = 50) -> List[Dict]:
        """搜索视频"""
        valid_fields = {"title", "bvid", "owner_name"}
        if field not in valid_fields:
            return []
        return self._run_query(
            f"SELECT * FROM videos WHERE {field} LIKE ? ORDER BY updated_at DESC LIMIT ?",
            (f"%{keyword}%", limit),
        )

    def get_video_list(self, sort_by: str = "updated_at", order: str = "DESC", limit: int = 100) -> List[Dict]:
        """获取视频列表，支持排序"""
        valid_sort = {"updated_at", "view_count", "created_at", "title", "pubdate"}
        if sort_by not in valid_sort:
            sort_by = "updated_at"
        order = "DESC" if order.upper() == "DESC" else "ASC"
        return self._run_query(
            f"SELECT bvid, title, view_count, like_count, owner_name, updated_at FROM videos ORDER BY {sort_by} {order} LIMIT ?",
            (limit,),
        )

    def get_summary_stats(self) -> Dict:
        """获取数据库汇总统计"""
        stats = {"total_videos": 0, "total_records": 0, "total_predictions": 0}
        try:
            for key, table in [
                ("total_videos", "videos"),
                ("total_records", "monitor_records"),
                ("total_predictions", "predictions"),
            ]:
                rows = self._run_query(f"SELECT COUNT(*) as cnt FROM {table}")
                if rows:
                    stats[key] = rows[0]["cnt"]
        except Exception as e:
            logger.warning("获取统计失败: %s", e)
        return stats

    def export_video_to_csv(self, bvid: str, filepath: str = None) -> str:
        """导出视频数据到 CSV 文件"""
        _validate_bvid(bvid)
        if filepath is None:
            exports_dir = os.path.join(os.path.dirname(self.db.db_path), "exports")
            os.makedirs(exports_dir, exist_ok=True)
            filepath = os.path.join(exports_dir, f"{bvid}.csv")
        try:
            video = self.db.get_video(bvid)
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "BV号",
                        "标题",
                        "UP主",
                        "播放量",
                        "点赞数",
                        "投币数",
                        "分享数",
                        "收藏数",
                        "弹幕数",
                        "评论数",
                        "APP观看人数",
                        "网页观看人数",
                        "总观看人数",
                        "播赞比",
                    ]
                )
                if video:
                    writer.writerow(
                        [
                            video.bvid,
                            video.title,
                            video.owner_name,
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
                            video.like_view_ratio,
                        ]
                    )
            return filepath
        except Exception as e:
            logger.warning("导出失败: %s", e)
            return ""
