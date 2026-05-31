"""
B站API模块 - 视频操作
视频信息、统计数据、观看人数、弹幕、评论获取
"""
import math
import random
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def get_video_info(self, bvid: str) -> Optional[Dict]:
    params = {"bvid": bvid}
    result = self._request("GET", self.VIDEO_URL, params=params)
    if result:
        return result
    result = _get_video_info_fallback(self, bvid)
    if result:
        return result
    return _get_video_info_browser_fallback(self, bvid)


def _get_video_info_browser_fallback(self, bvid: str) -> Optional[Dict]:
    try:
        from core.browser_fallback import fetch_video_info_playwright
        return fetch_video_info_playwright(bvid)
    except ImportError:
        pass
    except Exception as e:
        logger.debug("Playwright 兜底失败: %s", e)
    return None


def _get_video_info_fallback(self, bvid: str) -> Optional[Dict]:
    try:
        from bilibili_api import sync
        from bilibili_api.video import Video

        v = Video(bvid=bvid)
        info = sync(v.get_info())
        if not info:
            return None
        stat = info.get("stat", {})
        owner = info.get("owner", {})
        return {
            "title": info.get("title", ""),
            "pic": info.get("pic", ""),
            "desc": info.get("desc", ""),
            "duration": info.get("duration", 0),
            "aid": info.get("aid", 0),
            "bvid": bvid,
            "cid": info.get("cid", 0),
            "pubdate": info.get("pubdate", 0),
            "owner": {"mid": owner.get("mid", 0), "name": owner.get("name", "")},
            "stat": {
                "view": stat.get("view", 0),
                "like": stat.get("like", 0),
                "coin": stat.get("coin", 0),
                "favorite": stat.get("favorite", 0),
                "share": stat.get("share", 0),
                "danmaku": stat.get("danmaku", 0),
                "reply": stat.get("reply", 0),
            },
        }
    except ImportError:
        logger.debug("bilibili-api-python 未安装，跳过兜底")
    except Exception as e:
        logger.debug("bilibili-api-python 兜底获取视频信息失败: %s", e)
    return None


def get_video_stat(self, bvid: str) -> Optional[Dict]:
    video_info = get_video_info(self, bvid)
    if not video_info:
        return None
    stat = video_info.get("stat", {})
    return {
        "bvid": bvid,
        "view": stat.get("view", 0),
        "like": stat.get("like", 0),
        "coin": stat.get("coin", 0),
        "favorite": stat.get("favorite", 0),
        "share": stat.get("share", 0),
        "danmaku": stat.get("danmaku", 0),
        "reply": stat.get("reply", 0),
    }


def get_video_viewers(self, bvid: str, cid: int = None) -> Optional[Dict]:
    try:
        if cid is None:
            video_info = get_video_info(self, bvid)
            if video_info:
                cid = video_info.get("cid", 0)
            else:
                return None

        params = {"bvid": bvid, "cid": cid}
        data = self._request("GET", self.VIEWERS_URL, params=params)

        if data:
            return {
                "total": data.get("total", 0),
                "count": data.get("count", 0),
                "show_switch": data.get("show_switch", {}),
            }
        return _get_video_viewers_fallback(self, bvid, cid)
    except Exception as e:
        logger.error(f"获取观看人数失败: {type(e).__name__}")
    return None


def _get_video_viewers_fallback(self, bvid: str, cid: int) -> Optional[Dict]:
    try:
        from bilibili_api import sync
        from bilibili_api.video import Video

        v = Video(bvid=bvid)
        online = sync(v.get_online(cid=cid))
        if online:
            return {
                "total": str(online.get("total", "0")),
                "count": str(online.get("count", "0")),
                "show_switch": {},
            }
    except ImportError:
        pass
    except Exception as e:
        logger.debug("bilibili-api 兜底获取在线人数失败: %s", e)
    return None


def get_video_cid(self, bvid: str) -> Optional[int]:
    info = get_video_info(self, bvid)
    if info:
        return info.get("cid")
    return None


def get_video_danmaku(self, oid: int) -> List[Dict]:
    try:
        self._ensure_min_interval()
        logger.debug("→ GET %s?oid=%s", self.DANMAKU_URL, oid)
        resp = self.session.get(
            self.DANMAKU_URL,
            params={"oid": oid},
            headers={"User-Agent": random.choice(self.USER_AGENTS), "Referer": "https://www.bilibili.com/"},
            timeout=15,
        )
        logger.debug("← GET %s → %s", self.DANMAKU_URL.split("?")[0], resp.status_code)
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
            danmaku.append(
                {
                    "text": d.text or "",
                    "timestamp": float(parts[0]) if len(parts) > 0 else 0,
                    "mode": int(parts[1]) if len(parts) > 1 else 1,
                    "color": int(parts[2]) if len(parts) > 2 else 16777215,
                }
            )
        return danmaku
    except Exception as e:
        logger.error(f"获取弹幕失败: {e}")
        return []


def get_video_comments(self, aid: int, limit: int = 20) -> List[Dict]:
    max_pages = 50 if limit == 0 else max(1, math.ceil(limit / 20))
    max_pages = min(max_pages, 250)
    all_replies = []

    for page in range(1, max_pages + 1):
        params = {"oid": aid, "type": 1, "pn": page, "ps": 20, "sort": 2}
        params = self._wbi_sign(params)
        data = self._request("GET", self.COMMENT_URL, params=params)
        if not data or "replies" not in data or not data["replies"]:
            break

        for r in data["replies"]:
            all_replies.append(
                {
                    "content": r.get("content", {}).get("message", ""),
                    "like": r.get("like", 0),
                    "ctime": r.get("ctime", 0),
                    "uname": r.get("member", {}).get("uname", ""),
                    "mid": r.get("mid", 0),
                }
            )

        if limit > 0 and len(all_replies) >= limit:
            return all_replies[:limit]

    return all_replies[:limit] if limit > 0 else all_replies


class _VideoMixin:
    get_video_info = get_video_info
    _get_video_info_browser_fallback = _get_video_info_browser_fallback
    _get_video_info_fallback = _get_video_info_fallback
    get_video_stat = get_video_stat
    get_video_viewers = get_video_viewers
    _get_video_viewers_fallback = _get_video_viewers_fallback
    get_video_cid = get_video_cid
    get_video_danmaku = get_video_danmaku
    get_video_comments = get_video_comments
