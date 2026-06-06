"""
更新 main.py 中的源文件完整性哈希列表，并重新签名。

在发布前运行此脚本：
    1. 计算核心文件的 SHA-256 哈希
    2. 更新 main.py 中的 _INTEGRITY_HASHES（嵌入式回退列表）
    3. 调用 scripts/sign.py 重新签名（Ed25519 签名清单）

用法:
    python scripts/update_hashes.py              # 全部更新
    python scripts/update_hashes.py --hashes-only # 仅更新嵌入式哈希，不重新签名
"""

import hashlib
import os
import re
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 嵌入式回退的少量核心文件（与 sign.py 的 CORE_FILES 子集对应）
EMBEDDED_FILES = [
    "core/bilibili_api.py",
    "algorithms/registry.py",
    "algorithms/base.py",
    "core/notification.py",
]


def compute_hashes(files: list[str]) -> dict[str, str]:
    """计算文件的 SHA-256 哈希值"""
    hashes = {}
    for rel_path in files:
        filepath = os.path.join(PROJECT_ROOT, rel_path)
        if os.path.isfile(filepath):
            with open(filepath, "rb") as f:
                h = hashlib.sha256(f.read()).hexdigest().upper()
            hashes[rel_path] = h
        else:
            print(f"[WARN] 文件不存在: {rel_path}")
    return hashes


def update_main_py(hashes: dict[str, str]) -> None:
    """用新的哈希列表替换 main.py 中的 _INTEGRITY_HASHES"""
    main_py = os.path.join(PROJECT_ROOT, "main.py")
    with open(main_py, "r", encoding="utf-8") as f:
        content = f.read()

    items = ",\n".join(f'    "{k}": "{v}"' for k, v in hashes.items())
    new_block = f"_INTEGRITY_HASHES: dict[str, str] = {{\n{items},\n}}"

    pattern = r"_INTEGRITY_HASHES: dict\[str, str\] = \{[^}]+\}"
    if re.search(pattern, content):
        content = re.sub(pattern, new_block, content)
    else:
        print("[WARN] 未找到 _INTEGRITY_HASHES，请手动更新")
        return

    with open(main_py, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[OK] 已更新 {len(hashes)} 个嵌入式哈希到 main.py")


def run_sign() -> bool:
    """调用 sign.py 重新签名清单"""
    sign_script = os.path.join(os.path.dirname(__file__), "sign.py")
    if not os.path.isfile(sign_script):
        print("[WARN] sign.py 不存在，跳过签名")
        return False
    try:
        result = subprocess.run(
            [sys.executable, sign_script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        print(result.stdout)
        if result.returncode != 0:
            print(result.stderr)
            return False
        return True
    except subprocess.TimeoutExpired:
        print("[ERROR] 签名超时")
        return False
    except Exception as e:
        print(f"[ERROR] 签名失败: {e}")
        return False


def main():
    hashes_only = "--hashes-only" in sys.argv

    # 1. 更新嵌入式哈希
    hashes = compute_hashes(EMBEDDED_FILES)
    if hashes:
        update_main_py(hashes)
        for k, v in hashes.items():
            print(f"  {k}: {v}")

    if hashes_only:
        print("\n[OK] 嵌入式哈希已更新（跳过签名）。")
        print("提示: 运行 python scripts/sign.py 更新 Ed25519 签名清单。")
        return

    # 2. 重新签名
    print("\n--- 重新签名 ---")
    if run_sign():
        print("\n[OK] 哈希 + 签名已全部更新。")
    else:
        print("\n[WARN] 签名失败，但嵌入式哈希已更新。")


if __name__ == "__main__":
    main()
