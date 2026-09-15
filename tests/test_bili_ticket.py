"""bili_ticket 回归测试（离线：假 API + 文档向量）。

覆盖：hexsign 向量 / 首次申请并持久化 / 缓存命中不发请求 / 过期与 force 刷新 /
失败不阻塞 / 热路径只读缓存 / nav 顺带刷新 WBI 密钥 / JWT exp 解析 / 刷新周期封顶。
"""

import base64
import json
import time
from typing import Any, Dict, List, Optional

from core.bilibili_api import wbi_mixin_key
from core.bilibili_ticket import (
    HMAC_KEY,
    KEY_ID,
    REFRESH_INTERVAL,
    TICKET_COOKIE,
    TICKET_EXPIRES_COOKIE,
    ensure_ticket,
    gen_hexsign,
    jwt_expiry,
    load_cached_ticket,
    ticket_cookie,
)

IMG_URL = "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png"
SUB_URL = "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png"


def _jwt(exp: float) -> str:
    """构造一个只含 exp 的最小 JWT。"""
    payload = base64.urlsafe_b64encode(json.dumps({"exp": int(exp)}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class _StubAPI:
    """替身 API：记录请求 / 持久化调用，返回预设 ticket 响应。"""

    _WBI_KEY_TTL = 600.0

    def __init__(self, responses: Optional[List[Any]] = None, *, with_nav: bool = False) -> None:
        self._responses = list(responses if responses is not None else [])
        self.with_nav = with_nav
        self.calls: List[Dict[str, Any]] = []
        self.set_cookies_calls = 0
        self.persist_calls = 0
        self._cookies: Dict[str, Any] = {}
        self._bili_ticket = ""
        self._bili_ticket_expires = 0.0
        self._wbi_key: Optional[str] = None
        self._wbi_key_expire = 0.0

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        if not self._responses:
            return {"ticket": f"jwt-{len(self.calls)}", "nav": self._nav()}
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def _nav(self) -> Dict[str, str]:
        return {"img": IMG_URL, "sub": SUB_URL} if self.with_nav else {}

    def set_cookies(self, cookies: Dict[str, Any]) -> None:
        self.set_cookies_calls += 1
        self._cookies = dict(cookies)

    def _persist_cookies(self, cookies: Dict[str, Any]) -> None:
        self.persist_calls += 1


def test_hexsign_matches_documented_vector() -> None:
    """官方向量：hexsign = HMAC_SHA256("XgwSnGZ1p", "ts"+ms)。"""
    assert HMAC_KEY == "XgwSnGZ1p" and KEY_ID == "ec02"
    assert gen_hexsign(1700000000000) == "752843511305da2148f4835752201faab1a415562da7a114a9cfac6e19e41f2b"
    assert gen_hexsign(1) == "63216f0c9b503aeaa3a8b876a6da080ca900d883eba4a42e8ebe6d6a3368a7ed"
    assert len(gen_hexsign(1700000000000)) == 64


def test_first_call_requests_and_persists() -> None:
    api = _StubAPI()
    ticket = ensure_ticket(api)
    assert ticket == "jwt-1"
    assert len(api.calls) == 1
    call = api.calls[0]
    assert call["method"] == "POST" and call["url"].endswith("/GenWebTicket")
    payload = call["kwargs"]["data"]
    assert payload["key_id"] == "ec02"
    assert payload["hexsign"] == gen_hexsign(int(payload["context[ts]"]))
    assert api._bili_ticket == "jwt-1"
    assert api._bili_ticket_expires > time.time()
    assert api._cookies[TICKET_COOKIE] == "jwt-1"
    assert int(api._cookies[TICKET_EXPIRES_COOKIE]) > time.time()
    assert api.persist_calls == 1 and api.set_cookies_calls == 1


def test_cached_ticket_skips_request() -> None:
    api = _StubAPI()
    ensure_ticket(api)
    again = ensure_ticket(api)
    assert again == "jwt-1"
    assert len(api.calls) == 1, "缓存有效期内不得重复申请"
    assert api.persist_calls == 1


def test_expired_ticket_refreshes() -> None:
    api = _StubAPI()
    ensure_ticket(api)
    api._bili_ticket_expires = time.time() - 1
    refreshed = ensure_ticket(api)
    assert refreshed == "jwt-2"
    assert len(api.calls) == 2


def test_force_refreshes_even_if_cached() -> None:
    api = _StubAPI()
    ensure_ticket(api)
    assert ensure_ticket(api, force=True) == "jwt-2"
    assert len(api.calls) == 2


def test_failure_does_not_block() -> None:
    api = _StubAPI([None, {"ticket": ""}, RuntimeError("boom")])
    for _ in range(3):
        assert ensure_ticket(api, force=True) == ""
    assert api.persist_calls == 0, "申请失败不得写入 Cookie"


def test_ticket_cookie_never_issues_request() -> None:
    api = _StubAPI()
    assert ticket_cookie(api) == "", "无缓存时应返回空串而不是触发请求"
    assert api.calls == []
    ensure_ticket(api)
    calls_after_fetch = len(api.calls)
    assert ticket_cookie(api) == "jwt-1"
    assert len(api.calls) == calls_after_fetch, "热路径只读缓存，绝不发请求"
    api._bili_ticket_expires = time.time() - 1
    assert ticket_cookie(api) == ""
    assert len(api.calls) == calls_after_fetch, "过期也只返回空串，不刷新"


def test_nav_refreshes_wbi_key_from_ticket() -> None:
    api = _StubAPI(with_nav=True)
    assert IMG_URL.rsplit("/", 1)[-1].rsplit(".", 1)[0] == "7cd084941338484aae1ad9425b84077c"
    ensure_ticket(api)
    assert api._wbi_key == wbi_mixin_key("7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45")
    assert api._wbi_key == "ea1db124af3c7062474693fa704f4ff8", "应与文档验证向量一致"
    assert api._wbi_key_expire > time.time()


def test_jwt_expiry_parsing() -> None:
    assert jwt_expiry(_jwt(1700000000)) == 1700000000.0
    assert jwt_expiry("not-a-jwt") == 0.0
    assert jwt_expiry("a.!!!invalid!!!.c") == 0.0


def test_refresh_interval_caps_expiry() -> None:
    far = time.time() + 30 * 86400
    api = _StubAPI([{"ticket": _jwt(far), "nav": {}}])
    ensure_ticket(api)
    assert api._bili_ticket_expires <= time.time() + REFRESH_INTERVAL + 5, "刷新周期应封顶在 2 天"


def test_load_cached_ticket_falls_back_to_cookies() -> None:
    api = _StubAPI()
    api._cookies = {TICKET_COOKIE: "from-cookie", TICKET_EXPIRES_COOKIE: str(int(time.time() + 100))}
    ticket, expires = load_cached_ticket(api)
    assert ticket == "from-cookie" and expires > time.time()
