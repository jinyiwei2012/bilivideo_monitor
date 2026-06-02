"""
B站 API 模块 — 认证管理 (_AuthMixin)
=======================================

本模块提供 B站 认证相关的所有功能，通过 Mixin 模式注入到 BilibiliAPI 类中。

主要功能：
  1. Cookie 设置与管理       — 设置/获取/持久化登录 Cookie
  2. 密码登录                 — RSA 加密密码 → 极验验证码 → 换取 Cookie
  3. QR 扫码登录              — 获取二维码 → 轮询扫码状态 → 获取 Cookie
  4. 多账号管理               — 添加/删除/切换账号，密码登录失败时自动回退到 bilibili-api-python

安全设计：
  - 敏感 Cookie 字段（SESSDATA, bili_jct 等）存储前使用 AES 加密
  - 密码登录使用 B站 官方 RSA 公钥加密传输
  - QR 扫码的 token 不落地存储

注意事项：
  本模块中的函数均以模块级定义，通过 _AuthMixin 类属性赋值导入到 BilibiliAPI 中。
  使用 self 的第一个参数来引用 BilibiliAPI 实例的方法和属性。
"""
import json
import os
import logging
import random
import hashlib
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


def set_cookies(self, cookies: Dict):
    """设置当前账号的 Cookie 并更新 Session

    对传入的 Cookie 做 Latin-1 清理（防止编码错误），
    然后同时更新内部 _cookies 字典和 requests Session。

    Args:
        cookies: Cookie 字典，键为 Cookie 名称
    """
    cookies = self._sanitize_cookies(cookies)
    self._cookies = cookies
    self.session.cookies.update(cookies)
    logger.info("已设置Cookie")


def get_refresh_token(self) -> str:
    """获取当前账号的 refresh_token

    refresh_token 用于在 Cookie 过期后自动刷新登录态。

    Returns:
        refresh_token 字符串
    """
    return self._refresh_token


def get_accounts(self) -> list:
    """获取所有已保存的账号列表（浅拷贝）

    Returns:
        账号字典列表，每个元素含 name, cookies, refresh_token, active
    """
    return list(self._accounts)


def get_active_account(self) -> str:
    """获取当前活跃账号的名称

    Returns:
        当前活跃账号名
    """
    return self._account_name


def get_account_names(self) -> list:
    """获取所有账号的名称列表

    Returns:
        账号名称字符串列表
    """
    return [a["name"] for a in self._accounts]


def add_account(self, name: str, cookies: dict = None, refresh_token: str = ""):
    """添加或更新一个账号

    如果账号名已存在，则更新其 Cookie 和 refresh_token；
    否则创建新账号条目。

    Args:
        name: 账号名称（用户自定义）
        cookies: Cookie 字典（可选）
        refresh_token: refresh_token 字符串（可选）
    """
    for acc in self._accounts:
        if acc["name"] == name:
            # 已有账号：更新 Cookie 和 token
            acc["cookies"] = cookies or acc["cookies"]
            acc["refresh_token"] = refresh_token or acc["refresh_token"]
            return
    # 新账号：追加到列表
    self._accounts.append({"name": name, "cookies": cookies or {},
                            "refresh_token": refresh_token, "active": False})


def remove_account(self, name: str):
    """删除指定账号

    如果删除的是当前活跃账号，则自动切换到列表中的第一个账号。
    如果删除后没有剩余账号，则清除所有 Cookie 并设为"默认"。

    Args:
        name: 要删除的账号名称
    """
    self._accounts = [a for a in self._accounts if a["name"] != name]
    if self._account_name == name:
        if not self._accounts:
            # 没有剩余账号：恢复默认状态
            self._account_name = "默认"
            self._cookies = {}
            self._refresh_token = ""
            self.session.cookies.clear()
            return
        # 自动切换到第一个账号
        self._account_name = self._accounts[0]["name"]
        switch_account(self, self._account_name)


def switch_account(self, name: str):
    """切换到指定账号

    更新当前活跃账号的 Cookie 和 token，清除旧 Session Cookie，
    并应用新账号的 Cookie 到 requests Session。

    Args:
        name: 要切换到的账号名称

    Returns:
        True 表示切换成功，False 表示账号不存在
    """
    for acc in self._accounts:
        if acc["name"] == name:
            # 更新所有账号的 active 标记
            for a in self._accounts:
                a["active"] = (a["name"] == name)
            self._account_name = name
            self._cookies = dict(acc.get("cookies", {}))
            self._refresh_token = acc.get("refresh_token", "")
            self.session.cookies.clear()
            self.session.cookies.update(self._cookies)
            logger.info("已切换到账号: %s", name)
            return True
    return False


def login_with_password_fallback(self, username: str, password: str) -> Dict:
    """使用 bilibili-api-python 库兜底登录（简化的极验验证码流程）

    当自有密码登录失败时调用此函数作为备选方案。
    使用第三方库内置的极验验证码处理流程。

    Args:
        username: B站 用户名/手机号
        password: 密码（明文，通过自有加密传输）

    Returns:
        {"code": 0/..., "message": "....", "cookies": {...}, "refresh_token": "..."}
    """
    result = {"code": -1, "message": "", "cookies": {}, "refresh_token": ""}
    try:
        from bilibili_api import sync
        from bilibili_api.login_v2 import login_with_password as _bili_login
        from bilibili_api.utils.geetest import Geetest, GeetestType

        # 初始化极验验证码处理器
        g = Geetest(GeetestType.LOGIN)
        try:
            cred = sync(_bili_login(username, password, g))
        except Exception:
            result["message"] = "需通过极验验证码，请在 B站网页端登录后导入 Cookie"
            return result

        # 从登录凭证对象中提取 Cookie
        if hasattr(cred, "sessdata") and cred.sessdata:
            cookies = {
                "SESSDATA": str(cred.sessdata),
                "bili_jct": str(cred.bili_jct),
                "DedeUserID": str(cred.dedeuserid),
                "ac_time_value": getattr(cred, "ac_time_value", ""),
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


def login_with_password(
    self, username: str, password: str, captcha: str = "", captcha_type: int = 0
) -> Dict:
    """自有密码登录实现（RSA 加密 + 极验验证码自动求解）

    登录流程：
    1. 获取 B站 RSA 公钥（/x/passport-login/web/key）
    2. 使用公钥加密密码（PKCS#1 v1.5 填充）
    3. 发送登录请求
    4. 如需验证码，自动调用极验求解器
    5. 登录成功后提取并持久化 Cookie

    Args:
        username: B站 用户名/手机号
        password: 密码明文
        captcha: 验证码输入（用于二次验证提交）
        captcha_type: 验证码类型（-1 表示 geetest validate:seccode 格式）

    Returns:
        包含以下字段的字典：
          - code: 0=成功, -1=异常, 其他=API 错误码
          - message: 状态描述
          - cookies: 登录成功后的 Cookie 字典
          - refresh_token: 登录成功后的 refresh_token
          - need_captcha: 是否需要验证码
          - captcha_type: 验证码类型
          - captcha_phone: 绑定的手机号（用于短信验证码）
          - gt: 极验验证码的 gt 值（需要时返回）
          - challenge: 极验验证码的 challenge 值（需要时返回）
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.backends import default_backend

    try:
        # 步骤 1：获取 RSA 公钥
        key_url = "https://passport.bilibili.com/x/passport-login/web/key"
        _geetest_validate = ""
        _geetest_seccode = ""
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

        # 步骤 2：使用 RSA 公钥加密密码
        pub_key_obj = serialization.load_pem_public_key(pubkey.encode(), backend=default_backend())
        encrypted = pub_key_obj.encrypt(
            (hash_str + password).encode(),  # hash + 密码 拼接后加密
            padding.PKCS1v15(),
        )
        encrypted_password = encrypted.hex()

        # 步骤 3：发送登录请求
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

        # 步骤 4a：登录成功
        if api_code == 0:
            d = data.get("data", {})
            cookies = _extract_login_cookies(self, resp, d)
            if not cookies:
                # 从返回数据中构造 Cookie
                import hashlib as _hl
                mid_raw = str(d.get("mid", ""))
                ckMd5 = _hl.md5(mid_raw.encode()).hexdigest() if mid_raw else ""
                cookies = {
                    "SESSDATA": d.get("sessdata", ""),
                    "bili_jct": d.get("bili_jct", ""),
                    "DedeUserID": mid_raw,
                    "DedeUserID__ckMd5": ckMd5,
                    "sid": d.get("sid", ""),
                }
                cookies = {k: v for k, v in cookies.items() if v}
            set_cookies(self, cookies)
            refresh_token = d.get("refresh_token", "")
            self._refresh_token = refresh_token
            return {
                "code": 0,
                "message": "登录成功",
                "cookies": cookies,
                "refresh_token": refresh_token,
                "need_captcha": False,
                "captcha_type": 0,
                "captcha_phone": "",
            }

        # 步骤 4b：处理 geetest 格式的二次验证
        if captcha and captcha_type == -1 and ":" in captcha:
            validate, seccode = captcha.split(":", 1)
            _login_data = {
                "username": username, "password": encrypted_password,
                "keep": 1, "source": "main_web",
                "validate": validate, "seccode": seccode,
            }
            resp_g = self.session.post(login_url, data=_login_data, headers={
                "User-Agent": random.choice(self.USER_AGENTS),
                "Referer": "https://www.bilibili.com/",
            }, timeout=15)
            data_g = resp_g.json()
            if data_g.get("code") == 0:
                d_g = data_g.get("data", {})
                cookies = _extract_login_cookies(self, resp_g, d_g) or {
                    "SESSDATA": d_g.get("sessdata", ""), "bili_jct": d_g.get("bili_jct", ""),
                    "DedeUserID": str(d_g.get("mid", "")),
                }
                cookies = {k: v for k, v in cookies.items() if v}
                set_cookies(self, cookies)
                return {"code": 0, "message": "登录成功", "cookies": cookies,
                        "refresh_token": d_g.get("refresh_token", ""),
                        "need_captcha": False, "captcha_type": 0, "captcha_phone": ""}
            need_captcha = False  # 将在下方根据 API 返回值重新判断
            data = data_g
            api_code = data.get("code", -1)

        # 步骤 5：自动求解极验验证码
        need_captcha = data.get("need_captcha", False) or api_code in [-629, -352]
        if need_captcha and not captcha:
            d = data.get("data", {})
            gt = d.get("gt", "")
            challenge = d.get("challenge", "")
            if gt and challenge:
                solved = _auto_solve_geetest(self, gt, challenge)
                if solved:
                    validate, seccode = solved
                    _login_data = {
                        "username": username,
                        "password": encrypted_password,
                        "keep": 1,
                        "source": "main_web",
                        "validate": validate,
                        "seccode": seccode,
                    }
                    resp2 = self.session.post(login_url, data=_login_data, headers={
                        "User-Agent": random.choice(self.USER_AGENTS),
                        "Referer": "https://www.bilibili.com/",
                    }, timeout=15)
                    data2 = resp2.json()
                    if data2.get("code") == 0:
                        d2 = data2.get("data", {})
                        cookies = _extract_login_cookies(self, resp2, d2)
                        if not cookies:
                            mid2 = str(d2.get("mid", ""))
                            cookies = {k: v for k, v in {
                                "SESSDATA": d2.get("sessdata", ""),
                                "bili_jct": d2.get("bili_jct", ""),
                                "DedeUserID": mid2,
                                "DedeUserID__ckMd5": hashlib.md5(mid2.encode()).hexdigest() if mid2 else "",
                            }.items() if v}
                        set_cookies(self, cookies)
                        return {"code": 0, "message": "登录成功", "cookies": cookies,
                                "refresh_token": d2.get("refresh_token", ""),
                                "need_captcha": False, "captcha_type": 0, "captcha_phone": ""}
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

    except Exception as e:
        # 自有登录失败，尝试第三方库兜底
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


def _auto_solve_geetest(self, gt: str, challenge: str):
    """自动求解极验验证码

    使用本地图像识别模块（utils/geetest_solver.py）自动完成
    滑块验证码的缺口定位和轨迹生成。

    Args:
        gt: 极验验证码的 gt 参数
        challenge: 极验验证码的 challenge 参数

    Returns:
        (validate, seccode) 元组，或求解失败时返回 None
    """
    try:
        from utils.geetest_solver import solve

        result = solve(gt, challenge)
        if result:
            logger.info("极验验证码自动求解成功")
            return result
        logger.warning("极验验证码自动求解失败")
    except ImportError as e:
        logger.debug("极验自动求解依赖缺失: %s (需要 opencv-python, pycryptodome)", e)
    except Exception as e:
        logger.debug("极验自动求解异常: %s", e)
    return None


def _persist_cookies(self, cookies: dict):
    """将 Cookie 持久化到 network_config.json

    存储前对敏感字段（SESSDATA, bili_jct 等）进行 AES 加密。
    支持多账号格式（accounts 列表），兼容旧单账号格式。

    Args:
        cookies: 要持久化的 Cookie 字典
    """
    if not cookies:
        return
    try:
        from utils.crypto import encrypt_dict

        cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "network_config.json")
        net_cfg = {}
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                net_cfg = json.load(f)

        # 读取已有账号列表
        accounts = net_cfg.get("accounts", [])
        if not accounts and net_cfg.get("cookies"):
            # 旧格式兼容：单账号 cookies
            accounts = [{"name": net_cfg.get("account_name", "默认"),
                         "cookies": net_cfg["cookies"],
                         "refresh_token": net_cfg.get("refresh_token", ""), "active": False}]

        # 更新当前账号的 Cookie
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
            # 不存在则新建
            enc = dict(cookies)
            encrypt_dict(enc, "SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")
            accounts.append({"name": self._account_name, "cookies": enc,
                             "refresh_token": self._refresh_token, "active": False})

        # 写入文件
        net_cfg["accounts"] = accounts
        net_cfg["active_account"] = self._account_name
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(net_cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("持久化 Cookie 失败: %s", e)


def _extract_login_cookies(self, resp, data: dict) -> dict:
    """从登录响应中提取 Cookie

    从三个来源按优先级提取关键 Cookie：
    1. 登录重定向 URL 的 query 参数
    2. Set-Cookie 响应头
    3. resp.cookies 对象

    只提取 wanted 列表中的关键 Cookie 字段。

    Args:
        resp: requests.Response 对象
        data: 登录 API 返回的 data 字段

    Returns:
        提取到的 Cookie 字典
    """
    wanted = ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid", "buvid3", "buvid4", "buvid_fp")
    cookies = {}

    # 来源1：重定向 URL 中的 query 参数
    redirect_url = data.get("url", "")
    if redirect_url:
        parsed = urlparse(redirect_url)
        params = parse_qs(parsed.query)
        for key in wanted:
            if key not in cookies:
                val = params.get(key, [None])[0]
                if val:
                    cookies[key] = val

    # 来源2：Set-Cookie 响应头
    set_cookie = resp.headers.get("Set-Cookie", "")
    for part in set_cookie.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            k = k.strip()
            if k in wanted and k not in cookies:
                cookies[k] = v.split(";")[0].split(",")[0].strip()

    # 来源3：resp.cookies 属性
    for k in wanted:
        if k not in cookies and k in resp.cookies:
            cookies[k] = resp.cookies[k]

    return cookies


def _init_qr_session(self):
    """初始化 QR 扫码登录用的独立 Session

    QR 扫码使用独立的 requests Session（_qr_session），
    避免与主 Session 的 Cookie 和 UA 互相干扰。

    Returns:
        requests.Session 实例
    """
    if not hasattr(self, "_qr_session") or self._qr_session is None:
        import requests as _req

        self._qr_session = _req.Session()
        self._qr_session.headers.update({
            "User-Agent": random.choice(self.USER_AGENTS),
            "Referer": "https://www.bilibili.com/",
            "Accept": "application/json, text/plain, */*",
        })
    return self._qr_session


def get_qrcode_login_url(self) -> Optional[Dict]:
    """获取 QR 扫码登录的二维码 URL 和密钥

    调用 B站 passport 接口生成登录二维码。

    Returns:
        {"url": "二维码图片URL", "qrcode_key": "轮询密钥"} 或 None
    """
    sess = _init_qr_session(self)
    try:
        resp = sess.get("https://passport.bilibili.com/x/passport-login/web/qrcode/generate", timeout=15)
        if resp.status_code == 200:
            d = resp.json().get("data", {})
            return {"url": d.get("url", ""), "qrcode_key": d.get("qrcode_key", "")}
    except Exception as e:
        logger.debug("获取 QR 登录 URL 失败: %s", e)
    return None


def poll_qrcode_login(self, qrcode_key: str) -> Optional[Dict]:
    """轮询 QR 扫码登录状态

    不断查询二维码的扫描状态，直到扫码成功或二维码过期。
    成功登录后自动提取并持久化 Cookie。

    状态码：
      - 0: 等待扫码
      - 1: 已扫码但未确认
      - 2: 已确认（登录成功）
      - -1: 二维码已过期

    Args:
        qrcode_key: 从 get_qrcode_login_url 获取的轮询密钥

    Returns:
        {"status": 0/1/2/-1, "message": "描述", "cookies": {...}}
    """
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
        code = data.get("code", -1)
        if code == 86038:
            result["status"] = -1
            result["message"] = "二维码已过期"
            return result
        if code == 86101:
            result["message"] = "等待扫码"
            return result
        if code != 0:
            result["message"] = log_data.get("message", data.get("message", f"错误码 {code}"))
            return result

        d = data.get("data", {})
        raw_status = d.get("status")
        if raw_status == 2:
            result["status"] = 2
            result["message"] = "登录成功"
        elif raw_status == 1:
            result["status"] = 1
            result["message"] = d.get("message", "已扫码，请在手机上确认")
            return result
        elif raw_status == 0:
            result["message"] = "等待扫码"
            return result
        else:
            # 未识别状态码，保守视为成功
            result["status"] = 2
            result["message"] = "登录成功"

        # 从多个来源提取 Cookie
        cookies = _extract_login_cookies(self, resp, d)
        if not cookies:
            redirect_url = d.get("url", "")
            if redirect_url:
                parsed = urlparse(redirect_url)
                params = parse_qs(parsed.query)
                cookies = {k: params.get(k, [None])[0] for k in
                           ("SESSDATA", "bili_jct", "DedeUserID") if params.get(k, [None])[0]}
        if not cookies:
            for ci in d.get("cookie_info", {}).get("cookies", []):
                name = ci.get("name", "")
                if name in ("SESSDATA", "bili_jct", "DedeUserID"):
                    cookies[name] = ci.get("value", "")
        if not cookies:
            for k in ("SESSDATA", "bili_jct", "DedeUserID"):
                v = resp.cookies.get(k)
                if v:
                    cookies[k] = v
        if not cookies and d.get("refresh_token"):
            # 兜底：使用 refresh_token 换取 Cookie
            logger.debug("QR 登录未取到 Cookie，尝试从 refresh_token 换票")
            token_data = {"refresh_token": d["refresh_token"]}
            try:
                ex = sess.post("https://passport.bilibili.com/x/passport-login/web/exchange", data=token_data, timeout=10)
                if ex.status_code == 200:
                    exd = ex.json().get("data", {})
                    cookies = _extract_login_cookies(self, ex, exd)
            except Exception as e2:
                logger.debug("exchange 换票失败: %s", e2)
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
    """认证 Mixin 类 — 将所有模块级函数通过类属性注入到 BilibiliAPI

    Python 的 Mixin 模式：模块中的 top-level 函数在类定义时直接
    赋值给类属性，这样 BilibiliAPI 实例的 self 参数会自动传入。
    """
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
