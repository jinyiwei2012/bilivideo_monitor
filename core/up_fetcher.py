"""
UP主数据多源获取器

聚合多个 Python 库作为独立数据源，按优先级逐一尝试，避免单一库/API 被 412 限制时完全不可用。

数据源:
  A. bilibili-api-python  — 社区维护的 async 封装库
  B. curl_cffi            — 直接 requests（TLS 指纹伪装，最接近浏览器）
  C. 自有 API 实现         — BilibiliAPI 的 _request_public / _request

每个源的 HTTP 栈、UA、认证方式均不同，单个源被限流不影响其他源。
"""

import logging
from typing import Dict, List, Optional, Callable

import core.bilibili_api as _own_api_mod

logger = logging.getLogger(__name__)

# ── 延迟导入标记 ──────────────────────────────────────────
_HAS_BILIBILI_API = False
_HAS_CURL_CFFI = False

try:
    __import__("bilibili_api")
    _HAS_BILIBILI_API = True
except ImportError:
    pass

try:
    __import__("curl_cffi.requests")
    _HAS_CURL_CFFI = True
except ImportError:
    pass


# ── 工具 ──────────────────────────────────────────────────
def _fmt_tried(sources: list) -> str:
    """格式化已尝试的数据源列表，用箭头连接"""
    return " → ".join(s for s in sources if s)


# ══════════════════════════════════════════════════════════
# 多源获取器
# ══════════════════════════════════════════════════════════


def get_up_info_multi(uid: int, own_api_get_up_info: Callable) -> Optional[Dict]:
    """多源获取 UP 主基本信息

    Args:
        uid: UP 主 UID
        own_api_get_up_info: 自有 API 的回调（BilibiliAPI.get_up_info）

    Returns:
        统一格式的 UP 主信息 dict，所有源均失败时返回 None
    """
    tried = []

    # ── Source A: bilibili-api-python ──
    if _HAS_BILIBILI_API:
        result = _source_a_up_info(uid)
        tried.append("bilibili-api-python")
        if result:
            logger.debug("UP主信息 来源 A(bilibili-api-python) UID:%s", uid)
            return result

    # ── Source B: curl_cffi ──
    if _HAS_CURL_CFFI:
        result = _source_b_up_info(uid)
        tried.append("curl_cffi")
        if result:
            logger.debug("UP主信息 来源 B(curl_cffi) UID:%s", uid)
            return result

    # ── Source C: 自有 API ──
    result = own_api_get_up_info(uid)
    tried.append("own_api")
    if result:
        logger.debug("UP主信息 来源 C(own_api) UID:%s", uid)
        return result

    logger.warning("UP主信息 全部源失败 UID:%s [%s]", uid, _fmt_tried(tried))
    return None


def get_up_stat_multi(uid: int, own_api_get_up_stat: Callable) -> Optional[Dict]:
    """多源获取 UP 主统计数据（总播放 / 总点赞 / 粉丝）"""
    tried = []

    if _HAS_BILIBILI_API:
        result = _source_a_up_stat(uid)
        tried.append("bilibili-api-python")
        if result:
            logger.info("UP主统计 来源 A(bilibili-api-python) UID:%s", uid)
            return result

    if _HAS_CURL_CFFI:
        result = _source_b_up_stat(uid)
        tried.append("curl_cffi")
        if result:
            logger.info("UP主统计 来源 B(curl_cffi) UID:%s", uid)
            return result

    result = own_api_get_up_stat(uid)
    tried.append("own_api")
    if result:
        logger.info("UP主统计 来源 C(own_api) UID:%s", uid)
        return result

    logger.warning("UP主统计 全部源失败 UID:%s [%s]", uid, _fmt_tried(tried))
    return None


def search_up_users_multi(keyword: str, page: int, own_api_search: Callable) -> List[Dict]:
    """多源搜索 UP 主"""
    tried = []

    if _HAS_BILIBILI_API:
        result = _source_a_search(keyword, page)
        tried.append("bilibili-api-python")
        if result:
            logger.info("UP主搜索 来源 A(bilibili-api-python) kw:%s", keyword)
            return result

    if _HAS_CURL_CFFI:
        result = _source_b_search(keyword, page)
        tried.append("curl_cffi")
        if result:
            logger.info("UP主搜索 来源 B(curl_cffi) kw:%s", keyword)
            return result

    result = own_api_search(keyword, page)
    tried.append("own_api")
    if result:
        logger.info("UP主搜索 来源 C(own_api) kw:%s", keyword)
        return result

    logger.warning("UP主搜索 全部源失败 kw:%s [%s]", keyword, _fmt_tried(tried))
    return []


# ══════════════════════════════════════════════════════════
# Source A — bilibili-api-python
# ══════════════════════════════════════════════════════════


def _source_a_up_info(uid: int) -> Optional[Dict]:  # noqa: C901
    """数据源A：使用 bilibili-api-python 获取 UP 主基本信息"""
    try:
        from bilibili_api import sync
        from bilibili_api.user import User

        u = User(uid=uid)
        info = sync(u.get_user_info())
        if not info or not info.get("mid"):
            return None

        # 构建统一的 UP 主信息字典
        result = {
            "uid": info.get("mid", uid),
            "name": info.get("name", ""),
            "face": info.get("face", ""),
            "sign": info.get("sign", ""),
            "level": info.get("level", 0),
            "follower_count": 0,
            "video_count": 0,
            "official_verify": info.get("official", info.get("official_verify", {})),
            "nameplate": info.get("nameplate", {}),
        }

        # bilibili-api-python 新版 get_user_info() 不再返回 fans/videos
        # 从 get_relation_info() 单独获取粉丝数
        try:
            rel = sync(u.get_relation_info())
            if rel:
                result["follower_count"] = rel.get("follower", 0)
        except Exception as e:
            logger.debug("获取粉丝数失败 UID=%s: %s", uid, e)

        # 尝试获取投稿数（可能受 412 限制，失败不影响主流程）
        if not result["video_count"]:
            try:
                vdata = sync(u.get_videos(ps=1, pn=1))
                if vdata and "page" in vdata:
                    result["video_count"] = vdata["page"].get("count", 0)
            except Exception as e:
                logger.debug("获取投稿数失败 UID=%s: %s", uid, e)

        # 如果 bilibili-api-python 无法获取投稿数，尝试自有 API 兜底
        if not result["video_count"]:
            try:
                _api = _own_api_mod._get_api()
                # 优先使用 navnum 接口（轻量级，同时返回投稿数和粉丝数）
                data = _api._request_public(
                    "GET",
                    f"{_api.BASE_URL}/x/space/navnum",
                    params={"mid": uid, "jsonp": "jsonp"},
                )
                if data:
                    if data.get("video"):
                        result["video_count"] = data["video"]
            except Exception as e:
                logger.debug("自有API获取投稿数失败 UID=%s: %s", uid, e)

        return result
    except Exception as e:
        logger.debug("源 A get_up_info 失败: %s", e)
    return None


def _source_a_up_stat(uid: int) -> Optional[Dict]:
    """数据源A：使用 bilibili-api-python 获取 UP 主统计数据"""
    try:
        from bilibili_api import sync
        from bilibili_api.user import User

        u = User(uid=uid)
        stat = {"total_views": 0, "total_likes": 0, "follower_count": 0}

        # 关系信息（粉丝数）
        try:
            rel = sync(u.get_relation_info())
            if rel:
                stat["follower_count"] = rel.get("follower", 0)
        except Exception as e:
            logger.debug("源A获取粉丝数失败 UID=%s: %s", uid, e)

        # 视频列表（汇总播放/点赞）
        try:
            vdata = sync(u.get_videos(ps=50, pn=1))
            if vdata and "list" in vdata:
                views = sum(int(v.get("play", 0)) for v in vdata["list"])
                likes = sum(int(v.get("like", 0)) for v in vdata["list"])
                stat["total_views"] = views
                stat["total_likes"] = likes
        except Exception as e:
            logger.debug("源A获取视频列表失败 UID=%s: %s", uid, e)

        # get_videos 可能被 412 限流，用自有 API 的 upstat 兜底（带 Cookie）
        if not stat["total_views"]:
            try:
                from core.bilibili_api import _get_api as _own_api
                _api = _own_api()
                data = _api._request(
                    "GET", f"{_api.BASE_URL}/x/space/upstat",
                    params={"mid": uid},
                )
                if data and data.get("archive", {}).get("view"):
                    stat["total_views"] = data["archive"]["view"]
                if data and data.get("likes"):
                    stat["total_likes"] = data["likes"]
            except Exception as e:
                logger.debug("自有API upstat失败 UID=%s: %s", uid, e)

        if stat.get("follower_count") or stat.get("total_views"):
            return stat
    except Exception as e:
        logger.debug("源 A get_up_stat 失败: %s", e)
    return None


def _source_a_search(keyword: str, page: int) -> Optional[List[Dict]]:
    """数据源A：使用 bilibili-api-python 搜索 UP 主"""
    try:
        from bilibili_api import sync
        from bilibili_api.search import search_by_type, SearchObjectType

        results = sync(search_by_type(keyword, SearchObjectType.USER, page=page))
        if results and "result" in results:
            return results["result"]
    except Exception as e:
        logger.debug("源 A search 失败: %s", e)
    return None


# ══════════════════════════════════════════════════════════
# Source B — curl_cffi（直接 API 调用，TLS 指纹伪装）
# ══════════════════════════════════════════════════════════

_BASE_URL = "https://api.bilibili.com"

_CURL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _curl_get(path: str, params: dict = None) -> Optional[Dict]:
    """使用 curl_cffi 发起 GET 请求（TLS 指纹 = Chrome120）"""
    if not _HAS_CURL_CFFI:
        return None
    try:
        import curl_cffi.requests

        resp = curl_cffi.requests.get(
            f"{_BASE_URL}{path}",
            params=params,
            headers=_CURL_HEADERS,
            timeout=15,
            impersonate="chrome120",
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data")
        return None
    except Exception as e:
        logger.debug("curl_cffi GET %s 失败: %s", path, e)
        return None


def _source_b_up_info(uid: int) -> Optional[Dict]:
    """数据源B：使用 curl_cffi 获取 UP 主基本信息"""
    data = _curl_get("/x/space/acc/info", {"mid": uid})
    if data:
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
        }
    return None


def _source_b_up_stat(uid: int) -> Optional[Dict]:
    """数据源B：使用 curl_cffi 获取 UP 主统计数据"""
    data = _curl_get("/x/space/upstat", {"mid": uid})
    if data:
        return {
            "total_views": data.get("archive", {}).get("view", 0),
            "total_likes": data.get("archive", {}).get("like", 0),
            "follower_change": data.get("follower_change", data.get("follower", 0)),
            "follower_count": (
                data.get("follower", {}).get("follower", 0)
                if isinstance(data.get("follower"), dict)
                else data.get("follower", 0)
            ),
        }
    # 兜底：从视频列表汇总
    return _source_b_stat_from_videos(uid)


def _source_b_stat_from_videos(uid: int, max_pages: int = 5) -> Optional[Dict]:
    """数据源B 兜底：从 UP 主视频列表逐页汇总总播放量和总点赞数"""
    total_views = 0
    total_likes = 0
    try:
        for p in range(1, max_pages + 1):
            data = _curl_get("/x/space/arc/search", {"mid": uid, "pn": p, "ps": 30})
            if not data:
                break
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
                break  # 已取完所有视频
        if total_views > 0:
            return {"total_views": total_views, "total_likes": total_likes}
    except Exception as e:
        logger.debug("curl_cffi 视频汇总失败: %s", e)
    return None


def _source_b_search(keyword: str, page: int) -> Optional[List[Dict]]:
    """数据源B：使用 curl_cffi 搜索 UP 主"""
    data = _curl_get(
        "/x/web-interface/search/type",
        {"search_type": "bili_user", "keyword": keyword, "page": page},
    )
    if data and "result" in data:
        return data["result"]
    return None
