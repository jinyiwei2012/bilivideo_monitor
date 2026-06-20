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

import queue
from PyQt6.QtCore import QObject, pyqtSignal


class _MainInvoker(QObject):
    """跨线程安全地将回调调度到主线程执行。"""
    _wake = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._q = queue.Queue()
        self._wake.connect(self._drain)

    def invoke(self, fn):
        """从任意线程调用：fn 将在主线程被执行。"""
        self._q.put(fn)
        self._wake.emit()

    def _drain(self):
        while True:
            try:
                fn = self._q.get_nowait()
            except queue.Empty:
                break
            fn()


_invoker = _MainInvoker()


def invoke(fn):
    """在任意线程中调用，fn 会被调度到主线程执行。"""
    _invoker.invoke(fn)


def invoke_later(ms, fn):
    """延迟 ms 毫秒后在主线程执行 fn（线程安全）。"""
    from PyQt6.QtCore import QTimer

    def wrapper():
        QTimer.singleShot(ms, fn)

    _invoker.invoke(wrapper)
