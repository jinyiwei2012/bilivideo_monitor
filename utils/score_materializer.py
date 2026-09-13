"""分数惰性物化 — 把 monitor_records 按整点桶归档为周刊/年刊分数（幂等）。

事实前提：``weekly_scores`` / ``yearly_scores`` 存的是「某时刻计数器的排行榜分数」，
不是周/年时间窗聚合；而其全部输入（view/like/coin/favorite/danmaku/reply）都保留在
``monitor_records`` 中，因此任意时点的分数都能重算。

本模块只做两件事：
1. :func:`ensure_scores` — 按 timestamp 水位线增量补齐未归档的整点桶（``INSERT OR REPLACE``，
   幂等：同一 timestamp 只有一行；当前小时桶每次会刷新到该桶内最后一条记录）。
2. :func:`current_scores` — 用最新一条 monitor_record 现算当前分，**不落库**。

设计取舍：
- 入参用 ``VideoDatabase`` 实例而非 bvid —— 所有调用方（详情面板 / 分数中心窗口）本就
  持有实例，避免为拿 bvid 再构造一次数据库。
- 未打开窗口 / 未请求的视频零写入：本模块只在被显式调用时工作。
"""

import logging
from dataclasses import asdict
from typing import Dict, Optional, Tuple

from utils.weekly_score import calculate_from_dict as _calc_weekly
from utils.yearly_score import calculate_yearly_from_dict as _calc_yearly

logger = logging.getLogger(__name__)

_BUCKET_SUFFIX = ":00:00"  # 整点桶：规范化时间戳 "YYYY-MM-DD HH:MM:SS" 的秒位


def _hour_bucket(timestamp: str) -> Optional[str]:
    """把规范时间戳映射到整点桶 "YYYY-MM-DD HH:00:00"；格式不符返回 None。"""
    ts = str(timestamp or "")
    if len(ts) < 13:
        return None
    return ts[:13] + _BUCKET_SUFFIX


def _watermark(video_db) -> str:
    """已归档的最大时间戳（无归档时为空串 → 全量补齐）。"""
    latest = video_db.get_latest_weekly_score()
    return str((latest or {}).get("timestamp", "") or "")


def _bucketed_records(video_db, since: str) -> Dict[str, dict]:
    """取 timestamp > since 的监控记录，按整点桶保留桶内最后一条（返回 ts→record）。"""
    with video_db._get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM monitor_records WHERE timestamp > ? ORDER BY timestamp ASC",
            (since,),
        )
        rows = [dict(r) for r in cur.fetchall()]

    buckets: Dict[str, dict] = {}
    for row in rows:
        bucket = _hour_bucket(row.get("timestamp", ""))
        if bucket is None:
            continue
        buckets[bucket] = row  # 升序遍历 → 覆盖后即桶内最后一条
    return buckets


def _score_dicts(record: dict) -> Tuple[dict, dict]:
    """把一条 monitor_record 折算成 (周刊分数字典, 年刊分数字典)。"""
    data = {
        "view_count": record.get("view_count", 0) or 0,
        "like_count": record.get("like_count", 0) or 0,
        "coin_count": record.get("coin_count", 0) or 0,
        "favorite_count": record.get("favorite_count", 0) or 0,
        "danmaku_count": record.get("danmaku_count", 0) or 0,
        "reply_count": record.get("reply_count", 0) or 0,
    }
    return asdict(_calc_weekly(data)), asdict(_calc_yearly(data))


def ensure_scores(video_db, until: Optional[str] = None) -> Dict[str, int]:
    """按整点桶增量补齐分数归档（幂等）。

    Args:
        video_db: ``VideoDatabase`` 实例
        until: 可选上界（含），只归档 <= until 的桶

    Returns:
        {"computed": 处理的桶数, "written": 实际写入的周刊行数}
    """
    computed = 0
    written = 0
    try:
        since = _watermark(video_db)
        buckets = _bucketed_records(video_db, since)
        for bucket_ts in sorted(buckets):
            if until and bucket_ts > until:
                break
            weekly, yearly = _score_dicts(buckets[bucket_ts])
            computed += 1
            if video_db.add_weekly_score(bucket_ts, weekly):
                written += 1
            video_db.add_yearly_score(bucket_ts, yearly)
    except Exception as e:
        logger.warning("分数归档失败 %s: %s", getattr(video_db, "bvid", ""), e)
    return {"computed": computed, "written": written}


def current_scores(video_db) -> Optional[Tuple[dict, dict]]:
    """用最新一条 monitor_record 现算当前分数（不落库）。

    Returns:
        (周刊分数字典, 年刊分数字典)；无监控记录时返回 None。
    """
    try:
        with video_db._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM monitor_records ORDER BY timestamp DESC LIMIT 1")
            row = cur.fetchone()
        if not row:
            return None
        return _score_dicts(dict(row))
    except Exception as e:
        logger.debug("现算当前分数失败 %s: %s", getattr(video_db, "bvid", ""), e)
        return None
