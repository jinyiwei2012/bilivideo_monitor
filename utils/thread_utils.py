"""
线程工具模块 — 统一即弃线程创建模式，消除 41 处重复的 threading.Thread(daemon=True) 模板。
"""

import threading
import logging

logger = logging.getLogger(__name__)


def fire_and_forget(target, *args, name=None, **kwargs):
    """启动守护线程，自动捕获并记录异常。

    Args:
        target: 在线程中执行的函数
        *args: 传递给 target 的位置参数
        name: 线程名称（可选，用于日志标识）
        **kwargs: 传递给 target 的关键字参数

    Returns:
        threading.Thread: 已启动的线程对象

    Example:
        fire_and_forget(some_worker, gui, bvid, name="fetch-bv1xx")
    """
    thread_name = name or getattr(target, "__name__", "unknown")

    def _wrapper():
        try:
            target(*args, **kwargs)
        except Exception:
            logger.exception("即弃线程 %s 异常退出", thread_name)

    t = threading.Thread(target=_wrapper, daemon=True, name=thread_name)
    t.start()
    return t
