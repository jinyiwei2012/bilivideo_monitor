"""
代码签名工具 — Ed25519 数字签名源码完整性清单

首次运行生成密钥对，后续运行使用已有私钥签名。
签名清单写入 data/integrity_manifest.json，公钥需手动嵌入 main.py。

用法:
    python scripts/sign.py              # 签名所有核心文件
    python scripts/sign.py --init       # 仅生成密钥对（不签名）
    python scripts/sign.py --verify     # 验证现有签名
    python scripts/sign.py --export-pub # 导出公钥（用于嵌入 main.py）
"""

import hashlib
import json
import os
import sys
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_FILE = os.path.join(os.path.dirname(__file__), ".signing_key")
MANIFEST_FILE = os.path.join(PROJECT_ROOT, "data", "integrity_manifest.json")

# 需要签名的核心文件（相对于项目根目录）
CORE_FILES = [
    "main.py",
    "core/bilibili_api.py",
    "core/bilibili_request.py",
    "core/bilibili_auth.py",
    "core/bilibili_video.py",
    "core/bilibili_up.py",
    "core/notification.py",
    "core/proxy_manager.py",
    "core/smart_alert.py",
    "core/database/__init__.py",
    "core/database/models.py",
    "core/database/connection.py",
    "core/database/video_db.py",
    "core/database/central_db.py",
    "core/database/central_crud.py",
    "core/database/central_query.py",
    "core/database/central_backup.py",
    "algorithms/__init__.py",
    "algorithms/base.py",
    "algorithms/registry.py",
    "algorithms/model_adapter.py",
    "algorithms/weight_manager.py",
    "algorithms/online_learner.py",
    "algorithms/causal_inference.py",
    "algorithms/graph_neural.py",
    "config/__init__.py",
    "utils/crypto.py",
    "utils/file_logger.py",
    "utils/ai_qa.py",
]


def _load_crypto():
    """延迟加载 cryptography，首次使用时报清晰错误。"""
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.hazmat.primitives import serialization

        return ed25519, serialization
    except ImportError:
        print("[ERROR] 需要 cryptography 库: pip install cryptography")
        sys.exit(1)


def generate_keypair():
    """生成 Ed25519 密钥对，私钥写入 KEY_FILE，返回 (private_bytes, public_bytes)。"""
    ed25519, serialization = _load_crypto()
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private_bytes, public_bytes


def load_or_create_keypair():
    """加载已有私钥，不存在则生成新的。"""
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            private_bytes = f.read()
        if len(private_bytes) != 32:
            print("[ERROR] 私钥文件损坏（应为 32 字节），请删除 scripts/.signing_key 重新生成")
            sys.exit(1)

        ed25519, serialization = _load_crypto()
        private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_bytes)
        public_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )
        return private_bytes, public_bytes, private_key
    else:
        private_bytes, public_bytes = generate_keypair()
        os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
        # 设置文件权限（仅 Windows 下也无妨）
        with open(KEY_FILE, "wb") as f:
            f.write(private_bytes)
        try:
            os.chmod(KEY_FILE, 0o600)
        except Exception:
            # os.chmod 在 Windows 上仅影响只读属性，无实际权限控制作用
            # 私钥文件已位于 scripts/ 目录，依靠目录访问控制保护即可
            pass

        ed25519, _ = _load_crypto()
        private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_bytes)
        return private_bytes, public_bytes, private_key


def compute_hashes(files: list[str]) -> dict[str, str]:
    """计算所有文件的 SHA-256 哈希。"""
    hashes = {}
    for rel_path in files:
        filepath = os.path.join(PROJECT_ROOT, rel_path)
        if not os.path.isfile(filepath):
            print(f"[WARN] 文件不存在，跳过: {rel_path}")
            continue
        with open(filepath, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest().upper()
        hashes[rel_path] = h
    return hashes


def canonical_json(data: dict) -> bytes:
    """生成规范 JSON（排序键、无空格），用于签名。"""
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_manifest(hashes: dict[str, str], private_key) -> str:
    """对文件哈希清单签名，返回十六进制签名字符串。"""
    payload = canonical_json(hashes)
    signature = private_key.sign(payload)
    return signature.hex()


def verify_manifest(hashes: dict[str, str], signature_hex: str, public_bytes: bytes) -> bool:
    """验证签名是否有效。"""
    ed25519, _ = _load_crypto()
    public_key = ed25519.Ed25519PublicKey.from_public_bytes(public_bytes)
    payload = canonical_json(hashes)
    try:
        signature = bytes.fromhex(signature_hex)
        public_key.verify(signature, payload)
        return True
    except Exception:
        return False


def write_manifest(hashes: dict[str, str], signature_hex: str):
    """写入签名清单文件。"""
    os.makedirs(os.path.dirname(MANIFEST_FILE), exist_ok=True)
    manifest = {
        "version": 1,
        "files": hashes,
        "signature": signature_hex,
    }
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"[OK] 签名清单已写入: {MANIFEST_FILE}")
    print(f"     已签名 {len(hashes)} 个文件")


def load_manifest() -> Optional[dict]:
    """加载签名清单。"""
    if not os.path.isfile(MANIFEST_FILE):
        return None
    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_sign():
    """签名命令：计算哈希 → 签名 → 写入清单。"""
    _, public_bytes, private_key = load_or_create_keypair()
    hashes = compute_hashes(CORE_FILES)
    if not hashes:
        print("[ERROR] 没有找到任何可签名的文件")
        sys.exit(1)
    signature = sign_manifest(hashes, private_key)
    write_manifest(hashes, signature)

    print(f"\n--- 文件清单 ({len(hashes)} 个) ---")
    for path, h in hashes.items():
        print(f"  {path}: {h}")

    print("\n--- 公钥 (嵌入 main.py 的 _SIGNING_PUBLIC_KEY) ---")
    print(f"  {public_bytes.hex().upper()}")


def cmd_init():
    """仅生成密钥对。"""
    if os.path.exists(KEY_FILE):
        print(f"[WARN] 私钥已存在: {KEY_FILE}")
        print("  如需重新生成，请先删除该文件")
        return
    private_bytes, public_bytes, _ = load_or_create_keypair()
    print("[OK] 密钥对已生成")
    print(f"  私钥: {KEY_FILE}")
    print("\n--- 公钥 (嵌入 main.py 的 _SIGNING_PUBLIC_KEY) ---")
    print(f"  {public_bytes.hex().upper()}")


def cmd_verify():
    """验证命令：检查签名是否有效。"""
    manifest = load_manifest()
    if not manifest:
        print("[ERROR] 未找到签名清单，请先运行 python scripts/sign.py")
        sys.exit(1)

    hashes = manifest.get("files", {})
    signature = manifest.get("signature", "")

    if not hashes or not signature:
        print("[ERROR] 清单格式错误")
        sys.exit(1)

    # 读取公钥（仅读，不创建）
    if not os.path.exists(KEY_FILE):
        print(f"[ERROR] 签名密钥文件不存在: {KEY_FILE}")
        sys.exit(1)
    _, public_bytes, _ = load_or_create_keypair()

    # 1) 验证签名
    if verify_manifest(hashes, signature, public_bytes):
        print("[OK] Ed25519 签名验证通过")
    else:
        print("[ERROR] Ed25519 签名验证失败！文件清单可能被篡改")
        sys.exit(1)

    # 2) 验证文件哈希
    current = compute_hashes(list(hashes.keys()))
    all_ok = True
    for path, expected in hashes.items():
        actual = current.get(path, "")
        if actual == expected:
            print(f"  [OK] {path}")
        elif not actual:
            print(f"  [FAIL] {path} — 文件缺失")
            all_ok = False
        else:
            print(f"  [FAIL] {path} — 哈希不匹配（预期: {expected[:8]}... 实际: {actual[:8]}...）")
            all_ok = False

    if all_ok:
        print(f"\n[OK] 所有 {len(hashes)} 个文件验证通过")
    else:
        print("\n[ERROR] 验证失败")
        sys.exit(1)


def cmd_export_pub():
    """导出公钥。"""
    _, public_bytes, _ = load_or_create_keypair()
    print(public_bytes.hex().upper())


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "--init":
            cmd_init()
        elif cmd == "--verify":
            cmd_verify()
        elif cmd == "--export-pub":
            cmd_export_pub()
        else:
            print(f"未知参数: {cmd}")
            print("用法: python scripts/sign.py [--init|--verify|--export-pub]")
            sys.exit(1)
    else:
        cmd_sign()


if __name__ == "__main__":
    main()
