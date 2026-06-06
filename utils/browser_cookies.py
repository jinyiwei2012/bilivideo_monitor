"""
浏览器 Cookie 提取模块
从 Chrome/Edge 等浏览器的 Cookie 数据库中提取 B 站 Cookie
"""

import os
import json
import logging
import sqlite3
import shutil
import tempfile
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# 浏览器 Cookie 数据库路径
BROWSER_PATHS = {
    "chrome": os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data"),
    "edge": os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data"),
    "360": os.path.expandvars(r"%LOCALAPPDATA%\360Chrome\Chrome\User Data"),
    "qq": os.path.expandvars(r"%LOCALAPPDATA%\Tencent\QQBrowser\User Data"),
}


def _get_os_crypt_key(local_state_path: str) -> Optional[bytes]:
    """从 Chrome Local State 中获取加密的 AES key（DPAPI 解密）"""
    try:
        import win32crypt

        with open(local_state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        enc_key = state.get("os_crypt", {}).get("encrypted_key")
        if not enc_key:
            return None
        # 去掉 "DPAPI" 前缀（5 bytes）
        import base64

        enc_key_bytes = base64.b64decode(enc_key)
        if enc_key_bytes[:5] == b"DPAPI":
            enc_key_bytes = enc_key_bytes[5:]
        # 用 DPAPI 解密
        key = win32crypt.CryptUnprotectData(enc_key_bytes, None, None, None, 0)[1]
        return key
    except ImportError:
        logger.debug("win32crypt 不可用，无法解密 Chrome Cookie (pip install pypiwin32)")
    except Exception as e:
        logger.debug("获取 Chrome AES key 失败: %s", e)
    return None


def _decrypt_chrome_cookie(encrypted_value: bytes, key: bytes) -> Optional[str]:
    """解密 Chrome/Edge AES-GCM 加密的 Cookie 值"""
    try:
        from Cryptodome.Cipher import AES

        # Chrome 格式: nonce(12) + ciphertext + tag(16)
        nonce = encrypted_value[:12]
        ciphertext = encrypted_value[12:-16]
        tag = encrypted_value[-16:]
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        decrypted = cipher.decrypt_and_verify(ciphertext, tag)
        return decrypted.decode("utf-8")
    except Exception as e:
        logger.debug("解密 Cookie 值失败: %s", e)
        return None


def extract_from_browser(browser: str = "chrome") -> Optional[Dict]:
    """从指定浏览器提取 B 站 Cookie

    Args:
        browser: "chrome", "edge", "360", "qq"

    Returns:
        {"SESSDATA": "...", "bili_jct": "...", "DedeUserID": "..."} or None
    """
    user_data = BROWSER_PATHS.get(browser)
    if not user_data or not os.path.exists(user_data):
        logger.debug("浏览器 %s 未找到: %s", browser, user_data)
        return None

    # 找到默认 profile 的 Cookie 数据库
    for profile in ["Default", "Profile 1", "Profile 2"]:
        cookie_db = os.path.join(user_data, profile, "Network", "Cookies")
        if os.path.exists(cookie_db):
            break
        # 旧版 Chrome 路径
        cookie_db = os.path.join(user_data, profile, "Cookies")
        if os.path.exists(cookie_db):
            break
    else:
        logger.debug("未找到 Cookie 数据库")
        return None

    # 获取解密 key
    local_state = os.path.join(user_data, "Local State")
    key = _get_os_crypt_key(local_state)
    if not key:
        logger.debug("无法获取解密 key，Cookie 可能为明文或旧版")
        # 尝试读取明文 Cookie（旧版 Chrome）
        return _read_plain_cookies(cookie_db)

    return _read_encrypted_cookies(cookie_db, key, browser)


def _read_encrypted_cookies(cookie_db: str, key: bytes, browser: str) -> Optional[Dict]:
    """读取 AES 加密的 Cookie 数据库"""
    cookies = {}
    tmp_path = ""
    try:
        # 复制文件避免数据库锁
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(tmp_fd)
        shutil.copy2(cookie_db, tmp_path)

        conn = sqlite3.connect(tmp_path)
        cur = conn.cursor()
        # Chrome/Edge 新格式
        rows = cur.execute("SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%bilibili.com%'").fetchall()
        if not rows:
            # 有些浏览器用 host_key 字段不同
            rows = cur.execute("SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%bilibili%'").fetchall()
        for name, enc_val in rows:
            if name in ("SESSDATA", "bili_jct", "DedeUserID", "buvid3", "buvid4"):
                if enc_val and enc_val != b"":
                    decrypted = _decrypt_chrome_cookie(enc_val, key)
                    if decrypted:
                        cookies[name] = decrypted
        conn.close()
    except Exception as e:
        logger.debug("读取加密 Cookie 失败: %s", e)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    return cookies if cookies else None


def _read_plain_cookies(cookie_db: str) -> Optional[Dict]:
    """读取明文 Cookie（旧版 Chrome / 部分国产浏览器）"""
    cookies = {}
    tmp_path = ""
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(tmp_fd)
        shutil.copy2(cookie_db, tmp_path)

        conn = sqlite3.connect(tmp_path)
        cur = conn.cursor()
        rows = cur.execute("SELECT name, value FROM cookies WHERE host_key LIKE '%bilibili.com%'").fetchall()
        for name, val in rows:
            if name in ("SESSDATA", "bili_jct", "DedeUserID", "buvid3", "buvid4") and val:
                cookies[name] = val
        conn.close()
    except Exception as e:
        logger.debug("读取明文 Cookie 失败: %s", e)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    return cookies if cookies else None


def extract_from_all_browsers() -> Dict:
    """遍历所有浏览器尝试提取 Cookie"""
    for browser in ("chrome", "edge", "360", "qq"):
        result = extract_from_browser(browser)
        if result:
            logger.info("从 %s 提取到 Cookie: %s", browser, list(result.keys()))
            return result
    return {}
