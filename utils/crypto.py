"""
Cookie 与敏感配置的加密存储模块

提供两级加密方案，用于保护存储在配置文件中的敏感数据（如 B站 Cookie）：
  1. cryptography.fernet（推荐）— 基于 AES-128-CBC 的真实加密，安全级别高
  2. 内置 XOR + HMAC 流密码  — 基于机器标识的对称脱敏，无第三方依赖的回退方案

加密密钥衍生自本机机器标识（MachineGuid、MAC 地址、主机名、处理器序列号等），
确保加密数据只能在当前机器上解密，拷贝到其他机器将无法还原。

公开 API：
    encrypt(plaintext: str) -> str        加密明文
    decrypt(ciphertext: str) -> str       解密密文
    encrypt_dict(d, *keys) -> dict        批量加密字典中的指定键
    decrypt_dict(d, *keys) -> dict        批量解密字典中的指定键
    is_encrypted(value: str) -> bool      粗略判断值是否已加密
"""

import base64
import hashlib
import hmac
import logging
import os
import platform
import subprocess

logger = logging.getLogger(__name__)

# ── 后端选择：优先使用 cryptography，不可用时回退 XOR ──────

_HAZMAT = False
try:
    from cryptography.fernet import Fernet

    _HAZMAT = True  # "hazmat" 是 cryptography 库对底层加密原语的约定命名
except ImportError:
    Fernet = None  # type: ignore

# ── 机器标识密钥派生 ──────────────────────────────────────


def _machine_secret() -> bytes:
    """导出一个稳定的 32 字节机器密钥，跨进程/重启保持一致。

    采集多个系统唯一标识：
    1. Windows Registry 中的 MachineGuid（最稳定，重装系统前不变）
    2. 网卡 MAC 地址（真实物理 MAC，非虚拟/随机）
    3. 主机名
    4. 处理器序列号（通过 WMI 获取）
    5. 回退：用户名 + 计算机名

    使用 PBKDF2-HMAC-SHA256 进行多轮密钥派生（10 万次迭代），
    即使采集的原始标识不完全唯一，也能产生安全的密钥。
    """
    parts = []

    # Windows: MachineGuid 注册表值（最稳定）
    if platform.system() == "Windows":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                guid, _ = winreg.QueryValueEx(key, "MachineGuid")
                parts.append(guid)
        except Exception:
            pass

    # MAC 地址（仅使用真实物理地址，排除随机生成的虚拟 MAC）
    try:
        import uuid

        mac = uuid.getnode()
        if (mac >> 40) & 1 == 0:  # 仅当是真实 MAC（非随机）
            parts.append(str(mac))
    except Exception:
        pass

    # 主机名 + 处理器序列号
    parts.append(platform.node() or "unknown")
    try:
        if platform.system() == "Windows":
            output = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Processor | Select-Object -ExpandProperty ProcessorId"],
                timeout=3, stderr=subprocess.DEVNULL,
            )
            parts.append(output.decode().strip().split("\n")[-1].strip())
    except Exception:
        pass

    # 回退：当前用户名 + 系统路径
    if not parts:
        parts.append(os.environ.get("USERNAME", "default"))
        parts.append(os.environ.get("COMPUTERNAME", "localhost"))

    seed = "||".join(parts).encode("utf-8")
    # 使用 PBKDF2 派生 32 字节密钥（salt 固定，10 万次迭代）
    return hashlib.pbkdf2_hmac("sha256", seed, b"bilibili_monitor_salt_2026", 100000, dklen=32)


# 预计算密钥（模块加载时一次性计算）
_KEY = base64.urlsafe_b64encode(_machine_secret()) if _HAZMAT else None
_MACHINE_KEY = _machine_secret()
_FERNET = Fernet(_KEY) if _HAZMAT else None


def _fernet_encrypt(plaintext: str) -> str:
    """使用 Fernet (AES-128-CBC) 加密明文。

    Fernet 内置时间戳验证和 HMAC 签名，在 cryptography 库可用时使用。

    Args:
        plaintext: 要加密的明文字符串

    Returns:
        str: Base64 编码的密文字符串
    """
    return _FERNET.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def _fernet_decrypt(ciphertext: str) -> str:
    """使用 Fernet (AES-128-CBC) 解密密文。

    自动验证 HMAC 签名和时间戳，防止数据被篡改。

    Args:
        ciphertext: Base64 编码的密文字符串

    Returns:
        str: 解密后的原始明文字符串
    """
    return _FERNET.decrypt(ciphertext.encode("utf-8")).decode("utf-8")



def _xor_key_stream(key: bytes, length: int, start_counter: int = 0) -> bytearray:
    """使用 HMAC-SHA256 生成指定长度的密钥流（计数器模式）。

    Args:
        key: 密钥字节串
        length: 需要的密钥流长度
        start_counter: 起始计数器值（默认为 0）

    Returns:
        bytearray: 生成的密钥流（精确 length 字节）
    """
    stream = bytearray()
    counter = start_counter
    while len(stream) < length:
        block = hmac.new(key, (counter & 0xFFFFFFFF).to_bytes(4, "big"), "sha256").digest()
        stream.extend(block)
        counter += 1
    return stream[:length]


def _xor_encrypt(plaintext: str) -> str:
    """使用 XOR + HMAC 流密码加密（无 cryptography 库时的回退方案）。

    加密流程：
    1. 生成随机 8 字节 nonce，作为密钥流的起始计数器偏移
    2. 以 HMAC-SHA256 生成与明文等长的密钥流（CTR 模式思想）
    3. XOR 加密
    4. 附加 HMAC-SHA256 标签（前 8 字符）防止篡改
    5. 非加密前缀 nonce 后 Base64 编码输出

    Args:
        plaintext: 要加密的明文字符串

    Returns:
        str: Base64 编码的密文字符串（含 8 字节 HMAC 标签前缀 + 8 字节 nonce）
    """
    data = plaintext.encode("utf-8")
    key = _MACHINE_KEY
    nonce = os.urandom(8)
    nonce_int = int.from_bytes(nonce, "big")
    stream = _xor_key_stream(key, len(data), start_counter=nonce_int)
    encrypted = bytes(a ^ b for a, b in zip(data, stream[:len(data)]))
    tag = hmac.new(key, encrypted, hashlib.sha256).hexdigest()[:8]
    raw = nonce + encrypted
    return base64.urlsafe_b64encode(tag.encode() + raw).decode("utf-8")


def _xor_decrypt(ciphertext: str) -> str:
    """使用 XOR + HMAC 流密码解密（验证 HMAC 标签）。

    解密流程与加密对称：
    1. Base64 解码
    2. 提取并验证 HMAC 标签
    3. 提取 8 字节 nonce，恢复起始计数器
    4. 生成密钥流
    5. XOR 解密

    Args:
        ciphertext: Base64 编码的密文字符串

    Returns:
        str: 解密后的原始明文字符串

    Raises:
        ValueError: 当 HMAC 标签校验失败时（密文可能被篡改）
    """
    raw = base64.urlsafe_b64decode(ciphertext.encode("utf-8"))
    key = _MACHINE_KEY
    tag = raw[:8].decode()
    nonce = raw[8:16]
    encrypted = raw[16:]
    expected = hmac.new(key, encrypted, hashlib.sha256).hexdigest()[:8]
    if not hmac.compare_digest(tag, expected):
        raise ValueError("密文 HMAC 校验失败，数据可能被篡改")
    nonce_int = int.from_bytes(nonce, "big")
    stream = _xor_key_stream(key, len(encrypted), start_counter=nonce_int)
    decrypted = bytes(a ^ b for a, b in zip(encrypted, stream[:len(encrypted)]))
    return decrypted.decode("utf-8")


# ── 公开 API ───────────────────────────────────────────


def encrypt(plaintext: str) -> str:
    """加密明文，返回可安全存储的字符串（自动选择 Fernet 或 XOR 方案）。

    Args:
        plaintext: 要加密的明文字符串（空字符串返回空字符串）

    Returns:
        str: 加密后的密文字符串

    Example:
        >>> encrypted = encrypt("my_cookie_value")
        >>> print(encrypted)  # 类似 "gAAAAABm..."
    """
    if not plaintext:
        return ""
    if _HAZMAT:
        return _fernet_encrypt(plaintext)
    return _xor_encrypt(plaintext)


def decrypt(ciphertext: str) -> str:
    """解密密文，返回原始明文。

    Args:
        ciphertext: 加密后的密文字符串（空字符串返回空字符串）

    Returns:
        str: 解密后的明文字符串

    Example:
        >>> original = decrypt("gAAAAABm...")
        >>> print(original)  # "my_cookie_value"
    """
    if not ciphertext:
        return ""
    if _HAZMAT:
        return _fernet_decrypt(ciphertext)
    return _xor_decrypt(ciphertext)


def is_encrypted(value: str) -> bool:
    """粗略判断字符串是否已加密。

    启发式规则：已加密的字符串通常为纯字母数字和特殊符号，
    不含 JSON 特征字符（双引号、花括号、冒号）。

    Args:
        value: 待判断的字符串

    Returns:
        bool: True 表示可能已加密，False 表示可能为明文
    """
    if not value:
        return False
    return not any(c in value for c in ('"', "{", ":"))


def encrypt_dict(d: dict, *keys: str) -> dict:
    """加密字典中指定键的值（原地修改）。

    适用于保护配置字典中的敏感字段（如 api_key, cookie 等）。

    Args:
        d: 待处理的字典
        *keys: 需要加密的键名

    Returns:
        dict: 原地修改后的同一字典对象

    Example:
        >>> config = {"username": "user", "cookie": "secret123"}
        >>> encrypt_dict(config, "cookie")
        >>> print(config["cookie"])  # 已被加密
    """
    for k in keys:
        if k in d and isinstance(d[k], str) and d[k]:
            d[k] = encrypt(d[k])
    return d


def decrypt_dict(d: dict, *keys: str) -> dict:
    """解密字典中指定键的值（原地修改）。

    解密失败时记录警告日志但不中断，保留加密值供后续重试。

    Args:
        d: 待处理的字典
        *keys: 需要解密的键名

    Returns:
        dict: 原地修改后的同一字典对象

    Example:
        >>> config = {"username": "user", "cookie": "gAAAAABm..."}
        >>> decrypt_dict(config, "cookie")
        >>> print(config["cookie"])  # "secret123"
    """
    for k in keys:
        if k in d and isinstance(d[k], str) and d[k]:
            try:
                d[k] = decrypt(d[k])
            except Exception as e:
                logger.warning("解密失败: %s", e)
    return d
