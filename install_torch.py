#!/usr/bin/env python
"""install_torch.py — 自动检测系统 CUDA 版本并安装匹配的 PyTorch。

用法:
    python install_torch.py           # 自动选 GPU/CPU
    python install_torch.py --cpu     # 强制 CPU 版
    python install_torch.py --dry-run # 只打印决定，不实际安装

逻辑:
    1. nvidia-smi 拿驱动支持的 CUDA 版本（如 "13.2"）
    2. 按系统 CUDA 选最高可用的 PyTorch wheel（cu128 / cu126 / cu124 / cu121 / cu118）
    3. pip install --index-url <选定 URL> torch
    4. GPU 安装失败 → 回退 CPU
    5. 验证 import torch; torch.cuda.is_available()
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from typing import Optional

# PyTorch 当前提供的 CUDA wheel 索引，按 CUDA 版本从高到低
# 每项: (CUDA 版本元组, 标签, URL)
CUDA_WHEELS = [
    ((12, 8), "CUDA 12.8 (cu128)", "https://download.pytorch.org/whl/cu128"),
    ((12, 6), "CUDA 12.6 (cu126)", "https://download.pytorch.org/whl/cu126"),
    ((12, 4), "CUDA 12.4 (cu124)", "https://download.pytorch.org/whl/cu124"),
    ((12, 1), "CUDA 12.1 (cu121)", "https://download.pytorch.org/whl/cu121"),
    ((11, 8), "CUDA 11.8 (cu118)", "https://download.pytorch.org/whl/cu118"),
]
CPU_LABEL = "CPU only"
CPU_URL = "https://download.pytorch.org/whl/cpu"
TORCH_SPEC = "torch>=2.1.0"


def detect_cuda() -> Optional[tuple[int, int]]:
    """跑 nvidia-smi 取驱动支持的最高 CUDA 版本。返回 (major, minor) 或 None。"""
    try:
        out = subprocess.check_output(
            ["nvidia-smi"], encoding="utf-8", stderr=subprocess.STDOUT, timeout=10
        )
    except (FileNotFoundError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", out)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def pick_index(cuda: Optional[tuple[int, int]]) -> tuple[str, str]:
    """根据驱动 CUDA 选 PyTorch wheel 索引。返回 (label, url)。"""
    if cuda is None:
        return CPU_LABEL, CPU_URL
    for required, label, url in CUDA_WHEELS:
        if cuda >= required:
            return label, url
    return CPU_LABEL, CPU_URL


def pip_install(label: str, url: str, dry_run: bool) -> bool:
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", TORCH_SPEC, "--index-url", url]
    print(f"\n[install_torch] → 准备安装 {label}")
    print(f"[install_torch] $ {' '.join(cmd)}")
    if dry_run:
        print("[install_torch] --dry-run 已开启，跳过实际安装")
        return True
    r = subprocess.run(cmd)
    return r.returncode == 0


def verify() -> bool:
    """import torch 检查版本和 CUDA 可用性。"""
    code = (
        "import torch; "
        "print('torch', torch.__version__); "
        "print('CUDA available:', torch.cuda.is_available()); "
        "print('Device count:', torch.cuda.device_count()); "
        "import sys; "
        "[print('Device', i, torch.cuda.get_device_name(i)) for i in range(torch.cuda.device_count())]"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        print(f"[install_torch] ❌ 验证失败:\n{r.stderr}")
        return False
    print("[install_torch] ✅ 验证通过:")
    for line in r.stdout.strip().splitlines():
        print(f"    {line}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cpu", action="store_true", help="强制安装 CPU 版（跳过 CUDA 检测）")
    ap.add_argument("--dry-run", action="store_true", help="只打印决定，不实际安装")
    args = ap.parse_args()

    if args.cpu:
        cuda = None
        print("[install_torch] --cpu 已指定，跳过 CUDA 检测")
    else:
        cuda = detect_cuda()
        if cuda:
            print(f"[install_torch] 检测到驱动支持的 CUDA: {cuda[0]}.{cuda[1]}")
        else:
            print("[install_torch] 未检测到 NVIDIA GPU 或 nvidia-smi 不可用")

    label, url = pick_index(cuda)

    # 主尝试
    ok = pip_install(label, url, args.dry_run)

    # GPU 失败 → CPU 回退
    if not ok and label != CPU_LABEL:
        print(f"\n[install_torch] ⚠️ {label} 安装失败，回退到 {CPU_LABEL}")
        ok = pip_install(CPU_LABEL, CPU_URL, args.dry_run)

    if not ok:
        print("[install_torch] ❌ 全部安装路径失败")
        return 1

    if args.dry_run:
        return 0

    if not verify():
        return 2

    print("\n[install_torch] 🎉 完成。下一步：pip install -r requirements.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
