"""Cookie/敏感配置加密存储

支持两级加密：
  1. cryptography.fernet（推荐）— 真实 AES 加密
  2. 内置 XOR + HMAC 回退       — 基于机器标识的对称脱敏

公开 API：
    encrypt(plaintext: str) -> str
    decrypt(ciphertext: str) -> str
"""

import base64
import hashlib
import hmac
import logging
import os
import platform
import subprocess

logger = logging.getLogger(__name__)

# ── 后端选择 ──────────────────────────────────────────

_HAZMAT = False
try:
    from cryptography.fernet import Fernet

    _HAZMAT = True
except ImportError:
    Fernet = None  # type: ignore

# ── 机器标识密钥 ──────────────────────────────────────


def _machine_secret() -> bytes:
    """导出一个稳定的 32 字节机器密钥（跨进程/重启一致）。"""
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

    # MAC 地址
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
    # 使用 PBKDF2 派生 32 字节密钥
    return hashlib.pbkdf2_hmac("sha256", seed, b"bilibili_monitor_salt_2026", 100000, dklen=32)


_KEY = base64.urlsafe_b64encode(_machine_secret()) if _HAZMAT else None
_MACHINE_KEY = _machine_secret()


def _fernet_encrypt(plaintext: str) -> str:
    """使用 Fernet (AES) 加密"""
    f = Fernet(_KEY)
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def _fernet_decrypt(ciphertext: str) -> str:
    """使用 Fernet (AES) 解密"""
    f = Fernet(_KEY)
    return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def _xor_encrypt(plaintext: str) -> str:
    """使用 XOR + HMAC 流密码加密（无 cryptography 时的回退方案）"""
    data = plaintext.encode("utf-8")
    key = _MACHINE_KEY
    # 用 HMAC-SHA256 生成与明文等长的密钥流
    stream = bytearray()
    counter = 0
    while len(stream) < len(data):
        block = hmac.new(key, counter.to_bytes(4, "big"), "sha256").digest()
        stream.extend(block)
        counter += 1
    # XOR
    encrypted = bytes(a ^ b for a, b in zip(data, stream[: len(data)]))
    # HMAC-SHA256 标签（前 8 字符）防止篡改
    tag = hmac.new(key, encrypted, hashlib.sha256).hexdigest()[:8]
    return base64.urlsafe_b64encode(tag.encode() + encrypted).decode("utf-8")


def _xor_decrypt(ciphertext: str) -> str:
    """使用 XOR + HMAC 流密码解密（验证 HMAC 标签）"""
    raw = base64.urlsafe_b64decode(ciphertext.encode("utf-8"))
    key = _MACHINE_KEY
    tag = raw[:8].decode()
    encrypted = raw[8:]
    expected = hmac.new(key, encrypted, hashlib.sha256).hexdigest()[:8]
    if not hmac.compare_digest(tag, expected):
        raise ValueError("密文 HMAC 校验失败，数据可能被篡改")
    stream = bytearray()
    counter = 0
    while len(stream) < len(encrypted):
        block = hmac.new(key, counter.to_bytes(4, "big"), "sha256").digest()
        stream.extend(block)
        counter += 1
    decrypted = bytes(a ^ b for a, b in zip(encrypted, stream[: len(encrypted)]))
    return decrypted.decode("utf-8")


def encrypt(plaintext: str) -> str:
    """加密明文，返回可安全存储的字符串。"""
    if not plaintext:
        return ""
    if _HAZMAT:
        return _fernet_encrypt(plaintext)
    return _xor_encrypt(plaintext)


def decrypt(ciphertext: str) -> str:
    """解密密文，返回原始明文。"""
    if not ciphertext:
        return ""
    if _HAZMAT:
        return _fernet_decrypt(ciphertext)
    return _xor_decrypt(ciphertext)


def is_encrypted(value: str) -> bool:
    """粗略判断值是否已加密（非空且不含等号等 json 特征）。"""
    if not value:
        return False
    return not any(c in value for c in ('"', "{", ":"))


def encrypt_dict(d: dict, *keys: str) -> dict:
    """加密字典中的指定键（原地修改）。"""
    for k in keys:
        if k in d and isinstance(d[k], str) and d[k]:
            d[k] = encrypt(d[k])
    return d


def decrypt_dict(d: dict, *keys: str) -> dict:
    """解密字典中的指定键（原地修改）。"""
    for k in keys:
        if k in d and isinstance(d[k], str) and d[k]:
            try:
                d[k] = decrypt(d[k])
            except Exception as e:
                logger.warning("解密失败: %s", e)
    return d
