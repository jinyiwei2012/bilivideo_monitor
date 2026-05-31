"""
B站API模块 - UP主操作
UP主搜索、信息获取、统计数据和视频列表
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def search_up_users(self, keyword: str, page: int = 1, order: str = "fans") -> List[Dict]:
    from core.up_fetcher import search_up_users_multi

    return search_up_users_multi(keyword, page, _own_search_up_users)


def _own_search_up_users(self, keyword: str, page: int) -> List[Dict]:
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
        url2 = f"{self.BASE_URL}/x/web-interface/search/type"
        params2 = {"search_type": "bili_user", "keyword": keyword, "page": page}
        data = self._request_public("GET", url2, params=params2)

    if data and "result" in data:
        return data["result"]
    return []


def get_up_info(self, uid: int) -> Optional[Dict]:
    from core.up_fetcher import get_up_info_multi

    return get_up_info_multi(uid, _own_get_up_info)


def _own_get_up_info(self, uid: int) -> Optional[Dict]:
    data = self._request_public("GET", f"{self.BASE_URL}/x/space/acc/info", params={"mid": uid})
    if data is None:
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
    from core.up_fetcher import get_up_stat_multi

    return get_up_stat_multi(uid, _own_get_up_stat)


def _own_get_up_stat(self, uid: int) -> Optional[Dict]:
    data = self._request("GET", f"{self.BASE_URL}/x/space/upstat", params={"mid": uid})
    if data is None:
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
    logger.info("upstat 接口不可用，尝试从视频列表汇总总播放量 UID:%s", uid)
    return _calc_up_stat_from_videos(self, uid)


def _calc_up_stat_from_videos(self, uid: int, max_pages: int = 5) -> Optional[Dict]:
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
                break
        if total_views > 0:
            return {"total_views": total_views, "total_likes": total_likes}
    except Exception as e:
        logger.warning("从视频列表汇总数据失败 UID:%s: %s", uid, e)
    return None


def get_up_videos(self, uid: int, page: int = 1, page_size: int = 30) -> List[Dict]:
    url = f"{self.BASE_URL}/x/space/arc/search"
    params = {"mid": uid, "pn": page, "ps": page_size}
    data = self._request("GET", url, params=params)
    if data and "list" in data and "vlist" in data["list"]:
        return data["list"]["vlist"]
    if data and "vlist" in data:
        return data["vlist"]
    return []
