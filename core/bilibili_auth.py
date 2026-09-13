"""
B站API模块 - 认证管理
密码登录、QR扫码登录、Cookie持久化、多账号切换
"""

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


class _CredentialLike(Protocol):
    sessdata: str
    bili_jct: str
    dedeuserid: str
    ac_time_value: str


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


def _submit_geetest_login(
    self: Any, login_url: str, username: str, encrypted_password: str, captcha: str
) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    validate, seccode = captcha.split(":", 1)
    login_data = {
        "username": username,
        "password": encrypted_password,
        "keep": 1,
        "source": "main_web",
        "validate": validate,
        "seccode": seccode,
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
    self: Any, login_url: str, username: str, encrypted_password: str, data: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    d = data.get("data", {})
    gt = d.get("gt", "")
    challenge = d.get("challenge", "")
    if not gt or not challenge:
        return None
    solved = _auto_solve_geetest(self, gt, challenge)
    if not solved:
        return None
    validate, seccode = solved
    login_data = {
        "username": username,
        "password": encrypted_password,
        "keep": 1,
        "source": "main_web",
        "validate": validate,
        "seccode": seccode,
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
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.backends import default_backend

    try:
        key_url = "https://passport.bilibili.com/x/passport-login/web/key"
        key_resp = self._request("GET", key_url)
        if not key_resp or "key" not in key_resp:
            return {
                "code": -1,
                "message": "无法获取登录密钥",
                "cookies": {},
                "refresh_token": "",
                "need_captcha": False,
                "captcha_type": 0,
                "captcha_phone": "",
            }
        pubkey = key_resp["key"]
        hash_str = key_resp.get("hash", "")

        pub_key_obj = cast(
            rsa.RSAPublicKey, serialization.load_pem_public_key(pubkey.encode(), backend=default_backend())
        )
        encrypted = pub_key_obj.encrypt(
            (hash_str + password).encode(),
            padding.PKCS1v15(),
        )
        encrypted_password = encrypted.hex()

        login_url = "https://passport.bilibili.com/x/passport-login/web/login"
        login_data = {
            "username": username,
            "password": encrypted_password,
            "keep": 1,
            "source": "main_web",
        }
        if captcha:
            login_data["captcha"] = captcha
            login_data["captcha_type"] = captcha_type

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

        if captcha and captcha_type == -1 and ":" in captcha:
            geetest_result, data = _submit_geetest_login(self, login_url, username, encrypted_password, captcha)
            if geetest_result:
                return geetest_result
            api_code = data.get("code", -1)

        need_captcha = data.get("need_captcha", False) or api_code in [-629, -352]
        if need_captcha and not captcha:
            auto_result = _try_auto_geetest_login(self, login_url, username, encrypted_password, data)
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
    wanted = ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid", "buvid3", "buvid4", "buvid_fp")
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


def _init_qr_session(self: Any) -> Any:
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


def _close_qr_session(self: Any) -> None:
    """关闭二维码登录独立 Session"""
    if hasattr(self, "_qr_session") and self._qr_session is not None:
        try:
            self._qr_session.close()
        except Exception:
            pass
        self._qr_session = None


def get_qrcode_login_url(self: Any) -> Optional[Dict[str, Any]]:
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


def _collect_qr_redirect_cookies(self: Any, resp: Any, data: Dict[str, Any]) -> Dict[str, Any]:
    cookies = _extract_login_cookies(self, resp, data)
    if not cookies:
        redirect_url = data.get("url", "")
        if redirect_url:
            parsed = urlparse(redirect_url)
            params = parse_qs(parsed.query)
            cookies = {
                k: params.get(k, [None])[0] for k in ("SESSDATA", "bili_jct", "DedeUserID") if params.get(k, [None])[0]
            }
    return cookies


def _collect_qr_response_cookies(self: Any, resp: Any, data: Dict[str, Any]) -> Dict[str, Any]:
    cookies = _collect_qr_redirect_cookies(self, resp, data)
    if not cookies:
        for ci in data.get("cookie_info", {}).get("cookies", []):
            name = ci.get("name", "")
            if name in ("SESSDATA", "bili_jct", "DedeUserID"):
                cookies[name] = ci.get("value", "")
    if not cookies:
        for k in ("SESSDATA", "bili_jct", "DedeUserID"):
            value = resp.cookies.get(k)
            if value:
                cookies[k] = value
    return cookies


def _exchange_qr_refresh_token(self: Any, sess: Any, data: Dict[str, Any]) -> Dict[str, Any]:
    cookies: Dict[str, Any] = {}
    logger.debug("QR 登录未取到 Cookie，尝试从 refresh_token 换票")
    token_data = {"refresh_token": data["refresh_token"]}
    try:
        ex = sess.post("https://passport.bilibili.com/x/passport-login/web/exchange", data=token_data, timeout=10)
        if ex.status_code == 200:
            exd = ex.json().get("data", {})
            cookies = _extract_login_cookies(self, ex, exd)
    except Exception as e2:
        logger.debug("exchange 换票失败: %s", e2)
    return cookies


def _collect_qr_login_cookies(self: Any, sess: Any, resp: Any, data: Dict[str, Any]) -> Dict[str, Any]:
    cookies = _collect_qr_response_cookies(self, resp, data)
    if not cookies and data.get("refresh_token"):
        cookies = _exchange_qr_refresh_token(self, sess, data)
    return cookies


def poll_qrcode_login(self: Any, qrcode_key: str) -> Optional[Dict[str, Any]]:
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
