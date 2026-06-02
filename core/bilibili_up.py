"""
B站 API 模块 — UP 主操作 (_UpMixin)
=====================================

本模块提供 B站 UP 主（视频创作者）相关的所有 API 操作。

主要功能：
  1. search_up_users      — 搜索 UP 主（WBI 签名 + 多源兜底）
  2. get_up_info          — 获取 UP 主基本信息（名称、头像、粉丝数、直播状态）
  3. get_up_stat          — 获取 UP 主统计数据（总播放、总点赞、粉丝变化）
  4. get_up_videos        — 获取 UP 主的视频投稿列表

多源兜底策略：
  search_up_users → up_fetcher 多源 → 自有 WBI API
  get_up_info      → up_fetcher 多源 → 自有 _request_public
  get_up_stat      → up_fetcher 多源 → 自有 _request → 视频汇总兜底

每种操作都集成了 core.up_fetcher 模块的多源获取器，
优先使用 bilibili-api-python 或 curl_cffi 作为独立数据源。
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def search_up_users(self, keyword: str, page: int = 1, order: str = "fans") -> List[Dict]:
    """搜索 UP 主（多源兜底）

    通过 core.up_fetcher 模块的多源搜索器，
    依次尝试 bilibili-api-python → curl_cffi → 自有 API。
    单个数据源被 412 限流时自动切换到下一源。

    Args:
        keyword: 搜索关键词
        page: 页码（从 1 开始）
        order: 排序方式（"fans"=粉丝数排序）

    Returns:
        搜索结果列表，每个元素含 mid, uname, fans, videos 等字段
    """
    from core.up_fetcher import search_up_users_multi

    return search_up_users_multi(keyword, page, lambda kw, p: _own_search_up_users(self, kw, p))


def _own_search_up_users(self, keyword: str, page: int) -> List[Dict]:
    """自有 API 实现的 UP 主搜索（WBI 签名 + 公共 API 兜底）

    优先使用 WBI 签名接口（/x/web-interface/wbi/search/type），
    失败时回退到公共搜索接口（/x/web-interface/search/type）。

    Args:
        keyword: 搜索关键词
        page: 页码

    Returns:
        搜索结果列表
    """
    # 路径 1：WBI 签名搜索（需要登录态）
    url = f"{self.BASE_URL}/x/web-interface/wbi/search/type"
    params = {
        "search_type": "bili_user",
        "keyword": keyword,
        "page": page,
        "user_type": 1,
    }
    params = self._wbi_sign(params)
    data = self._request("GET", url, params=params)

    if data is None:
        # 路径 2：公共搜索（免 WBI 签名，使用 _request_public）
        url2 = f"{self.BASE_URL}/x/web-interface/search/type"
        params2 = {"search_type": "bili_user", "keyword": keyword, "page": page}
        data = self._request_public("GET", url2, params=params2)

    if data and "result" in data:
        return data["result"]
    return []


def get_up_info(self, uid: int) -> Optional[Dict]:
    """获取 UP 主基本信息（多源兜底）

    通过 core.up_fetcher 的多源获取器获取 UP 主信息，
    包含直播状态和直播房间信息。

    Args:
        uid: UP 主 UID

    Returns:
        UP 主信息字典，包含 uid, name, face, sign, level,
        follower_count, video_count, official_verify, nameplate, live_room
    """
    from core.up_fetcher import get_up_info_multi

    return get_up_info_multi(uid, lambda u: _own_get_up_info(self, u))


def _own_get_up_info(self, uid: int) -> Optional[Dict]:
    """自有 API 实现的 UP 主信息获取

    通过公共 API 获取空间信息（/x/space/acc/info），
    失败时回退到带 Cookie 的主请求通道。

    Args:
        uid: UP 主 UID

    Returns:
        UP 主信息字典，包含直播状态信息
    """
    # 先用公共 API（免 Cookie，轻量快速）
    data = self._request_public("GET", f"{self.BASE_URL}/x/space/acc/info", params={"mid": uid})
    if data is None:
        # 公共 API 不可用，回退到主请求通道（带 Cookie）
        data = self._request("GET", f"{self.BASE_URL}/x/space/acc/info", params={"mid": uid})
    if data:
        lr = data.get("live_room", {})
        return {
            "uid": data.get("mid", uid),
            "name": data.get("name", ""),
            "face": data.get("face", ""),
            "sign": data.get("sign", ""),
            "level": data.get("level", 0),
            "follower_count": data.get("fans", 0) or data.get("follower", 0),
            "video_count": data.get("video_count", data.get("videos", 0)),
            "official_verify": data.get("official_verify", {}),
            "nameplate": data.get("nameplate", {}),
            "live_room": {
                "roomid": lr.get("roomid", 0),
                "live_status": lr.get("liveStatus", 0),
                "live_title": lr.get("title", ""),
                "live_cover": lr.get("cover", ""),
                "live_url": lr.get("url", ""),
            } if lr else None,
        }
    return None


def get_up_stat(self, uid: int) -> Optional[Dict]:
    """获取 UP 主统计数据（多源兜底）

    通过 core.up_fetcher 的多源获取器获取统计信息。

    Args:
        uid: UP 主 UID

    Returns:
        UP 主统计字典，包含 total_views, total_likes, follower_change, follower_count
    """
    from core.up_fetcher import get_up_stat_multi

    return get_up_stat_multi(uid, lambda u: _own_get_up_stat(self, u))


def _own_get_up_stat(self, uid: int) -> Optional[Dict]:
    """自有 API 实现的 UP 主统计获取

    优先使用 upstat 接口（/x/space/upstat），
    失败时回退到公共 API，再失败则通过视频列表汇总计算。

    目标 UP 主的 /x/space/upstat 接口可能返回 412，
    此时自动回退到二级方案。

    Args:
        uid: UP 主 UID

    Returns:
        统计数据字典
    """
    # 一级方案：专用 upstat 接口
    data = self._request("GET", f"{self.BASE_URL}/x/space/upstat", params={"mid": uid})
    if data is None:
        # 二级方案：公共 API
        data = self._request_public("GET", f"{self.BASE_URL}/x/space/upstat", params={"mid": uid})
    if data:
        return {
            "total_views": data.get("archive", {}).get("view", 0),
            "total_likes": data.get("likes", 0) or data.get("archive", {}).get("like", 0),
            "follower_change": data.get("follower_change", data.get("follower", 0)),
            "follower_count": (
                data.get("follower", {}).get("follower", 0)
                if isinstance(data.get("follower"), dict)
                else data.get("follower", 0)
            ),
        }
    # 三级方案：从视频列表逐页汇总（最慢但最可靠）
    logger.info("upstat 接口不可用，尝试从视频列表汇总总播放量 UID:%s", uid)
    return _calc_up_stat_from_videos(self, uid)


def _calc_up_stat_from_videos(self, uid: int, max_pages: int = 5) -> Optional[Dict]:
    """从 UP 主的视频投稿列表逐页汇总总播放量和总点赞数

    当 upstat 接口不可用时作为兜底方案。
    通过 /x/space/arc/search 接口逐页获取视频列表，
    累加每个视频的播放量和点赞数。

    Args:
        uid: UP 主 UID
        max_pages: 最大翻页数（每页 30 条，默认 5 页 = 150 条）

    Returns:
        含 total_views 和 total_likes 的字典，失败返回 None
    """
    total_views = 0
    total_likes = 0
    try:
        for page in range(1, max_pages + 1):
            url = f"{self.BASE_URL}/x/space/arc/search"
            params = {"mid": uid, "pn": page, "ps": 30}
            data = self._request_public("GET", url, params=params)
            if data is None:
                data = self._request("GET", url, params=params)
            if not data:
                break
            # 兼容两种响应格式
            vlist = []
            if "list" in data and "vlist" in data["list"]:
                vlist = data["list"]["vlist"]
            elif "vlist" in data:
                vlist = data["vlist"]
            if not vlist:
                break
            for v in vlist:
                total_views += int(v.get("play", 0))
                total_likes += int(v.get("like", 0))
            if len(vlist) < 30:
                break  # 最后一页，已取完所有视频
        if total_views > 0:
            return {"total_views": total_views, "total_likes": total_likes}
    except Exception as e:
        logger.warning("从视频列表汇总数据失败 UID:%s: %s", uid, e)
    return None


def get_up_videos(self, uid: int, page: int = 1, page_size: int = 30) -> List[Dict]:
    """获取 UP 主的视频投稿列表

    Args:
        uid: UP 主 UID
        page: 页码（从 1 开始）
        page_size: 每页数量（最大 30）

    Returns:
        视频列表，每个元素含 aid, bvid, title, play, like 等字段
    """
    url = f"{self.BASE_URL}/x/space/arc/search"
    params = {"mid": uid, "pn": page, "ps": page_size}
    data = self._request("GET", url, params=params)
    if data and "list" in data and "vlist" in data["list"]:
        return data["list"]["vlist"]
    if data and "vlist" in data:
        return data["vlist"]
    return []


class _UpMixin:
    """UP 主 Mixin 类 — 将所有模块级函数通过类属性注入到 BilibiliAPI"""
    search_up_users = search_up_users
    _own_search_up_users = _own_search_up_users
    get_up_info = get_up_info
    _own_get_up_info = _own_get_up_info
    get_up_stat = get_up_stat
    _own_get_up_stat = _own_get_up_stat
    _calc_up_stat_from_videos = _calc_up_stat_from_videos
    get_up_videos = get_up_videos
