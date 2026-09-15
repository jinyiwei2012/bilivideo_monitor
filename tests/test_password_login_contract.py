"""密码登录契约回归测试（离线：假 API + 真实 RSA 密钥对，无网络）。

覆盖 docs/bilibili_api_contract.md §7 表格中标记「未修」的 4 项缺陷修复：
(a) 登录密码密文以 base64 提交（可 PKCS1v15 解回 hash+password，旧 hex 形式必失败）；
(b) 极验 seccode 带 "|jordan" 后缀（手动/自动两条提交路径），且 _with_jordan 幂等；
(c) code==0 但 data.status != 0 判为风控失败（message 含「风控」、不写 Cookie）；
(d) refresh_token 换票 URL 为 /web/exchange_cookie（而非旧的 /web/exchange）。
"""

import base64
from typing import Any, Dict, List, Optional, Tuple

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from core import bilibili_auth
from core.bilibili_auth import (
    _exchange_qr_refresh_token,
    _password_login_result,
    _submit_geetest_login,
    _try_auto_geetest_login,
    _with_jordan,
    login_with_password,
)


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
    """记录 post(url, data=...) 的会话替身，永远返回预设 payload。"""

    def __init__(self, payload: Dict[str, Any]) -> None:
        self.payload = payload
        self.cookies = _StubCookies()
        self.posts: List[Dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> _StubResponse:
        self.posts.append({"url": url, **kwargs})
        return _StubResponse(self.payload)


class _StubAPI:
    """最小 API 替身：提供密码登录 mixin 用到的属性（_request / session / USER_AGENTS）。"""

    USER_AGENTS = ["ua-test"]

    def __init__(
        self,
        *,
        key_payload: Optional[Dict[str, Any]] = None,
        login_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._key_payload = key_payload or {}
        self.session = _StubSession(login_payload or {"code": -1, "message": "stub-stop"})
        self._cookies: Dict[str, Any] = {}
        self._refresh_token = ""

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        return self._key_payload

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
    posted_password = api.session.posts[0]["data"]["password"]
    ciphertext = base64.b64decode(posted_password, validate=True)
    decrypted = private_key.decrypt(ciphertext, padding.PKCS1v15())
    assert decrypted.decode() == hash_str + plain_password


def test_submit_geetest_seccode_carries_jordan_suffix() -> None:
    """(b1) 手动极验重提：captcha "validate:seccode" 拆分后 seccode 必须带 "|jordan"。"""
    api = _StubAPI()
    result, raw = _submit_geetest_login(api, "https://example/login", "user", "enc-pass", "val-1:sec-1")

    assert result is None, "stub 响应 code!=0，不应判成功"
    posted = api.session.posts[0]["data"]
    assert posted["validate"] == "val-1"
    assert posted["seccode"] == "sec-1|jordan"
    assert posted["username"] == "user"
    assert posted["password"] == "enc-pass"


def test_auto_geetest_seccode_carries_jordan_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    """(b2) 自动求解路径：_auto_solve_geetest 返回的 seccode 同样补 "|jordan"。"""
    api = _StubAPI()
    monkeypatch.setattr(bilibili_auth, "_auto_solve_geetest", lambda self, gt, challenge: ("v-auto", "s-auto"))

    result = _try_auto_geetest_login(
        api, "https://example/login", "user", "enc-pass", {"data": {"gt": "g-1", "challenge": "c-1"}}
    )

    assert result is None, "stub 响应 code!=0，不应判成功"
    posted = api.session.posts[0]["data"]
    assert posted["validate"] == "v-auto"
    assert posted["seccode"] == "s-auto|jordan"


def test_with_jordan_is_idempotent() -> None:
    """(b3) 幂等：已带后缀不重复追加。"""
    assert _with_jordan("abc") == "abc|jordan"
    assert _with_jordan("abc|jordan") == "abc|jordan"


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


def test_exchange_uses_exchange_cookie_endpoint() -> None:
    """(d) QR 换票必须打 /web/exchange_cookie（旧 /web/exchange 已失效）。"""
    api = _StubAPI()
    sess = _StubSession({"data": {}})

    cookies = _exchange_qr_refresh_token(api, sess, {"refresh_token": "rt-123"})

    assert len(sess.posts) == 1
    assert sess.posts[0]["url"] == "https://passport.bilibili.com/x/passport-login/web/exchange_cookie"
    assert sess.posts[0]["data"] == {"refresh_token": "rt-123"}
    assert cookies == {}
