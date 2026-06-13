"""数据库连接管理及全局 HTTP 会话"""

import requests
import logging

logger = logging.getLogger(__name__)

# 模块级共享 Session，复用 TCP 连接，提升封面下载性能
_http_session = requests.Session()
_http_session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
    }
)


def close_http_session():
    """关闭全局 HTTP Session，释放连接池内存（应用退出时调用）。"""
    global _http_session
    try:
        _http_session.close()
    except Exception as e:
        logger.debug("关闭 HTTP Session 失败: %s", e)
    _http_session = None


class _ConnectionCtx:
    """线程安全的数据库连接上下文管理器
    自动在退出时提交或回滚事务，并释放锁
    """

    __slots__ = ("_conn", "_lock")

    def __init__(self, conn, lock):
        """初始化连接上下文

        Args:
            conn: SQLite 数据库连接对象
            lock: 线程锁，用于保证线程安全
        """
        self._conn = conn
        self._lock = lock

    def __enter__(self):
        """进入上下文：获取锁并返回数据库连接"""
        self._lock.acquire()
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文：无异常则提交，有异常则回滚，最后释放锁"""
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._lock.release()
        return False

    def cursor(self):
        """获取数据库游标"""
        return self._conn.cursor()
