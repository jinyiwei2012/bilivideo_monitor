"""
实时弹幕拉取与持久化模块
======================

基于 B站段式弹幕 API 实现增量弹幕抓取，支持：
- 两阶段拉取：先 dm/web/view 获取总段数 → 再 seg.so 逐段拉取
- Protobuf + XML 双格式自动解析
- WBI 签名新版 API（/x/v2/dm/wbi/web/seg.so）
- DB 持久化进度恢复

用法:
    from core.bilibili_danmaku import DanmakuMonitor
    monitor = DanmakuMonitor(bilibili_api)
    new_count = monitor.fetch_new_danmaku(bvid, cid, video_db, aid=114514)

参考:
    pakku.js (github.com/xmcp/pakku.js)
    bilibili-API-collect (github.com/SocialSisterYi/bilibili-API-collect)
"""

import logging
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── API 端点 ──────────────────────────────────────
_DANMAKU_SEG_URL = "https://api.bilibili.com/x/v2/dm/web/seg.so"
_DANMAKU_WBI_SEG_URL = "https://api.bilibili.com/x/v2/dm/wbi/web/seg.so"
_DANMAKU_VIEW_URL = "https://api.bilibili.com/x/v2/dm/web/view"
_DANMAKU_HISTORY_INDEX_URL = "https://api.bilibili.com/x/v2/dm/history/index"
_DANMAKU_HISTORY_SEG_URL = "https://api.bilibili.com/x/v2/dm/web/history/seg.so"

# ── 拉取参数 ──────────────────────────────────────
_MAX_SEGMENTS = 300          # 兜底上限（6分钟/段，300段=30小时）
_MAX_SEGMENTS_KNOWN_BOGUS = 100  # DmSegConfig.total 固定返回值（最大容量，非实际段数）
_MAX_EMPTY_STREAK = 10       # 连续空段停止阈值
_MAX_ERROR_STREAK = 3        # 连续 API 错误放弃阈值
_SEGMENT_DELAY = 0.3         # 段间请求间隔（秒）


class DanmakuMonitor:
    """视频弹幕增量拉取器。

    两阶段拉取策略：
    1. 调用 dm/web/view (Protobuf) 获取总段数
    2. 从上次进度开始逐段拉取 seg.so (Protobuf → XML 降级)

    进度追踪：内存 _progress + DB get_max_danmaku_segment() 双重保障。
    """

    def __init__(self, api):
        self._api = api
        self._lock = threading.Lock()
        self._progress: Dict[str, int] = {}

    def _make_key(self, bvid: str, cid: int) -> str:
        return f"{bvid}:{cid}"

    def get_last_segment(self, bvid: str, cid: int) -> int:
        """获取上次拉取的段号，-1 表示从未拉取。"""
        return self._progress.get(self._make_key(bvid, cid), -1)

    # ──────────────────────────────────────────────
    #  主入口：增量拉取
    # ──────────────────────────────────────────────

    def fetch_new_danmaku(self, bvid: str, cid: int, video_db=None, aid: int = 0) -> int:
        """增量拉取新弹幕段，返回新增弹幕数量。

        两阶段流程：
        1. GET dm/web/view → 获取 total_segments（准确停止点）
        2. 从 (last_seg+1) 开始逐段 fetch seg.so
        3. Proto/XML 自动检测解析，写入 DB

        Args:
            bvid: 视频 BV 号
            cid: 视频分 P ID
            video_db: VideoDatabase 实例
            aid: 视频 avid（非必须，但新版 API 推荐传入）

        Returns:
            int: 新增弹幕数量
        """
        key = self._make_key(bvid, cid)

        # ── 恢复进度 ──
        with self._lock:
            last_seg = self._progress.get(key, -1)

        if last_seg < 0 and video_db:
            try:
                db_last = video_db.get_max_danmaku_segment()
                if db_last > 0:
                    last_seg = db_last
                    with self._lock:
                        self._progress[key] = db_last
            except Exception:
                logger.debug("[弹幕] 从 DB 恢复进度失败，将从段 1 重新获取")

        # ── 阶段 1: 获取视频弹幕元数据 ──
        view_info = self._fetch_danmaku_view(cid, aid)
        total_segs = view_info.get("total_segments", 0)
        danmaku_count = view_info.get("count", 0)
        page_size_ms = view_info.get("page_size", 360000)

        # 无弹幕的视频直接跳过（count 字段可靠，为 0 表示确实无弹幕）
        if danmaku_count == 0 and view_info:
            logger.debug("[弹幕] %s 弹幕数为 0，跳过拉取", bvid)
            return 0

        # total_segments 可靠性判断：
        # - DmSegConfig.total (field 2) 在 API 中为"最大分页容量"（固定 100），非实际段数
        # - 实际段数 = ceil(视频时长 / page_size_ms)
        # - 若无法获取时长，用空段检测兜底
        if total_segs == _MAX_SEGMENTS_KNOWN_BOGUS:
            # API 返回的是固定值 100，不可信 → 用空段试探
            max_seg = _MAX_SEGMENTS
            total_segs = 0  # 标记为不可信
        elif total_segs > 0:
            max_seg = min(total_segs, _MAX_SEGMENTS)
        else:
            max_seg = _MAX_SEGMENTS

        start_seg = max(1, last_seg + 1)
        if start_seg > max_seg:
            return 0  # 全部已拉取

        logger.info("[弹幕] %s 开始拉取 段 %d-%d (总段数=%d)", bvid, start_seg, max_seg, total_segs or -1)

        # ── 阶段 2: 逐段拉取 ──
        total_new = 0
        empty_streak = 0
        error_streak = 0
        seg = start_seg
        parsed_fmt = None  # 第一次成功解析后锁定格式

        while seg <= max_seg:
            danmaku_list, is_error = self._fetch_segment(cid, seg, aid, prefer_fmt=parsed_fmt)

            if is_error:
                error_streak += 1
                if error_streak >= _MAX_ERROR_STREAK:
                    logger.warning("[弹幕] %s 连续 %d 次 API 错误，段=%d 放弃本轮",
                                   bvid, error_streak, seg)
                    break  # 不前进 seg——该段将在下一轮重试
                time.sleep(1.0)
                continue

            error_streak = 0

            if not danmaku_list:
                # 有可靠段数时不停在空段上（已确认视频长度覆盖）
                if total_segs > 0 and total_segs != _MAX_SEGMENTS_KNOWN_BOGUS:
                    seg += 1
                    if seg % 10 == 0:
                        time.sleep(_SEGMENT_DELAY)
                    continue

                # 无可靠段数时用空段试探停止
                empty_streak += 1
                if empty_streak >= _MAX_EMPTY_STREAK:
                    logger.debug("[弹幕] %s 连续 %d 个空段，停止拉取", bvid, empty_streak)
                    break
                seg += 1
                if seg % 5 == 0:
                    time.sleep(_SEGMENT_DELAY)
                continue

            empty_streak = 0
            if parsed_fmt is None and danmaku_list and danmaku_list[0].get("dmid", 0) > 0:
                parsed_fmt = "proto"

            # 存库
            if video_db:
                self._save_to_db(video_db, bvid, cid, seg, danmaku_list)

            total_new += len(danmaku_list)
            seg += 1
            time.sleep(_SEGMENT_DELAY)

        # 更新进度
        with self._lock:
            self._progress[key] = seg - 1

        if total_new > 0:
            logger.info("[弹幕] %s 新增 %d 条 (段 %d-%d, fmt=%s)",
                         bvid, total_new, start_seg, seg - 1, parsed_fmt or "unknown")
        return total_new

    # ──────────────────────────────────────────────
    #  阶段 1: 获取元数据
    # ──────────────────────────────────────────────

    def _fetch_danmaku_view(self, cid: int, aid: int = 0) -> dict:
        """通过 dm/web/view 获取视频弹幕元数据。

        Returns:
            {
                "total_segments": int,  # DmSegConfig.total（注意：固定 100，非实际段数）
                "page_size": int,       # DmSegConfig.pageSize（每段时长 ms，360000=6min）
                "count": int,           # 实际弹幕总数
                "state": int,           # 弹幕开放状态（0=开放）
            }
            获取失败返回空字典。
        """
        try:
            params = {"type": 1, "oid": cid}
            if aid:
                params["pid"] = aid

            resp = self._api.session.get(
                _DANMAKU_VIEW_URL,
                params=params,
                headers={
                    "User-Agent": self._api.USER_AGENTS[0],
                    "Referer": "https://www.bilibili.com/",
                },
                timeout=10,
            )
            if resp.status_code != 200:
                logger.debug("dm/web/view HTTP %d cid=%d", resp.status_code, cid)
                return {}

            from core.bilibili_danmaku_proto import parse_danmaku_view
            view = parse_danmaku_view(resp.content)
            if view:
                logger.debug("[弹幕] cid=%d count=%d page_size=%d total=%d",
                             cid, view.get("count", 0), view.get("page_size", 0),
                             view.get("total_segments", 0))
            return view
        except Exception as e:
            logger.debug("dm/web/view 失败 cid=%d: %s", cid, e)
            return {}

    # ──────────────────────────────────────────────
    #  阶段 2: 逐段拉取（Proto + XML 双解析）
    # ──────────────────────────────────────────────

    def _fetch_segment(self, cid: int, seg: int, aid: int = 0,
                       prefer_fmt: Optional[str] = None) -> Tuple[List[Dict], bool]:
        """拉取单个弹幕段。使用 WBI 签名新版 API，Proto/XML 自动检测。

        Args:
            cid: 视频 cid
            seg: 段号
            aid: avid（可选）
            prefer_fmt: 已知的响应格式 → 跳过检测直接解析

        Returns:
            (danmaku_list, is_error):
            - (list, False): 成功（列表可能为空）
            - (list, True):  网络/API 错误需重试
        """
        try:
            params = {"type": 1, "oid": cid, "segment_index": seg}
            if aid:
                params["pid"] = aid

            # 使用 WBI 签名新版 API
            params = self._api._wbi_sign(params)

            resp = self._api.session.get(
                _DANMAKU_WBI_SEG_URL,
                params=params,
                headers={
                    "User-Agent": self._api.USER_AGENTS[0],
                    "Referer": "https://www.bilibili.com/",
                },
                timeout=10,
            )
            if resp.status_code == 404:
                return [], False  # 超出视频时长
            if resp.status_code == 412:
                logger.debug("弹幕段 API 412 cid=%s seg=%d", cid, seg)
                return [], True
            if resp.status_code != 200:
                logger.debug("弹幕段 HTTP %d cid=%s seg=%d", resp.status_code, cid, seg)
                return [], True

            # 解析
            from core.bilibili_danmaku_proto import try_parse_danmaku
            if prefer_fmt == "proto":
                from core.bilibili_danmaku_proto import parse_danmaku_segment
                elems = parse_danmaku_segment(resp.content)
                return self._normalize_elems(elems), False
            if prefer_fmt == "xml":
                elems = self._parse_xml(resp.content)
                return elems, False

            elems, fmt = try_parse_danmaku(resp.content)
            if fmt == "none" or elems is None:
                return [], False  # 无法解析但 HTTP 200 → 视为空段
            if fmt == "proto":
                return self._normalize_elems(elems), False
            # fmt == "xml": already in old format
            return elems, False

        except Exception as e:
            logger.debug("拉取弹幕段失败 cid=%s seg=%d: %s", cid, seg, e)
            return [], True

    def _normalize_elems(self, proto_elems: List[Dict]) -> List[Dict]:
        """将 Proto 格式的弹幕字段名统一为 DB 存储格式。

        Proto 字段 → 存储字段:
            id/dmid      → dmid (int64 弹幕唯一ID)
            progress(ms) → timestamp(s)
            midHash      → uid
            ctime        → send_time
            fontsize     → font_size (int)
            likeCount    → like_count (new!)
            pool         → pool (new!)
            dmFrom       → dm_from (new!)
        """
        normalized = []
        for e in proto_elems:
            normalized.append({
                "dmid": e.get("dmid", 0),
                "id_str": e.get("id_str", ""),
                "text": e.get("content", ""),
                "timestamp": e.get("progress", 0) / 1000.0,   # ms → s
                "mode": e.get("mode", 1),
                "fontsize": e.get("fontsize", 25),
                "color": e.get("color", 16777215),
                "send_time": e.get("ctime", 0),
                "weight": e.get("weight", 1),
                "uid": e.get("mid_hash", ""),
                "like_count": e.get("like_count", 0),
                "pool": e.get("pool", 0),
                "dm_from": e.get("dm_from", 0),
            })
        return normalized

    def _parse_xml(self, data: bytes) -> List[Dict]:
        """XML 格式降级解析。"""
        from defusedxml.ElementTree import fromstring as _xml_parse
        try:
            root = _xml_parse(data)
            danmaku = []
            for d in root.findall(".//d"):
                p = d.get("p", "")
                parts = p.split(",")
                danmaku.append({
                    "dmid": 0,
                    "text": (d.text or "").strip(),
                    "timestamp": float(parts[0]) if len(parts) > 0 else 0,
                    "mode": int(parts[1]) if len(parts) > 1 else 1,
                    "fontsize": int(parts[2]) if len(parts) > 2 else 25,
                    "color": int(parts[3]) if len(parts) > 3 else 16777215,
                    "send_time": int(parts[4]) if len(parts) > 4 else 0,
                    "weight": int(parts[6]) if len(parts) > 6 else 1,
                    "uid": parts[7] if len(parts) > 7 else "",
                    "like_count": 0,
                    "pool": 0,
                    "dm_from": 0,
                })
            return danmaku
        except Exception:
            return []

    # ──────────────────────────────────────────────
    #  历史弹幕
    # ──────────────────────────────────────────────

    def fetch_history_index(self, cid: int, month: str) -> List[str]:
        """查询指定月份有哪些日期存在历史弹幕。

        API: GET /x/v2/dm/history/index
        需要登录 (Cookie: SESSDATA)

        Args:
            cid:   视频 cid
            month: 月份，格式 "YYYY-MM"

        Returns:
            日期列表，如 ["2024-06-15", "2024-06-16"]。失败或无弹幕返回空列表。
        """
        try:
            resp = self._api.session.get(
                _DANMAKU_HISTORY_INDEX_URL,
                params={"type": 1, "oid": cid, "month": month},
                headers={
                    "User-Agent": self._api.USER_AGENTS[0],
                    "Referer": "https://www.bilibili.com/",
                },
                timeout=15,
            )
            if resp.status_code != 200:
                logger.debug("历史弹幕索引 HTTP %d cid=%d month=%s", resp.status_code, cid, month)
                return []
            data = resp.json()
            if data.get("code") != 0:
                logger.debug("历史弹幕索引失败 cid=%d month=%s: code=%s msg=%s",
                             cid, month, data.get("code"), data.get("message"))
                return []
            return data.get("data") or []
        except Exception as e:
            logger.debug("历史弹幕索引异常 cid=%d month=%s: %s", cid, month, e)
            return []

    def fetch_history_segment(self, cid: int, date: str) -> List[Dict]:
        """拉取指定日期的一条历史弹幕段。

        API: GET /x/v2/dm/web/history/seg.so
        需要登录。返回 DmSegMobileReply（与实时弹幕相同 Proto 格式）。

        Args:
            cid:  视频 cid
            date: 日期，格式 "YYYY-MM-DD"

        Returns:
            标准化弹幕列表。失败返回空列表。
        """
        try:
            resp = self._api.session.get(
                _DANMAKU_HISTORY_SEG_URL,
                params={"type": 1, "oid": cid, "date": date},
                headers={
                    "User-Agent": self._api.USER_AGENTS[0],
                    "Referer": "https://www.bilibili.com/",
                },
                timeout=15,
            )
            if resp.status_code != 200:
                logger.debug("历史弹幕段 HTTP %d cid=%d date=%s", resp.status_code, cid, date)
                return []

            from core.bilibili_danmaku_proto import parse_danmaku_segment
            elems = parse_danmaku_segment(resp.content)
            if not elems:
                return []
            return self._normalize_elems(elems)
        except Exception as e:
            logger.debug("历史弹幕段异常 cid=%d date=%s: %s", cid, date, e)
            return []

    def fetch_history_danmaku(self, bvid: str, cid: int, video_db=None,
                               month: str = None, on_progress=None) -> int:
        """拉取指定月份的全部历史弹幕并存入 DB。

        两步流程：
        1. GET history/index 获取有弹幕的日期列表
        2. 逐日拉取 history/seg.so（日弹幕只有一个段）

        Args:
            bvid:        视频 BV 号
            cid:         视频 cid
            video_db:    VideoDatabase 实例（存库用）
            month:       月份 "YYYY-MM"，默认当前月
            on_progress: 进度回调 (date: str, count: int, total_dates: int) -> None

        Returns:
            int: 新增弹幕总数
        """
        if month is None:
            from datetime import datetime
            month = datetime.now().strftime("%Y-%m")

        # 1. 获取有弹幕的日期
        dates = self.fetch_history_index(cid, month)
        if not dates:
            logger.info("[历史弹幕] %s %s 无弹幕数据", bvid, month)
            return 0

        logger.info("[历史弹幕] %s 开始拉取 %s (%d 天)", bvid, month, len(dates))

        # 2. 逐日拉取
        total_new = 0
        for i, date in enumerate(dates):
            elems = self.fetch_history_segment(cid, date)
            count = len(elems)

            if elems and video_db:
                # 历史弹幕用 date 作为 segment_index 标识
                self._save_to_db(video_db, bvid, cid, 0, elems)

            total_new += count
            if on_progress:
                on_progress(date, count, len(dates))

            if count > 0:
                logger.debug("[历史弹幕] %s %s: %d 条", bvid, date, count)
            time.sleep(_SEGMENT_DELAY)

        logger.info("[历史弹幕] %s 完成: %d 条 (%d 天)", bvid, total_new, len(dates))
        return total_new

    # ──────────────────────────────────────────────
    #  存库
    # ──────────────────────────────────────────────

    def _save_to_db(self, video_db, bvid: str, cid: int, seg: int, elems: List[Dict]):
        """将弹幕以统一格式写入 DB。"""
        try:
            rows = []
            for d in elems:
                rows.append({
                    "bvid": bvid,
                    "oid": cid,
                    "segment_index": seg,
                    "dmid": d.get("dmid", 0),
                    "id_str": d.get("id_str", ""),
                    "content": d.get("text", ""),
                    "video_ts": d.get("timestamp", 0),
                    "mode": d.get("mode", 1),
                    "font_size": d.get("fontsize", 25),
                    "color": d.get("color", 16777215),
                    "send_time": d.get("send_time", 0),
                    "weight": d.get("weight", 1),
                    "uid": d.get("uid", ""),
                    "like_count": d.get("like_count", 0),
                    "pool": d.get("pool", 0),
                    "dm_from": d.get("dm_from", 0),
                })
            video_db.add_danmaku_batch(rows)
        except Exception as e:
            logger.debug("弹幕存库失败 %s seg=%d: %s", bvid, seg, e)

    # ──────────────────────────────────────────────
    #  进度管理
    # ──────────────────────────────────────────────

    def reset_progress(self, bvid: str, cid: int = 0):
        """重置弹幕拉取进度（强制从头拉取）。"""
        if cid:
            with self._lock:
                self._progress.pop(self._make_key(bvid, cid), None)
        else:
            with self._lock:
                prefix = f"{bvid}:"
                keys = [k for k in self._progress if k.startswith(prefix)]
                for k in keys:
                    self._progress.pop(k, None)

    def get_stats(self, bvid: str, cid: int = 0) -> Dict:
        """获取弹幕拉取统计。"""
        if cid:
            return {"last_segment": self._progress.get(self._make_key(bvid, cid), -1)}
        with self._lock:
            prefix = f"{bvid}:"
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
