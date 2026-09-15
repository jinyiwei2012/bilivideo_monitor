"""``w_webid`` 取值、按天缓存与签名注入 helper。

依据见 ``docs/risk_control_playbook.md`` §5（来源：``magicdawn/Bilibili-Gate``，MIT）：

- 取值：``GET https://space.bilibili.com/<mid>`` 页面里的 ``#__RENDER_DATA__``（URL 编码 JSON）
  解出 ``access_id``；**不区分目标 mid**（用自己的 mid 取一次即可）；
- 按天缓存（上游 ``dailyCache``），跨天重取；备选取法为 ``GET https://live.bilibili.com/lol``；
- 参与签名：必须在 ``_wbi_sign(params)`` **之前**把 ``w_webid`` 放进 params，
  这样它同时进入 ``w_rid`` 的 md5 与最终 query。

⚠ 使用范围（上游做法）：**仅部分 WBI 接口需要**（上游只在 ``x/space/wbi/acc/info`` 一带带上）。
本仓库当前调用的是 ``/x/space/acc/info``、``/x/space/arc/search`` 等**非 WBI 变体**，
因此本模块暂不主动注入任何现有请求——等确有必要时用 :func:`with_w_webid` 显式接入
（例如后续改用 ``/x/space/wbi/acc/info``）：``params = api._wbi_sign(with_w_webid(api, params))``。

所有失败路径都不抛错：取不到就返回空串，调用方原样不带该参数。
"""

import json
import logging
import os
import re
import time
from typing import Any, Dict, Optional
from urllib.parse import unquote

logger = logging.getLogger(__name__)

SPACE_URL = "https://space.bilibili.com/{mid}"
LIVE_URL = "https://live.bilibili.com/lol"
ACCESS_ID_KEYS = ("access_id", "accessId")

_RENDER_DATA_RE = re.compile(r'id="__RENDER_DATA__"[^>]*>(.*?)</script>', re.S)
_CACHE_NAME = "w_webid.json"


def _cache_file() -> str:
    """缓存文件路径（``data/w_webid.json``）。"""
    from utils import project_path

    return project_path("data", _CACHE_NAME)


def _find_access_id(node: Any, depth: int = 0) -> str:
    """在解析后的 JSON 里递归找 ``access_id``（页面结构会变，别只认顶层）。"""
    if depth > 6:
        return ""
    if isinstance(node, dict):
        for key in ACCESS_ID_KEYS:
            value = node.get(key)
            if isinstance(value, str) and value:
                return value
        for value in node.values():
            found = _find_access_id(value, depth + 1)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_access_id(item, depth + 1)
            if found:
                return found
    return ""


def extract_access_id(html: str) -> str:
    """从页面 HTML 中解析 ``access_id``（``#__RENDER_DATA__`` 是 URL 编码 JSON）。"""
    match = _RENDER_DATA_RE.search(str(html or ""))
    if not match:
        return ""
    raw = match.group(1).strip()
    for text in (unquote(raw), raw):
        try:
            return _find_access_id(json.loads(text))
        except (ValueError, TypeError) as e:
            logger.debug("__RENDER_DATA__ 解析失败: %s", e)
    return ""


def load_cache() -> Dict[str, Any]:
    """读取本地缓存（缺失或损坏返回空 dict）。"""
    path = _cache_file()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as e:
        logger.debug("读取 w_webid 缓存失败: %s", e)
        return {}
    return data if isinstance(data, dict) else {}


def save_cache(access_id: str, now: Optional[float] = None) -> None:
    """写入缓存（含时间戳，用于按天判断新鲜度）。"""
    if not access_id:
        return
    path = _cache_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"access_id": access_id, "ts": float(now if now is not None else time.time())}, handle)
    except OSError as e:
        logger.debug("写入 w_webid 缓存失败: %s", e)


def clear_cache() -> None:
    """删除缓存（排障用）。"""
    try:
        os.remove(_cache_file())
    except OSError:
        pass


def is_fresh(cache: Dict[str, Any], now: Optional[float] = None) -> bool:
    """缓存是否新鲜：有值且与当前是**同一天**（按天过期，跨天重取）。"""
    if not isinstance(cache, dict) or not cache.get("access_id"):
        return False
    stamp = float(now if now is not None else time.time())
    try:
        cached_ts = float(cache.get("ts", 0) or 0)
    except (TypeError, ValueError):
        return False
    return time.strftime("%Y-%m-%d", time.localtime(cached_ts)) == time.strftime("%Y-%m-%d", time.localtime(stamp))


def _page_urls(api: Any) -> list[str]:
    """按优先级给出候选页面：自己的空间页（带 mid）→ 直播页备选。"""
    mid = str((getattr(api, "_cookies", {}) or {}).get("DedeUserID", "") or "")
    urls = [SPACE_URL.format(mid=mid)] if mid else []
    urls.append(LIVE_URL)
    return urls


def fetch_access_id(api: Any) -> str:
    """从页面取 ``access_id``（失败返回空串，绝不抛错）。"""
    for url in _page_urls(api):
        try:
            response = api._request_raw("GET", url)
        except Exception as e:
            logger.debug("w_webid 页面请求失败 %s: %s", url, e)
            continue
        value = extract_access_id(str(getattr(response, "text", "") or ""))
        if value:
            return value
    logger.info("未能解析出 w_webid（access_id），本次不带该参数")
    return ""


def get_w_webid(api: Any, *, force: bool = False) -> str:
    """取 ``w_webid``：同一天内命中缓存则**零请求**，否则取一次页面并写缓存。

    Args:
        api: ``BilibiliAPI`` 实例（或等价替身，需要 ``_request_raw`` 与 ``_cookies``）
        force: 忽略当天缓存强制重取

    Returns:
        ``access_id``；取不到时回退旧缓存值，仍无则返回 ``""``
    """
    cache = load_cache()
    if not force and is_fresh(cache):
        return str(cache.get("access_id", "") or "")
    value = fetch_access_id(api)
    if value:
        save_cache(value)
        return value
    return str(cache.get("access_id", "") or "")


def with_w_webid(api: Any, params: Dict[str, Any], *, value: Optional[str] = None) -> Dict[str, Any]:
    """把 ``w_webid`` 并入参数（**必须在** ``_wbi_sign`` 之前调用，否则不参与签名）。

    Args:
        api: ``BilibiliAPI`` 实例
        params: 待签名参数
        value: 直接指定值（跳过取值/缓存，便于测试与调用方复用）

    Returns:
        新参数字典；取不到 ``w_webid`` 时原样返回（不引入空参数）
    """
    resolved = value if value is not None else get_w_webid(api)
    if not resolved:
        return dict(params)
    merged = dict(params)
    merged["w_webid"] = resolved
    return merged


def cache_state() -> Dict[str, Any]:
    """缓存观测（供设置页/日志展示）。"""
    cache = load_cache()
    return {
        "has_value": bool(cache.get("access_id")),
        "fresh": is_fresh(cache),
        "ts": float(cache.get("ts", 0) or 0),
        "path": _cache_file(),
    }
