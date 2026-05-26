"""GPU / NPU 自动检测

公开 API：
- is_torch_available() — torch 是否已安装
- get_device()         — 返回 torch.device；torch 未装时返回 None
- get_device_info()    — 返回 dict{device, name, total_memory_gb, is_gpu}
- force_cpu(flag)      — 强制 CPU（设置后 get_device 永远返回 cpu）

后端优先级：cuda > DirectML > XPU (IPEX, Linux) > MPS > CPU

NPU (Intel AI Boost) 支持：
- Windows: torch-directml (pip install torch-directml --pre)
- Linux: intel-extension-for-pytorch (pip install intel-extension-for-pytorch)
"""

import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

_torch_available = True
try:
    import torch
except ImportError:
    _torch_available = False

_xpu_available = False
try:
    import intel_extension_for_pytorch  # noqa: F401 — registers torch.xpu backend (Linux only)

    _xpu_available = True
except ImportError:
    pass

_dml_available = False
try:
    import torch_directml  # noqa: F401 — DirectML backend for Windows

    _dml_available = True
except ImportError:
    pass

_force_cpu = False


def is_torch_available() -> bool:
    return _torch_available


def force_cpu(flag: bool):
    """全局强制使用 CPU（不持久化，UI 配置可调）"""
    global _force_cpu
    _force_cpu = bool(flag)


def _try_cuda():
    try:
        if torch.cuda.is_available():
            torch.cuda.synchronize()
            return torch.device("cuda:0")
    except Exception as e:
        logger.warning("CUDA 冒烟测试失败: %s", e)
    return None


def _try_dml():
    if not _dml_available:
        return None
    try:
        return torch_directml.device()
    except Exception as e:
        logger.warning("DirectML 冒烟测试失败: %s", e)
    return None


def _try_xpu():
    if not _xpu_available:
        return None
    try:
        if torch.xpu.is_available():
            torch.xpu.synchronize()
            return torch.device("xpu:0")
    except Exception as e:
        logger.warning("Intel XPU 冒烟测试失败: %s", e)
    return None


def _try_mps():
    try:
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return torch.device("mps")
    except Exception as e:
        logger.debug("MPS 检测异常: %s", e)
    return None


def get_device() -> Optional[Any]:
    if not _torch_available:
        return None
    if _force_cpu:
        return torch.device("cpu")
    if os.environ.get("CUDA_VISIBLE_DEVICES", "") == "" and "CUDA_VISIBLE_DEVICES" in os.environ:
        return torch.device("cpu")
    return _try_cuda() or _try_dml() or _try_xpu() or _try_mps() or torch.device("cpu")


def get_device_info() -> Dict[str, Any]:
    """返回设备详情，用于 UI 显示。

    Example:
        {"device": "cuda:0", "name": "NVIDIA RTX 4070", "total_memory_gb": 8.0, "is_gpu": True}
        {"device": "cpu", "name": "CPU", "total_memory_gb": 0.0, "is_gpu": False}
        {"device": None, "name": "torch 未安装", "total_memory_gb": 0.0, "is_gpu": False}
    """
    if not _torch_available:
        return {"device": None, "name": "torch 未安装", "total_memory_gb": 0.0, "is_gpu": False}

    device = get_device()
    if device is None:
        return {"device": None, "name": "无可用设备", "total_memory_gb": 0.0, "is_gpu": False}

    info = {"device": str(device), "name": "CPU", "total_memory_gb": 0.0, "is_gpu": False}

    if device.type == "cuda":
        try:
            idx = device.index if device.index is not None else 0
            props = torch.cuda.get_device_properties(idx)
            info["name"] = props.name
            info["total_memory_gb"] = round(props.total_memory / (1024**3), 1)
            info["is_gpu"] = True
        except Exception as e:
            logger.debug("读取 CUDA 设备信息失败: %s", e)
            info["name"] = "NVIDIA GPU"
            info["is_gpu"] = True
    elif device.type == "xpu":
        try:
            idx = device.index if device.index is not None else 0
            name = torch.xpu.get_device_name(idx)
            props = torch.xpu.get_device_properties(idx)
            info["name"] = name
            info["total_memory_gb"] = round(props.total_memory / (1024**3), 1)
            info["is_gpu"] = True
        except Exception as e:
            logger.debug("读取 Intel XPU 设备信息失败: %s", e)
            info["name"] = "Intel XPU (GPU/NPU)"
            info["is_gpu"] = True
    elif device.type == "privateuseone":
        info["name"] = "DirectML (Intel GPU/NPU)"
        info["is_gpu"] = True
    elif device.type == "mps":
        info["name"] = "Apple Silicon (MPS)"
        info["is_gpu"] = True

    return info
