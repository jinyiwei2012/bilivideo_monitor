"""bili_ticket 申请 / 持久化 / 注入（降低反复风控）。

规格与来源见 ``docs/risk_control_playbook.md`` §3：

- ``POST /bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket``，``key_id=ec02``，
  ``hexsign = HMAC_SHA256("XgwSnGZ1p", "ts" + <毫秒时间戳>)``，``context[ts]=<毫秒>``；
- 响应 ``data.ticket``（JWT，约 3 天）与 ``data.nav.img`` / ``data.nav.sub``（可直接用于刷新 WBI 密钥）；
- ``ticket`` 与 ``bili_ticket_expires`` 都作为 **Cookie** 走既有的加密持久化出口
  （``BilibiliAPI.set_cookies`` + ``_persist_cookies``），不写源码、不写明文配置；
- 注入点在 ``core/bilibili_request.py::_get_request_cookies``，那里**只读缓存、不发请求**
  （请求热路径绝不能因取 ticket 而额外发一次网络请求）。
"""

import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Tuple

logger = logging.getLogger(__name__)

TICKET_URL = "/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket"
KEY_ID = "ec02"
HMAC_KEY = "XgwSnGZ1p"
TICKET_COOKIE = "bili_ticket"
TICKET_EXPIRES_COOKIE = "bili_ticket_expires"
REFRESH_INTERVAL = 2 * 86400.0  # 有效期约 3 天 → 刷新周期 2 天（留 1 天余量）


@dataclass
class TicketInfo:
    """一次 ticket 申请的结果（失败时各字段为空）。"""

    ticket: str = ""
    expires: float = 0.0
    img_url: str = ""
    sub_url: str = ""


def gen_hexsign(ts_ms: int) -> str:
    """``hexsign = HMAC_SHA256("XgwSnGZ1p", "ts" + 毫秒时间戳)`` 的小写 hex。"""
    return hmac.new(HMAC_KEY.encode(), f"ts{int(ts_ms)}".encode(), hashlib.sha256).hexdigest()


def jwt_expiry(ticket: str) -> float:
    """从 ticket（JWT）中取 ``exp``；解析失败返回 0.0。"""
    try:
        payload = ticket.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        return float(data.get("exp", 0) or 0)
    except Exception as e:  # JWT 结构由服务端决定，异常一律退回默认刷新周期
        logger.debug("解析 bili_ticket JWT 失败: %s", e)
        return 0.0


def request_ticket(api: Any) -> TicketInfo:
    """申请一次 ticket；任何失败都返回空 ``TicketInfo``（绝不抛错、不阻塞主流程）。"""
    ts_ms = int(time.time() * 1000)
    payload = {"key_id": KEY_ID, "hexsign": gen_hexsign(ts_ms), "context[ts]": str(ts_ms)}
    try:
        data = api._request("POST", TICKET_URL, data=payload)
    except Exception as e:
        logger.warning("bili_ticket 申请异常: %s", e)
        return TicketInfo()
    if not isinstance(data, dict):
        logger.warning("bili_ticket 申请失败：无响应数据")
        return TicketInfo()
    ticket = str(data.get("ticket") or "")
    if not ticket:
        logger.warning("bili_ticket 申请失败：响应缺少 ticket")
        return TicketInfo()
    nav = data.get("nav") or {}
    exp = jwt_expiry(ticket)
    expires = min(exp, time.time() + REFRESH_INTERVAL) if exp else time.time() + REFRESH_INTERVAL
    return TicketInfo(
        ticket=ticket,
        expires=expires,
        img_url=str(nav.get("img") or ""),
        sub_url=str(nav.get("sub") or ""),
    )


def _apply_wbi_from_ticket(api: Any, info: TicketInfo) -> None:
    """顺带用 ticket 响应里的 nav 刷新 WBI 密钥（省一次 nav 请求，nav 被风控时也能拿到密钥）。"""
    if not (info.img_url and info.sub_url):
        return
    from core.bilibili_api import wbi_key_from_url, wbi_mixin_key

    img_key = wbi_key_from_url(info.img_url)
    sub_key = wbi_key_from_url(info.sub_url)
    if img_key and sub_key:
        api._wbi_key = wbi_mixin_key(img_key, sub_key)
        api._wbi_key_expire = time.time() + float(getattr(api, "_WBI_KEY_TTL", 600.0))


def _store(api: Any, info: TicketInfo) -> None:
    """把 ticket 与过期时间并回 Cookie（与账号 Cookie 同一加密出口）。"""
    cookies = dict(getattr(api, "_cookies", {}) or {})
    cookies[TICKET_COOKIE] = info.ticket
    cookies[TICKET_EXPIRES_COOKIE] = str(int(info.expires))
    setter = getattr(api, "set_cookies", None)
    if callable(setter):
        setter(cookies)
    else:
        api._cookies = cookies
    persist = getattr(api, "_persist_cookies", None)
    if callable(persist):
        try:
            persist(cookies)
        except Exception as e:
            logger.debug("持久化 bili_ticket 失败: %s", e)


def load_cached_ticket(api: Any) -> Tuple[str, float]:
    """读取缓存（先实例属性、再 Cookie），返回 ``(ticket, expires)``。"""
    cookies = getattr(api, "_cookies", {}) or {}
    ticket = str(getattr(api, "_bili_ticket", "") or "") or str(cookies.get(TICKET_COOKIE, "") or "")
    raw: Any = getattr(api, "_bili_ticket_expires", 0.0)
    if not raw:
        raw = cookies.get(TICKET_EXPIRES_COOKIE, 0)
    try:
        expires = float(raw or 0)
    except (TypeError, ValueError):
        expires = 0.0
    return ticket, expires


def ticket_cookie(api: Any) -> str:
    """供请求热路径使用：**只读缓存**，过期或缺失返回空串（绝不发网络请求）。"""
    ticket, expires = load_cached_ticket(api)
    if expires and expires <= time.time():
        return ""
    return ticket


def ensure_ticket(api: Any, *, force: bool = False) -> str:
    """确保有可用 ticket：命中缓存直接返回，否则申请一次。

    Args:
        api: ``BilibiliAPI`` 实例（或等价替身）
        force: 忽略缓存强制刷新（风控命中后调用）

    Returns:
        ticket 字符串；申请失败返回 ``""``（不阻塞主流程）
    """
    ticket, expires = load_cached_ticket(api)
    if ticket and not force and expires > time.time():
        return ticket
    info = request_ticket(api)
    if not info.ticket:
        return ""
    api._bili_ticket = info.ticket
    api._bili_ticket_expires = info.expires
    _apply_wbi_from_ticket(api, info)
    _store(api, info)
    logger.info("bili_ticket 已更新（%.1f 小时后刷新）", (info.expires - time.time()) / 3600.0)
    return info.ticket
