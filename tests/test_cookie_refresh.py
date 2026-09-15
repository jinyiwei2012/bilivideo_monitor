"""Cookie 续期链回归测试（离线：假 API + 假响应，不写用户配置）。

覆盖：公钥可加载且 1024 位 / CorrespondPath 加解密往返 / refresh_csrf 解析 /
不需要续期时零动作 / -101 掉登录 / 缺 refresh_token / 五步字段与 URL /
86095 与 -111 分流 / 确认失败仍保留新 Cookie / 节流。
"""

import base64
from typing import Any, Dict, List, Optional

from core.bilibili_api import BilibiliAPI
from core.bilibili_cookie_refresh import (
    CONFIRM_URL,
    CORRESPOND_URL,
    REFRESH_URL,
    RENEW_PUBLIC_KEY_PEM,
    STATUS_CSRF_FAILED,
    STATUS_ERROR,
    STATUS_LOGGED_OUT,
    STATUS_MISMATCH,
    STATUS_NO_TOKEN,
    STATUS_OK,
    STATUS_UNCHANGED,
    STATUS_UNCONFIRMED,
    extract_cookies,
    gen_correspond_path,
    maybe_refresh,
    parse_refresh_csrf,
    renew_state,
    refresh_now,
)

DOC_HTML = """<body>
  <div id="1-name">b0cc8411ded2f9db2cff2edb3123acac</div>
  <div id="token-iframe-app"></div>
</body>"""

SET_COOKIE_OK = (
    "SESSDATA=new-sessdata; Path=/; Domain=bilibili.com; HttpOnly, "
    "bili_jct=new-csrf; Path=/, DedeUserID=42; Path=/, "
    "DedeUserID__ckMd5=abc123; Path=/, sid=new-sid; Path=/"
)


class _FakeResponse:
    """替身响应：可给 JSON 体、HTML 文本、Set-Cookie 头或 cookie jar。"""

    def __init__(
        self,
        payload: Optional[Dict[str, Any]] = None,
        *,
        text: str = "",
        set_cookie: str = "",
        cookies: Optional[Dict[str, str]] = None,
    ) -> None:
        self._payload = payload
        self.text = text
        self.headers = {"set-cookie": set_cookie} if set_cookie else {}
        self.cookies = cookies or {}

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class _StubAPI:
    """替身 API：第 1 步走 ``_request``，其余步骤走 ``_request_raw``。"""

    def __init__(
        self,
        *,
        info: Optional[Dict[str, Any]] = None,
        responses: Optional[List[_FakeResponse]] = None,
        cookies: Optional[Dict[str, str]] = None,
        refresh_token: str = "old-token",
        logged_out: bool = False,
    ) -> None:
        self.info = info
        self._responses = list(responses or [])
        self._cookies = dict(cookies if cookies is not None else {"SESSDATA": "old", "bili_jct": "oldcsrf"})
        self._refresh_token = refresh_token
        self._logged_out = logged_out
        self._account_name = "默认"
        self._cookie_refresh_at = 0.0
        self.info_calls: List[Dict[str, Any]] = []
        self.raw_calls: List[Dict[str, Any]] = []
        self.set_cookies_calls = 0
        self.persist_calls = 0
        self.account_updates: List[Dict[str, Any]] = []

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        self.info_calls.append({"method": method, "url": url, "kwargs": kwargs})
        return self.info

    def _request_raw(self, method: str, url: str, **kwargs: Any) -> Any:
        self.raw_calls.append({"method": method, "url": url, "kwargs": kwargs})
        return self._responses.pop(0)

    def set_cookies(self, cookies: Dict[str, Any]) -> None:
        self.set_cookies_calls += 1
        self._cookies = dict(cookies)

    def _persist_cookies(self, cookies: Dict[str, Any]) -> None:
        self.persist_calls += 1

    def add_account(self, name: str, cookies: Optional[Dict[str, Any]] = None, refresh_token: str = "") -> None:
        self.account_updates.append({"name": name, "refresh_token": refresh_token, "cookies": cookies or {}})


def _happy_path_api(**kwargs: Any) -> _StubAPI:
    """构造一个「需要续期且五步都成功」的替身。"""
    return _StubAPI(
        info={"refresh": True, "timestamp": 1684466082562},
        responses=[
            _FakeResponse(text=DOC_HTML),  # 第 3 步
            _FakeResponse(  # 第 4 步
                payload={"code": 0, "data": {"status": 0, "refresh_token": "new-token"}},
                set_cookie=SET_COOKIE_OK,
            ),
            _FakeResponse(payload={"code": 0, "message": "0", "ttl": 1}),  # 第 5 步
        ],
        **kwargs,
    )


def test_shipped_public_key_is_loadable_and_1024_bit() -> None:
    """守卫：手抄 PEM 出错会静默破坏续期，这里强制校验可加载 + 密钥长度。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

    key = serialization.load_pem_public_key(RENEW_PUBLIC_KEY_PEM.encode())
    assert isinstance(key, RSAPublicKey)
    assert key.key_size == 1024
    assert base64.b64decode("".join(RENEW_PUBLIC_KEY_PEM.splitlines()[1:-1])), "PEM 应为合法 base64"


def test_correspond_path_roundtrip_with_test_key() -> None:
    """用自建密钥对验证方案正确（RSA-OAEP/SHA-256 + ``refresh_{ms}`` 明文）。"""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    ts = 1684466082562
    path = gen_correspond_path(ts, public_pem.decode())
    assert len(path) == 256 and path == path.lower()
    plaintext = private_key.decrypt(
        bytes.fromhex(path),
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    assert plaintext.decode() == f"refresh_{ts}"


def test_parse_refresh_csrf_from_documented_html() -> None:
    assert parse_refresh_csrf(DOC_HTML) == "b0cc8411ded2f9db2cff2edb3123acac"
    assert parse_refresh_csrf("<html>404</html>") == ""
    assert parse_refresh_csrf("") == ""


def test_not_needed_does_nothing() -> None:
    api = _StubAPI(info={"refresh": False, "timestamp": 1})
    result = refresh_now(api)
    assert result.status == STATUS_UNCHANGED and result.ok is False
    assert api.raw_calls == [] and api.set_cookies_calls == 0 and api.persist_calls == 0


def test_logged_out_is_reported_without_requests() -> None:
    api = _StubAPI(info=None, logged_out=True)
    result = refresh_now(api)
    assert result.status == STATUS_LOGGED_OUT
    assert "重新登录" in result.message
    assert api.raw_calls == []


def test_missing_refresh_token_stops_before_network() -> None:
    api = _StubAPI(info={"refresh": True, "timestamp": 1}, refresh_token="")
    result = refresh_now(api)
    assert result.status == STATUS_NO_TOKEN
    assert api.raw_calls == []


def test_full_flow_urls_and_fields() -> None:
    api = _happy_path_api()
    result = refresh_now(api)

    assert result.status == STATUS_OK and result.ok is True
    assert len(api.raw_calls) == 3
    correspond, refresh, confirm = api.raw_calls
    assert correspond["method"] == "GET" and correspond["url"].startswith(CORRESPOND_URL.format(path=""))
    assert refresh["method"] == "POST" and refresh["url"] == REFRESH_URL
    payload = refresh["kwargs"]["data"]
    assert payload["csrf"] == "oldcsrf", "第 4 步的 csrf 应取当前 Cookie 里的 bili_jct"
    assert payload["refresh_csrf"] == "b0cc8411ded2f9db2cff2edb3123acac"
    assert payload["source"] == "main_web"
    assert payload["refresh_token"] == "old-token", "第 4 步应提交旧 token"
    assert confirm["url"] == CONFIRM_URL
    confirm_payload = confirm["kwargs"]["data"]
    assert confirm_payload["csrf"] == "new-csrf", "第 5 步的 csrf 必须用新 Cookie"
    assert confirm_payload["refresh_token"] == "old-token", "第 5 步仍用旧 token 让旧凭证失效"

    assert result.cookies["SESSDATA"] == "new-sessdata"
    assert api._cookies["bili_jct"] == "new-csrf"
    assert api._refresh_token == "new-token"
    assert api.persist_calls == 1 and api.set_cookies_calls == 1
    assert api.account_updates and api.account_updates[0]["refresh_token"] == "new-token"
    assert api._logged_out is False
    assert renew_state(api)["has_refresh_token"] is True


def test_csrf_page_failure_gives_reason() -> None:
    api = _StubAPI(info={"refresh": True, "timestamp": 1}, responses=[_FakeResponse(text="<html>404</html>")])
    result = refresh_now(api)
    assert result.status == STATUS_CSRF_FAILED
    assert "refresh_csrf" in result.message
    assert len(api.raw_calls) == 1, "取不到 csrf 时不得继续提交续期"


def test_mismatch_and_csrf_error_codes() -> None:
    mismatch = _StubAPI(
        info={"refresh": True, "timestamp": 1},
        responses=[_FakeResponse(text=DOC_HTML), _FakeResponse(payload={"code": 86095, "message": "0"})],
    )
    result = refresh_now(mismatch)
    assert result.status == STATUS_MISMATCH and "86095" in result.message

    bad_csrf = _StubAPI(
        info={"refresh": True, "timestamp": 1},
        responses=[_FakeResponse(text=DOC_HTML), _FakeResponse(payload={"code": -111, "message": "csrf"})],
    )
    result = refresh_now(bad_csrf)
    assert result.status == STATUS_ERROR and "csrf" in result.message


def test_confirm_failure_keeps_new_cookies() -> None:
    api = _happy_path_api()
    api._responses[2] = _FakeResponse(payload={"code": -400, "message": "bad request"})
    result = refresh_now(api)
    assert result.status == STATUS_UNCONFIRMED and result.ok is True
    assert "确认步骤失败" in result.message
    assert api._cookies["SESSDATA"] == "new-sessdata", "已换到的新 Cookie 必须保留"
    assert api.persist_calls == 1


def test_missing_new_cookies_is_error() -> None:
    api = _StubAPI(
        info={"refresh": True, "timestamp": 1},
        responses=[
            _FakeResponse(text=DOC_HTML),
            _FakeResponse(payload={"code": 0, "data": {"refresh_token": "new-token"}}),
        ],
    )
    result = refresh_now(api)
    assert result.status == STATUS_ERROR
    assert "未带回新 Cookie" in result.message


def test_extract_cookies_from_jar_and_header() -> None:
    from_jar = extract_cookies(_FakeResponse(cookies={"SESSDATA": "s", "bili_jct": "j", "other": "x"}))
    assert from_jar == {"SESSDATA": "s", "bili_jct": "j"}
    from_header = extract_cookies(_FakeResponse(set_cookie=SET_COOKIE_OK))
    assert set(from_header) == {"SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"}


def test_maybe_refresh_throttles_by_interval() -> None:
    api = _happy_path_api()
    first = maybe_refresh(api, interval_hours=12.0)
    assert first is not None and first.status == STATUS_OK
    assert len(api.raw_calls) == 3
    api.info = {"refresh": True, "timestamp": 1}
    assert maybe_refresh(api, interval_hours=12.0) is None, "未到间隔不得再发请求"
    assert len(api.raw_calls) == 3
    api._responses = [
        _FakeResponse(text=DOC_HTML),
        _FakeResponse(payload={"code": 0, "data": {"refresh_token": "t2"}}, set_cookie=SET_COOKIE_OK),
        _FakeResponse(payload={"code": 0, "message": "0"}),
    ]
    forced = maybe_refresh(api, interval_hours=12.0, force=True)
    assert forced is not None and len(api.raw_calls) == 6
    assert renew_state(api)["last_refresh_at"] > 0


def test_real_api_exposes_raw_request() -> None:
    api = BilibiliAPI()
    api._persist_cookies = lambda cookies: None
    try:
        assert callable(getattr(api, "_request_raw", None)), "续期依赖原始响应能力"
        assert renew_state(api)["last_refresh_at"] == 0.0
    finally:
        api.close()
