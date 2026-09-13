"""Shared guarded PyTorch imports and runtime constants."""

import logging
import threading
from typing import TYPE_CHECKING

from utils.memory_guard import get_safe_model_slots

logger = logging.getLogger("algorithms.models.deep_learning._torch_upgrade")

_torch_available = True
if TYPE_CHECKING:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
else:
    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as F
    except ImportError:
        _torch_available = False
        torch = None
        nn = None
        F = None

DEFAULT_FEATURES = ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]
DEFAULT_WINDOW = 10
DEFAULT_HORIZON = 3

_model_load_semaphore = threading.BoundedSemaphore(get_safe_model_slots())
_model_sem_lock = threading.Lock()

__all__ = [
    "DEFAULT_FEATURES",
    "DEFAULT_HORIZON",
    "DEFAULT_WINDOW",
    "F",
    "_model_load_semaphore",
    "_model_sem_lock",
    "_torch_available",
    "logger",
    "nn",
    "torch",
]
