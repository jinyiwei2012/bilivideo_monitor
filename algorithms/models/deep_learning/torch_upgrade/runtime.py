"""Extracted torch-upgrade helpers."""

import threading
import time
from collections import OrderedDict

from .context import logger, torch

_GPU_MODEL_LRU: OrderedDict = OrderedDict()
_GPU_LRU_LOCK = threading.Lock()
_GPU_VRAM_RESERVE_MB = 512
_GPU_VRAM_MIN_FREE_RATIO = 0.15


def _estimate_model_vram(model) -> int:
    """估算模型占用显存（MB），含 20% CUDA 上下文开销。"""
    try:
        total_bytes = sum(p.numel() * p.element_size() for p in model.parameters())
        return int(total_bytes * 1.2 / (1024 * 1024))
    except Exception:
        return 0


def _get_free_vram_mb(device) -> int:
    """获取 GPU 空闲显存（MB），不可用时返回 -1。"""
    try:
        if device.type == "cuda":
            total = torch.cuda.get_device_properties(device).total_memory
            reserved = torch.cuda.memory_reserved(device)
            return (total - reserved) // (1024 * 1024)
    except Exception:
        pass
    return -1


def _evict_lru_gpu_model():
    """将最久未用的模型从 GPU 移回 CPU，释放显存。"""
    with _GPU_LRU_LOCK:
        if not _GPU_MODEL_LRU:
            return
        key, (model, vram_mb, _ts) = _GPU_MODEL_LRU.popitem(last=False)
    try:
        model.cpu()
        torch.cuda.empty_cache()
        logger.debug("[VRAM] 驱逐 %s → CPU，释放 ~%dMB", key, vram_mb)
    except Exception as e:
        logger.debug("[VRAM] 驱逐模型 %s 失败: %s", key, e)


def _ensure_vram(headroom_needed_mb: int, device):
    """确保有足够显存加载新模型，不足时淘汰 LRU 模型。"""
    free_mb = _get_free_vram_mb(device)
    if free_mb < 0:
        return  # 无法检测，直接放行

    try:
        total_mb = torch.cuda.get_device_properties(device).total_memory // (1024 * 1024)
    except Exception:
        return
    target = max(_GPU_VRAM_RESERVE_MB, int(total_mb * _GPU_VRAM_MIN_FREE_RATIO))

    while (free_mb - headroom_needed_mb) < target:
        with _GPU_LRU_LOCK:
            if len(_GPU_MODEL_LRU) <= 1:
                break
        _evict_lru_gpu_model()
        free_mb = _get_free_vram_mb(device)
        if free_mb < 0:
            break


def _touch_gpu_lru(key: str):
    """标记模型为最近使用。"""
    with _GPU_LRU_LOCK:
        if key in _GPU_MODEL_LRU:
            _GPU_MODEL_LRU.move_to_end(key)


def _register_gpu_model(key: str, model, device):
    """将模型注册到 GPU LRU 缓存。"""
    if device.type != "cuda":
        return
    vram_mb = _estimate_model_vram(model)
    _ensure_vram(vram_mb, device)
    with _GPU_LRU_LOCK:
        _GPU_MODEL_LRU.pop(key, None)
        _GPU_MODEL_LRU[key] = (model, vram_mb, time.time())


def _unregister_gpu_model(key: str):
    """从 GPU LRU 移除模型（预测完成后释放显存）。"""
    with _GPU_LRU_LOCK:
        _GPU_MODEL_LRU.pop(key, None)


def clear_all_gpu_models():
    """释放所有 GPU 缓存的模型（退出时调用）。"""
    with _GPU_LRU_LOCK:
        keys = list(_GPU_MODEL_LRU.keys())
    for key in keys:
        with _GPU_LRU_LOCK:
            entry = _GPU_MODEL_LRU.pop(key, None)
        if entry:
            try:
                entry[0].cpu()
            except Exception:
                pass
    try:
        torch.cuda.empty_cache()
    except Exception:
        pass


def release_cached_models(algorithms_dict: dict = None, keep_bvid: str = "") -> int:
    """释放各算法实例缓存的 PyTorch 模型以回收内存，保留 ONNX session（体积小）。

    Args:
        algorithms_dict: AlgorithmRegistry._algorithms 或类似 dict。
        keep_bvid: 保留该 bvid 对应的模型缓存（当前活跃视频），避免立刻重载。

    Returns:
        int: 实际释放的模型数量。
    """
    if algorithms_dict is None:
        try:
            from algorithms.registry import AlgorithmRegistry

            algorithms_dict = AlgorithmRegistry._algorithms
        except Exception:
            return 0
    count = 0
    for algo in algorithms_dict.values():
        if getattr(algo, "_cached_torch_model", None) is None:
            continue
        # 保留当前活跃视频的模型，避免下一轮预测立刻重载（LRU 语义）
        if keep_bvid and getattr(algo, "_cached_bvid", "") == keep_bvid:
            continue
        try:
            algo._cached_torch_model.cpu()
        except Exception:
            pass
        algo._cached_torch_model = None
        algo._cached_bvid = ""
        for attr in ("_cached_ckpt_sig", "_cached_model_source"):
            try:
                setattr(algo, attr, None)
            except Exception:
                pass
        count += 1
    if count > 0:
        import gc

        gc.collect()
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass
        logger.debug("[Mem] 释放 %d 个 PyTorch 模型缓存 (保留 bvid=%s)", count, keep_bvid or "-")
    return count


def _initialize_torch_runtime(algorithm):
    """懒加载 checkpoint manager 和推理设备。"""
    if not hasattr(algorithm, "_ckpt"):
        from algorithms.training.checkpoint_manager import CheckpointManager

        algorithm._ckpt = CheckpointManager(getattr(algorithm, "algorithm_id", "unknown"))
    if not hasattr(algorithm, "_device"):
        from algorithms.training.device import get_device

        algorithm._device = get_device()


def _load_prediction_checkpoint(algorithm, algo_id, bvid, checkpoint_signature, load_best_checkpoint):
    """优先复用签名未变的缓存，否则加载最佳 checkpoint。"""
    state = None
    cached_model = getattr(algorithm, "_cached_torch_model", None)
    cache_ok = (
        cached_model is not None
        and (not bvid or getattr(algorithm, "_cached_bvid", "") == bvid)
        and getattr(algorithm, "_cached_model_source", None) is not None
    )
    if cache_ok:
        cur_sig = checkpoint_signature(algo_id, bvid)
        if cur_sig is None or cur_sig != getattr(algorithm, "_cached_ckpt_sig", None):
            cache_ok = False  # checkpoint 变化/不可解析 → 走常规加载

    if cache_ok:
        return state, algorithm._cached_model_source, True

    state, model_source = load_best_checkpoint(algo_id, bvid=bvid)
    if state is not None:
        # 记录签名与来源，供后续调用走缓存优先路径
        try:
            algorithm._cached_ckpt_sig = checkpoint_signature(algo_id, bvid)
            algorithm._cached_model_source = model_source
        except Exception:
            pass
    return state, model_source, False
