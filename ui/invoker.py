"""
线程安全的主线程调用桥 — 跨模块共享

用于替代在工作线程中直接调用 QTimer.singleShot（会触发
"QObject::startTimer: Timers cannot be started from another thread" 错误）。

用法：
    from ui.invoker import invoke, invoke_later

    # 在任意线程：
    invoke(lambda: label.setText("done"))          # 立即在主线程执行
    invoke_later(1000, lambda: label.hide())        # 1 秒后在主线程执行
"""

import logging
import queue
import threading

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

_MAX_QUEUE = 4096  # 背压上限：积压回调数达到此值时丢弃新回调


class _MainInvoker(QObject):
    """跨线程安全地将回调调度到主线程执行。"""

    _wake = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._q = queue.Queue()
        self._keyed = {}  # key -> 最新待执行回调（按 key 合并）
        self._queued_keys = set()  # 已入队占位的 key
        self._lock = threading.Lock()
        self._wake.connect(self._drain)

    def invoke(self, fn, key=None):
        """从任意线程调用：fn 将在主线程被执行。

        key 非空时按 key 合并——同一 key 的待执行回调只保留最新一个；
        队列积压达到 _MAX_QUEUE 时丢弃本次回调（背压）。
        """
        if key is None:
            if self._q.qsize() >= _MAX_QUEUE:
                logger.warning("invoker 队列积压（>=%d），丢弃回调", _MAX_QUEUE)
                return
            self._q.put((None, fn))
        else:
            with self._lock:
                if key in self._queued_keys:
                    self._keyed[key] = fn  # 合并：覆盖为最新回调
                elif self._q.qsize() >= _MAX_QUEUE:
                    logger.warning("invoker 队列积压（>=%d），丢弃 key=%s 回调", _MAX_QUEUE, key)
                    return
                else:
                    self._queued_keys.add(key)
                    self._keyed[key] = fn
                    self._q.put((key, None))
        self._wake.emit()

    def _drain(self):
        while True:
            try:
                key, fn = self._q.get_nowait()
            except queue.Empty:
                break
            if key is not None:
                with self._lock:
                    self._queued_keys.discard(key)
                    fn = self._keyed.pop(key, None)
                if fn is None:
                    continue
            try:
                fn()
            except Exception:
                # 单回调异常隔离：失败不阻断后续回调，避免队列无限积压
                logger.exception("invoker 回调执行异常")


_invoker = _MainInvoker()


def invoke(fn, key=None):
    """在任意线程中调用，fn 会被调度到主线程执行。

    key 非空时按 key 合并：同一 key 的待执行回调只保留最新一个。
    """
    _invoker.invoke(fn, key)


def invoke_later(ms, fn):
    """延迟 ms 毫秒后在主线程执行 fn（线程安全）。"""
    from PyQt6.QtCore import QTimer

    def wrapper():
        QTimer.singleShot(ms, fn)

    _invoker.invoke(wrapper)
