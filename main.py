"""
B站视频监控与播放量预测系统
主入口文件
"""

import sys
import os
import hashlib

# 添加项目根目录到Python路径（兼容 PyInstaller 打包）
if getattr(sys, "frozen", False):
    project_root = os.path.dirname(sys.executable)
else:
    project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ui import main


# ── 源码完整性校验 ──────────────────────────
# SHA-256 哈希列表，在发布前通过 python scripts/update_hashes.py 更新
# 开发时创建 .devmode 文件（内容 SHA-256 须匹配 _DEVMODE_HASH）可跳过校验
_INTEGRITY_HASHES: dict[str, str] = {
    "main.py": "E6D6FF21709DD30514F0425876AC248534811BD8BD5A6F86ED52AA90FD6C6C2F",
    "core/bilibili_api.py": "53E89671FF3024E282C6CECB8A0D2D0B714D9949E4788EAE7A1973D6718D4BA6",
    "algorithms/registry.py": "69E9982411ED9A4DEF95B6C2C197B9EB42FD28775763550258D32B4D446EA77E",
    "algorithms/base.py": "C93D499D9BAF3C1A74C5BBF489F3221BA1EF63368561FEF851143D895F959258",
    "core/notification.py": "8B48903EDDFE10483486B741422913EA9CB6B4A77BE8885D1937DA4B16CB88BA",
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
            except Exception:
                pass
    return False


def _verify_source_integrity() -> None:
    """使用 SHA-256 校验核心源文件完整性。

    开发环境（_verify_devmode 通过 或 frozen 打包）跳过校验。
    哈希不匹配时给出清晰的错误指引。
    """
    if getattr(sys, "frozen", False):
        return
    if _verify_devmode():
        return
    if not _INTEGRITY_HASHES:
        return

    for rel_path, expected_hash in _INTEGRITY_HASHES.items():
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


_verify_source_integrity()

if __name__ == "__main__":
    main()
