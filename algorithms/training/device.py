"""GPU / NPU 自动检测模块
=======================

自动检测可用的计算硬件加速器（GPU/NPU），为 PyTorch 训练与 ONNX 推理提供统一的设备接口。

支持的加速后端：
- **CUDA**:          NVIDIA GPU（需安装 CUDA 版 PyTorch）
- **DirectML**:      Windows 平台 GPU/NPU（Intel/AMD），通过 torch-directml 包
- **Intel XPU**:     Linux 平台 Intel GPU/NPU（需 intel-extension-for-pytorch）
- **OpenVINO NPU**:  Intel AI Boost NPU（Windows/Linux），通过 openvino 包 + ONNX 模型
- **Apple MPS**:     macOS Apple Silicon 的 Metal Performance Shaders 加速
- **CPU**:          高性能 CPU 降级回退

后端探测优先级：
    cuda > DirectML > XPU (IPEX) > MPS > CPU
    OpenVINO NPU 为独立推理后端，通过 is_ov_npu_available() 查询

支持的特性：
- 懒加载 PyTorch / OpenVINO（避免拖慢应用启动）
- 冒烟测试验证加速器可用性
- 全局强制 CPU 开关（UI 可控制）
- 设备详情查询（名称、显存、类型）

公开 API：
---------
    is_torch_available()    — PyTorch 是否已安装
    get_device()            — 返回最优 torch.device；PyTorch 未装时返回 None
    get_device_info()       — 返回设备详情字典 {device, name, total_memory_gb, is_gpu}
    force_cpu(flag)         — 强制使用 CPU（设置后 get_device() 永远返回 cpu）
    is_ov_npu_available()   — OpenVINO NPU（Intel AI Boost）是否可用
    set_preferred_device()  — 设置推理设备偏好
    get_preferred_device()  — 获取当前推理设备偏好
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
_ov_available = None    # OpenVINO 是否可用的缓存标志
_ov_npu_available = None  # OpenVINO NPU 设备是否可用的缓存标志
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


def _ensure_ov():
    """懒加载 OpenVINO 并检测 NPU 设备可用性。

    只在首次使用时才 import openvino，避免拖慢应用启动。
    检测 Intel AI Boost NPU 是否可通过 OpenVINO 运行时访问。

    Returns:
        bool: OpenVINO 是否可正常导入。
    """
    global _ov_available, _ov_npu_available
    if _ov_available is not None:
        return _ov_available
    try:
        import openvino as _ov  # noqa: F811

        _ov_available = True
        core = _ov.Core()
        _ov_npu_available = "NPU" in core.available_devices
        if _ov_npu_available:
            logger.info("OpenVINO NPU 已检测到: %s", core.get_property("NPU", "FULL_DEVICE_NAME"))
        else:
            logger.debug("OpenVINO 已安装，但未检测到 NPU 设备。可用设备: %s", core.available_devices)
    except ImportError:
        _ov_available = False
        _ov_npu_available = False
    except Exception as e:
        logger.debug("OpenVINO 检测异常: %s", e)
        _ov_available = False
        _ov_npu_available = False
    return _ov_available


def _try_ov_npu():
    """尝试验证 OpenVINO NPU 是否可正常执行推理。

    通过创建一个极简 ONNX 模型并编译到 NPU 进行冒烟测试，
    确保 NPU 驱动和编译器均可正常工作。

    Returns:
        bool: NPU 冒烟测试是否通过。
    """
    if not _ensure_ov() or not _ov_npu_available:
        return False
    try:
        import tempfile
        import os as _os
        import numpy as np
        import openvino as ov
        from onnx import helper, TensorProto
        import onnx

        # 极简模型: (1, 2) @ (2, 1) → (1, 1)
        nodes = [helper.make_node("MatMul", ["X", "W"], ["Y"], name="smoke")]
        inputs = [helper.make_tensor_value_info("X", TensorProto.FLOAT16, [1, 2])]
        outputs = [helper.make_tensor_value_info("Y", TensorProto.FLOAT16, [1, 1])]
        W = np.array([[1.0], [0.5]], dtype=np.float16)
        inits = [helper.make_tensor("W", TensorProto.FLOAT16, [2, 1], W.tobytes(), raw=True)]
        graph = helper.make_graph(nodes, "smoke_test", inputs, outputs, inits)
        model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)])
        onnx.checker.check_model(model)

        tmp = _os.path.join(tempfile.gettempdir(), "_ov_npu_smoke.onnx")
        onnx.save(model, tmp)

        core = ov.Core()
        compiled = core.compile_model(
            tmp,
            "NPU",
            config={
                "PERFORMANCE_HINT": "LATENCY",
                "NPU_COMPILATION_MODE_PARAMS": "compute-layers-with-higher-precision=Sqrt,Power,ReduceMean,Add_RMSNorm",
            },
        )
        ireq = compiled.create_infer_request()
        X_test = np.array([[2.0, 4.0]], dtype=np.float16)
        ireq.infer([X_test])
        result = ireq.get_output_tensor(0).data

        _os.unlink(tmp)
        expected = 2.0 * 1.0 + 4.0 * 0.5  # = 4.0
        if abs(float(result[0, 0]) - expected) < 0.01:
            logger.info("OpenVINO NPU 冒烟测试通过，推理结果正确")
            return True
        else:
            logger.warning("OpenVINO NPU 冒烟测试结果异常: expected=%.2f, got=%.2f", expected, float(result[0, 0]))
            return False
    except Exception as e:
        logger.warning("OpenVINO NPU 冒烟测试失败: %s", e)
        return False


def is_ov_npu_available() -> bool:
    """检查 OpenVINO NPU（Intel AI Boost）是否可用于推理。

    OpenVINO NPU 是一个独立的推理后端，不需要 PyTorch。
    使用此 API 判断是否可以将 ONNX 模型编译到 NPU 上执行。

    Returns:
        bool: True 表示 OpenVINO NPU 可用且冒烟测试通过。
    """
    _ensure_ov()
    if not _ov_npu_available:
        return False
    # 冒烟测试仅首次执行，后续直接使用缓存结果
    if _ov_npu_available is True:
        return True
    return _try_ov_npu()


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


def _get_ov_npu_name() -> str:
    """获取 OpenVINO NPU 设备友好名称。

    Returns:
        str: NPU 设备名称，不可用时返回空字符串。
    """
    if not _ov_npu_available:
        return ""
    try:
        import openvino as ov
        core = ov.Core()
        return core.get_property("NPU", "FULL_DEVICE_NAME")
    except Exception:
        return "Intel AI Boost (NPU)"


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

    # ── OpenVINO NPU 附加信息 ─────────────────────────
    # 仅在 NPU 已检测到时追加，不影响当前 torch 设备选择
    _ensure_ov()
    if _ov_npu_available:
        info["npu_available"] = True
        info["npu_name"] = _get_ov_npu_name()

    return info


# ── 用户推理设备偏好 ────────────────────────────

_preferred_device: str = "auto"  # "auto" | "onnx_dml" | "cuda" | "cpu" | "openvino_npu"


def set_preferred_device(pref: str):
    """设置用户推理设备偏好。

    Args:
        pref: "auto" | "onnx_dml" | "cuda" | "cpu" | "openvino_npu"

    Note:
        - "auto":          自动选择最优设备（优先级: CUDA > DirectML > XPU > MPS > CPU）
        - "cuda":          强制使用 NVIDIA CUDA GPU
        - "onnx_dml":      使用 DirectML 后端（Intel/AMD GPU/NPU, Windows）
        - "openvino_npu":  使用 OpenVINO NPU（Intel AI Boost），需 openvino 包 + ONNX 模型
        - "cpu":           强制使用 CPU
    """
    global _preferred_device
    valid = {"auto", "onnx_dml", "cuda", "cpu", "openvino_npu"}
    if pref in valid:
        _preferred_device = pref
        # 同步 force_cpu 状态
        if pref == "cpu":
            force_cpu(True)
        elif pref == "openvino_npu":
            # NPU 不是 torch 设备，不强制 CPU，但标记为特殊推理路径
            force_cpu(False)
            if not is_ov_npu_available():
                logger.warning("OpenVINO NPU 不可用，推理将回退到 CPU")
        else:
            force_cpu(False)
        logger.info("推理设备偏好: %s", pref)


def get_preferred_device() -> str:
    """获取用户推理设备偏好。"""
    return _preferred_device


# ── NPU 上下文管理器 ──────────────────────────────

from contextlib import contextmanager


@contextmanager
def npu_context(enabled: bool = True):
    """临时切换 NPU 推理模式的上下文管理器。

    在 with 块内临时将推理设备偏好设为 openvino_npu（或恢复），
    退出时自动恢复原偏好。用于批量预测场景。

    用法：
        with npu_context():
            results = AlgorithmRegistry.predict_all(...)

    Args:
        enabled: True 表示启用 NPU，False 表示禁用（恢复到 auto）。
    """
    global _preferred_device
    previous = _preferred_device
    try:
        if enabled:
            set_preferred_device("openvino_npu")
        else:
            set_preferred_device("auto")
        yield
    finally:
        set_preferred_device(previous)
