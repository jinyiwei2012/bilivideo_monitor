"""设备标识回归测试（离线：假 API，不写用户配置）。

覆盖：`_uuid`/`b_lsid` 格式与校验 / UA 硬约束过滤与轮换 / spi 取值 / 首次补齐并持久化 /
已持久化时不重复请求也不重新生成 / 远端失败保留本地兜底 / 真实 API 的注入路径。
"""

import re
import time
from typing import Any, Dict, List, Optional, Tuple

from core.bilibili_api import BilibiliAPI
from core.constants import USER_AGENTS
from core.device_identity import (
    B_LSID_COOKIE,
    B_NUT_COOKIE,
    BUVID3_COOKIE,
    BUVID4_COOKIE,
    SPI_URL,
    UUID_COOKIE,
    ensure_identity,
    extract_spi_buvids,
    gen_b_lsid,
    gen_uuid,
    is_valid_b_lsid,
    is_valid_uuid,
    load_identity,
    pick_user_agent,
    sanitize_user_agent,
)

B_LSID_RE = re.compile(r"^[0-9A-F]{8}_[0-9A-F]+$")
UUID_RE = re.compile(r"^[0-9a-f]{32}$")


class _StubAPI:
    """替身 API：记录请求与持久化，可预设 spi 响应。"""

    def __init__(self, spi: Optional[Any] = None, cookies: Optional[Dict[str, Any]] = None) -> None:
        self._spi = spi
        self.calls: List[Tuple[str, str]] = []
        self.persist_calls = 0
        self.set_cookies_calls = 0
        self._cookies: Dict[str, Any] = dict(cookies or {})
        self._buvid3 = "LOCALFAKEBVID3"
        self._buvid4 = "LOCALFAKEBVID4"
        self._uuid = ""
        self._b_lsid = ""
        self._b_nut = ""

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        self.calls.append((method, url))
        if isinstance(self._spi, Exception):
            raise self._spi
        return self._spi

    def set_cookies(self, cookies: Dict[str, Any]) -> None:
        self.set_cookies_calls += 1
        self._cookies = dict(cookies)

    def _persist_cookies(self, cookies: Dict[str, Any]) -> None:
        self.persist_calls += 1


SPI_OK = {"buvid3": "SERVER-BUVID3-INFOC", "buvid4": "SERVER-BUVID4-INFOC"}


def test_uuid_format_and_validation() -> None:
    value = gen_uuid()
    assert UUID_RE.fullmatch(value)
    assert is_valid_uuid(value) is True
    assert is_valid_uuid("") is False
    assert is_valid_uuid("ZZZZ") is False


def test_b_lsid_format_and_validation() -> None:
    value = gen_b_lsid()
    assert B_LSID_RE.fullmatch(value), value
    assert is_valid_b_lsid(value) is True
    assert is_valid_b_lsid("abc_def") is False
    # 后缀为毫秒时间戳的十六进制 → 应在合理区间内
    suffix = int(value.split("_")[1], 16)
    assert abs(suffix - time.time() * 1000) < 60_000


def test_sanitize_user_agent_filters_documented_words() -> None:
    good = USER_AGENTS[0]
    assert sanitize_user_agent(good) == good
    for bad in ("curl/8.0", "python-requests/2.31", "AwA/1.0", "Python/3.10 aiohttp"):
        assert sanitize_user_agent(bad, "FALLBACK") == "FALLBACK", bad
    assert sanitize_user_agent("", "FALLBACK") == "FALLBACK"


def test_pick_user_agent_never_repeats_previous() -> None:
    previous = USER_AGENTS[0]
    for _ in range(30):
        chosen = pick_user_agent(USER_AGENTS, previous)
        assert chosen and chosen != previous
        previous = chosen
    assert pick_user_agent(["curl/8.0", "python/3.10"], "") == "", "池内全不合规时返回空串"


def test_shipped_user_agent_pool_is_compliant() -> None:
    for ua in USER_AGENTS:
        assert sanitize_user_agent(ua) == ua, ua


def test_extract_spi_buvids() -> None:
    assert extract_spi_buvids(SPI_OK) == ("SERVER-BUVID3-INFOC", "SERVER-BUVID4-INFOC")
    assert extract_spi_buvids({"buvid3": "x"}) == ("x", "")
    assert extract_spi_buvids(None) == ("", "")


def test_first_call_fetches_and_persists() -> None:
    api = _StubAPI(SPI_OK)
    identity = ensure_identity(api)
    assert api.calls == [("GET", SPI_URL)]
    assert identity[BUVID3_COOKIE] == "SERVER-BUVID3-INFOC"
    assert identity[BUVID4_COOKIE] == "SERVER-BUVID4-INFOC"
    assert is_valid_uuid(identity[UUID_COOKIE])
    assert is_valid_b_lsid(identity[B_LSID_COOKIE])
    assert identity[B_NUT_COOKIE].isdigit()
    assert api.persist_calls == 1 and api.set_cookies_calls == 1
    assert api._cookies[UUID_COOKIE] == identity[UUID_COOKIE]


def test_persisted_identity_is_not_regenerated() -> None:
    api = _StubAPI(SPI_OK)
    first = ensure_identity(api)
    second = ensure_identity(api)
    assert second == first, "已有标识一律保留，避免指纹频繁变化"
    assert len(api.calls) == 1, "buvid 已持久化后不得再请求 spi"
    assert api.persist_calls == 1, "没有变化就不该再写配置"


def test_remote_failure_keeps_local_fallback() -> None:
    api = _StubAPI(RuntimeError("boom"))
    identity = ensure_identity(api)
    assert identity[BUVID3_COOKIE] == "LOCALFAKEBVID3", "远端失败时保留本地兜底 buvid"
    assert identity[BUVID4_COOKIE] == "LOCALFAKEBVID4"
    assert is_valid_uuid(identity[UUID_COOKIE]) and is_valid_b_lsid(identity[B_LSID_COOKIE])


def test_invalid_persisted_values_are_replaced() -> None:
    api = _StubAPI(SPI_OK, cookies={UUID_COOKIE: "not-hex", B_LSID_COOKIE: "bad"})
    identity = ensure_identity(api)
    assert is_valid_uuid(identity[UUID_COOKIE]) and identity[UUID_COOKIE] != "not-hex"
    assert is_valid_b_lsid(identity[B_LSID_COOKIE]) and identity[B_LSID_COOKIE] != "bad"


def test_real_api_generates_identity_without_network() -> None:
    api = BilibiliAPI()
    api._persist_cookies = lambda cookies: None  # 测试不写用户配置
    try:
        api._uuid = ""
        api._b_lsid = ""
        api._b_nut = ""
        identity = ensure_identity(api, fetch_remote=False)
        assert is_valid_uuid(identity[UUID_COOKIE]) and is_valid_b_lsid(identity[B_LSID_COOKIE])
        cookies = api._get_request_cookies()
        assert cookies[UUID_COOKIE] == identity[UUID_COOKIE]
        assert cookies[B_LSID_COOKIE] == identity[B_LSID_COOKIE]
        assert cookies[B_NUT_COOKIE] == identity[B_NUT_COOKIE]
        assert api._get_request_cookies()[BUVID3_COOKIE], "buvid3 必须始终存在"
    finally:
        api.close()


def test_load_identity_prefers_persisted_cookie() -> None:
    """Cookie 优先：已持久化的指纹不得被实例属性里的本地兜底值覆盖。"""
    api = _StubAPI(SPI_OK, cookies={UUID_COOKIE: "from-cookie"})
    api._uuid = "from-attr"
    assert load_identity(api)[UUID_COOKIE] == "from-cookie"
    api._cookies[UUID_COOKIE] = ""
    assert load_identity(api)[UUID_COOKIE] == "from-attr"


def test_buvid_is_persisted_so_restart_keeps_the_same_value() -> None:
    """真机冒烟发现的回归：buvid3/4 过去只在实例属性里，每次启动都重新伪造。"""
    api = _StubAPI(SPI_OK)
    first = ensure_identity(api)
    assert api._cookies[BUVID3_COOKIE] == first[BUVID3_COOKIE], "buvid3 必须落 Cookie"
    # 模拟重启：新实例仍从 Cookie 读旧指纹，并重新生成"本地兜底值"
    api._buvid3 = "REGENERATED-FAKE-3"
    api._buvid4 = "REGENERATED-FAKE-4"
    second = ensure_identity(api)
    assert second[BUVID3_COOKIE] == first[BUVID3_COOKIE], "重启后不得改变已持久化的 buvid"
    assert second[BUVID4_COOKIE] == first[BUVID4_COOKIE]
    assert second == first
