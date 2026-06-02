"""
浏览器 Cookie 提取模块

从 Chrome / Edge / 360 / QQ 等主流浏览器的 Cookie 数据库中，
自动提取 B站 的登录 Cookie（SESSDATA、bili_jct、DedeUserID 等）。

技术要点：
1. 支持 AES-GCM 加密的 Cookie（新版 Chrome/Edge，需要 win32crypt + pycryptodomex）
2. 支持明文 Cookie（旧版 Chrome / 部分国产浏览器）
3. 先复制后读取：使用临时文件避免锁定原始 Cookie 数据库
4. 自动探测浏览器 Profile（Default、Profile 1、Profile 2）
5. DPAPI 解密 Chrome 的 AES 密钥（Windows 专属，绑定当前用户会话）

依赖：
- win32crypt (pypiwin32) — Windows DPAPI 解密
- pycryptodomex          — AES-GCM 解密 Cookie 值
"""

import os
import json
import logging
import sqlite3
import shutil
import tempfile
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# ── 各浏览器的 Cookie 数据库路径 ────────────────────────
# 使用 %LOCALAPPDATA% 环境变量定位 User Data 目录
BROWSER_PATHS = {
    "chrome": os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data"),
    "edge": os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data"),
    "360": os.path.expandvars(r"%LOCALAPPDATA%\360Chrome\Chrome\User Data"),
    "qq": os.path.expandvars(r"%LOCALAPPDATA%\Tencent\QQBrowser\User Data"),
}


def _get_os_crypt_key(local_state_path: str) -> Optional[bytes]:
    """从 Chrome 的 Local State 文件中提取并解密 AES 加密密钥。

    Chrome 使用 DPAPI（Data Protection API）保护 AES 密钥：
    1. 读取 Local State JSON 中的 os_crypt.encrypted_key 字段
    2. Base64 解码
    3. 去掉 "DPAPI" 前缀（前 5 字节）
    4. 使用 win32crypt.CryptUnprotectData 解密

    Args:
        local_state_path: Chrome Local State 文件的路径

    Returns:
        bytes | None: 解密后的 256 位 AES 密钥；解密失败返回 None
    """
    try:
        import win32crypt  # Windows DPAPI 解密库

        with open(local_state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        enc_key = state.get("os_crypt", {}).get("encrypted_key")
        if not enc_key:
            return None
        # 去掉 "DPAPI" 前缀（5 字节标识）
        import base64

        enc_key_bytes = base64.b64decode(enc_key)
        if enc_key_bytes[:5] == b"DPAPI":
            enc_key_bytes = enc_key_bytes[5:]
        # 用 DPAPI 解密 AES 密钥（绑定当前 Windows 用户会话）
        key = win32crypt.CryptUnprotectData(enc_key_bytes, None, None, None, 0)[1]
        return key
    except ImportError:
        logger.debug("win32crypt 不可用，无法解密 Chrome Cookie (pip install pypiwin32)")
    except Exception as e:
        logger.debug("获取 Chrome AES key 失败: %s", e)
    return None


def _decrypt_chrome_cookie(encrypted_value: bytes, key: bytes) -> Optional[str]:
    """解密 Chrome/Edge 的 AES-GCM 加密 Cookie 值。

    Chrome Cookie 加密格式（v10+）：
    - 前 12 字节: nonce（初始化向量）
    - 中间部分: AES-GCM 加密的密文
    - 后 16 字节: GCM 认证标签（tag）

    Args:
        encrypted_value: 加密的 Cookie 值（二进制）
        key: AES 密钥（32 字节，即 256 位）

    Returns:
        str | None: 解密后的 Cookie 值字符串；解密失败返回 None
    """
    try:
        from Cryptodome.Cipher import AES

        # Chrome 格式: nonce(12) + ciphertext + tag(16)
        nonce = encrypted_value[:12]  # 前 12 字节为 nonce
        ciphertext = encrypted_value[12:-16]  # 中间为密文
        tag = encrypted_value[-16:]  # 最后 16 字节为 GCM tag
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        decrypted = cipher.decrypt_and_verify(ciphertext, tag)
        return decrypted.decode("utf-8")
    except Exception as e:
        logger.debug("解密 Cookie 值失败: %s", e)
        return None


def extract_from_browser(browser: str = "chrome") -> Optional[Dict]:
    """从指定浏览器提取 B站 Cookie。

    支持的 Cookie 字段：SESSDATA、bili_jct、DedeUserID、buvid3、buvid4

    Args:
        browser: 浏览器标识 ("chrome", "edge", "360", "qq")

    Returns:
        dict | None: {"SESSDATA": "...", "bili_jct": "...", ...} 或 None（未找到/提取失败）

    Example:
        >>> cookies = extract_from_browser("chrome")
        >>> if cookies:
        ...     print(cookies["SESSDATA"])
    """
    user_data = BROWSER_PATHS.get(browser)
    if not user_data or not os.path.exists(user_data):
        logger.debug("浏览器 %s 未找到: %s", browser, user_data)
        return None

    # 找到默认 profile 的 Cookie 数据库（按优先级遍历多个 Profile）
    for profile in ["Default", "Profile 1", "Profile 2"]:
        cookie_db = os.path.join(user_data, profile, "Network", "Cookies")  # 新版 Chrome 路径
        if os.path.exists(cookie_db):
            break
        # 旧版 Chrome/Edge 路径（Cookies 文件直接在 Profile 目录下）
        cookie_db = os.path.join(user_data, profile, "Cookies")
        if os.path.exists(cookie_db):
            break
    else:
        logger.debug("未找到 Cookie 数据库")
        return None

    # 获取解密 key（新版 Chrome 需要 AES-GCM 解密）
    local_state = os.path.join(user_data, "Local State")
    key = _get_os_crypt_key(local_state)
    if not key:
        logger.debug("无法获取解密 key，Cookie 可能为明文或旧版")
        # 尝试读取明文 Cookie（旧版 Chrome / 部分国产浏览器）
        return _read_plain_cookies(cookie_db)

    return _read_encrypted_cookies(cookie_db, key, browser)


def _read_encrypted_cookies(cookie_db: str, key: bytes, browser: str) -> Optional[Dict]:
    """读取并解密 AES-GCM 加密的 Cookie 数据库。

    流程：
    1. 复制 Cookie 数据库到临时文件（避免锁定原始文件）
    2. SQLite 查询 bilibili.com 相关 Cookie
    3. 逐条 AES-GCM 解密
    4. 清理临时文件

    Args:
        cookie_db: Cookie SQLite 数据库路径
        key: AES 解密密钥
        browser: 浏览器标识

    Returns:
        dict | None: 解密后的 Cookie 键值对；未找到有效 Cookie 返回 None
    """
    cookies = {}
    tmp_path = ""
    try:
        # 复制文件到临时目录避免数据库锁
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(tmp_fd)
        shutil.copy2(cookie_db, tmp_path)

        conn = sqlite3.connect(tmp_path)
        cur = conn.cursor()
        # Chrome/Edge 新格式：Cookie 值存储在 encrypted_value 列
        rows = cur.execute(
            "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%bilibili.com%'"
        ).fetchall()
        if not rows:
            # 兼容：有些浏览器 host_key 只用 %bilibili% 匹配
            rows = cur.execute(
                "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%bilibili%'"
            ).fetchall()
        for name, enc_val in rows:
            # 只提取 B站 登录相关的核心 Cookie
            if name in ("SESSDATA", "bili_jct", "DedeUserID", "buvid3", "buvid4"):
                if enc_val and enc_val != b"":
                    decrypted = _decrypt_chrome_cookie(enc_val, key)
                    if decrypted:
                        cookies[name] = decrypted
        conn.close()
    except Exception as e:
        logger.debug("读取加密 Cookie 失败: %s", e)
    finally:
        # 清理临时文件（无论成功失败都删除）
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    return cookies if cookies else None


def _read_plain_cookies(cookie_db: str) -> Optional[Dict]:
    """读取明文 Cookie（旧版 Chrome / 部分国产浏览器）。

    与 _read_encrypted_cookies 流程相同，但读取的是 value 列（而非 encrypted_value 列）。

    Args:
        cookie_db: Cookie SQLite 数据库路径

    Returns:
        dict | None: Cookie 键值对；未找到有效 Cookie 返回 None
    """
    cookies = {}
    tmp_path = ""
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(tmp_fd)
        shutil.copy2(cookie_db, tmp_path)

        conn = sqlite3.connect(tmp_path)
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT name, value FROM cookies WHERE host_key LIKE '%bilibili.com%'"
        ).fetchall()
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
    """遍历所有已配置的浏览器，尝试提取 B站 Cookie。

    按优先级顺序探测：chrome → edge → 360 → qq，
    找到第一个可用 Cookie 后立即返回，不继续尝试其他浏览器。

    Returns:
        dict: 找到的 Cookie 键值对（可能为空字典 {}）
    """
    for browser in ("chrome", "edge", "360", "qq"):
        result = extract_from_browser(browser)
        if result:
            logger.info("从 %s 提取到 Cookie: %s", browser, list(result.keys()))
            return result
    return {}
