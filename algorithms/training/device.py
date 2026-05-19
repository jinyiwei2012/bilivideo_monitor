"""GPU 自动检测

公开 API：
- is_torch_available() — torch 是否已安装
- get_device()         — 返回 torch.device（cuda > mps > cpu）；torch 未装时返回 None
- get_device_info()    — 返回 dict{device, name, total_memory_gb, is_gpu}
- force_cpu(flag)      — 强制 CPU（设置后 get_device 永远返回 cpu）
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

_force_cpu = False


def is_torch_available() -> bool:
    return _torch_available


def force_cpu(flag: bool):
    """全局强制使用 CPU（不持久化，UI 配置可调）"""
    global _force_cpu
    _force_cpu = bool(flag)


def get_device() -> Optional[Any]:
    """返回 torch.device；torch 未装时返回 None。

    选择顺序：
        1. 用户强制 CPU 或 CUDA_VISIBLE_DEVICES='' → cpu
        2. CUDA 可用 → cuda
        3. MPS 可用（Apple Silicon） → mps
        4. 兜底 → cpu
    """
    if not _torch_available:
        return None
    if _force_cpu:
        return torch.device("cpu")
    if os.environ.get("CUDA_VISIBLE_DEVICES", "") == "" and "CUDA_VISIBLE_DEVICES" in os.environ:
        return torch.device("cpu")
    try:
        if torch.cuda.is_available():
            return torch.device("cuda:0")
    except Exception as e:
        logger.debug("CUDA 检测异常: %s", e)
    try:
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return torch.device("mps")
    except Exception as e:
        logger.debug("MPS 检测异常: %s", e)
    return torch.device("cpu")


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
    elif device.type == "mps":
        info["name"] = "Apple Silicon (MPS)"
        info["is_gpu"] = True

    return info
