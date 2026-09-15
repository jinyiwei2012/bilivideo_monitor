"""w_webid 回归测试（离线：假 API + 临时缓存文件）。

覆盖：__RENDER_DATA__ 解析（URL 编码/明文/嵌套） / 按天缓存（当天零请求、跨天重取、force） /
失败回退不抛错 / 直播页备选 / 参与 WBI 签名（出现在 query 且改变 w_rid） / 排序。
"""

import json
import time
from typing import Any, Dict, List, Optional
from unittest import mock
from urllib.parse import quote

import core.w_webid as w_webid
from core.bilibili_api import BilibiliAPI, wbi_query
from core.w_webid import (
    LIVE_URL,
    SPACE_URL,
    cache_state,
    clear_cache,
    extract_access_id,
    fetch_access_id,
    is_fresh,
    load_cache,
    save_cache,
    with_w_webid,
)

ACCESS_ID = "e5f0a1b2c3d4e5f60718293a4b5c6d7e"
RENDER_PAYLOAD = {"access_id": ACCESS_ID, "other": 1}


def _page(payload: Any = RENDER_PAYLOAD, *, encode: bool = True) -> str:
    """构造带 ``#__RENDER_DATA__`` 的页面（默认 URL 编码，与真实页面一致）。"""
    raw = json.dumps(payload)
    inner = quote(raw, safe="") if encode else raw
    return (
        f'<html><head></head><body><script id="__RENDER_DATA__" type="application/json">{inner}</script></body></html>'
    )


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.headers: Dict[str, str] = {}
        self.cookies: Dict[str, str] = {}


class _StubAPI:
    def __init__(self, pages: Optional[List[str]] = None, *, cookies: Optional[Dict[str, str]] = None) -> None:
        self.pages = list(pages if pages is not None else [_page()])
        self.calls: List[str] = []
        self._cookies = dict(cookies if cookies is not None else {"DedeUserID": "42"})
        self._request_raw_raises = False

    def _request_raw(self, method: str, url: str, **kwargs: Any) -> Any:
        self.calls.append(url)
        if self._request_raw_raises:
            raise RuntimeError("boom")
        return _FakeResponse(self.pages.pop(0) if self.pages else "")


def _patch_cache(tmp_path: Any) -> Any:
    """把缓存文件指到临时目录（绝不碰真实 data/）。"""
    return mock.patch.object(w_webid, "_cache_file", lambda: str(tmp_path / "w_webid.json"))


def test_extract_access_id_from_url_encoded_render_data(tmp_path: Any) -> None:
    with _patch_cache(tmp_path):
        assert extract_access_id(_page()) == ACCESS_ID
        assert extract_access_id(_page(encode=False)) == ACCESS_ID, "明文 JSON 也要能解析"


def test_extract_access_id_nested_and_missing(tmp_path: Any) -> None:
    with _patch_cache(tmp_path):
        nested = {"route": {"nav": {"access_id": "nested-id"}}}
        assert extract_access_id(_page(nested)) == "nested-id"
        assert extract_access_id(_page({"route": {}})) == ""
        assert extract_access_id("<html>no render data</html>") == ""
        assert extract_access_id("") == ""


def test_is_fresh_is_same_day(tmp_path: Any) -> None:
    with _patch_cache(tmp_path):
        now = time.time()
        assert is_fresh({"access_id": "x", "ts": now}, now) is True
        assert is_fresh({"access_id": "x", "ts": now - 86400 * 2}, now) is False, "跨天应失效"
        assert is_fresh({"access_id": "", "ts": now}, now) is False
        assert is_fresh({}, now) is False
        assert is_fresh({"access_id": "x", "ts": "bad"}, now) is False


def test_same_day_cache_hit_makes_no_request(tmp_path: Any) -> None:
    with _patch_cache(tmp_path):
        api = _StubAPI()
        first = w_webid.get_w_webid(api)
        assert first == ACCESS_ID and len(api.calls) == 1
        assert api.calls[0] == SPACE_URL.format(mid="42"), "应优先用自己的空间页"
        second = w_webid.get_w_webid(api)
        assert second == ACCESS_ID
        assert len(api.calls) == 1, "同一天内第二次调用不得再发请求"
        assert load_cache()["access_id"] == ACCESS_ID


def test_force_and_cross_day_refetch(tmp_path: Any) -> None:
    with _patch_cache(tmp_path):
        api = _StubAPI([_page({"access_id": "id-1"}), _page({"access_id": "id-2"}), _page({"access_id": "id-3"})])
        assert w_webid.get_w_webid(api) == "id-1"
        assert w_webid.get_w_webid(api, force=True) == "id-2"
        save_cache("stale", now=time.time() - 86400 * 3)
        assert w_webid.get_w_webid(api) == "id-3", "跨天缓存应重取"
        assert len(api.calls) == 3


def test_failure_falls_back_without_raising(tmp_path: Any) -> None:
    with _patch_cache(tmp_path):
        api = _StubAPI()
        api._request_raw_raises = True
        assert w_webid.get_w_webid(api) == "", "请求异常时返回空串"
        save_cache("cached-id", now=time.time() - 86400 * 3)  # 陈旧缓存
        assert w_webid.get_w_webid(api) == "cached-id", "取不到新值时回退旧值，不阻塞调用方"


def test_live_page_fallback_when_space_page_empty(tmp_path: Any) -> None:
    with _patch_cache(tmp_path):
        api = _StubAPI(["<html>empty</html>", _page({"access_id": "from-live"})])
        assert fetch_access_id(api) == "from-live"
        assert api.calls == [SPACE_URL.format(mid="42"), LIVE_URL]


def test_no_mid_still_tries_live_page(tmp_path: Any) -> None:
    with _patch_cache(tmp_path):
        api = _StubAPI([_page({"access_id": "no-mid-id"})], cookies={})
        assert fetch_access_id(api) == "no-mid-id"
        assert api.calls == [LIVE_URL]


def test_with_w_webid_participates_in_wbi_signature() -> None:
    api = BilibiliAPI()
    api._persist_cookies = lambda cookies: None
    try:
        api._wbi_key = "0123456789abcdef0123456789abcdef"
        api._wbi_key_expire = time.time() + 600
        base = {"mid": 42}
        signed_plain = api._wbi_sign(dict(base))
        signed_webid = api._wbi_sign(with_w_webid(api, base, value="webid-value"))

        assert "w_webid" not in signed_plain
        assert signed_webid["w_webid"] == "webid-value"
        assert signed_webid["wts"] and signed_webid["w_rid"]
        assert signed_webid["w_rid"] != signed_plain["w_rid"], "w_webid 必须进入 w_rid 的 md5"
        query = wbi_query(signed_webid)
        assert "w_webid=webid-value" in query
        assert query == "&".join(sorted(query.split("&"))), "query 必须按 key 升序（w_webid 参与排序）"
    finally:
        api.close()


def test_with_w_webid_without_value_returns_params_unchanged(tmp_path: Any) -> None:
    with _patch_cache(tmp_path):
        api = _StubAPI(["<html>empty</html>", "<html>empty</html>"])
        params = {"mid": 42}
        assert with_w_webid(api, params) == params, "取不到值时不得引入空参数"
        assert "w_webid" not in with_w_webid(api, params)


def test_cache_state_and_clear(tmp_path: Any) -> None:
    with _patch_cache(tmp_path):
        assert cache_state()["has_value"] is False
        save_cache(ACCESS_ID)
        state = cache_state()
        assert state["has_value"] is True and state["fresh"] is True
        clear_cache()
        assert cache_state()["has_value"] is False
