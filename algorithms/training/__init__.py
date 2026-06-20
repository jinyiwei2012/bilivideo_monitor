"""训练基础设施包
============

本包提供 B站视频播放量预测模型的训练基础设施，包括：
- GPU/NPU 自动检测与设备选择
- 多版本 Checkpoint 管理（全局预训练 + 按视频微调）
- 时序数据加载与增量训练支持
- 统一训练管线（全局预训练 + 视频微调）
- HuggingFace Foundation 模型懒加载
- 自定义学习率调度器（双曲线衰减 + Plateau 检测）
- NPU 推理引擎（ONNX 导出 + OpenVINO NPU 编译 + 模型缓存）

模块概览：
---------
- device.py             — GPU/NPU 自动检测，支持 CUDA/DirectML/XPU/MPS/CPU/OpenVINO NPU
- checkpoint_manager.py — 多版本 Checkpoint 管理，支持增删改查与激活切换
- dataset.py            — 从 core/data/<BVID>/<BVID>.db 加载时序训练数据
- trainer.py            — 统一训练管线编排器，支持全局预训练与按视频微调
- hf_loader.py          — HuggingFace Foundation 模型（MOIRAI-2 / Lag-Llama）懒加载
- schedulers.py         — 自定义学习率调度器（HyperbolicLR + ComboScheduler）
- npu_inference.py      — NPU 推理引擎（ONNX 导出 + 编译 + 缓存 + 批量推理）

使用示例：
---------
    from algorithms.training import get_device, get_device_info, CheckpointManager
    device = get_device()
    ckpt = CheckpointManager("my_algo")
    if ckpt.has_checkpoint():
        state_dict = ckpt.load()
"""

from algorithms.training.device import (
    get_device,
    get_device_info,
    is_torch_available,
    is_ov_npu_available,
    set_preferred_device,
    get_preferred_device,
    npu_context,
)
from algorithms.training.checkpoint_manager import CheckpointManager

# 对外公开的 API 接口
__all__ = [
    "get_device",
    "get_device_info",
    "is_torch_available",
    "is_ov_npu_available",
    "set_preferred_device",
    "get_preferred_device",
    "npu_context",
    "CheckpointManager",
]
