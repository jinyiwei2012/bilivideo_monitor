"""安装 uni2ts 2.0.0, 解锁其硬性依赖约束 (MOIRAI 基础模型)。

用法:
    python install_uni2ts.py [版本号]     # 默认 2.0.0

为什么需要这个脚本:
    uni2ts 2.0.0 的 wheel 元数据写死了:
        torch<2.5,>=2.1
        numpy~=1.26.0
        scipy~=1.11.3
    直接 `pip install uni2ts` 会被 pip 强制把 torch/numpy/scipy 降级,
    破坏 GPU 推理 (torch 2.13 + numpy 2.2.x + scipy 1.13+ 全部不满足)。

解锁方案:
    1. `pip install --no-deps uni2ts==2.0.0`
       → 只装 uni2ts 本体, 不读取其元数据约束 (torch/numpy/scipy 保持现状)
    2. 手动安装 uni2ts 的运行时依赖 (去掉 torch/numpy/scipy 三个冲突项,
       其余保持 uni2ts 声明的版本)
    3. 自检: import uni2ts.model.moirai, 验证可加载

注意:
    - 需先执行 install_torch.py (GPU torch) + pip install -r requirements.txt
    - 若 torch 版本 < 2.6, 旧版 torch.load 行为兼容性更好; torch 2.13 下
      MOIRAI 通过 safetensors 加载权重, 不受 weights_only 变更影响
"""
from __future__ import annotations

import subprocess
import sys

UNI2TS_VERSION = "2.0.0"
GLUONTS_PIN = "gluonts==0.14.4"

# uni2ts 2.0.0 的运行时依赖 (保留原版本约束, 剔除与 torch/numpy/scipy 冲突的项)
# 剔除项: torch, numpy, scipy, huggingface-hub(requirements 已有), safetensors(transformers 依赖),
#         lightning(requirements 已有), gluonts(见下方单独 --no-deps 安装)
# gluonts 0.14.4 额外硬钉 numpy~=1.16 + pandas<2.2.0, 会让 pip 把 numpy/pandas
# 降回 1.x 时代 → 必须 --no-deps 安装, 否则触发 numpy 二进制不兼容崩溃
UNI2TS_DEPS = [
    "datasets~=2.17.1",
    "einops==0.7.*",
    "jaxtyping~=0.2.24",
    "hydra-core==1.3",
    "orjson",
    "python-dotenv==1.0.0",
    "tensorboard",
    "multiprocess",
    "jax[cpu]",
]

PYPI_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"


def run(cmd: list[str]) -> bool:
    print(f"\n>>> {' '.join(cmd)}\n")
    try:
        subprocess.run(cmd, check=True)
        return True
    except (subprocess.CalledProcessError, KeyboardInterrupt) as e:
        print(f"\n执行失败: {e}")
        return False


def check_imports() -> bool:
    """验证 uni2ts 关键模块可导入。"""
    code = (
        "try:\n"
        "    from uni2ts.model.moirai import MoiraiModule\n"
        "    from uni2ts.model.moirai_moe import MoiraiMoEModule\n"
        "    print('OK: uni2ts', end=' ')\n"
        "    import uni2ts\n"
        "    print(uni2ts.__version__ if hasattr(uni2ts, '__version__') else '')\n"
        "except Exception as e:\n"
        "    print('FAIL:', type(e).__name__, e)\n"
        "    raise SystemExit(1)\n"
    )
    return subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def check_torch() -> None:
    """检查 torch 是否可用及其 CUDA/版本状态, 仅提示不中断。"""
    code = (
        "import sys\n"
        "try:\n"
        "    import torch\n"
        "    print(f'torch {torch.__version__} cuda={torch.cuda.is_available()}')\n"
        "except Exception as e:\n"
        "    print('torch 未安装或不可用:', e)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=False)


def ensure_numpy_pandas() -> bool:
    """确保 numpy>=2.2 且 pandas>=2.2 (gluonts 的旧钉可能把两者降回 1.x)。"""
    code = (
        "import sys\n"
        "import numpy, pandas\n"
        "ok = True\n"
        "if tuple(map(int, numpy.__version__.split('.')[:2])) < (2, 2):\n"
        "    print('numpy 过低:', numpy.__version__); ok = False\n"
        "if tuple(map(int, pandas.__version__.split('.')[:2])) < (2, 2):\n"
        "    print('pandas 过低:', pandas.__version__); ok = False\n"
        "if ok:\n"
        "    print('numpy', numpy.__version__, '/ pandas', pandas.__version__, 'OK')\n"
        "sys.exit(0 if ok else 1)\n"
    )
    ret = subprocess.run([sys.executable, "-c", code], check=False).returncode
    if ret == 0:
        return True
    print("检测到 numpy/pandas 被降级 → 用 --no-deps 恢复到 requirements 要求的版本...")
    return run(
        [
            sys.executable, "-m", "pip", "install",
            "numpy>=2.2.0,<2.3.0", "pandas>=2.2.0",
            "--no-deps",
            "--index-url", PYPI_MIRROR,
        ]
    )


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else UNI2TS_VERSION
    print("=" * 60)
    print(f"uni2ts {version} 安装器 (解锁 torch<2.5 / numpy~=1.26 / scipy~=1.11 硬约束)")
    print("=" * 60)

    check_torch()

    print(f"\n[1/4] 安装 uni2ts=={version} (--no-deps, 绕过元数据约束)")
    if not run(
        [
            sys.executable, "-m", "pip", "install",
            f"uni2ts=={version}",
            "--no-deps",
            "--index-url", PYPI_MIRROR,
        ]
    ):
        return 1

    print("\n[2/4] 安装 uni2ts 运行时依赖 (torch/numpy/scipy 保持不变)")
    if not run(
        [
            sys.executable, "-m", "pip", "install",
            *UNI2TS_DEPS,
            "--index-url", PYPI_MIRROR,
        ]
    ):
        return 1

    print(f"\n[2.5/4] 安装 gluonts=={GLUONTS_PIN} (--no-deps, 解锁 numpy~=1.16 + pandas<2.2 钉)")
    if not run(
        [
            sys.executable, "-m", "pip", "install",
            GLUONTS_PIN,
            "--no-deps",
            "--index-url", PYPI_MIRROR,
        ]
    ):
        return 1

    print("\n[3/4] 校验/恢复 numpy>=2.2 + pandas>=2.2 (防止被 gluonts 旧钉拖回 1.x)")
    if not ensure_numpy_pandas():
        return 1

    print("\n[4/4] 自检: import uni2ts.model.moirai")
    if check_imports():
        print("\n✅ uni2ts 安装成功, MOIRAI torch 推理可用。")
        return 0
    print("\n⚠️ uni2ts 已安装但导入失败, 应用会降级到 numpy 路径 (不影响其他功能)。")
    print("   可手动补装缺失依赖: pip install jax[cpu] einops datasets gluonts jaxtyping")
    return 1


if __name__ == "__main__":
    sys.exit(main())
