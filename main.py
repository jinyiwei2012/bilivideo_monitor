"""
B站视频监控与播放量预测系统
主入口文件
"""

import os
import sys

# ── 内存优化：在加载任何重型模块之前设置 ──────────
# 减少 glibc malloc arena 膨胀，避免长期运行 RSS 线性增长
os.environ.setdefault("PYTHONMALLOC", "malloc")
os.environ.setdefault("MALLOC_ARENA_MAX", "2")

import hashlib
import json
import logging

logger = logging.getLogger(__name__)

# 添加项目根目录到Python路径（兼容 PyInstaller 打包）
if getattr(sys, "frozen", False):
    project_root = os.path.dirname(sys.executable)
else:
    project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


# ── 源码完整性校验 ──────────────────────────
# 两层校验机制（由强到弱自动回退）：
#   第1层 Ed25519 签名清单 → data/integrity_manifest.json（公钥嵌入下方常量）
#   第2层 嵌入式哈希回退 → _INTEGRITY_HASHES（向后兼容，无 cryptography 时使用）
#
# 校验在 from ui import main 之前执行，防止篡改代码先于检查加载。
# 开发时创建 .devmode 文件（内容 SHA-256 须匹配 _DEVMODE_HASH）可跳过校验。
# main.py 自身不参与校验（SHA256(self)=H 数学上不可解），信任根由以下保证：
#   - Ed25519 公钥嵌入本文件（篡改者需同时持有私钥才能伪造签名）
#   - 打包发布时建议 PyInstaller .spec 嵌入签名清单 + 公钥到二进制

# Ed25519 公钥（由 scripts/sign.py 生成，发布前更新）
_SIGNING_PUBLIC_KEY = "E7356306F6472CC113456BD5DC75E605486835A71FB7C109E4E718C286D29F65"

# 嵌入式哈希回退列表（向后兼容，手动维护或通过 scripts/update_hashes.py 更新）
_INTEGRITY_HASHES: dict[str, str] = {
    "core/bilibili_api.py": "5849EB9ED6B63894CC64DFDB49B805E46F2A1B83C165DD11F92BC7BC18B802A4",
    "algorithms/registry.py": "FC286B0791E251D2011E70EDF89EE9AE8307FFE52244D8E6E20544F9AF85CBC3",
    "algorithms/base.py": "F746D8E7A74B2E8A8AE704B1CD37CB2BD83F8A05AF82E343DAB14D0B5E6666C3",
    "core/notification.py": "48A1C7C69D41F8F7CB1DF2F12B3F928000C996E5F8957A20D9B88F2C185FF08C",
}

# .devmode 文件内容的期望 SHA-256（去除首尾空白后）
_DEVMODE_HASH = "40175C25B9517A906FCF778E50387017BB8FA6121D28EBD0720474E85EE7ECA8"


def _verify_devmode() -> bool:
    """校验 .devmode 文件是否存在且内容哈希匹配。"""
    devmode = os.path.join(project_root, ".devmode")
    devmode2 = os.path.join(project_root, "devmode")
    for path in (devmode, devmode2):
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                h = hashlib.sha256(content.encode()).hexdigest().upper()
                if h == _DEVMODE_HASH:
                    return True
            except Exception as e:
                logger.debug("读取 .devmode 文件失败 (%s): %s", path, e)
    return False


def _verify_file_hashes(hashes: dict[str, str]) -> None:
    """验证文件哈希是否匹配，不匹配则抛出 RuntimeError。"""
    for rel_path, expected_hash in hashes.items():
        filepath = os.path.join(project_root, rel_path)
        if not os.path.isfile(filepath):
            raise RuntimeError(
                f"文件缺失: {rel_path}\n\n"
                f"请执行 git restore 还原源文件，或创建 .devmode 文件跳过校验。\n"
                f"参考 README.md 文件"
            )
        with open(filepath, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest().upper()
        if actual_hash != expected_hash:
            raise RuntimeError(
                f"文件已被篡改: {rel_path}\n"
                f"  预期: {expected_hash}\n"
                f"  实际: {actual_hash}\n\n"
                f"请执行 git restore 还原源文件，或创建 .devmode 文件跳过校验。\n"
                f"参考 README.md 文件"
            )


def _verify_ed25519_signature(hashes: dict, signature_hex: str) -> bool:
    """使用 Ed25519 公钥验证文件哈希清单的签名。

    返回 True 表示签名有效，False 表示签名无效或 cryptography 不可用。
    """
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError:
        logger.debug("cryptography 未安装，跳过 Ed25519 签名验证")
        return False

    try:
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(_SIGNING_PUBLIC_KEY))
        payload = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = bytes.fromhex(signature_hex)
        public_key.verify(signature, payload)
        return True
    except Exception as e:
        logger.debug("Ed25519 签名验证失败: %s", e)
        return False


def _verify_signed_manifest() -> bool:
    """尝试加载并验证 Ed25519 签名清单。

    返回 True 表示签名清单存在、签名有效、且所有文件哈希匹配。
    返回 False 表示清单不存在或签名无效（触发回退到嵌入式哈希）。
    文件缺失或哈希不匹配时抛出 RuntimeError（与嵌入式哈希行为一致）。
    """
    manifest_path = os.path.join(project_root, "data", "integrity_manifest.json")
    if not os.path.isfile(manifest_path):
        logger.debug("签名清单不存在，回退到嵌入式哈希验证")
        return False

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        logger.debug("读取签名清单失败: %s", e)
        return False

    files = manifest.get("files", {})
    signature = manifest.get("signature", "")
    if not files or not signature:
        logger.debug("签名清单格式无效")
        return False

    # 1) 验证 Ed25519 签名
    if not _verify_ed25519_signature(files, signature):
        logger.warning("Ed25519 签名验证失败！签名清单可能被篡改，回退到嵌入式哈希")
        return False

    # 2) 验证每个文件的哈希
    _verify_file_hashes(files)

    logger.debug("Ed25519 签名清单验证通过 (%d 个文件)", len(files))
    return True


def _verify_source_integrity() -> None:
    """校验核心源文件完整性（两层回退）。

    1. 优先使用 Ed25519 签名清单验证
    2. 回退到嵌入式 _INTEGRITY_HASHES 验证
    3. 开发模式（.devmode）或打包模式（frozen）跳过所有校验
    """
    if getattr(sys, "frozen", False):
        return
    if _verify_devmode():
        return

    # 第1层：Ed25519 签名清单（最强防护）
    if _verify_signed_manifest():
        return

    # 第2层：嵌入式哈希回退（向后兼容）
    if not _INTEGRITY_HASHES:
        return
    _verify_file_hashes(_INTEGRITY_HASHES)


_verify_source_integrity()

# ── GC 调参：长运行桌面应用，减少 GC 检查频率避免随机卡顿 ──
import gc
gc.set_threshold(50000, 20, 20)  # 默认 (700,10,10)，减少 ~70x 扫描频率

# ── 内存追踪：长期运行中检测泄漏 ──
import tracemalloc
tracemalloc.start(1)  # 1 帧深度，开销 <5%，生产级可用
_last_tracemalloc_snap = None  # 模块级，供定期对比使用

from ui import main

if __name__ == "__main__":
    """主入口 — 启动 GUI 程序"""
    main()
