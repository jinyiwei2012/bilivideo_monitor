"""Web 端 Cookie 续期链（留档：``docs/bilibili-api/frozen-fork/cookie_refresh.md``）。

五步流程（逐字段对齐留档）：

1. ``GET /x/passport-login/web/cookie/info`` → ``data.refresh``（是否需要续期）、``data.timestamp``（毫秒）；
   ``code=-101`` 表示账号未登录 → 直接判掉登录；
2. ``refresh_{timestamp}`` 用固定 RSA 公钥做 **RSA-OAEP(SHA-256)** 加密 → 小写 base16 = ``CorrespondPath``；
3. ``GET https://www.bilibili.com/correspond/1/{CorrespondPath}`` → HTML 里
   ``<div id="1-name">`` 的内容即 ``refresh_csrf``；
4. ``POST /x/passport-login/web/cookie/refresh``（``csrf`` = 当前 Cookie 里的 ``bili_jct``、
   ``refresh_csrf``、``source=main_web``、``refresh_token`` = **旧的** ac_time_value）
   → 新 Cookie 只在 ``Set-Cookie`` 响应头里，body 返回**新的** ``refresh_token``；
5. ``POST /x/passport-login/web/confirm/refresh``（``csrf`` 用**新** Cookie 里的 ``bili_jct``，
   ``refresh_token`` 仍是**旧值**）→ 让旧 token 失效。

因为第 4 步的新 Cookie 只在响应头里，本模块走 ``_request_raw``（只返回 ``data`` 的 ``_request``
拿不到 Set-Cookie）。所有失败路径都不抛错，只返回带原因的结果，供 UI 决定是否提示。
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

COOKIE_INFO_URL = "https://passport.bilibili.com/x/passport-login/web/cookie/info"
CORRESPOND_URL = "https://www.bilibili.com/correspond/1/{path}"
REFRESH_URL = "https://passport.bilibili.com/x/passport-login/web/cookie/refresh"
CONFIRM_URL = "https://passport.bilibili.com/x/passport-login/web/confirm/refresh"
SOURCE = "main_web"

# 固定公钥（留档原样，勿改）
RENEW_PUBLIC_KEY_PEM = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDLgd2OAkcGVtoE3ThUREbio0Eg\n"
    "Uc/prcajMKXvkCKFCWhJYJcLkcM2DKKcSeFpD/j6Boy538YXnR6VhcuUJOhH2x71\n"
    "nzPjfdTcqMz7djHum0qSZA0AyCBDABUqCrfNgCiJ00Ra7GmRj+YCK1NJEuewlb40\n"
    "JNrRuoEUXpabUzGB8QIDAQAB\n"
    "-----END PUBLIC KEY-----\n"
)

# 续期后服务端会下发的 Cookie（留档明确列出）
RENEWED_COOKIE_NAMES = ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")

STATUS_OK = "refreshed"
STATUS_UNCONFIRMED = "refreshed_unconfirmed"
STATUS_UNCHANGED = "not_needed"
STATUS_LOGGED_OUT = "logged_out"
STATUS_NO_TOKEN = "no_refresh_token"
STATUS_CSRF_FAILED = "csrf_failed"
STATUS_MISMATCH = "mismatch"
STATUS_ERROR = "error"

_CSRF_DIV_RE = re.compile(r'id="1-name"[^>]*>([^<]+)<')
_DEFAULT_INTERVAL_HOURS = 12.0


@dataclass
class CookieRefreshResult:
    """一次续期尝试的结果。"""

    status: str
    message: str = ""
    cookies: Dict[str, str] = field(default_factory=dict)
    refresh_token: str = ""

    @property
    def ok(self) -> bool:
        """是否真的换到了新 Cookie（确认步骤失败也算换到了，只是未确认）。"""
        return self.status in (STATUS_OK, STATUS_UNCONFIRMED)


def gen_correspond_path(ts_ms: int, public_key_pem: str = RENEW_PUBLIC_KEY_PEM) -> str:
    """把 ``refresh_{毫秒时间戳}`` 加密为小写 hex 的 ``CorrespondPath``。"""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

    public_key = serialization.load_pem_public_key(public_key_pem.encode())
    if not isinstance(public_key, RSAPublicKey):
        raise ValueError("续期公钥必须是 RSA 公钥")
    ciphertext = public_key.encrypt(
        f"refresh_{int(ts_ms)}".encode(),
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    return ciphertext.hex()


def parse_refresh_csrf(html: str) -> str:
    """从 Correspond 页面取 ``refresh_csrf``（``<div id="1-name">…</div>``）。"""
    match = _CSRF_DIV_RE.search(str(html or ""))
    return match.group(1).strip() if match else ""


def _json_of(response: Any) -> Dict[str, Any]:
    """尽力把响应体解析为 dict（失败返回空 dict）。"""
    try:
        body = response.json()
    except Exception as e:
        logger.debug("响应不是 JSON: %s", e)
        return {}
    return body if isinstance(body, dict) else {}


def extract_cookies(response: Any) -> Dict[str, str]:
    """只从原始响应里提取续期相关的 5 个 Cookie（cookie jar 优先，回退 Set-Cookie 头）。"""
    found: Dict[str, str] = {}
    jar = getattr(response, "cookies", None)
    items: Optional[List[Tuple[str, str]]] = None
    if jar is not None:
        try:
            items = list(dict(jar).items())
        except Exception:
            try:
                items = list(jar.items())
            except Exception:
                items = None
    for name, value in items or []:
        if name in RENEWED_COOKIE_NAMES and value:
            found[str(name)] = str(value)
    if len(found) < len(RENEWED_COOKIE_NAMES):
        headers = getattr(response, "headers", None)
        raw = ""
        if headers is not None:
            getter = getattr(headers, "get_list", None)
            if callable(getter):
                raw = "; ".join(getter("set-cookie") or [])
            else:
                raw = str(headers.get("set-cookie", "") or "")
        for name in RENEWED_COOKIE_NAMES:
            if name in found or not raw:
                continue
            match = re.search(rf"{re.escape(name)}=([^;,\s]+)", raw)
            if match:
                found[name] = match.group(1)
    return found


def cookie_info(api: Any) -> Dict[str, Any]:
    """第 1 步：查询是否需要续期。"""
    csrf = str((getattr(api, "_cookies", {}) or {}).get("bili_jct", "") or "")
    data = api._request("GET", COOKIE_INFO_URL, params={"csrf": csrf})
    if not isinstance(data, dict):
        logged_out = bool(getattr(api, "_logged_out", False))
        return {"refresh": False, "timestamp": 0, "logged_out": logged_out}
    try:
        timestamp = int(data.get("timestamp", 0) or 0)
    except (TypeError, ValueError):
        timestamp = 0
    return {"refresh": bool(data.get("refresh")), "timestamp": timestamp, "logged_out": False}


def fetch_refresh_csrf(api: Any, ts_ms: int) -> str:
    """第 2-3 步：生成 CorrespondPath 并取回 ``refresh_csrf``（失败返回空串）。"""
    try:
        path = gen_correspond_path(ts_ms)
        response = api._request_raw("GET", CORRESPOND_URL.format(path=path))
    except Exception as e:
        logger.warning("获取 refresh_csrf 失败: %s", e)
        return ""
    return parse_refresh_csrf(str(getattr(response, "text", "") or ""))


def refresh_cookie(api: Any, refresh_csrf: str, refresh_token: str) -> Tuple[Dict[str, str], str, int]:
    """第 4 步：提交续期。返回 ``(新 Cookie, 新 refresh_token, code)``（code!=0 表示失败）。"""
    payload = {
        "csrf": str((getattr(api, "_cookies", {}) or {}).get("bili_jct", "") or ""),
        "refresh_csrf": refresh_csrf,
        "source": SOURCE,
        "refresh_token": refresh_token,
    }
    try:
        response = api._request_raw("POST", REFRESH_URL, data=payload)
    except Exception as e:
        logger.warning("Cookie 续期请求异常: %s", e)
        return {}, "", -1
    body = _json_of(response)
    try:
        code = int(body.get("code", -1))
    except (TypeError, ValueError):
        code = -1
    if code != 0:
        return {}, "", code
    new_cookies = extract_cookies(response)
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    return new_cookies, str((data or {}).get("refresh_token", "") or ""), 0


def confirm_refresh(api: Any, old_refresh_token: str, new_cookies: Dict[str, str]) -> Tuple[bool, str]:
    """第 5 步：确认续期（csrf 取**新** Cookie，refresh_token 传**旧**值让旧 token 失效）。"""
    csrf = str(new_cookies.get("bili_jct", "") or (getattr(api, "_cookies", {}) or {}).get("bili_jct", "") or "")
    try:
        response = api._request_raw("POST", CONFIRM_URL, data={"csrf": csrf, "refresh_token": old_refresh_token})
    except Exception as e:
        return False, f"确认续期异常: {e}"
    body = _json_of(response)
    try:
        code = int(body.get("code", -1))
    except (TypeError, ValueError):
        code = -1
    if code == 0:
        return True, ""
    return False, code_message(code, body)


def code_message(code: int, body: Optional[Dict[str, Any]] = None) -> str:
    """把续期接口的返回码翻译成可解释的中文原因。"""
    known = {
        -101: "账号未登录（-101），需重新登录",
        -111: "csrf 校验失败（-111）",
        86095: "refresh_csrf 无效，或 refresh_token 与当前 Cookie 不匹配（86095）",
    }
    if code in known:
        return known[code]
    detail = str((body or {}).get("message", "") or "")
    return f"code={code} {detail}".strip()


def refresh_now(api: Any) -> CookieRefreshResult:
    """完整执行 1-5 步并把新 Cookie / refresh_token 落盘；任何失败都不抛错。"""
    info = cookie_info(api)
    if info["logged_out"]:
        return CookieRefreshResult(status=STATUS_LOGGED_OUT, message=code_message(-101))
    if not info["refresh"]:
        return CookieRefreshResult(status=STATUS_UNCHANGED, message="服务端未要求续期")
    old_token = str(getattr(api, "_refresh_token", "") or "")
    if not old_token:
        return CookieRefreshResult(status=STATUS_NO_TOKEN, message="缺少 refresh_token，需重新登录一次以获取")
    ts_ms = info["timestamp"] or int(time.time() * 1000)
    csrf = fetch_refresh_csrf(api, ts_ms)
    if not csrf:
        return CookieRefreshResult(
            status=STATUS_CSRF_FAILED, message="未取到 refresh_csrf（Correspond 页面无效或已过期）"
        )
    new_cookies, new_token, code = refresh_cookie(api, csrf, old_token)
    if code != 0:
        status = STATUS_MISMATCH if code == 86095 else STATUS_ERROR
        return CookieRefreshResult(status=status, message=code_message(code))
    if not new_cookies:
        return CookieRefreshResult(status=STATUS_ERROR, message="续期响应未带回新 Cookie")

    merged = {**(getattr(api, "_cookies", {}) or {}), **new_cookies}
    setter = getattr(api, "set_cookies", None)
    if callable(setter):
        setter(merged)
    else:
        api._cookies = merged
    if new_token:
        api._refresh_token = new_token
    persist = getattr(api, "_persist_cookies", None)
    if callable(persist):
        try:
            persist(merged)
        except Exception as e:
            logger.debug("续期后持久化失败: %s", e)
    add_account = getattr(api, "add_account", None)
    account_name = str(getattr(api, "_account_name", "") or "")
    if callable(add_account) and account_name:
        try:
            add_account(account_name, merged, new_token)
        except Exception as e:
            logger.debug("更新账号 refresh_token 失败: %s", e)

    confirmed, confirm_error = confirm_refresh(api, old_token, new_cookies)
    api._logged_out = False
    status = STATUS_OK if confirmed else STATUS_UNCONFIRMED
    message = "续期成功" if confirmed else f"已换新 Cookie，但确认步骤失败：{confirm_error}"
    logger.info("Cookie 续期: %s（%s）", status, message)
    return CookieRefreshResult(status=status, message=message, cookies=new_cookies, refresh_token=new_token)


def maybe_refresh(
    api: Any, *, interval_hours: float = _DEFAULT_INTERVAL_HOURS, force: bool = False
) -> Optional[CookieRefreshResult]:
    """按间隔节流地续期（应用启动 / 定时器调用）；未到间隔返回 ``None``（不发请求）。"""
    now = time.time()
    last = float(getattr(api, "_cookie_refresh_at", 0.0) or 0.0)
    if not force and last and now - last < max(0.0, float(interval_hours)) * 3600:
        return None
    api._cookie_refresh_at = now
    return refresh_now(api)


def renew_state(api: Any) -> Dict[str, Any]:
    """续期观测（与 ``risk_state`` 一起上报）。"""
    return {
        "last_refresh_at": float(getattr(api, "_cookie_refresh_at", 0.0) or 0.0),
        "has_refresh_token": bool(getattr(api, "_refresh_token", "") or ""),
        "logged_out": bool(getattr(api, "_logged_out", False)),
    }
