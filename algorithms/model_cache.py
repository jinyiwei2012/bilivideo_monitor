"""已拟合估计器的按内容缓存（M2.6b）。

用途：``random_forest`` / ``xgboost`` / ``gaussian_process`` 等重型估计器在每个预测轮次
都会重新 ``fit`` 一遍同样的历史数据。本模块用 **内容寻址** 复用拟合结果：

    键 = (algo_key, 训练数组内容摘要)

历史未变化 → 摘要不变 → 直接复用已拟合模型（不重训）；
历史新增点 → 摘要变化 → 自动重新拟合。因此**不存在陈旧风险**，无需 TTL。
仅以 LRU 上限约束内存（拟合远比摘要计算昂贵）。

线程安全：``AlgorithmRegistry.predict_all`` 用线程池并发跑算法，读写缓存在锁内完成，
估计器的 ``predict`` 本身是只读的，可并发调用。
"""

import hashlib
import logging
import threading
from collections import OrderedDict

import numpy as np

logger = logging.getLogger(__name__)

_MAXSIZE = 24  # 缓存的已拟合模型数上限（估计器可能较大）

_CACHE: "OrderedDict[tuple, object]" = OrderedDict()
_LOCK = threading.Lock()


def content_digest(*arrays) -> str:
    """对训练数组做稳定摘要（形状 + 位级内容）。"""
    h = hashlib.blake2b(digest_size=16)
    for arr in arrays:
        a = np.ascontiguousarray(np.asarray(arr, dtype=np.float64))
        h.update(str(a.shape).encode())
        h.update(a.tobytes())
    return h.hexdigest()


def get_or_fit(algo_key: str, factory, *fit_args, **fit_kwargs):
    """返回按内容缓存的已拟合估计器。

    Args:
        algo_key: 算法标识（缓存命名空间）。**必须包含影响拟合结果的构造参数**
            （例如 ``f"quantile_ensemble:{tau}"``），否则不同参数的模型会互相污染
        factory: 无参可调用，缓存未命中时用它新建估计器
        *fit_args: 传给 ``estimator.fit`` 的位置参数（同时构成缓存键）
        **fit_kwargs: 传给 ``estimator.fit`` 的关键字参数

    Returns:
        已拟合的估计器（命中缓存则为同一实例，仅用于只读 predict）
    """
    try:
        key = (algo_key, content_digest(*fit_args))
    except Exception as e:  # 无法摘要（如稀疏/对象数组）→ 不缓存，保证正确性
        logger.debug("模型缓存键构造失败 %s: %s", algo_key, e)
        model = factory()
        model.fit(*fit_args, **fit_kwargs)
        return model

    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            _CACHE.move_to_end(key)
            return hit

    model = factory()
    model.fit(*fit_args, **fit_kwargs)

    with _LOCK:
        _CACHE[key] = model
        _CACHE.move_to_end(key)
        while len(_CACHE) > _MAXSIZE:
            _CACHE.popitem(last=False)
    return model


def clear_model_cache() -> int:
    """清空缓存，返回清理掉的模型数（测试 / 内存回收用）。"""
    with _LOCK:
        n = len(_CACHE)
        _CACHE.clear()
    return n


def cache_size() -> int:
    """当前缓存中的模型数。"""
    with _LOCK:
        return len(_CACHE)
