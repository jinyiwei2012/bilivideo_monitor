"""
B站 API 模块 — 视频操作 (_VideoMixin)
=======================================

本模块提供 B站 视频相关的所有 API 操作，通过 Mixin 模式注入到 BilibiliAPI 中。

主要功能：
  1. get_video_info         — 获取视频基本信息（标题、描述、UP主、统计数据）
  2. get_video_stat         — 获取视频统计摘要（播放、点赞、投币等 7 项核心指标）
  3. get_video_viewers      — 获取实时观看人数（总人数 + Web端人数）
  4. get_video_cid          — 获取视频的 cid（分P ID）
  5. get_video_danmaku      — 获取弹幕列表（解析 XML 格式）
  6. get_video_comments     — 获取评论列表（支持分页 + WBI 签名）

多级兜底策略：
  自有 API → bilibili-api-python 库 → Playwright 无头浏览器（最后兜底）
  每个数据源使用不同的 HTTP 栈/TLS 指纹，单源被限流不影响其他源。
"""
import math
import random
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def get_video_info(self, bvid: str) -> Optional[Dict]:
    """获取视频基本信息（三级兜底）

    优先级：
      1. 自有 API 请求 (self._request → /x/web-interface/view)
      2. bilibili-api-python 库兜底 (_get_video_info_fallback)
      3. Playwright 无头浏览器兜底 (_get_video_info_browser_fallback)

    Args:
        bvid: 视频 BV 号

    Returns:
        视频信息字典，包含 title, desc, pic, duration, aid, bvid, cid,
        pubdate, owner, stat 等字段
    """
    params = {"bvid": bvid}
    result = self._request("GET", self.VIDEO_URL, params=params)
    if result:
        return result
    result = _get_video_info_fallback(self, bvid)
    if result:
        return result
    return _get_video_info_browser_fallback(self, bvid)


def _get_video_info_browser_fallback(self, bvid: str) -> Optional[Dict]:
    """Playwright 无头浏览器兜底：模拟真实用户访问视频页面解析数据

    这是最终兜底方案—当所有 API 方式均被 412 限制时启动 Chrome 无头浏览器
    访问真实的 B站视频页面，从 HTML 中解析视频信息。

    Args:
        bvid: 视频 BV 号

    Returns:
        视频信息字典，失败返回 None
    """
    try:
        from core.browser_fallback import fetch_video_info_playwright
        return fetch_video_info_playwright(bvid)
    except ImportError:
        pass
    except Exception as e:
        logger.debug("Playwright 兜底失败: %s", e)
    return None


def _get_video_info_fallback(self, bvid: str) -> Optional[Dict]:
    """使用 bilibili-api-python 库兜底获取视频信息

    bilibili-api-python 是一个社区维护的 B站 API 封装库，
    HTTP 栈和我们的自有实现不同，可作为独立数据源使用。

    Args:
        bvid: 视频 BV 号

    Returns:
        统一格式的视频信息字典，失败返回 None
    """
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
    """获取视频核心统计指标摘要

    先通过 get_video_info 获取完整信息，再提取统计数据。
    返回 7 项核心指标：播放、点赞、投币、收藏、分享、弹幕、评论。

    Args:
        bvid: 视频 BV 号

    Returns:
        统计数据字典，包含 bvid, view, like, coin, favorite, share, danmaku, reply
    """
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


def get_video_viewers(self, bvid: str, cid: Optional[int] = None) -> Optional[Dict]:
    """获取视频实时观看人数

    如果未提供 cid，会先通过 get_video_info 自动获取。

    Args:
        bvid: 视频 BV 号
        cid: 视频分P ID（可选，自动获取）

    Returns:
        观看人数字典，包含:
          - total: 总在线人数（Web + App）
          - count: Web 端在线人数
          - show_switch: 显示开关配置
    """
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
    """使用 bilibili-api-python 库兜底获取在线观看人数

    Args:
        bvid: 视频 BV 号
        cid: 视频分P ID

    Returns:
        观看人数字典，失败返回 None
    """
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
    """获取视频的 cid（分P ID）

    cid 是 B站 视频系统中唯一标识一个分P（视频分段）的 ID。
    单P 视频只有一个 cid，多P 视频每个分段都有独立的 cid。

    Args:
        bvid: 视频 BV 号

    Returns:
        cid 整数，失败返回 None
    """
    info = get_video_info(self, bvid)
    if info:
        return info.get("cid")
    return None


def get_video_danmaku(self, oid: int) -> List[Dict]:
    """获取视频弹幕列表（解析 B站 原生 XML 格式）

    B站 弹幕接口返回的是 XML 格式数据（不是 JSON）。
    每个 <d> 元素代表一条弹幕，p 属性包含弹幕的元数据。

    p 属性格式（逗号分隔）：时间戳,模式,字号,颜色,发送时间,弹幕池,用户ID,rowID

    Args:
        oid: 弹幕对象 ID（视频的 aid 或 cid）

    Returns:
        弹幕列表，每条弹幕包含 text, timestamp, mode, color 字段
    """
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
        # 优先使用 defusedxml（安全 XML 解析器），不可用时回退标准库
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
                    "color": int(parts[2]) if len(parts) > 2 else 16777215,  # 默认白色
                }
            )
        return danmaku
    except Exception as e:
        logger.error(f"获取弹幕失败: {e}")
        return []


def get_video_comments(self, aid: int, limit: int = 20) -> List[Dict]:
    """获取视频评论列表（分页获取，带 WBI 签名）

    每条评论包含：内容、点赞数、发送时间、发送者用户名和 UID。

    Args:
        aid: 视频的 aid（av号对应的数字 ID）
        limit: 返回的最大评论数（0 表示不限制，实际上限 5000 条）

    Returns:
        评论列表，每条评论含 content, like, ctime, uname, mid 字段
    """
    # 每页固定 20 条，计算最大页码
    max_pages = 50 if limit == 0 else max(1, math.ceil(limit / 20))
    max_pages = min(max_pages, 250)  # 安全上限：最多 250 页 = 5000 条
    all_replies = []

    for page in range(1, max_pages + 1):
        params = {"oid": aid, "type": 1, "pn": page, "ps": 20, "sort": 2}
        params = self._wbi_sign(params)  # 评论接口需要 WBI 签名
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
    """视频 Mixin 类 — 将所有模块级函数通过类属性注入到 BilibiliAPI"""
    get_video_info = get_video_info
    _get_video_info_browser_fallback = _get_video_info_browser_fallback
    _get_video_info_fallback = _get_video_info_fallback
    get_video_stat = get_video_stat
    get_video_viewers = get_video_viewers
    _get_video_viewers_fallback = _get_video_viewers_fallback
    get_video_cid = get_video_cid
    get_video_danmaku = get_video_danmaku
    get_video_comments = get_video_comments
