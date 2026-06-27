"""
视频数据库 — 周刊/年刊分数操作 Mixin

从 video_db.py 提取的分数相关方法，作为 Mixin 被 VideoDatabase 继承。
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class _ScoreOpsMixin:
    """周刊/年刊分数的增删查操作（需要 self._get_connection, self._lock, self._mirror_conn, self.bvid）"""

    # ── 镜像同步（内部方法）──────────────────────────────

    def _mirror_add_weekly_score(self, timestamp: str, score_data: dict):
        """将周刊分数同步写入镜像数据库"""
        if not self._mirror_conn:
            return
        try:
            with self._lock:
                self._mirror_conn.execute(
                    """
                    INSERT INTO weekly_scores
                    (timestamp, total_score, view_score, interaction_score,
                     favorite_score, coin_score, like_score,
                     correction_a, correction_b, correction_c, correction_d,
                     base_view_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
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
                self._mirror_conn.commit()
        except Exception as e:
            logger.debug("镜像添加周刊分数失败 %s: %s", self.bvid, e)

    def _mirror_add_yearly_score(self, timestamp: str, score_data: dict):
        """将年刊分数同步写入镜像数据库"""
        if not self._mirror_conn:
            return
        try:
            with self._lock:
                self._mirror_conn.execute(
                    """
                    INSERT INTO yearly_scores
                    (timestamp, total_score, view_score, interaction_score,
                     favorite_score, coin_score, like_score,
                     correction_a, correction_b, correction_c)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
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
                self._mirror_conn.commit()
        except Exception as e:
            logger.debug("镜像添加年刊分数失败 %s: %s", self.bvid, e)

    # ── 周刊分数 ──────────────────────────────────────

    def add_weekly_score(self, timestamp: str, score_data: dict) -> bool:
        """添加周刊分数记录"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO weekly_scores
                    (timestamp, total_score, view_score, interaction_score,
                     favorite_score, coin_score, like_score,
                     correction_a, correction_b, correction_c, correction_d,
                     base_view_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
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
            self._mirror_add_weekly_score(timestamp, score_data)
            return True
        except Exception as e:
            logger.warning("添加周刊分数记录失败 %s: %s", self.bvid, e, exc_info=True)
            return False

    def get_weekly_scores(self, limit: int = 0) -> list:
        """获取周刊分数历史（最新在前）"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if limit and limit > 0:
                    cursor.execute("SELECT * FROM weekly_scores ORDER BY timestamp DESC LIMIT ?", (limit,))
                else:
                    cursor.execute("SELECT * FROM weekly_scores ORDER BY timestamp DESC")
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning("获取周刊分数记录失败 %s: %s", self.bvid, e, exc_info=True)
            return []

    def get_latest_weekly_score(self) -> Optional[Dict]:
        """获取最新一条周刊分数"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM weekly_scores ORDER BY timestamp DESC LIMIT 1")
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception:
            return None

    # ── 年刊分数 ──────────────────────────────────────

    def add_yearly_score(self, timestamp: str, score_data: dict) -> bool:
        """添加年刊分数记录"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO yearly_scores
                    (timestamp, total_score, view_score, interaction_score,
                     favorite_score, coin_score, like_score,
                     correction_a, correction_b, correction_c)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
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
            self._mirror_add_yearly_score(timestamp, score_data)
            return True
        except Exception as e:
            logger.warning("添加年刊分数记录失败 %s: %s", self.bvid, e, exc_info=True)
            return False

    def get_yearly_scores(self, limit: int = 0) -> list:
        """获取年刊分数历史（最新在前）"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if limit and limit > 0:
                    cursor.execute("SELECT * FROM yearly_scores ORDER BY timestamp DESC LIMIT ?", (limit,))
                else:
                    cursor.execute("SELECT * FROM yearly_scores ORDER BY timestamp DESC")
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning("获取年刊分数记录失败 %s: %s", self.bvid, e, exc_info=True)
            return []

    def get_latest_yearly_score(self) -> Optional[Dict]:
        """获取最新一条年刊分数"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM yearly_scores ORDER BY timestamp DESC LIMIT 1")
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.debug("获取最新年刊分数失败: %s", e)
            return None
