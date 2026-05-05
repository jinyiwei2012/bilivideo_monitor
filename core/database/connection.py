"""数据库连接管理"""

import requests
import threading

# 模块级共享 Session，复用 TCP 连接，提升封面下载性能
_http_session = requests.Session()
_http_session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
    }
)


class _ConnectionCtx:
    """线程安全的数据库连接上下文管理器"""

    __slots__ = ("_conn", "_lock")

    def __init__(self, conn, lock):
        self._conn = conn
        self._lock = lock

    def __enter__(self):
        self._lock.acquire()
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._lock.release()
        return False

    def cursor(self):
        return self._conn.cursor()
