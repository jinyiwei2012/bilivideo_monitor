"""
内存守护模块 — 基于系统可用内存动态限制并发
==========================================

检测系统总内存和可用内存，计算安全的并发模型加载数和线程池大小。
用于防止多线程同时加载 PyTorch 模型导致 OOM。

用法:
    from utils.memory_guard import get_safe_model_slots, get_safe_workers

    slots = get_safe_model_slots()        # 估算 200MB/模型，返回安全并发数
    workers = get_safe_workers()           # 线程池推荐大小
"""

import os
import logging
import threading

logger = logging.getLogger(__name__)

# 每个模型估算内存占用（MB），含 PyTorch 运行时开销
_EST_MODEL_MB = 200
# 系统基础开销（MB），留给 OS + 主进程 + Tkinter + DB
_SYSTEM_OVERHEAD_MB = 1500
# 每模型至少保留的余量（MB）
_MIN_HEADROOM_MB = 512

# 缓存检测结果，避免频繁系统调用
_cache_lock = threading.Lock()
_cached_total_mb: int = 0
_cached_avail_mb: int = 0


def _get_memory_info():
    """获取系统内存信息，返回 (total_mb, available_mb)。"""
    global _cached_total_mb, _cached_avail_mb
    with _cache_lock:
        if _cached_total_mb > 0:
            return _cached_total_mb, _cached_avail_mb

    total_mb = 0
    avail_mb = 0

    # Windows
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        mem = MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
            total_mb = int(mem.ullTotalPhys // (1024 * 1024))
            avail_mb = int(mem.ullAvailPhys // (1024 * 1024))
    except Exception:
        pass

    # Linux / macOS fallback
    if total_mb == 0:
        try:
            mem_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            total_mb = int(mem_bytes // (1024 * 1024))
            avail_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES")
            avail_mb = int(avail_bytes // (1024 * 1024))
        except Exception:
            pass

    # 最终兜底
    if total_mb == 0:
        total_mb = 8192  # 假设 8GB
        avail_mb = 4096
        logger.debug("[MemoryGuard] 无法检测系统内存，假设 8GB 总 / 4GB 可用")

    with _cache_lock:
        _cached_total_mb = total_mb
        _cached_avail_mb = avail_mb

    logger.info("[MemoryGuard] 系统内存: %dMB 总 / %dMB 可用", total_mb, avail_mb)
    return total_mb, avail_mb


def refresh_memory_info():
    """重新检测系统内存（用于 UI 刷新）。"""
    global _cached_total_mb, _cached_avail_mb
    with _cache_lock:
        _cached_total_mb = 0
        _cached_avail_mb = 0
    return _get_memory_info()


def get_safe_model_slots() -> int:
    """计算可安全并发加载的模型数。

    基于可用内存，每个模型估算 200MB，保留系统开销。
    返回 1~8 之间的整数。
    """
    total_mb, avail_mb = _get_memory_info()
    safe_mb = max(0, avail_mb - _SYSTEM_OVERHEAD_MB - _MIN_HEADROOM_MB)
    slots = max(1, min(8, safe_mb // _EST_MODEL_MB))
    logger.debug("[MemoryGuard] 安全模型并发数: %d (可用 %dMB)", slots, avail_mb)
    return slots


def get_safe_workers() -> int:
    """计算线程池推荐大小。

    基于总内存，大于 16GB 的系统可以支持更多并发。
    返回 2~8 之间的整数。
    """
    total_mb, _ = _get_memory_info()
    if total_mb >= 32768:   # 32GB+
        return 6
    elif total_mb >= 16384:  # 16GB+
        return 4
    elif total_mb >= 8192:   # 8GB+
        return 3
    else:
        return 2


def get_memory_usage_mb() -> int:
    """获取当前进程内存占用（MB）。"""
    try:
        import psutil
        proc = psutil.Process()
        return int(proc.memory_info().rss // (1024 * 1024))
    except ImportError:
        return 0


def format_memory_info() -> str:
    """格式化内存信息供 UI 显示。"""
    total_mb, avail_mb = _get_memory_info()
    usage_mb = get_memory_usage_mb()
    slots = get_safe_model_slots()
    workers = get_safe_workers()
    return (
        f"系统: {total_mb // 1024}GB 总 / {avail_mb // 1024:.1f}GB 可用  |  "
        f"进程: {usage_mb}MB  |  模型并发: {slots}  |  线程池: {workers}"
    )
