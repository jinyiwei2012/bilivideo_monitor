"""
UP 主数据多源获取器 (UpFetcher)
================================

本模块是 UP 主数据获取的聚合层，整合了多个独立数据源以实现高可用数据获取。

数据源（按优先级从高到低）：
  A. bilibili-api-python   — 社区维护的 async 封装库（独立的 HTTP 栈和认证方式）
  B. curl_cffi             — 直接 API 调用（TLS 指纹伪装为 Chrome120，最接近浏览器）
  C. 自有 API 实现          — BilibiliAPI 的 _request_public / _request（自主可控）

为什么需要多源：
  B站 的风控系统（412 限流）可能对不同来源的请求表现出不同的容忍度。
  - bilibili-api-python 使用 aiohttp（独立 TCP 连接池）
  - curl_cffi 使用 TLS 指纹伪装（JA3 指纹与 Chrome 相同）
  - 自有 API 使用 requests + 代理池 + Cookie

  即使一个源被 412 限流，其他源仍可能正常返回数据。

提供的多源函数：
  - get_up_info_multi   — 多源获取 UP 主基本信息
  - get_up_stat_multi   — 多源获取 UP 主统计数据
  - search_up_users_multi — 多源搜索 UP 主

架构说明：
  本模块的每个多源函数接收一个回调参数 (own_api_xxx)，
  作为自有 API 的数据源。回调由 BilibiliAPI 的对应方法提供，
  形成了"多源聚合 → 自有 API 回调"的两层架构。

  在 up_fetcher 中，自有 API 只是众多数据源之一（Source C），
  优先级排在其他两个数据源之后。
"""
import logging
from typing import Dict, List, Optional, Callable

import core.bilibili_api as _own_api_mod

logger = logging.getLogger(__name__)

# ── 延迟导入标记 ──────────────────────────────────────────
# 检测各个第三方库是否已安装（在模块加载时完成检测）
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


# ── 工具函数 ──────────────────────────────────────────────

def _fmt_tried(sources: list) -> str:
    """格式化已尝试的数据源列表，用箭头连接显示尝试顺序

    示例输出：
      "bilibili-api-python → curl_cffi → own_api"

    Args:
        sources: 已尝试的数据源名称列表

    Returns:
        格式化后的字符串
    """
    return " → ".join(s for s in sources if s)


# ══════════════════════════════════════════════════════════
# 多源获取器 — 按优先级尝试各个数据源
# ══════════════════════════════════════════════════════════


def get_up_info_multi(uid: int, own_api_get_up_info: Callable) -> Optional[Dict]:
    """多源获取 UP 主基本信息

    按优先级依次尝试 Source A → B → C，任意源成功即返回。
    当所有源都失败时记录警告日志并返回 None。

    Args:
        uid: UP 主 UID（数字）
        own_api_get_up_info: 自有 API 的回调函数（签名: (uid) -> Optional[Dict]）
                             由 BilibiliAPI._own_get_up_info 提供

    Returns:
        统一格式的 UP 主信息字典，包含:
          uid, name, face, sign, level, follower_count, video_count,
          official_verify, nameplate, live_room
        所有源均失败时返回 None
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
    """多源获取 UP 主统计数据（总播放 / 总点赞 / 粉丝数）

    数据来源按优先级：A → B → C。

    Args:
        uid: UP 主 UID
        own_api_get_up_stat: 自有 API 的回调函数

    Returns:
        统计字典，包含 total_views, total_likes, follower_count 等字段
        所有源均失败时返回 None
    """
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
    """多源搜索 UP 主

    数据来源按优先级：A → B → C。

    Args:
        keyword: 搜索关键词
        page: 页码
        own_api_search: 自有 API 的搜索回调函数

    Returns:
        搜索结果列表，每个元素含 mid, uname, fans, videos 等字段
        所有源均失败时返回空列表
    """
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
# 使用社区维护的异步 API 封装库获取数据
# ══════════════════════════════════════════════════════════


def _source_a_up_info(uid: int) -> Optional[Dict]:
    """数据源 A：使用 bilibili-api-python 获取 UP 主基本信息

    通过 bilibili-api-python 库的 User.get_user_info() 获取基础信息，
    再通过 get_relation_info() 获取粉丝数，最后通过 get_videos() 获取投稿数。

    如果 get_videos 被 412 限流，回退到自有 API 的 x/space/navnum 接口获取投稿数。

    Args:
        uid: UP 主 UID

    Returns:
        UP 主信息字典，失败返回 None
    """
    try:
        from bilibili_api import sync
        from bilibili_api.user import User

        u = User(uid=uid)
        result = _fetch_from_bilibili_api(u, uid)  # 获取基础信息
        if result is None:
            return None

        _fetch_relation_info(u, uid, result)  # 补充粉丝数
        if not result["video_count"]:
            _fetch_video_count(u, uid, result)  # 补充投稿数

        return result
    except Exception as e:
        logger.debug("源 A get_up_info 失败: %s", e)
    return None


def _fetch_from_bilibili_api(u, uid: int) -> Optional[Dict]:
    """从 bilibili-api-python 的 get_user_info() 获取 UP 主基本信息

    Args:
        u: bilibili-api-python 的 User 对象
        uid: UP 主 UID

    Returns:
        UP 主信息字典（不含粉丝数和投稿数），获取失败返回 None
    """
    from bilibili_api import sync

    info = sync(u.get_user_info())
    if not info or not info.get("mid"):
        return None

    return {
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


def _fetch_relation_info(u, uid: int, result: Dict) -> None:
    """从 get_relation_info() 获取粉丝数并填充到 result 中

    Args:
        u: bilibili-api-python 的 User 对象
        uid: UP 主 UID（用于日志）
        result: 待填充的 UP 主信息字典（原地修改）
    """
    from bilibili_api import sync

    try:
        rel = sync(u.get_relation_info())
        if rel:
            result["follower_count"] = rel.get("follower", 0)
    except Exception as e:
        logger.debug("获取粉丝数失败 UID=%s: %s", uid, e)


def _fetch_video_count(u, uid: int, result: Dict) -> None:
    """获取投稿数：先用 bilibili-api-python，再用自有 API 兜底

    Args:
        u: bilibili-api-python 的 User 对象
        uid: UP 主 UID
        result: 待填充的 UP 主信息字典（原地修改）
    """
    from bilibili_api import sync

    try:
        # 路径 1：通过 get_videos(ps=1) 获取视频列表的总数
        vdata = sync(u.get_videos(ps=1, pn=1))
        if vdata and "page" in vdata:
            result["video_count"] = vdata["page"].get("count", 0)
    except Exception as e:
        logger.debug("获取投稿数失败 UID=%s: %s", uid, e)

    if not result["video_count"]:
        # 路径 2：回退到自有 API 的 space/navnum 接口（轻量，不需要分页）
        try:
            _api = _own_api_mod._get_api()
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


def _source_a_up_stat(uid: int) -> Optional[Dict]:
    """数据源 A：使用 bilibili-api-python 获取 UP 主统计数据

    组合获取：
      1. get_relation_info() → 粉丝数
      2. get_videos(ps=50)   → 汇总播放量和点赞数
      3. 自有 API upstat     → 兜底（当 get_videos 被 412 限流时）

    Args:
        uid: UP 主 UID

    Returns:
        统计字典，失败返回 None
    """
    try:
        from bilibili_api import sync
        from bilibili_api.user import User

        u = User(uid=uid)
        stat = {"total_views": 0, "total_likes": 0, "follower_count": 0}

        # 步骤 1：获取关系信息（粉丝数）
        try:
            rel = sync(u.get_relation_info())
            if rel:
                stat["follower_count"] = rel.get("follower", 0)
        except Exception as e:
            logger.debug("源A获取粉丝数失败 UID=%s: %s", uid, e)

        # 步骤 2：从视频列表汇总播放和点赞（取前 50 个视频）
        try:
            vdata = sync(u.get_videos(ps=50, pn=1))
            if vdata and "list" in vdata:
                views = sum(int(v.get("play", 0)) for v in vdata["list"])
                likes = sum(int(v.get("like", 0)) for v in vdata["list"])
                stat["total_views"] = views
                stat["total_likes"] = likes
        except Exception as e:
            logger.debug("源A获取视频列表失败 UID=%s: %s", uid, e)

        # 步骤 3：get_videos 可能被 412 限流，用自有 API 的 upstat 兜底（带 Cookie）
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
    """数据源 A：使用 bilibili-api-python 搜索 UP 主

    Args:
        keyword: 搜索关键词
        page: 页码

    Returns:
        搜索结果列表，失败返回 None
    """
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
# 使用 curl_cffi 库模拟 Chrome 浏览器的 TLS 指纹
# ══════════════════════════════════════════════════════════

_BASE_URL = "https://api.bilibili.com"

# curl_cffi 请求头（模拟 Chrome 125 浏览器）
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
    """使用 curl_cffi 发起 GET 请求（TLS 指纹 = chrome120）

    通过 impersonate="chrome120" 参数让请求的 JA3/JA4 指纹
    与 Chrome 120 浏览器完全一致。

    Args:
        path: API 路径（如 "/x/space/acc/info"）
        params: URL 查询参数

    Returns:
        API 返回的 data 字段，失败返回 None
    """
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
    """数据源 B：使用 curl_cffi 获取 UP 主基本信息

    直接调用 /x/space/acc/info 获取空间信息。

    Args:
        uid: UP 主 UID

    Returns:
        UP 主信息字典
    """
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
    """数据源 B：使用 curl_cffi 获取 UP 主统计数据

    优先调用 /x/space/upstat，失败时回退到视频列表汇总。

    Args:
        uid: UP 主 UID

    Returns:
        统计字典
    """
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
    """数据源 B 兜底：从 UP 主视频列表逐页汇总总播放量和总点赞数

    通过 /x/space/arc/search 逐页获取，累加每个视频的 play 和 like。

    Args:
        uid: UP 主 UID
        max_pages: 最大翻页数

    Returns:
        统计字典（含 total_views, total_likes）
    """
    total_views = 0
    total_likes = 0
    try:
        for p in range(1, max_pages + 1):
            data = _curl_get("/x/space/arc/search", {"mid": uid, "pn": p, "ps": 30})
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
                break  # 已取完所有视频
        if total_views > 0:
            return {"total_views": total_views, "total_likes": total_likes}
    except Exception as e:
        logger.debug("curl_cffi 视频汇总失败: %s", e)
    return None


def _source_b_search(keyword: str, page: int) -> Optional[List[Dict]]:
    """数据源 B：使用 curl_cffi 搜索 UP 主

    Args:
        keyword: 搜索关键词
        page: 页码

    Returns:
        搜索结果列表，失败返回 None
    """
    data = _curl_get(
        "/x/web-interface/search/type",
        {"search_type": "bili_user", "keyword": keyword, "page": page},
    )
    if data and "result" in data:
        return data["result"]
    return None
