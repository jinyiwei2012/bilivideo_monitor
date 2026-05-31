"""
更新 main.py 中的源文件完整性哈希列表。
在发布前运行此脚本，确保 _INTEGRITY_HASHES 包含最新的 SHA-256 哈希。
"""

import hashlib
import os
import re

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 需要校验的核心文件（相对于项目根目录）
CORE_FILES = [
    "main.py",
    "core/bilibili_api.py",
    "algorithms/registry.py",
    "algorithms/base.py",
    "core/notification.py",
]


def compute_hashes() -> dict[str, str]:
    hashes = {}
    for rel_path in CORE_FILES:
        filepath = os.path.join(PROJECT_ROOT, rel_path)
        if os.path.isfile(filepath):
            with open(filepath, "rb") as f:
                h = hashlib.sha256(f.read()).hexdigest().upper()
            hashes[rel_path] = h
        else:
            print(f"⚠ 文件不存在: {rel_path}")
    return hashes


def update_main_py(hashes: dict[str, str]) -> None:
    main_py = os.path.join(PROJECT_ROOT, "main.py")
    with open(main_py, "r", encoding="utf-8") as f:
        content = f.read()

    items = ",\n".join(f'    "{k}": "{v}"' for k, v in hashes.items())
    new_block = f"_INTEGRITY_HASHES: dict[str, str] = {{\n{items},\n}}"

    pattern = r"_INTEGRITY_HASHES: dict\[str, str\] = \{[^}]+\}"
    if re.search(pattern, content):
        content = re.sub(pattern, new_block, content)
    else:
        print("⚠ 未找到 _INTEGRITY_HASHES 占位，请手动更新")

    with open(main_py, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"✅ 已更新 {len(hashes)} 个文件哈希到 main.py")


if __name__ == "__main__":
    hashes = compute_hashes()
    if hashes:
        update_main_py(hashes)
        for k, v in hashes.items():
            print(f"  {k}: {v}")
