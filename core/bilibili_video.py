"""
B站API模块 - 视频操作
视频信息、统计数据、观看人数、弹幕、评论获取
"""

import random
import logging
from typing import Any, Dict, List, Optional, cast

logger = logging.getLogger(__name__)


def get_video_info(self: Any, bvid: str) -> Optional[Dict[str, Any]]:
    params = {"bvid": bvid}
    result = self._request("GET", self.VIDEO_URL, params=params)
    if result:
        return cast(Dict[str, Any], result)
    result = _get_video_info_fallback(self, bvid)
    if result:
        return result
    return _get_video_info_browser_fallback(self, bvid)


def _get_video_info_browser_fallback(self: Any, bvid: str) -> Optional[Dict[str, Any]]:
    try:
        from core.browser_fallback import fetch_video_info_playwright

        return cast(Optional[Dict[str, Any]], fetch_video_info_playwright(bvid))
    except ImportError:
        pass
    except Exception as e:
        logger.debug("Playwright 兜底失败: %s", e)
    return None


def _get_video_info_fallback(self: Any, bvid: str) -> Optional[Dict[str, Any]]:
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


def get_video_stat(self: Any, bvid: str) -> Optional[Dict[str, Any]]:
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


def get_video_viewers(self: Any, bvid: str, cid: Optional[int] = None) -> Optional[Dict[str, Any]]:
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


def _get_video_viewers_fallback(self: Any, bvid: str, cid: int) -> Optional[Dict[str, Any]]:
    try:
        from bilibili_api import sync
        from bilibili_api.video import Video

        v = Video(bvid=bvid)
        online = sync(v.get_online(cid=cid))
        if online:
            return {
                "total": int(online.get("total") or 0),
                "count": int(online.get("count") or 0),
                "show_switch": {},
            }
    except ImportError:
        pass
    except Exception as e:
        logger.debug("bilibili-api 兜底获取在线人数失败: %s", e)
    return None


def get_video_cid(self: Any, bvid: str) -> Optional[int]:
    info = get_video_info(self, bvid)
    if info:
        return info.get("cid")
    return None


def get_video_danmaku(self: Any, oid: int) -> List[Dict[str, Any]]:
    try:
        self._ensure_min_interval()
        idx, proxy, ua = self.proxy_manager.get_proxy_binding()
        request_kwargs = {
            "params": {"oid": oid},
            "headers": {"User-Agent": ua or random.choice(self.USER_AGENTS), "Referer": "https://www.bilibili.com/"},
            "timeout": 15,
        }
        if proxy:
            request_kwargs["proxies"] = proxy
        logger.debug("→ GET %s?oid=%s", self.DANMAKU_URL, oid)
        # 走共享 _do_http_request 管道 (curl_cffi TLS 伪装 + 代理处理)
        resp = self._do_http_request("GET", self.DANMAKU_URL, request_kwargs, cookies=None)
        logger.debug("← GET %s → %s", self.DANMAKU_URL.split("?")[0], resp.status_code)
        if resp.status_code != 200:
            if proxy:
                self.proxy_manager.on_request_failure(idx)
            return []
        from defusedxml.ElementTree import fromstring as _xml_parse

        root = _xml_parse(resp.content)
        danmaku: List[Dict[str, Any]] = []
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


def get_video_comments(self: Any, aid: int, limit: int = 20) -> List[Dict[str, Any]]:
    """顶层评论（委托 ``core.bilibili_comment`` —— ``/x/v2/reply/wbi/main`` 游标翻页）。

    签名与输出契约不变：``limit=0`` 返回全部（有页数保护）；无评论返回空列表；
    元素键为 ``content`` / ``like`` / ``ctime`` / ``uname`` / ``mid``。
    函数内导入以避免 ``core.bilibili_comment`` ↔ ``core.bilibili_api`` 循环依赖。
    """
    from core.bilibili_comment import fetch_top_comments

    return fetch_top_comments(self, aid, limit=limit)


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
