"""
实时弹幕拉取与持久化模块
======================

基于 B站段式弹幕 API（/x/v2/dm/web/seg.so）实现增量弹幕抓取。
每个视频的弹幕按 6 分钟一段存储，本模块追踪每个视频已拉取的段号，
后续轮询时只拉取新增的段。

弹幕存储到 per-video SQLite 数据库的 danmaku_records 表中，
供弹幕分析模块使用。

用法:
    from core.bilibili_danmaku import DanmakuMonitor

    monitor = DanmakuMonitor(bilibili_api, video_db)
    new_count = monitor.fetch_new_danmaku(bvid, cid)
"""

import logging
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)

# 段式弹幕 API 端点
_DANMAKU_SEG_URL = "https://api.bilibili.com/x/v2/dm/web/seg.so"
# 每个视频最多拉取的段数上限（6分钟/段，100段=10小时覆盖）
_MAX_SEGMENTS = 300


class DanmakuMonitor:
    """视频弹幕增量拉取器。

    使用段式 API 按 6 分钟为一段拉取弹幕，
    内部追踪每个 (bvid, cid) 的已拉取段号避免重复。
    """

    def __init__(self, api):
        """
        Args:
            api: BilibiliAPI 实例
        """
        self._api = api
        self._lock = threading.Lock()
        # 追踪每个视频的段落进度: (bvid, cid) -> last_segment_index
        self._progress: Dict[str, int] = {}

    def _make_key(self, bvid: str, cid: int) -> str:
        return f"{bvid}:{cid}"

    def get_last_segment(self, bvid: str, cid: int) -> int:
        """获取上次拉取的段号，-1 表示从未拉取。"""
        key = self._make_key(bvid, cid)
        return self._progress.get(key, -1)

    def fetch_new_danmaku(self, bvid: str, cid: int, video_db=None) -> int:
        """增量拉取新弹幕段，返回新增弹幕数量。

        流程：
        1. 查询上次已拉取的段号
        2. 从段号 1 开始拉取，跳过已有段
        3. 新弹幕写入 video_db.danmaku_records 表
        4. 段号达到上限或连续空段 3 次时停止

        Args:
            bvid: 视频 BV 号
            cid: 视频分 P ID
            video_db: VideoDatabase 实例（可选，不传则不存库）

        Returns:
            int: 新增弹幕数量
        """
        key = self._make_key(bvid, cid)
        with self._lock:
            last_seg = self._progress.get(key, -1)

        total_new = 0
        empty_streak = 0
        seg = max(1, last_seg + 1)

        while seg <= _MAX_SEGMENTS:
            danmaku_list = self._fetch_segment(cid, seg)
            if not danmaku_list:
                empty_streak += 1
                if empty_streak >= 3:
                    break  # 连续 3 段为空，认为视频弹幕已拉完
                seg += 1
                continue
            empty_streak = 0

            # 存库
            if video_db:
                try:
                    rows = [
                        {
                            "bvid": bvid,
                            "oid": cid,
                            "segment_index": seg,
                            "content": d["text"],
                            "video_ts": d.get("timestamp", 0),
                            "mode": d.get("mode", 1),
                            "font_size": d.get("fontsize", 25),
                            "color": d.get("color", 16777215),
                            "send_time": d.get("send_time", 0),
                            "weight": d.get("weight", 1),
                            "uid": d.get("uid", ""),
                        }
                        for d in danmaku_list
                    ]
                    video_db.add_danmaku_batch(rows)
                except Exception as e:
                    logger.debug("弹幕存库失败 %s seg=%d: %s", bvid, seg, e)

            total_new += len(danmaku_list)
            seg += 1

        # 更新进度
        with self._lock:
            self._progress[key] = seg - 1

        if total_new > 0:
            logger.info("[弹幕] %s 新增 %d 条 (段 %d-%d)", bvid, total_new,
                         max(1, last_seg + 1), seg - 1)
        return total_new

    def _fetch_segment(self, cid: int, seg: int) -> List[Dict]:
        """拉取单个弹幕段，返回弹幕列表。"""
        try:
            resp = self._api.session.get(
                _DANMAKU_SEG_URL,
                params={"oid": cid, "segment_index": seg},
                headers={
                    "User-Agent": self._api.USER_AGENTS[0],
                    "Referer": "https://www.bilibili.com/",
                },
                timeout=10,
            )
            if resp.status_code != 200:
                return []

            try:
                from defusedxml.ElementTree import fromstring as _xml_parse
            except ImportError:
                import xml.etree.ElementTree as _ET
                _xml_parse = _ET.fromstring

            root = _xml_parse(resp.content)
            danmaku = []
            for d in root.findall(".//d"):
                p = d.get("p", "")
                parts = p.split(",")
                danmaku.append({
                    "text": (d.text or "").strip(),
                    "timestamp": float(parts[0]) if len(parts) > 0 else 0,
                    "mode": int(parts[1]) if len(parts) > 1 else 1,
                    "fontsize": int(parts[2]) if len(parts) > 2 else 25,
                    "color": int(parts[3]) if len(parts) > 3 else 16777215,
                    "send_time": int(parts[4]) if len(parts) > 4 else 0,
                    "weight": int(parts[6]) if len(parts) > 6 else 1,
                    "uid": parts[7] if len(parts) > 7 else "",
                })
            return danmaku
        except Exception as e:
            logger.debug("拉取弹幕段失败 cid=%s seg=%d: %s", cid, seg, e)
            return []

    def reset_progress(self, bvid: str, cid: int = 0):
        """重置弹幕拉取进度（强制从头拉取）。"""
        if cid:
            key = self._make_key(bvid, cid)
            with self._lock:
                self._progress.pop(key, None)
        else:
            # 清除该视频所有 cid 的进度
            with self._lock:
                prefix = f"{bvid}:"
                keys = [k for k in self._progress if k.startswith(prefix)]
                for k in keys:
                    self._progress.pop(k, None)

    def get_stats(self, bvid: str, cid: int = 0) -> Dict:
        """获取弹幕拉取统计。"""
        if cid:
            key = self._make_key(bvid, cid)
            return {"last_segment": self._progress.get(key, -1)}
        prefix = f"{bvid}:"
        with self._lock:
            segs = {k: v for k, v in self._progress.items() if k.startswith(prefix)}
        return {"segments": segs, "count": len(segs)}


# ── 模块级单例 ──
_danmaku_monitor: Optional[DanmakuMonitor] = None
_danmaku_lock = threading.Lock()


def get_danmaku_monitor(api=None) -> DanmakuMonitor:
    """获取全局弹幕监控单例。"""
    global _danmaku_monitor
    if _danmaku_monitor is None:
        with _danmaku_lock:
            if _danmaku_monitor is None:
                if api is None:
                    from core import bilibili_api
                    api = bilibili_api
                _danmaku_monitor = DanmakuMonitor(api)
    return _danmaku_monitor
