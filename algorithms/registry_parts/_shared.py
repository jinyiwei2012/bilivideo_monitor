"""Shared registry implementation details."""

import logging
import sys
from collections import OrderedDict

from ..weight_manager import get_weight_manager as _default_get_weight_manager

logger = logging.getLogger("algorithms.registry")

_MAX_CACHE_SIZE = 200


def get_weight_manager():
    registry_module = sys.modules.get("algorithms.registry")
    if registry_module is not None:
        return registry_module.get_weight_manager()
    return _default_get_weight_manager()


class _LRUDict(OrderedDict):
    """固定容量的 LRU 字典，超出容量时自动淘汰最久未使用的条目。"""

    __slots__ = ("maxsize",)

    def __init__(self, maxsize=_MAX_CACHE_SIZE, *args, **kwargs):
        self.maxsize = maxsize
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if len(self) > self.maxsize:
            # 不能用 popitem(last=False)：CPython 中其内部会经子类 __getitem__
            # 访问被淘汰的 key，而该 key 已从 dict 移除 → move_to_end 抛 KeyError。
            # 改为手动取最旧键删除，绕开该调用链。
            try:
                oldest = next(iter(self))
            except StopIteration:
                return
            del self[oldest]

    def __getitem__(self, key):
        self.move_to_end(key)
        return super().__getitem__(key)


# ── 模块级单例：surge detector（避免每轮预测重复创建类） ──
_surge_detector = None


def _get_surge_detector():
    """获取 surge detector 模块级单例，延迟初始化。"""
    global _surge_detector
    if _surge_detector is None:
        from algorithms.base import BaseAlgorithm as BA

        class _SurgeDetector(BA):
            def predict(self, video_data=None, threshold=100000):
                pass

        _surge_detector = _SurgeDetector()
    return _surge_detector
