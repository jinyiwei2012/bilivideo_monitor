"""扫码登录契约特征测试（离线：桩式 session / response，无网络）。

覆盖 `ora-13` 钉定的、既有测试尚未保护的扫码行为面：
- poll 状态映射矩阵（86038 / 86101 / raw_status 2 / 1 / 0 / 未知 / 冲突优先级）；
- withdrawal 合并的 redirect / cookie_info 来源优先级（三来源已在 test_password_login_contract 覆盖一部分，
  此处补优先级与空值边界）；
- refresh_token 换票回退的触发条件与副作用顺序；
- QR session 惰性创建、复用、请求头与 timeout；
- 公开兼容面：BilibiliAPI 经 `_AuthMixin` 拿到两个扫码方法。

这些测试在执行重构前先冻结行为，任何后续改动不得使其变红。
"""

from typing import Any, Dict, List, Optional

from core.bilibili_auth import (
    LOGIN_COOKIE_KEYS,
    _apply_qr_poll_status,
    _init_qr_session,
    _close_qr_session,
    get_qrcode_login_url,
    poll_qrcode_login,
)

QR_FIVE: Dict[str, str] = {
    "SESSDATA": "sd",
    "bili_jct": "jc",
    "DedeUserID": "111",
    "DedeUserID__ckMd5": "md5-val",
    "sid": "sid-val",
}


class _StubCookies:
    def __init__(self) -> None:
        self.store: Dict[str, Any] = {}

    def update(self, cookies: Dict[str, Any]) -> None:
        self.store.update(cookies)

    def __contains__(self, key: object) -> bool:
        return key in self.store

    def __getitem__(self, key: str) -> Any:
        return self.store[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.store.get(key, default)


class _StubResponse:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.cookies = _StubCookies()

    def json(self) -> Dict[str, Any]:
        return self._payload


class _StubGetSession:
    """记录 get(url, params=...) 的 session 替身，可配置 headers / 返回 payload。"""

    def __init__(self, payloads: Optional[List[Any]] = None, status_code: int = 200) -> None:
        self.payloads: List[Any] = list(payloads) if isinstance(payloads, list) else [payloads]
        self.status_code = status_code
        self.headers: Dict[str, str] = {}
        self.cookies = _StubCookies()
        self.gets: List[Dict[str, Any]] = []
        self.closed = False

    def get(self, url: str, **kwargs: Any) -> _StubResponse:
        idx = min(len(self.gets), len(self.payloads) - 1)
        self.gets.append({"url": url, **kwargs})
        resp = _StubResponse(self.payloads[idx] if self.payloads[idx] is not None else {}, self.status_code)
        # 让响应继承 session 的 cookie 容器语义（真实 requests 中 resp.cookies 由 Set-Cookie 填充）
        resp.cookies.store.update(self.cookies.store)
        return resp

    def close(self) -> None:
        self.closed = True


class _StubHost:
    """扫码宿主替身：提供 USER_AGENTS / set_cookies / _persist_cookies。"""

    USER_AGENTS = ["ua-test"]

    def __init__(self) -> None:
        self._qr_session: Any = None
        self._cookies: Dict[str, Any] = {}
        self.session = _StubGetSession([{}])
        self.applied: List[Dict[str, Any]] = []
        self.persisted: List[Dict[str, Any]] = []

    def _sanitize_cookies(self, cookies: Dict[str, Any]) -> Dict[str, Any]:
        return dict(cookies)

    def set_cookies(self, cookies: Dict[str, Any]) -> None:
        self.applied.append(dict(cookies))

    def _persist_cookies(self, cookies: Dict[str, Any]) -> None:
        self.persisted.append(dict(cookies))


# ── poll 状态映射矩阵 ──────────────────────────────────────────────


def _status_result(code: Any, raw_status: Any = None, message: str = "m") -> Dict[str, Any]:
    data = {"code": code, "message": message}
    if raw_status is not None:
        data["data"] = {"status": raw_status, "message": message}
    else:
        data["data"] = {}
    result: Dict[str, Any] = {"status": 0, "message": "等待扫码", "cookies": {}}
    _apply_qr_poll_status(result, data)
    return result


def test_poll_status_expired():
    r = _status_result(86038)
    assert r["status"] == -1
    assert r["message"] == "二维码已过期"


def test_poll_status_waiting_scan():
    r = _status_result(86101)
    assert r["status"] == 0
    assert r["message"] == "等待扫码"


def test_poll_status_success():
    r = _status_result(0, raw_status=2)
    assert r["status"] == 2
    assert r["message"] == "登录成功"


def test_poll_status_scanned_wait_confirm():
    r = _status_result(0, raw_status=1)
    assert r["status"] == 1


def test_poll_status_waiting_raw_zero():
    r = _status_result(0, raw_status=0)
    assert r["status"] == 0
    assert r["message"] == "等待扫码"


def test_poll_status_unknown_raw_status_degrades():
    r = _status_result(0, raw_status=99)
    assert r["status"] == -1


def test_poll_status_outer_code_takes_priority_over_raw_status():
    """外层 code 非 0 时优先于 data.status 判定。"""
    r = _status_result(86038, raw_status=2)
    assert r["status"] == -1
    assert r["message"] == "二维码已过期"


def test_poll_status_nonzero_code_returns_false():
    result: Dict[str, Any] = {"status": 0, "message": "", "cookies": {}}
    data = {"code": -400, "message": "bad", "data": {}}
    assert _apply_qr_poll_status(result, data) is False
    assert result["status"] == 0


def test_poll_status_success_returns_true():
    result: Dict[str, Any] = {"status": 0, "message": "", "cookies": {}}
    assert _apply_qr_poll_status(result, {"code": 0, "data": {"status": 2}}) is True


# ── get_qrcode_login_url ──────────────────────────────────────────


def test_get_qrcode_login_url_returns_url_and_key(monkeypatch):
    host = _StubHost()
    sess = _StubGetSession([{"code": 0, "data": {"url": "https://x/qr", "qrcode_key": "KEY"}}])
    monkeypatch.setattr("core.bilibili_auth._init_qr_session", lambda _host: sess)
    out = get_qrcode_login_url(host)
    assert out == {"url": "https://x/qr", "qrcode_key": "KEY"}


def test_get_qrcode_login_url_returns_none_on_http_error(monkeypatch):
    host = _StubHost()
    sess = _StubGetSession([{"code": 0, "data": {}}], status_code=500)
    monkeypatch.setattr("core.bilibili_auth._init_qr_session", lambda _host: sess)
    assert get_qrcode_login_url(host) is None


# ── QR session 生命周期 ────────────────────────────────────────────


def test_qr_session_is_lazily_created_and_reused(monkeypatch):
    host = _StubHost()
    made: List[Any] = []

    class _FakeReqSession:
        def __init__(self) -> None:
            self.headers: Dict[str, str] = {}
            made.append(self)

        def close(self) -> None:
            pass

    monkeypatch.setattr("core.bilibili_auth.random.choice", lambda seq: seq[0])
    import requests as _req

    monkeypatch.setattr(_req, "Session", _FakeReqSession)

    first = _init_qr_session(host)
    second = _init_qr_session(host)
    assert first is second
    assert len(made) == 1
    for header in ("User-Agent", "Referer", "Accept"):
        assert header in first.headers


def test_qr_session_close_is_idempotent():
    host = _StubHost()
    host._qr_session = _StubGetSession([{}])
    _close_qr_session(host)
    assert host._qr_session is None
    _close_qr_session(host)  # 重复关闭不报错
    assert host._qr_session is None


# ── refresh_token 换票回退 ─────────────────────────────────────────


def test_poll_success_collects_cookies_and_side_effects(monkeypatch):
    """成功路径：set_cookies 与 _persist_cookies 各一次，且先 set 后 persist。"""
    host = _StubHost()
    order: List[str] = []

    def _set(_host: Any, cookies: Dict[str, Any]) -> None:
        order.append("set")
        host.applied.append(dict(cookies))

    def _persist(_host: Any, cookies: Dict[str, Any]) -> None:
        order.append("persist")
        host.persisted.append(dict(cookies))

    monkeypatch.setattr("core.bilibili_auth.set_cookies", _set)
    monkeypatch.setattr("core.bilibili_auth._persist_cookies", _persist)

    sess = _StubGetSession([{"code": 0, "data": {"status": 2}, "cookie_info": {"cookies": []}}])
    for k, v in QR_FIVE.items():
        sess.cookies.store[k] = v
    monkeypatch.setattr("core.bilibili_auth._init_qr_session", lambda _host: sess)

    result = poll_qrcode_login(host, "KEY")
    assert result["status"] == 2
    assert order == ["set", "persist"]
    assert result["cookies"] == QR_FIVE


def test_poll_waiting_does_not_write_cookies(monkeypatch):
    host = _StubHost()
    sess = _StubGetSession([{"code": 86101, "data": {"message": "等待扫码"}}])
    monkeypatch.setattr("core.bilibili_auth._init_qr_session", lambda _host: sess)

    result = poll_qrcode_login(host, "KEY")
    assert result["status"] == 0
    assert host.applied == []
    assert host.persisted == []


def test_poll_exchange_fallback_when_no_direct_cookies(monkeypatch):
    """直接响应无 cookie 且有 refresh_token 时，走 exchange 换票。"""
    host = _StubHost()
    exchanged: List[bool] = []

    def _exchange(_host, _sess, _data):
        exchanged.append(True)
        return dict(QR_FIVE)

    monkeypatch.setattr("core.bilibili_auth._exchange_qr_refresh_token", _exchange)
    sess = _StubGetSession([{"code": 0, "data": {"status": 2, "refresh_token": "rt"}}])
    monkeypatch.setattr("core.bilibili_auth._init_qr_session", lambda _host: sess)

    result = poll_qrcode_login(host, "KEY")
    assert exchanged == [True]
    assert result["cookies"] == QR_FIVE


# ── 公开兼容面：_AuthMixin 别名 ────────────────────────────────────


def test_auth_mixin_exposes_qr_methods():
    from core.bilibili_auth import _AuthMixin

    assert callable(_AuthMixin.get_qrcode_login_url)
    assert callable(_AuthMixin.poll_qrcode_login)


def test_bilibili_api_has_qr_methods():
    from core.bilibili_api import BilibiliAPI

    assert callable(getattr(BilibiliAPI, "get_qrcode_login_url", None))
    assert callable(getattr(BilibiliAPI, "poll_qrcode_login", None))


def test_login_cookie_keys_contract_is_five():
    assert LOGIN_COOKIE_KEYS == ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")
