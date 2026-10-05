"""
B站API模块 - 认证管理
密码登录、QR扫码登录、Cookie持久化、多账号切换
"""

import base64
import json
import os
import logging
import random
import hashlib
import threading
from typing import Any, Dict, Optional, Protocol, cast
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)
_persist_lock = threading.Lock()  # 防止并发写入 network_config.json

# 密码登录端点（契约 §2：**每次提交前**都要重取 key/salt —— 盐有效期仅约 20s）
_PWD_KEY_URL = "https://passport.bilibili.com/x/passport-login/web/key"
_PWD_LOGIN_URL = "https://passport.bilibili.com/x/passport-login/web/login"
# 申请人机验证（契约 §2：`token`/`challenge` 来自这里）
_CAPTCHA_URL = "https://passport.bilibili.com/x/passport-login/captcha"
# 登录必须收全的 Cookie 键（契约 §3：扫码经 Set-Cookie 下发这 5 个，缺一不可）
LOGIN_COOKIE_KEYS = ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")


class _CredentialLike(Protocol):
    sessdata: str
    bili_jct: str
    dedeuserid: str
    ac_time_value: str


class _QRCodeAuthHost(Protocol):
    """扫码登录函数对宿主的**最小能力契约**（结构性，不要求运行时基类）。

    扫码段（get_qrcode_login_url / poll_qrcode_login 及其私有辅助）只依赖这些成员；
    仅描述实际访问面，不扩张为整个 BilibiliAPI 接口。
    """

    USER_AGENTS: list
    _qr_session: Any

    def set_cookies(self, cookies: Dict[str, Any]) -> None:
        pass

    def _persist_cookies(self, cookies: Dict[str, Any]) -> None:
        pass

    def _extract_login_cookies(self, resp: Any, data: Dict[str, Any]) -> Dict[str, Any]:
        pass


def set_cookies(self: Any, cookies: Dict[str, Any]) -> None:
    cookies = self._sanitize_cookies(cookies)
    self._cookies = cookies
    self.session.cookies.update(cookies)
    logger.info("已设置Cookie")


def get_refresh_token(self: Any) -> str:
    return str(self._refresh_token)


def get_accounts(self: Any) -> list[Dict[str, Any]]:
    return cast(list[Dict[str, Any]], list(self._accounts))


def get_active_account(self: Any) -> str:
    return str(self._account_name)


def get_account_names(self: Any) -> list[str]:
    return [str(a["name"]) for a in self._accounts]


def add_account(self: Any, name: str, cookies: Optional[Dict[str, Any]] = None, refresh_token: str = "") -> None:
    for acc in self._accounts:
        if acc["name"] == name:
            acc["cookies"] = cookies or acc["cookies"]
            acc["refresh_token"] = refresh_token or acc["refresh_token"]
            return
    self._accounts.append({"name": name, "cookies": cookies or {}, "refresh_token": refresh_token, "active": False})


def remove_account(self: Any, name: str) -> None:
    self._accounts = [a for a in self._accounts if a["name"] != name]
    if self._account_name == name:
        if not self._accounts:
            self._account_name = "默认"
            self._cookies = {}
            self._refresh_token = ""
            self.session.cookies.clear()
            return
        self._account_name = self._accounts[0]["name"]
        switch_account(self, self._account_name)


def switch_account(self: Any, name: str) -> bool:
    for acc in self._accounts:
        if acc["name"] == name:
            for a in self._accounts:
                a["active"] = a["name"] == name
            self._account_name = name
            self._cookies = dict(acc.get("cookies", {}))
            self._refresh_token = acc.get("refresh_token", "")
            self.session.cookies.clear()
            self.session.cookies.update(self._cookies)
            logger.info("已切换到账号: %s", name)
            return True
    return False


def login_with_password_fallback(self: Any, username: str, password: str) -> Dict[str, Any]:
    result = {"code": -1, "message": "", "cookies": {}, "refresh_token": ""}
    try:
        from bilibili_api import sync
        from bilibili_api.login_v2 import login_with_password as _bili_login
        from bilibili_api.utils.geetest import Geetest, GeetestType

        geetest_class: Any = Geetest
        g = geetest_class(GeetestType.LOGIN)
        try:
            cred = sync(_bili_login(username, password, g))
        except Exception:
            result["message"] = "需通过极验验证码，请在 B站网页端登录后导入 Cookie"
            return result

        if hasattr(cred, "sessdata") and cred.sessdata:
            credential = cast(_CredentialLike, cred)
            cookies = {
                "SESSDATA": str(credential.sessdata),
                "bili_jct": str(credential.bili_jct),
                "DedeUserID": str(credential.dedeuserid),
                "ac_time_value": getattr(credential, "ac_time_value", ""),
            }
            set_cookies(self, cookies)
            _persist_cookies(self, cookies)
            result.update({"code": 0, "message": "登录成功", "cookies": cookies})
            return result
    except ImportError:
        result["message"] = "bilibili-api-python 未安装"
    except Exception as e:
        result["message"] = f"兜底登录失败: {e}"
    return result


def _password_login_result(self: Any, resp: Any, data: Dict[str, Any], include_sid: bool = False) -> Dict[str, Any]:
    status = int(data.get("status", 0) or 0)
    if status != 0:
        return {
            "code": -1,
            "message": f"登录被风控拦截 (status={status})",
            "cookies": {},
            "refresh_token": "",
            "need_captcha": False,
            "captcha_type": 0,
            "captcha_phone": "",
        }
    cookies = _extract_login_cookies(self, resp, data)
    if not cookies:
        mid_raw = str(data.get("mid", ""))
        cookie_values = {
            "SESSDATA": data.get("sessdata", ""),
            "bili_jct": data.get("bili_jct", ""),
            "DedeUserID": mid_raw,
            "DedeUserID__ckMd5": hashlib.md5(mid_raw.encode(), usedforsecurity=False).hexdigest() if mid_raw else "",
        }
        if include_sid:
            cookie_values["sid"] = data.get("sid", "")
        cookies = {k: v for k, v in cookie_values.items() if v}
    set_cookies(self, cookies)
    refresh_token = data.get("refresh_token", "")
    return {
        "code": 0,
        "message": "登录成功",
        "cookies": cookies,
        "refresh_token": refresh_token,
        "need_captcha": False,
        "captcha_type": 0,
        "captcha_phone": "",
    }


def _with_jordan(seccode: str) -> str:
    """为极验 seccode 附加契约要求的 "|jordan" 后缀（幂等：已带则不重复追加）。"""
    if seccode.endswith("|jordan"):
        return seccode
    return f"{seccode}|jordan"


def _encrypt_password(self: Any, password: str) -> Optional[str]:
    """取 key/salt 并加密密码（**每次提交前调用**：盐可能 20s 就过期，契约 §2）。

    Returns:
        base64 密文 ``base64(RSA(PKCS1v15, hash + password))``；取不到公钥时返回 ``None``
    """
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    key_resp = self._request("GET", _PWD_KEY_URL)
    if not key_resp or "key" not in key_resp:
        return None
    public_key = key_resp["key"]
    salt = key_resp.get("hash", "")
    pub_key_obj = cast(
        rsa.RSAPublicKey,
        serialization.load_pem_public_key(public_key.encode(), backend=default_backend()),
    )
    encrypted = pub_key_obj.encrypt((salt + password).encode(), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()


def _geetest_fields(validate: str, seccode: str, challenge: str = "", token: str = "") -> Dict[str, Any]:
    """极验提交字段（契约 §2 必填表）。

    契约明确 `captcha` / `captcha_type` **不存在**；正确字段是
    `validate` / `seccode`(= validate + ``|jordan``) / `challenge` / `token`。
    `challenge` / `token` 有值才带（只透传服务端给的值，绝不构造）。
    """
    fields: Dict[str, Any] = {"validate": validate, "seccode": _with_jordan(seccode)}
    if challenge:
        fields["challenge"] = challenge
    if token:
        fields["token"] = token
    return fields


def _fetch_captcha_challenge(self: Any, source: str = "main_web") -> tuple[str, str, str]:
    """申请人机验证：``GET /x/passport-login/captcha?source=main_web`` → ``(token, gt, challenge)``。

    契约 §2 的 `token`/`challenge` 就来自这里（`data.token` + `data.geetest.{gt,challenge}`）；
    失败时返回三个空串，调用方据此放弃自动求解而**不报错**。
    """
    resp = self._request("GET", f"{_CAPTCHA_URL}?source={source}")
    if not resp or not isinstance(resp, dict):
        return "", "", ""
    data = resp.get("data", {}) or {}
    geetest = data.get("geetest", {}) or {}
    return (
        str(data.get("token", "") or ""),
        str(geetest.get("gt", "") or ""),
        str(geetest.get("challenge", "") or ""),
    )


def _submit_geetest_login(
    self: Any,
    login_url: str,
    username: str,
    password: str,
    captcha: str,
    challenge: str = "",
    token: str = "",
) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """带极验票据提交登录（`captcha` 形如 ``"<validate>:<seccode>"``）。

    提交前**重取 key/salt 重新加密**（契约 §2），避免用过期盐导致 `-662`。
    """
    encrypted_password = _encrypt_password(self, password)
    if encrypted_password is None:
        return None, {"code": -1, "message": "无法获取登录密钥"}
    validate, seccode = captcha.split(":", 1)
    login_data = {
        "username": username,
        "password": encrypted_password,
        "keep": 1,
        "source": "main_web",
        **_geetest_fields(validate, seccode, challenge, token),
    }
    resp = self.session.post(
        login_url,
        data=login_data,
        headers={
            "User-Agent": random.choice(self.USER_AGENTS),
            "Referer": "https://www.bilibili.com/",
        },
        timeout=15,
    )
    data = resp.json()
    if data.get("code") == 0:
        d = data.get("data", {})
        cookies = _extract_login_cookies(self, resp, d) or {
            "SESSDATA": d.get("sessdata", ""),
            "bili_jct": d.get("bili_jct", ""),
            "DedeUserID": str(d.get("mid", "")),
        }
        cookies = {k: v for k, v in cookies.items() if v}
        set_cookies(self, cookies)
        return {
            "code": 0,
            "message": "登录成功",
            "cookies": cookies,
            "refresh_token": d.get("refresh_token", ""),
            "need_captcha": False,
            "captcha_type": 0,
            "captcha_phone": "",
        }, data
    return None, data


def _try_auto_geetest_login(
    self: Any, login_url: str, username: str, password: str, data: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """自动求解极验后重提（提交前重取 key/salt 重新加密，契约 §2）。"""
    d = data.get("data", {})
    gt = d.get("gt", "")
    challenge = d.get("challenge", "")
    token = str(d.get("token", "") or "")
    if not gt or not challenge:
        # 失败响应没带极验参数 → 主动申请一次验证码（契约 §2 的 token/challenge 来源）
        token, gt, challenge = _fetch_captcha_challenge(self)
    if not gt or not challenge:
        return None
    solved = _auto_solve_geetest(self, gt, challenge)
    if not solved:
        return None
    validate, seccode = solved
    encrypted_password = _encrypt_password(self, password)
    if encrypted_password is None:
        return None
    login_data = {
        "username": username,
        "password": encrypted_password,
        "keep": 1,
        "source": "main_web",
        **_geetest_fields(validate, seccode, challenge, token),
    }
    resp = self.session.post(
        login_url,
        data=login_data,
        headers={
            "User-Agent": random.choice(self.USER_AGENTS),
            "Referer": "https://www.bilibili.com/",
        },
        timeout=15,
    )
    data = resp.json()
    if data.get("code") == 0:
        return _password_login_result(self, resp, data.get("data", {}))
    return None


def _password_login_failure(data: Dict[str, Any], api_code: int, need_captcha: bool) -> Dict[str, Any]:
    ct = 0
    phone = ""
    gt_val = ""
    challenge_val = ""
    if need_captcha:
        d = data.get("data", {})
        ct = d.get("captcha_type", 6)
        phone = d.get("phone", "") or d.get("captcha_phone", "")
        gt_val = d.get("gt", "")
        challenge_val = d.get("challenge", "")
    return {
        "code": api_code,
        "message": data.get("message", "登录失败"),
        "cookies": {},
        "refresh_token": "",
        "need_captcha": need_captcha,
        "captcha_type": ct,
        "captcha_phone": phone,
        "gt": gt_val,
        "challenge": challenge_val,
    }


def login_with_password(
    self: Any, username: str, password: str, captcha: str = "", captcha_type: int = 0
) -> Dict[str, Any]:
    try:
        encrypted_password = _encrypt_password(self, password)
        if encrypted_password is None:
            return {
                "code": -1,
                "message": "无法获取登录密钥",
                "cookies": {},
                "refresh_token": "",
                "need_captcha": False,
                "captcha_type": 0,
                "captcha_phone": "",
            }

        login_url = _PWD_LOGIN_URL
        validate, seccode = captcha.split(":", 1) if ":" in captcha else ("", "")
        # 契约 §2：不存在 captcha/captcha_type 字段；极验字段是 validate/seccode/challenge/token
        geetest: Dict[str, Any] = _geetest_fields(validate, seccode) if validate else {}
        login_data = {
            "username": username,
            "password": encrypted_password,
            "keep": 1,
            "source": "main_web",
            **geetest,
        }

        resp = self.session.post(
            login_url,
            data=login_data,
            headers={
                "User-Agent": random.choice(self.USER_AGENTS),
                "Referer": "https://www.bilibili.com/",
            },
            timeout=15,
        )
        data = resp.json()
        api_code = data.get("code", -1)

        if api_code == -662:
            # 盐过期（契约 §2：`-662` = 密码时间戳过期）→ 重取 key/salt 重算密文重试一次
            retried = _encrypt_password(self, password)
            if retried:
                logger.debug("密码时间戳过期(-662)，重取 key/salt 后重试一次")
                encrypted_password = retried
                login_data["password"] = retried
                resp = self.session.post(
                    login_url,
                    data=login_data,
                    headers={
                        "User-Agent": random.choice(self.USER_AGENTS),
                        "Referer": "https://www.bilibili.com/",
                    },
                    timeout=15,
                )
                data = resp.json()
                api_code = data.get("code", -1)

        if api_code == 0:
            d = data.get("data", {})
            result = _password_login_result(self, resp, d, include_sid=True)
            self._refresh_token = result["refresh_token"]
            return result

        if captcha and ":" in captcha:
            geetest_result, data = _submit_geetest_login(self, login_url, username, password, captcha)
            if geetest_result:
                return geetest_result
            api_code = data.get("code", -1)

        need_captcha = data.get("need_captcha", False) or api_code in [-629, -352]
        if need_captcha and not captcha:
            auto_result = _try_auto_geetest_login(self, login_url, username, password, data)
            if auto_result:
                return auto_result
        return _password_login_failure(data, api_code, need_captcha)

    except Exception as e:
        logger.warning(f"自有密码登录失败，尝试 bilibili-api-python 兜底: {e}")
        fallback = login_with_password_fallback(self, username, password)
        if fallback.get("code") == 0:
            return fallback
        return {
            "code": -1,
            "message": f"登录异常: {e}",
            "cookies": {},
            "refresh_token": "",
            "need_captcha": False,
            "captcha_type": 0,
            "captcha_phone": "",
        }


def _auto_solve_geetest(self: Any, gt: str, challenge: str) -> Optional[tuple[str, str]]:
    try:
        from utils.geetest_solver import solve

        result: Optional[tuple[str, str]] = solve(gt, challenge)
        if result:
            logger.info("极验验证码自动求解成功")
            return result
        logger.warning("极验验证码自动求解失败")
    except ImportError as e:
        logger.debug("极验自动求解依赖缺失: %s (需要 opencv-python, pycryptodome)", e)
    except Exception as e:
        logger.debug("极验自动求解异常: %s", e)
    return None


def _persist_cookies(self: Any, cookies: Dict[str, Any]) -> None:
    if not cookies:
        return
    with _persist_lock:
        try:
            from utils.crypto import encrypt_dict
            from utils import project_path

            cfg_path = project_path("data", "network_config.json")
            net_cfg = {}
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    net_cfg = json.load(f)

            accounts = net_cfg.get("accounts", [])
            if not accounts and net_cfg.get("cookies"):
                accounts = [
                    {
                        "name": net_cfg.get("account_name", "默认"),
                        "cookies": net_cfg["cookies"],
                        "refresh_token": net_cfg.get("refresh_token", ""),
                        "active": False,
                    }
                ]

            updated = False
            for acc in accounts:
                if acc["name"] == self._account_name:
                    enc = dict(cookies)
                    encrypt_dict(enc, "SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")
                    acc["cookies"] = enc
                    acc["refresh_token"] = self._refresh_token
                    updated = True
                    break
            if not updated:
                enc = dict(cookies)
                encrypt_dict(enc, "SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")
                accounts.append(
                    {"name": self._account_name, "cookies": enc, "refresh_token": self._refresh_token, "active": False}
                )

            net_cfg["accounts"] = accounts
            net_cfg["active_account"] = self._account_name
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(net_cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("持久化 Cookie 失败: %s", e)


def _extract_login_cookies(self: Any, resp: Any, data: Dict[str, Any]) -> Dict[str, Any]:
    wanted = LOGIN_COOKIE_KEYS + ("buvid3", "buvid4", "buvid_fp")
    cookies: Dict[str, Any] = {}

    redirect_url = data.get("url", "")
    if redirect_url:
        parsed = urlparse(redirect_url)
        params = parse_qs(parsed.query)
        for key in wanted:
            if key not in cookies:
                val = params.get(key, [None])[0]
                if val:
                    cookies[key] = val

    # 优先使用 resp.cookies（正确处理多个 Set-Cookie 头部）
    for k in wanted:
        if k in resp.cookies:
            cookies[k] = resp.cookies[k]

    return cookies


def _init_qr_session(self: _QRCodeAuthHost) -> Any:
    if not hasattr(self, "_qr_session") or self._qr_session is None:
        import requests as _req

        self._qr_session = _req.Session()
        self._qr_session.headers.update(
            {
                "User-Agent": random.choice(self.USER_AGENTS),
                "Referer": "https://www.bilibili.com/",
                "Accept": "application/json, text/plain, */*",
            }
        )
    return self._qr_session


def _close_qr_session(self: _QRCodeAuthHost) -> None:
    """关闭二维码登录独立 Session"""
    if hasattr(self, "_qr_session") and self._qr_session is not None:
        try:
            self._qr_session.close()
        except Exception:
            pass
        self._qr_session = None


def get_qrcode_login_url(self: _QRCodeAuthHost) -> Optional[Dict[str, Any]]:
    """获取 QR 扫码登录 URL 和密钥"""
    sess = _init_qr_session(self)
    try:
        resp = sess.get("https://passport.bilibili.com/x/passport-login/web/qrcode/generate", timeout=15)
        if resp.status_code == 200:
            d = resp.json().get("data", {})
            return {"url": d.get("url", ""), "qrcode_key": d.get("qrcode_key", "")}
    except Exception as e:
        logger.debug("获取 QR 登录 URL 失败: %s", e)
    return None


def _apply_qr_poll_status(result: Dict[str, Any], data: Dict[str, Any]) -> bool:
    code = data.get("code", -1)
    log_data = data.get("data", {})
    if code == 86038:
        result["status"] = -1
        result["message"] = "二维码已过期"
        return False
    if code == 86101:
        result["message"] = "等待扫码"
        return False
    if code != 0:
        result["message"] = log_data.get("message", data.get("message", f"错误码 {code}"))
        return False
    raw_status = log_data.get("status")
    if raw_status == 2:
        result["status"] = 2
        result["message"] = "登录成功"
        return True
    if raw_status == 1:
        result["status"] = 1
        result["message"] = log_data.get("message", "已扫码，请在手机上确认")
    elif raw_status == 0:
        result["message"] = "等待扫码"
    else:
        result["status"] = -1
        result["message"] = "未知的扫码状态，请重试"
    return False


def _fill_missing_cookies(target: Dict[str, Any], source: Dict[str, Optional[str]], keys: tuple[str, ...]) -> None:
    """把 ``source`` 中 ``target`` 尚缺的键补入 ``target``（不覆盖已有，不补空值）。

    这是 cookie 三来源合并的通用原语：各来源按序提供，缺哪个补哪个。
    """
    for key in keys:
        if key in target:
            continue
        value = source.get(key)
        if value:
            target[key] = value


def _collect_qr_redirect_cookies(self: _QRCodeAuthHost, resp: Any, data: Dict[str, Any]) -> Dict[str, Any]:
    cookies = dict(_extract_login_cookies(self, resp, data))
    # 重定向 URL 兜底：**合并**（不是覆盖），键集与 LOGIN_COOKIE_KEYS 同源（契约 §3 要求 5 个）
    redirect_url = data.get("url", "")
    if redirect_url:
        params = {k: vs[0] for k, vs in parse_qs(urlparse(redirect_url).query).items() if vs}
        _fill_missing_cookies(cookies, params, LOGIN_COOKIE_KEYS)
    return cookies


def _collect_qr_response_cookies(self: _QRCodeAuthHost, resp: Any, data: Dict[str, Any]) -> Dict[str, Any]:
    """三种来源**合并**收全登录 Cookie（契约 §3：`Set-Cookie` 下发 5 个，缺一不可）。"""
    cookies = dict(_collect_qr_redirect_cookies(self, resp, data))
    for ci in data.get("cookie_info", {}).get("cookies", []):
        name = ci.get("name", "")
        value = ci.get("value", "")
        if name in LOGIN_COOKIE_KEYS and name not in cookies and value:
            cookies[name] = value
    _fill_missing_cookies(cookies, {k: resp.cookies.get(k) for k in LOGIN_COOKIE_KEYS}, LOGIN_COOKIE_KEYS)
    return cookies


def _exchange_qr_refresh_token(self: _QRCodeAuthHost, sess: Any, data: Dict[str, Any]) -> Dict[str, Any]:
    cookies: Dict[str, Any] = {}
    logger.debug("QR 登录未取到 Cookie，尝试从 refresh_token 换票")
    token_data = {"refresh_token": data["refresh_token"]}
    try:
        ex = sess.post(
            "https://passport.bilibili.com/x/passport-login/web/exchange_cookie", data=token_data, timeout=10
        )
        if ex.status_code == 200:
            exd = ex.json().get("data", {})
            cookies = _extract_login_cookies(self, ex, exd)
    except Exception as e2:
        logger.debug("exchange 换票失败: %s", e2)
    return cookies


def _collect_qr_login_cookies(self: _QRCodeAuthHost, sess: Any, resp: Any, data: Dict[str, Any]) -> Dict[str, Any]:
    cookies = _collect_qr_response_cookies(self, resp, data)
    if not cookies and data.get("refresh_token"):
        cookies = _exchange_qr_refresh_token(self, sess, data)
    return cookies


def poll_qrcode_login(self: _QRCodeAuthHost, qrcode_key: str) -> Optional[Dict[str, Any]]:
    sess = _init_qr_session(self)
    url = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
    result = {"status": 0, "message": "等待扫码", "cookies": {}}
    try:
        logger.debug("→ GET passport.bilibili.com/qrcode/poll")
        resp = sess.get(url, params={"qrcode_key": qrcode_key}, timeout=15)
        logger.debug("← passport.bilibili.com/qrcode/poll → %s", resp.status_code)
        if resp.status_code != 200:
            result["message"] = f"HTTP {resp.status_code}"
            return result
        data = resp.json()
        log_data = data.get("data", {})
        logger.debug("QR poll response: code=%s status=%s", data.get("code"), log_data.get("status"))
        if not _apply_qr_poll_status(result, data):
            return result

        cookies = _collect_qr_login_cookies(self, sess, resp, log_data)
        if cookies:
            set_cookies(self, cookies)
            _persist_cookies(self, cookies)
            result["cookies"] = cookies
            logger.info("QR 登录成功，已获取 Cookie: %s", list(cookies.keys()))
    except Exception as e:
        result["message"] = f"轮询异常: {e}"
        logger.debug("QR poll exception: %s", e)
    return result


class _AuthMixin:
    _qr_session: Any  # 仅注解，不赋值：保留 _init_qr_session 的 hasattr 惰性语义

    set_cookies = set_cookies
    get_refresh_token = get_refresh_token
    get_accounts = get_accounts
    get_active_account = get_active_account
    get_account_names = get_account_names
    add_account = add_account
    remove_account = remove_account
    switch_account = switch_account
    login_with_password_fallback = login_with_password_fallback
    login_with_password = login_with_password
    _auto_solve_geetest = _auto_solve_geetest
    _persist_cookies = _persist_cookies
    _extract_login_cookies = _extract_login_cookies
    _init_qr_session = _init_qr_session
    get_qrcode_login_url = get_qrcode_login_url
    poll_qrcode_login = poll_qrcode_login
