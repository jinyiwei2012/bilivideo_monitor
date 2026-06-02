"""
更新 main.py 中的源文件完整性哈希列表。

在发布前运行此脚本，确保 _INTEGRITY_HASHES 包含最新的 SHA-256 哈希。

用途：
- 计算 CORE_FILES 中列出的所有核心源文件的 SHA-256 哈希
- 自动更新 main.py 中的 _INTEGRITY_HASHES 字典
- 用于启动时源码完整性校验，防止核心文件被篡改

运行方式：
    python scripts/update_hashes.py
"""

import hashlib
import os
import re

# 项目根目录（scripts/ 的上一级）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 需要校验的核心文件（相对于项目根目录）
# 这些文件是系统的核心组件，启动时会校验其完整性
CORE_FILES = [
    "main.py",
    "core/bilibili_api.py",
    "algorithms/registry.py",
    "algorithms/base.py",
    "core/notification.py",
]


def compute_hashes() -> dict[str, str]:
    """
    计算所有核心文件的 SHA-256 哈希值。
    
    遍历 CORE_FILES 列表，对存在的文件计算哈希，不存在的文件打印警告并跳过。
    哈希值以大写十六进制字符串表示。
    
    Returns:
        dict[str, str]: {相对路径: SHA-256 哈希值} 的字典
    """
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
    """
    用新的哈希列表替换 main.py 中的 _INTEGRITY_HASHES。
    
    通过正则表达式匹配 main.py 中的 _INTEGRITY_HASHES 定义块，
    将其替换为更新后的哈希字典。
    如果未找到匹配模式，则提示手动更新。
    
    Args:
        hashes: 由 compute_hashes() 返回的哈希字典
    """
    main_py = os.path.join(PROJECT_ROOT, "main.py")
    with open(main_py, "r", encoding="utf-8") as f:
        content = f.read()

    # 构造新的哈希字典文本
    items = ",\n".join(f'    "{k}": "{v}"' for k, v in hashes.items())
    new_block = f"_INTEGRITY_HASHES: dict[str, str] = {{\n{items},\n}}"

    # 用正则匹配并替换原有定义
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
