"""安装 GPU 版 PyTorch (镜像加速)。

用法:
    python install_torch.py

流程:
  1. 调 nvidia-smi 检测驱动支持的 CUDA 版本
  2. 按驱动版本选择 PyTorch CUDA wheel (cu118 / cu121 / cu124 / cu126 / cu128)
  3. 已安装可用 GPU torch 时跳过
  4. 无 GPU 或检测失败 → 安装 CPU 版
  5. 安装后验证 torch.cuda.is_available()
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

# 可用 CUDA wheel 版本, 按驱动兼容性从新到旧选择
CUDA_WHEELS = ["cu128", "cu126", "cu124", "cu121", "cu118"]

# PyTorch wheel 镜像 (优先使用, 均与官方 download.pytorch.org/whl 结构一致)
TORCH_MIRRORS = [
    "https://mirrors.nju.edu.cn/pytorch/whl",
    "https://mirrors.tuna.tsinghua.edu.cn/pytorch-wheels",
    "https://download.pytorch.org/whl",
]

# PyPI 镜像 (用于 nvidia-* 等辅助包)
PYPI_MIRRORS = [
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple",
]


@dataclass
class CudaInfo:
    driver_supports: tuple[int, int] | None  # (major, minor) 驱动支持的最高 CUDA
    gpu_name: str | None


def detect_cuda() -> CudaInfo:
    """通过 nvidia-smi 检测 GPU 与驱动支持的 CUDA 版本。"""
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return CudaInfo(None, None)
    try:
        out = subprocess.run(
            [nvidia_smi], capture_output=True, text=True, timeout=30
        ).stdout
    except Exception:
        return CudaInfo(None, None)

    gpu = None
    cuda = None
    for line in out.splitlines():
        if "NVIDIA-SMI" in line or "CUDA Version" in line:
            m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", line)
            if m:
                cuda = (int(m.group(1)), int(m.group(2)))
        if gpu is None and "GeForce" in line or "NVIDIA" in line and "NVIDIA-SMI" not in line:
            m = re.search(r"(NVIDIA [A-Za-z0-9 \-]+(?:GPU)?)", line)
            if m:
                gpu = m.group(1).strip()
    # 第一行一般是驱动名, 最后匹配到的 GPU 型号最可靠
    if gpu is None:
        for line in out.splitlines():
            if "NVIDIA" in line and "CUDA" not in line and "Graphics" not in line:
                gpu = line.strip()
                break
    return CudaInfo(cuda, gpu)


def pick_wheel(cuda: tuple[int, int] | None) -> str | None:
    """根据驱动支持的 CUDA 版本挑选 wheel。返回 None 表示装 CPU 版。"""
    if cuda is None:
        return None
    major, minor = cuda
    # 驱动向后兼容: 支持的 CUDA >= wheel 需要的 CUDA 即可
    for wheel in CUDA_WHEELS:
        w_major, w_minor = int(wheel[2]), int(wheel[3:])
        if (major, minor) >= (w_major, w_minor):
            return wheel
    return None


def run_pip(args: list[str]) -> bool:
    cmd = [sys.executable, "-m", "pip", *args]
    print(f"\n>>> {' '.join(cmd)}\n")
    try:
        subprocess.run(cmd, check=False)
        return True
    except KeyboardInterrupt:
        print("\n安装被中断。")
        return False


def torch_usable() -> bool:
    """检查已安装的 torch 是否可用 (含 CUDA)。"""
    try:
        code = (
            "import torch;"
            "print('torch', torch.__version__);"
            "print('cuda_available', torch.cuda.is_available());"
            "print('gpu', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
        )
        if out.returncode != 0:
            return False
        print(out.stdout.strip())
        return "cuda_available True" in out.stdout
    except Exception:
        return False


def install_from(mirror: str, wheel: str, packages: list[str]) -> bool:
    """从指定镜像安装, 失败时回退 --no-deps (应对 uni2ts 等包的 torch 元数据拦截)。"""
    index = f"{mirror}/{wheel}"
    if run_pip(["install", *packages, "--index-url", index, "--extra-index-url", PYPI_MIRRORS[0]]):
        return True
    print(f"  常规安装失败 (可能被已装包的元数据拦截), 尝试 --no-deps ...")
    return run_pip(["install", *packages, "--no-deps", "--index-url", index])


def main() -> int:
    print("=" * 60)
    print("PyTorch 安装器 (镜像加速)")
    print("=" * 60)

    info = detect_cuda()
    if info.gpu_name:
        print(f"检测到 GPU: {info.gpu_name}")
    if info.driver_supports:
        print(f"驱动支持 CUDA: {info.driver_supports[0]}.{info.driver_supports[1]}")
    else:
        print("未检测到 NVIDIA GPU 或 nvidia-smi 不可用 → 将安装 CPU 版")

    if torch_usable():
        print("\n已存在可用的 GPU torch, 跳过安装。")
        return 0

    wheel = pick_wheel(info.driver_supports) if info.driver_supports else None

    if wheel is None:
        print("\n[方案] 安装 CPU 版 torch")
        for mirror in TORCH_MIRRORS:
            if install_from(mirror, "cpu", ["torch", "torchvision", "torchaudio"]):
                break
        else:
            print("CPU 版安装失败, 请检查网络。")
            return 1
    else:
        print(f"\n[方案] 安装 GPU 版 torch ({wheel})")
        installed = False
        for mirror in TORCH_MIRRORS:
            if install_from(mirror, wheel, ["torch", "torchvision", "torchaudio"]):
                installed = True
                break
        if not installed:
            print("GPU 版安装失败, 尝试回退 CPU 版...")
            for mirror in TORCH_MIRRORS:
                if run_pip(["install", "torch", "--index-url", f"{mirror}/cpu"]):
                    break

    if torch_usable():
        print("\n✅ PyTorch 安装完成, CUDA 可用。")
        return 0
    print("\n⚠️ torch 已安装但 CUDA 不可用 (可能是 CPU 版)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
