"""
中央数据库查询与导出模块
========================
本模块封装了对中央总数据库的只读查询操作，作为 Database 的委托子模块。
提供监控记录时间范围查询、视频搜索、视频列表排序、汇总统计
以及 CSV 数据导出等功能。

所有查询都包含完整的异常捕获和日志记录，确保查询失败返回空结果
而非抛出异常。
"""
import csv
import logging
import os
from typing import List, Dict

from .models import _validate_bvid

# ── 模块级日志 ────────────────────────────────────────────────────
logger = logging.getLogger(__name__)


class CentralQuery:
    """中央数据库的查询操作管理器

    作为 Database 的委托子模块，负责以下只读操作：
    - 监控记录查询（支持时间范围过滤）
    - 视频搜索（按标题/BV号/UP主名称模糊搜索）
    - 视频列表（支持排序和分页）
    - 数据库汇总统计（视频数/记录数/预测数）
    - CSV 数据导出
    所有查询仅读取活跃库，不访问备份库。
    """

    def __init__(self, database):
        """
        初始化查询管理器

        Args:
            database: Database 实例引用，用于访问数据库连接
        """
        self.db = database

    def _run_query(self, sql: str, params: tuple = ()) -> List[Dict]:
        """执行查询并返回字典列表

        内部使用线程安全的连接上下文执行 SQL，将结果转换为字典列表。

        Args:
            sql: SQL 查询语句
            params: 查询参数元组

        Returns:
            字典列表，查询失败返回空列表
        """
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning("查询失败: %s", e)
            return []

    def _run_video_query(self, bvid: str, sql: str, params: tuple = ()) -> List[Dict]:
        """执行指定视频的查询

        在 SQL 参数前自动追加 bvid 参数。

        Args:
            bvid: BV 号
            sql: SQL 查询语句（应包含 ? 占位符用于 bvid）
            params: 额外的查询参数元组

        Returns:
            字典列表
        """
        return self._run_query(sql, (bvid,) + params)

    def query_monitor_records(
        self, bvid: str, start_time: str = None, end_time: str = None, limit: int = 1000
    ) -> List[Dict]:
        """按时间范围查询监控记录

        支持可选的起始时间和结束时间过滤。结果按时间戳升序排列。

        Args:
            bvid: BV 号
            start_time: 起始时间字符串（可选，格式如 "2024-01-01 00:00:00"）
            end_time: 结束时间字符串（可选）
            limit: 返回条数限制

        Returns:
            监控记录字典列表
        """
        # ── 动态构建 WHERE 条件 ─────────────────────────────────
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
        """搜索视频

        在指定字段中进行模糊搜索（LIKE %keyword%）。

        Args:
            keyword: 搜索关键词
            field: 搜索字段（可选 "title"、"bvid"、"owner_name"）
            limit: 返回条数限制

        Returns:
            匹配的视频字典列表，按 updated_at 倒序
        """
        # ── 白名单校验搜索字段，防止 SQL 注入 ────────────────────
        valid_fields = {"title", "bvid", "owner_name"}
        if field not in valid_fields:
            return []
        return self._run_query(
            f"SELECT * FROM videos WHERE {field} LIKE ? ORDER BY updated_at DESC LIMIT ?",
            (f"%{keyword}%", limit),
        )

    def get_video_list(self, sort_by: str = "updated_at", order: str = "DESC", limit: int = 100) -> List[Dict]:
        """获取视频列表，支持排序

        Args:
            sort_by: 排序字段（可选 "updated_at"、"view_count"、"created_at"、"title"、"pubdate"）
            order: 排序方向（"ASC" 或 "DESC"，默认 "DESC"）
            limit: 返回条数限制

        Returns:
            视频摘要字典列表（含 bvid、title、view_count、like_count、owner_name、updated_at）
        """
        # ── 白名单校验排序字段和方向，防止 SQL 注入 ──────────────
        valid_sort = {"updated_at", "view_count", "created_at", "title", "pubdate"}
        if sort_by not in valid_sort:
            sort_by = "updated_at"  # 非法字段回退到默认值
        order = "DESC" if order.upper() == "DESC" else "ASC"
        return self._run_query(
            f"SELECT bvid, title, view_count, like_count, owner_name, updated_at FROM videos ORDER BY {sort_by} {order} LIMIT ?",
            (limit,),
        )

    def get_summary_stats(self) -> Dict:
        """获取数据库汇总统计

        统计总量级指标：视频总数、监控记录总数、预测记录总数。

        Returns:
            包含 total_videos、total_records、total_predictions 的字典
        """
        stats = {"total_videos": 0, "total_records": 0, "total_predictions": 0}
        try:
            # ── 逐表统计行数 ────────────────────────────────────
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
        """导出视频数据到 CSV 文件

        导出指定视频的元数据到 CSV 文件，包含中文列名。

        Args:
            bvid: BV 号
            filepath: 目标 CSV 文件路径（None 则自动生成到 data/exports/<BV>.csv）

        Returns:
            导出的文件路径，失败返回空字符串
        """
        _validate_bvid(bvid)  # 校验 BV 号格式
        if filepath is None:
            # 自动生成导出路径
            exports_dir = os.path.join(os.path.dirname(self.db.db_path), "exports")
            os.makedirs(exports_dir, exist_ok=True)
            filepath = os.path.join(exports_dir, f"{bvid}.csv")
        try:
            # 获取视频元数据
            video = self.db.get_video(bvid)
            # 使用 utf-8-sig 编码（带 BOM），确保 Excel 正确识别中文
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                # ── 写入中文表头 ────────────────────────────────
                writer.writerow([
                    "BV号", "标题", "UP主", "播放量", "点赞数", "投币数",
                    "分享数", "收藏数", "弹幕数", "评论数", "APP观看人数",
                    "网页观看人数", "总观看人数", "播赞比",
                ])
                if video:
                    writer.writerow([
                        video.bvid, video.title, video.owner_name,
                        video.view_count, video.like_count, video.coin_count,
                        video.share_count, video.favorite_count, video.danmaku_count,
                        video.reply_count, video.viewers_app, video.viewers_web,
                        video.viewers_total, video.like_view_ratio,
                    ])
            return filepath
        except Exception as e:
            logger.warning("导出失败: %s", e)
            return ""
