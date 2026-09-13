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
from typing import Optional

logger = logging.getLogger(__name__)

# ── 密文版本前缀（is_encrypted 据此精确判定，不再依赖"解密试算"猜测）──
_PREFIX_FERNET = "f1:"
_PREFIX_XOR = "x1:"
_XOR_TAG_HEX_LEN = 64  # 完整 hmac-sha256 hex 标签（旧格式为 8）

# ── 后端选择 ──────────────────────────────────────────

_HAZMAT = False
try:
    from cryptography.fernet import Fernet

    _HAZMAT = True
except ImportError:
    Fernet = None  # type: ignore
    logger.warning("cryptography 未安装，将使用 XOR 回退加密（安全性降低，建议 pip install cryptography）")

# ── 机器标识密钥（惰性派生 + 进程内缓存）──────────────
# 仅用「读注册表 / 取 MAC / 主机名」这类快速且始终可用的标识派生密钥。
#
# 为何不含 CPU 序列号：历史实现会用 PowerShell 取 Win32_Processor.ProcessorId，
# 但 PowerShell 冷启动约 3.5s 而超时设为 3s —— 实际每次都超时失败、该成分从未生效，
# 却让**每个进程启动**都白等约 3s（实测 2.3–3.1s）。去掉子进程后：
#   1) 派生结果与历史完全一致（cpu_id 从未参与），既有密文不受影响；
#   2) 启动不再有任何子进程开销。

_MACHINE_SECRET: "Optional[bytes]" = None
_KEY_CACHE: dict = {}


def _compute_machine_secret() -> bytes:
    """导出稳定的 32 字节机器密钥（跨进程/重启一致；成分与历史保持一致）。"""
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

    # 主机名（CPU 序列号已不再参与，见文件头说明）
    parts.append(platform.node() or "unknown")

    # 回退：当前用户名 + 系统路径
    if not parts:
        parts.append(os.environ.get("USERNAME", "default"))
        parts.append(os.environ.get("COMPUTERNAME", "localhost"))

    seed = "||".join(parts).encode("utf-8")
    # 使用 PBKDF2 派生 32 字节密钥
    return hashlib.pbkdf2_hmac("sha256", seed, b"bilibili_monitor_salt_2026", 100000, dklen=32)


def machine_key() -> bytes:
    """回退加密用的 32 字节机器密钥（惰性派生、进程内缓存）。"""
    global _MACHINE_SECRET
    if _MACHINE_SECRET is None:
        _MACHINE_SECRET = _compute_machine_secret()
    return _MACHINE_SECRET


def _fernet_key() -> bytes:
    """Fernet 用的 base64 密钥（惰性、进程内缓存）。"""
    key = _KEY_CACHE.get("fernet")
    if key is None:
        key = base64.urlsafe_b64encode(machine_key())
        _KEY_CACHE["fernet"] = key
    return key


def _fernet_encrypt(plaintext: str) -> str:
    """使用 Fernet (AES) 加密"""
    f = Fernet(_fernet_key())
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def _fernet_decrypt(ciphertext: str) -> str:
    """使用 Fernet (AES) 解密"""
    f = Fernet(_fernet_key())
    return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def _xor_encrypt(plaintext: str) -> str:
    """使用 XOR + HMAC 流密码加密（无 cryptography 时的回退方案）。

    密文格式：``x1:`` + base64(完整 HMAC-SHA256 hex 标签 ‖ 密文体)。
    旧实现只取标签前 8 个 hex 字符（32 bit），完整性强度过弱，已改为完整 64 字符。
    """
    data = plaintext.encode("utf-8")
    key = machine_key()
    # 用 HMAC-SHA256 生成与明文等长的密钥流（CTR 构造）
    stream = bytearray()
    counter = 0
    while len(stream) < len(data):
        block = hmac.new(key, counter.to_bytes(4, "big"), "sha256").digest()
        stream.extend(block)
        counter += 1
    encrypted = bytes(a ^ b for a, b in zip(data, stream[: len(data)]))
    tag = hmac.new(key, encrypted, hashlib.sha256).hexdigest()
    return _PREFIX_XOR + base64.urlsafe_b64encode(tag.encode() + encrypted).decode("utf-8")


def _xor_decrypt_raw(body: str, tag_hex_len: int) -> str:
    """按给定标签长度解密 XOR 密文体（供新/旧格式复用）。"""
    raw = base64.urlsafe_b64decode(body.encode("utf-8"))
    tag = raw[:tag_hex_len].decode()
    encrypted = raw[tag_hex_len:]
    expected = hmac.new(machine_key(), encrypted, hashlib.sha256).hexdigest()[:tag_hex_len]
    if not hmac.compare_digest(tag, expected):
        raise ValueError("密文 HMAC 校验失败，数据可能被篡改")
    stream = bytearray()
    counter = 0
    while len(stream) < len(encrypted):
        block = hmac.new(machine_key(), counter.to_bytes(4, "big"), "sha256").digest()
        stream.extend(block)
        counter += 1
    decrypted = bytes(a ^ b for a, b in zip(encrypted, stream[: len(encrypted)]))
    return decrypted.decode("utf-8")


def _xor_decrypt(ciphertext: str) -> str:
    """解密 XOR 回退密文；兼容历史无前缀 / 短标签（8 hex）格式。"""
    if ciphertext.startswith(_PREFIX_XOR):
        return _xor_decrypt_raw(ciphertext[len(_PREFIX_XOR) :], _XOR_TAG_HEX_LEN)
    try:
        return _xor_decrypt_raw(ciphertext, _XOR_TAG_HEX_LEN)
    except Exception:
        return _xor_decrypt_raw(ciphertext, 8)  # 历史格式


def encrypt(plaintext: str) -> str:
    """加密明文，返回带版本前缀、可安全存储的字符串。"""
    if not plaintext:
        return ""
    if _HAZMAT:
        return _PREFIX_FERNET + _fernet_encrypt(plaintext)
    return _xor_encrypt(plaintext)


def decrypt(ciphertext: str) -> str:
    """解密密文，返回原始明文（兼容历史无前缀密文）。"""
    if not ciphertext:
        return ""
    if ciphertext.startswith(_PREFIX_FERNET):
        return _fernet_decrypt(ciphertext[len(_PREFIX_FERNET) :])
    if ciphertext.startswith(_PREFIX_XOR):
        return _xor_decrypt(ciphertext)
    # 历史无前缀密文：先按当前后端试，失败再试另一种（旧 XOR 密文可能在装了
    # cryptography 之后才被读到，反之亦然）
    if _HAZMAT:
        try:
            return _fernet_decrypt(ciphertext)
        except Exception:
            return _xor_decrypt(ciphertext)
    return _xor_decrypt(ciphertext)


def is_encrypted(value: str) -> bool:
    """判断值是否已加密：优先凭版本前缀精确判定，避免"试算猜谜"。

    历史实现「解密不抛错即视为密文」会把恰好可解码的明文误判（XOR 回退下更随机）。
    现对**本模块产生的密文**只查前缀（确定、廉价）；仅对历史无前缀值保留试算兜底，
    并用 ``isprintable()`` 收紧判定。
    """
    if not value or not isinstance(value, str):
        return False
    if value.startswith((_PREFIX_FERNET, _PREFIX_XOR)):
        return True
    if any(c in value for c in ('"', "{", ":")):
        # 含 JSON 特征，几乎不可能是密文
        return False
    try:
        decrypted = decrypt(value)
    except Exception:
        return False
    return bool(decrypted) and decrypted.isprintable()


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
