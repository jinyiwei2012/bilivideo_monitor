"""密码登录 / 扫码登录契约回归测试（离线：假 API + 真实 RSA 密钥对，无网络）。

覆盖 `docs/bilibili_api_contract.md` §7 的实现项：
(a) ④ 登录密码密文以 base64 提交（可 PKCS1v15 解回 hash+password，旧 hex 形式必失败）；
(b) ⑥ 极验 seccode 带 "|jordan"、challenge/token 透传、**不发**不存在的 captcha/captcha_type；
(c) ⑦ code==0 但 data.status != 0 判为风控失败（message 含「风控」、不写 Cookie）；
(d) ⑧ refresh_token 换票 URL 为 /web/exchange_cookie（而非旧的 /web/exchange）；
(e) ⑤ 每次提交前重取 key/salt：`-662` 重取重试一次；极验重提同样重取；
(f) ⑨ 扫码三来源**合并**收全 5 个登录 Cookie（键集与 LOGIN_COOKIE_KEYS 同源）。
"""

import base64
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from core import bilibili_auth
from core.bilibili_auth import (
    LOGIN_COOKIE_KEYS,
    _collect_qr_response_cookies,
    _exchange_qr_refresh_token,
    _password_login_result,
    _submit_geetest_login,
    _try_auto_geetest_login,
    _with_jordan,
    login_with_password,
)

QR_FIVE: Dict[str, str] = {
    "SESSDATA": "sd",
    "bili_jct": "jc",
    "DedeUserID": "111",
    "DedeUserID__ckMd5": "md5-val",
    "sid": "sid-val",
}


class _StubCookies:
    """最小 Session Cookie 容器替身（requests.Session.cookies 的使用面）。"""

    def __init__(self) -> None:
        self.store: Dict[str, Any] = {}

    def update(self, cookies: Dict[str, Any]) -> None:
        self.store.update(cookies)

    def __contains__(self, key: object) -> bool:
        return key in self.store

    def __getitem__(self, key: str) -> Any:
        return self.store[key]


class _StubResponse:
    """最小 HTTP 响应替身：json() + cookies + status_code。"""

    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload
        self.cookies: Dict[str, Any] = {}
        self.status_code = 200

    def json(self) -> Dict[str, Any]:
        return self._payload


class _StubSession:
    """记录 post(url, data=...) 的会话替身；可给一串 payload（按调用顺序取，末尾重复）。"""

    def __init__(self, payload: Any) -> None:
        self.payloads: List[Any] = list(payload) if isinstance(payload, list) else [payload]
        self.cookies = _StubCookies()
        self.posts: List[Dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> _StubResponse:
        idx = min(len(self.posts), len(self.payloads) - 1)
        recorded = dict(kwargs)
        if isinstance(recorded.get("data"), dict):
            recorded["data"] = dict(recorded["data"])  # 快照：调用方改自己的 dict 不应污染已记录内容
        self.posts.append({"url": url, **recorded})
        return _StubResponse(self.payloads[idx])


class _StubAPI:
    """最小 API 替身：提供密码登录 mixin 用到的属性（_request / session / USER_AGENTS）。"""

    USER_AGENTS = ["ua-test"]

    def __init__(
        self,
        *,
        key_payload: Optional[Dict[str, Any]] = None,
        key_payloads: Optional[List[Dict[str, Any]]] = None,
        captcha_payload: Optional[Dict[str, Any]] = None,
        login_payload: Any = None,
    ) -> None:
        if key_payloads is not None:
            self._key_payloads = list(key_payloads)
        else:
            self._key_payloads = [key_payload] if key_payload else [{}]
        self.key_calls = 0
        self.captcha_calls = 0
        self._captcha_payload = captcha_payload if captcha_payload is not None else {}
        self.session = _StubSession(login_payload if login_payload is not None else {"code": -1, "message": "stub"})
        self._cookies: Dict[str, Any] = {}
        self._refresh_token = ""

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        if "/captcha" in url:
            self.captcha_calls += 1
            return self._captcha_payload
        payload = self._key_payloads[min(self.key_calls, len(self._key_payloads) - 1)]
        if url.endswith("/web/key"):
            self.key_calls += 1
        return payload

    def _sanitize_cookies(self, cookies: Dict[str, Any]) -> Dict[str, Any]:
        return dict(cookies)


def _rsa_keypair() -> Tuple[str, rsa.RSAPrivateKey]:
    """生成一次性 RSA-2048 密钥对，返回 (公钥 PEM, 私钥对象)。"""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    pem = (
        private_key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return pem, private_key


def _decrypt(posted: Dict[str, Any], private_key: rsa.RSAPrivateKey) -> str:
    """解回 ``salt + password`` 明文。"""
    ciphertext = base64.b64decode(posted["password"], validate=True)
    return private_key.decrypt(ciphertext, padding.PKCS1v15()).decode()


# ═══════════════ ④ 密文 base64 ═══════════════


def test_password_ciphertext_is_base64_not_hex() -> None:
    """(a) 提交的 password 必须是 base64，且解回明文 == hash + 原始密码。

    若回退到旧的 ``encrypted.hex()``：hex 串虽能被 base64 解出字节，但长度
    不再是 RSA 分组大小，PKCS1v15 解密会直接抛错 —— 本断言必然失败。
    """
    pem, private_key = _rsa_keypair()
    hash_str = "0123456789abcdef"
    plain_password = "p@ssw0rd!"
    api = _StubAPI(
        key_payload={"key": pem, "hash": hash_str},
        login_payload={"code": -2100, "message": "stub-stop"},
    )

    login_with_password(api, "user@example.com", plain_password)

    assert len(api.session.posts) == 1
    assert _decrypt(api.session.posts[0]["data"], private_key) == hash_str + plain_password


# ═══════════════ ⑥ 极验字段 ═══════════════


def test_submit_geetest_seccode_carries_jordan_suffix() -> None:
    """(b1) 手动极验重提：seccode 带 "|jordan"、明文可解、不带不存在的 captcha 字段。"""
    pem, private_key = _rsa_keypair()
    api = _StubAPI(key_payload={"key": pem, "hash": "salt-1"})

    result, _raw = _submit_geetest_login(api, "https://example/login", "user", "p@ss", "val-1:sec-1")

    assert result is None, "stub 响应 code!=0，不应判成功"
    posted = api.session.posts[0]["data"]
    assert posted["validate"] == "val-1"
    assert posted["seccode"] == "sec-1|jordan"
    assert posted["username"] == "user"
    assert _decrypt(posted, private_key) == "salt-1p@ss"
    assert "captcha" not in posted and "captcha_type" not in posted, "契约 §2：不存在这两个字段"
    assert api.key_calls == 1, "提交前必须重取 key/salt"


def test_auto_geetest_passes_challenge_and_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """(b2) 自动求解路径：seccode 带 "|jordan"，服务端给的 challenge/token 必须透传。"""
    pem, _private_key = _rsa_keypair()
    api = _StubAPI(key_payload={"key": pem, "hash": "salt-2"})
    monkeypatch.setattr(bilibili_auth, "_auto_solve_geetest", lambda self, gt, challenge: ("v-auto", "s-auto"))

    result = _try_auto_geetest_login(
        api,
        "https://example/login",
        "user",
        "p@ss",
        {"data": {"gt": "g-1", "challenge": "c-1", "token": "tok-1"}},
    )

    assert result is None, "stub 响应 code!=0，不应判成功"
    posted = api.session.posts[0]["data"]
    assert posted["validate"] == "v-auto"
    assert posted["seccode"] == "s-auto|jordan"
    assert posted["challenge"] == "c-1"
    assert posted["token"] == "tok-1"
    assert "captcha" not in posted


def test_auto_geetest_fetches_captcha_challenge_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """(b4) 失败响应没给 gt/challenge 时：必须先申请验证码，并把 token/challenge 一起提交。

    证据（公开实现一致）：`GET /x/passport-login/captcha?source=main_web` →
    `data.token` + `data.geetest.{gt,challenge}`；`token` 是密码登录体字段。
    """
    pem, _private_key = _rsa_keypair()
    api = _StubAPI(
        key_payload={"key": pem, "hash": "salt-3"},
        captcha_payload={"data": {"token": "tk-9", "geetest": {"gt": "gt-9", "challenge": "ch-9"}}},
        login_payload={"code": -2100, "message": "stop"},
    )
    solved: List[str] = []

    def _fake_solve(self: Any, gt: str, challenge: str) -> Any:
        solved.append(f"{gt}:{challenge}")
        return ("v-9", "s-9")

    monkeypatch.setattr(bilibili_auth, "_auto_solve_geetest", _fake_solve)

    result = _try_auto_geetest_login(api, "https://example/login", "user", "p@ss", {"code": -2100})

    assert api.captcha_calls == 1, "必须调用申请验证码接口"
    assert solved == ["gt-9:ch-9"], "应当用申请到的 gt/challenge 去求解"
    assert result is None, "stub 响应 code!=0，不应判成功"
    posted = api.session.posts[0]["data"]
    assert posted["token"] == "tk-9"
    assert posted["challenge"] == "ch-9"
    assert posted["validate"] == "v-9"
    assert posted["seccode"] == "s-9|jordan"


def test_auto_geetest_gives_up_when_captcha_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """(b5) 申请验证码失败（无 gt/challenge）时安静放弃：不抛异常、不发登录请求。"""
    api = _StubAPI(key_payload={"key": "x", "hash": "y"})
    monkeypatch.setattr(bilibili_auth, "_auto_solve_geetest", lambda self, gt, challenge: ("v", "s"))

    assert _try_auto_geetest_login(api, "https://example/login", "user", "p@ss", {"code": -2100}) is None
    assert api.session.posts == [], "没有极验参数就不该提交登录"


def test_with_jordan_is_idempotent() -> None:
    """(b3) 幂等：已带后缀不重复追加。"""
    assert _with_jordan("abc") == "abc|jordan"
    assert _with_jordan("abc|jordan") == "abc|jordan"


# ═══════════════ ⑦ 风控 status ═══════════════


def test_risk_control_status_forces_failure_and_skips_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    """(c) code==0 但 data.status!=0：视为风控失败，不调用 set_cookies。"""
    api = _StubAPI()
    set_cookie_calls: List[Dict[str, Any]] = []
    monkeypatch.setattr(bilibili_auth, "set_cookies", lambda self, cookies: set_cookie_calls.append(dict(cookies)))

    risk = _password_login_result(api, _StubResponse({"code": 0}), {"status": 1, "url": ""}, include_sid=True)
    assert risk["code"] != 0, "status!=0 不得返回 code==0"
    assert "风控" in risk["message"]
    assert risk["cookies"] == {}
    assert risk["need_captcha"] is False
    assert risk["refresh_token"] == "", "失败结果必须保留 refresh_token 键（登录主流程直接取下标）"
    assert set_cookie_calls == [], "风控失败不得写入任何 Cookie"

    # 基线行为不变：status==0 仍按成功路径返回
    ok = _password_login_result(api, _StubResponse({"code": 0}), {"status": 0, "url": ""}, include_sid=True)
    assert ok["code"] == 0
    assert ok["message"] == "登录成功"


# ═══════════════ ⑧ 换票 URL ═══════════════


def test_exchange_uses_exchange_cookie_endpoint() -> None:
    """(d) QR 换票必须打 /web/exchange_cookie（旧 /web/exchange 已失效）。"""
    api = _StubAPI()
    sess = _StubSession({"data": {}})

    cookies = _exchange_qr_refresh_token(api, sess, {"refresh_token": "rt-123"})

    assert len(sess.posts) == 1
    assert sess.posts[0]["url"] == "https://passport.bilibili.com/x/passport-login/web/exchange_cookie"
    assert sess.posts[0]["data"] == {"refresh_token": "rt-123"}
    assert cookies == {}


# ═══════════════ ⑤ 每次提交前重取 key/salt ═══════════════


def test_minus_662_refetches_key_and_retries_once() -> None:
    """(e1) `-662`（盐过期）→ 重取 key/salt 重新加密后重试一次（契约验收：key 接口 ≥2 次）。"""
    pem1, key1 = _rsa_keypair()
    pem2, key2 = _rsa_keypair()
    api = _StubAPI(
        key_payloads=[{"key": pem1, "hash": "s1"}, {"key": pem2, "hash": "s2"}],
    )
    api.session = _StubSession([{"code": -662, "message": "时间戳过期"}, {"code": -2100, "message": "stop"}])

    login_with_password(api, "u", "p@ss")

    assert api.key_calls == 2, "必须重取一次 key/salt"
    assert len(api.session.posts) == 2, "必须重试且只重试一次"
    assert _decrypt(api.session.posts[0]["data"], key1) == "s1p@ss"
    assert _decrypt(api.session.posts[1]["data"], key2) == "s2p@ss", "重试必须用新盐重新加密"


def test_geetest_resubmit_refetches_key() -> None:
    """(e2) 极验重提路径同样重取 key/salt（主提交 + 重提各一次）。"""
    pem, key = _rsa_keypair()
    api = _StubAPI(key_payload={"key": pem, "hash": "s"})
    api.session = _StubSession([{"code": -2100, "message": "need geetest"}, {"code": -2100, "message": "stop"}])

    login_with_password(api, "u", "p@ss", captcha="val-1:sec-1", captcha_type=-1)

    assert api.key_calls == 2
    assert len(api.session.posts) == 2
    first, second = api.session.posts[0]["data"], api.session.posts[1]["data"]
    assert first["validate"] == "val-1" and second["seccode"] == "sec-1|jordan"
    assert "captcha" not in first and "captcha_type" not in first, "首个提交也不得带不存在的字段"


# ═══════════════ ⑨ 扫码收全 5 个 Cookie ═══════════════


def test_login_cookie_keys_are_the_five() -> None:
    """(f1) 登录 Cookie 键名单是契约 §3 的 5 个（单一来源，防再次漂移）。"""
    assert LOGIN_COOKIE_KEYS == ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")


def test_qr_redirect_url_provides_all_five() -> None:
    """(f2) crossDomain 重定向 URL 带回全部 5 个键。"""
    api = _StubAPI()
    url = "https://passport.biligame.com/crossDomain?" + urlencode(QR_FIVE)

    cookies = _collect_qr_response_cookies(api, _StubResponse({"code": 0}), {"url": url})

    assert set(QR_FIVE) <= set(cookies)


def test_qr_cookies_merge_across_sources() -> None:
    """(f3) 三来源各给一部分时必须**合并**收全 5 个（旧实现「首个非空即返回」会丢键）。"""
    api = _StubAPI()
    resp = _StubResponse({"code": 0})
    resp.cookies = {"sid": QR_FIVE["sid"]}
    data = {
        "url": "https://passport.biligame.com/crossDomain?"
        + urlencode({"SESSDATA": "sd", "bili_jct": "jc", "DedeUserID": "111"}),
        "cookie_info": {"cookies": [{"name": "DedeUserID__ckMd5", "value": QR_FIVE["DedeUserID__ckMd5"]}]},
    }

    cookies = _collect_qr_response_cookies(api, resp, data)

    assert cookies == QR_FIVE, "必须从三处来源合并出完整 5 键"
