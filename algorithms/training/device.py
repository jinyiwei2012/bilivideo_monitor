"""GPU / NPU 自动检测模块
=======================

自动检测可用的计算硬件加速器（GPU/NPU），为 PyTorch 训练提供统一的设备接口。

支持的加速后端：
- **CUDA**:          NVIDIA GPU（需安装 CUDA 版 PyTorch）
- **DirectML**:      Windows 平台 GPU/NPU（Intel/AMD），通过 torch-directml 包
- **Intel XPU**:     Linux 平台 Intel GPU/NPU（需 intel-extension-for-pytorch）
- **Apple MPS**:     macOS Apple Silicon 的 Metal Performance Shaders 加速
- **CPU**:          高性能 CPU 降级回退

后端探测优先级：
    cuda > DirectML > XPU (IPEX) > MPS > CPU

支持的特性：
- 懒加载 PyTorch（避免拖慢应用启动）
- 冒烟测试验证加速器可用性
- 全局强制 CPU 开关（UI 可控制）
- 设备详情查询（名称、显存、类型）

公开 API：
---------
    is_torch_available()   — PyTorch 是否已安装
    get_device()           — 返回最优 torch.device；PyTorch 未装时返回 None
    get_device_info()      — 返回设备详情字典 {device, name, total_memory_gb, is_gpu}
    force_cpu(flag)        — 强制使用 CPU（设置后 get_device() 永远返回 cpu）

NPU (Intel AI Boost) 支持：
--------------------------
- **Windows**: pip install torch-directml --pre
- **Linux**:   pip install intel-extension-for-pytorch
"""

import os
import logging
from typing import Optional, Dict, Any

# 模块级日志记录器
logger = logging.getLogger(__name__)

# ── 全局状态变量 ─────────────────────────────────────
_torch = None           # PyTorch 模块引用（懒加载后缓存）
_torch_available = None # PyTorch 是否可用的缓存标志
_xpu_available = None   # Intel XPU 是否可用的缓存标志
_dml_available = None   # DirectML 是否可用的缓存标志
_force_cpu = False      # 是否全局强制使用 CPU


def _ensure_torch():
    """懒加载 PyTorch 并检测各种加速器后端。

    只在首次使用时才 import torch，避免拖慢应用启动。
    同时检测 cuda/directml/intel_xpu 的可用性并缓存结果。

    Returns:
        Optional[module]: PyTorch 模块，不可用时返回 None。
    """
    global _torch, _torch_available, _xpu_available, _dml_available
    if _torch_available is not None:
        return _torch
    try:
        import torch as _t

        _torch = _t
        _torch_available = True
    except ImportError:
        # PyTorch 完全不可用
        _torch_available = False
        _xpu_available = False
        _dml_available = False
        return None

    # ── 检测 Intel XPU (Linux) ────────────────────────
    _xpu_available = False
    try:
        import intel_extension_for_pytorch  # noqa: F401

        _xpu_available = True
    except ImportError:
        pass

    # ── 检测 DirectML (Windows) ───────────────────────
    _dml_available = False
    try:
        import torch_directml  # noqa: F401

        _dml_available = True
    except ImportError:
        pass
    return _torch


def is_torch_available() -> bool:
    """检查 PyTorch 是否已安装。

    Returns:
        bool: True 表示 PyTorch 可正常导入。
    """
    if _torch_available is None:
        _ensure_torch()
    return bool(_torch_available)


def force_cpu(flag: bool):
    """全局强制使用 CPU 进行计算。

    设置后 get_device() 将始终返回 CPU 设备，
    不会尝试使用任何 GPU/NPU 加速器。
    此设置不持久化，重启应用后重置。

    Args:
        flag: True 表示强制使用 CPU，False 表示恢复自动检测。
    """
    global _force_cpu
    _force_cpu = bool(flag)


def _try_cuda():
    """尝试获取 CUDA 设备并进行冒烟测试。

    冒烟测试通过 synchronize() 验证 CUDA 驱动是否正常工作。

    Returns:
        Optional[torch.device]: CUDA 设备对象，不可用时返回 None。
    """
    t = _ensure_torch()
    if t is None:
        return None
    try:
        if t.cuda.is_available():
            # 冒烟测试：强制同步验证 CUDA 堆栈完整性
            t.cuda.synchronize()
            return t.device("cuda:0")
    except Exception as e:
        logger.warning("CUDA 冒烟测试失败: %s", e)
    return None


def _try_dml():
    """尝试获取 DirectML 设备（Intel/AMD GPU/NPU on Windows）。

    需要安装 torch-directml 包（pip install torch-directml --pre）。

    Returns:
        Optional[torch.device]: DirectML 设备对象，不可用时返回 None。
    """
    t = _ensure_torch()
    if t is None or not _dml_available:
        return None
    try:
        import torch_directml
        return torch_directml.device()
    except Exception as e:
        logger.warning("DirectML 冒烟测试失败: %s", e)
    return None


def _try_xpu():
    """尝试获取 Intel XPU 设备（Linux 上的 Intel GPU/NPU）。

    需要安装 intel-extension-for-pytorch。

    Returns:
        Optional[torch.device]: Intel XPU 设备对象，不可用时返回 None。
    """
    t = _ensure_torch()
    if t is None or not _xpu_available:
        return None
    try:
        if t.xpu.is_available():
            # 冒烟测试：同步验证 XPU 运行时
            t.xpu.synchronize()
            return t.device("xpu:0")
    except Exception as e:
        logger.warning("Intel XPU 冒烟测试失败: %s", e)
    return None


def _try_mps():
    """尝试获取 Apple Silicon MPS 设备（macOS）。

    MPS（Metal Performance Shaders）是 macOS 上 Apple Silicon 的 GPU 加速方案。

    Returns:
        Optional[torch.device]: MPS 设备对象，不可用时返回 None。
    """
    t = _ensure_torch()
    if t is None:
        return None
    try:
        if hasattr(t.backends, "mps") and t.backends.mps.is_available():
            return t.device("mps")
    except Exception as e:
        logger.debug("MPS 检测异常: %s", e)
    return None


def get_device() -> Optional[Any]:
    """获取最优可用的计算设备。

    按照优先级顺序尝试：CUDA → DirectML → Intel XPU → MPS → CPU
    并考虑全局强制 CPU 开关和环境变量 CUDA_VISIBLE_DEVICES。

    Returns:
        Optional[Any]: torch.device 对象，PyTorch 未安装时返回 None。

    Note:
        - 当 CUDA_VISIBLE_DEVICES="" 时返回 CPU（明确禁用所有 CUDA 设备）。
        - 当 force_cpu(True) 被调用后，始终返回 CPU。
    """
    t = _ensure_torch()
    if t is None:
        return None
    # 全局强制 CPU 开关
    if _force_cpu:
        return t.device("cpu")
    # CUDA_VISIBLE_DEVICES 环境变量为空字符串 = 显式禁用 CUDA
    if os.environ.get("CUDA_VISIBLE_DEVICES", "") == "" and "CUDA_VISIBLE_DEVICES" in os.environ:
        return t.device("cpu")
    # 按优先级尝试各后端，最终回退到 CPU
    return _try_cuda() or _try_dml() or _try_xpu() or _try_mps() or t.device("cpu")


def get_device_info() -> Dict[str, Any]:
    """返回设备详细信息，用于 UI 显示。

    返回格式示例：
        {"device": "cuda:0", "name": "NVIDIA RTX 4070", "total_memory_gb": 8.0, "is_gpu": True}
        {"device": "cpu", "name": "CPU", "total_memory_gb": 0.0, "is_gpu": False}
        {"device": None, "name": "torch 未安装", "total_memory_gb": 0.0, "is_gpu": False}
        {"device": "privateuseone", "name": "DirectML (Intel GPU/NPU)", "total_memory_gb": 0.0, "is_gpu": True}

    Returns:
        Dict[str, Any]: 设备详情字典，包含：
            - device:         设备标识字符串
            - name:           设备友好名称
            - total_memory_gb: 总显存/内存（GB），精度 0.1GB
            - is_gpu:         是否为 GPU/NPU 加速器
    """
    t = _ensure_torch()
    if t is None:
        return {"device": None, "name": "torch 未安装", "total_memory_gb": 0.0, "is_gpu": False}

    device = get_device()
    if device is None:
        return {"device": None, "name": "无可用设备", "total_memory_gb": 0.0, "is_gpu": False}

    # 默认为 CPU 信息
    info = {"device": str(device), "name": "CPU", "total_memory_gb": 0.0, "is_gpu": False}

    if device.type == "cuda":
        # NVIDIA CUDA GPU
        try:
            idx = device.index if device.index is not None else 0
            props = t.cuda.get_device_properties(idx)
            info["name"] = props.name
            # 字节转 GB：/(1024^3)
            info["total_memory_gb"] = round(props.total_memory / (1024**3), 1)
            info["is_gpu"] = True
        except Exception as e:
            logger.debug("读取 CUDA 设备信息失败: %s", e)
            info["name"] = "NVIDIA GPU"
            info["is_gpu"] = True
    elif device.type == "xpu":
        # Intel XPU (GPU/NPU, Linux)
        try:
            idx = device.index if device.index is not None else 0
            name = t.xpu.get_device_name(idx)
            props = t.xpu.get_device_properties(idx)
            info["name"] = name
            info["total_memory_gb"] = round(props.total_memory / (1024**3), 1)
            info["is_gpu"] = True
        except Exception as e:
            logger.debug("读取 Intel XPU 设备信息失败: %s", e)
            info["name"] = "Intel XPU (GPU/NPU)"
            info["is_gpu"] = True
    elif device.type == "privateuseone":
        # DirectML 在 PyTorch 中使用 privateuseone 类型
        info["name"] = "DirectML (Intel GPU/NPU)"
        info["is_gpu"] = True
    elif device.type == "mps":
        # Apple Silicon MPS 加速
        info["name"] = "Apple Silicon (MPS)"
        info["is_gpu"] = True

    return info
