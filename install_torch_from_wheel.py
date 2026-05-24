"""install_torch_from_wheel.py — 从已下载的 .whl 文件直接解压安装 torch，不用 pip。

实现 PEP 427 wheel 安装的最小子集：
  1. 校验文件存在 + 大小
  2. zipfile.extractall 到 site-packages
  3. 处理 .data/scripts/ 目录（脚本拷到 Scripts/ 目录，如 torchrun）
  4. 写 INSTALLER 标记（让以后 pip 知道是哪个工具装的）
  5. import 验证 + CUDA 可用性检查

依赖（filelock / typing_extensions / sympy / networkx / jinja2 / fsspec / mpmath）
必须已经装好；本脚本不处理它们。
"""

from __future__ import annotations

import argparse
import importlib
import shutil
import site
import sys
import sysconfig
import zipfile
from pathlib import Path


def install_wheel(wheel_path: Path) -> Path:
    """解压 wheel 到 site-packages，返回 dist-info 目录路径。"""
    site_pkgs = Path(site.getsitepackages()[0])
    print(f"[install] site-packages → {site_pkgs}")

    if not wheel_path.exists():
        sys.exit(f"[install] ❌ 找不到 wheel: {wheel_path}")
    size_gb = wheel_path.stat().st_size / 1024**3
    print(f"[install] wheel size: {size_gb:.2f} GB")

    # 解压到 site-packages，.data/ 目录另外处理
    dist_info_dir: Path | None = None
    scripts_dest = Path(sysconfig.get_path("scripts"))

    with zipfile.ZipFile(wheel_path) as z:
        names = z.namelist()
        print(f"[install] 文件数: {len(names)}")

        # 找 .dist-info 目录名
        for n in names:
            parts = n.split("/", 1)
            if parts[0].endswith(".dist-info"):
                dist_info_dir = site_pkgs / parts[0]
                break

        # 实际解压
        for i, n in enumerate(names):
            # .data/scripts/ 走 Scripts 目录，其它走 site-packages
            parts = n.split("/", 2)
            if len(parts) >= 3 and parts[0].endswith(".data") and parts[1] == "scripts":
                target = scripts_dest / parts[2]
            elif len(parts) >= 2 and parts[0].endswith(".data"):
                # 其它 .data 子目录（headers/data/purelib/platlib）— torch 通常没有
                # 简单处理：直接放 site-packages
                target = site_pkgs / parts[1]
            else:
                target = site_pkgs / n

            if n.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)

            if (i + 1) % 1000 == 0:
                print(f"[install]   {i + 1}/{len(names)} ...")

    print(f"[install] ✅ 解压完成 → {site_pkgs}")
    return dist_info_dir if dist_info_dir else site_pkgs


def write_installer_marker(dist_info_dir: Path) -> None:
    """在 .dist-info 里写 INSTALLER 文件标识。"""
    if dist_info_dir.exists():
        (dist_info_dir / "INSTALLER").write_text("install_torch_from_wheel\n", encoding="utf-8")
        print(f"[install] 写 INSTALLER 标记 → {dist_info_dir / 'INSTALLER'}")


def verify() -> bool:
    importlib.invalidate_caches()
    code = (
        "import torch;"
        "print('torch', torch.__version__);"
        "print('CUDA available:', torch.cuda.is_available());"
        "print('Device count:', torch.cuda.device_count());"
        "[print('Device', i, torch.cuda.get_device_name(i)) for i in range(torch.cuda.device_count())]"
    )
    import subprocess

    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print(f"[install] ❌ 验证失败:\n{r.stderr}")
        return False
    print("[install] ✅ 验证通过:")
    for line in r.stdout.strip().splitlines():
        print(f"    {line}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "wheel",
        nargs="?",
        default="_wheels/torch-2.11.0+cu128-cp312-cp312-win_amd64.whl",
        help="本地 wheel 文件路径",
    )
    args = ap.parse_args()

    dist_info = install_wheel(Path(args.wheel))
    write_installer_marker(dist_info)

    if not verify():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
