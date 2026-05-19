"""训练基础设施

模块概览：
- device.py             — GPU 自动检测
- checkpoint_manager.py — 多版本 checkpoint 管理
- dataset.py            — 从 core/data/<BVID>/<BVID>.db 加载训练数据
- trainer.py            — 统一训练管线（全局预训练 + 视频微调）
- hf_loader.py          — Foundation 模型懒加载（MOIRAI-2 / Lag-Llama）
"""

from algorithms.training.device import get_device, get_device_info, is_torch_available
from algorithms.training.checkpoint_manager import CheckpointManager

__all__ = [
    "get_device",
    "get_device_info",
    "is_torch_available",
    "CheckpointManager",
]
