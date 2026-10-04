"""数据库连接管理及全局 HTTP 会话"""

import logging
import sqlite3
import threading
from types import TracebackType
from typing import Any, Literal, Optional

import requests
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

# 模块级共享 Session 按需创建，避免导入 core 时初始化 HTTP 基础设施
_http_session: Optional[requests.Session] = None
_http_session_lock = threading.Lock()


def get_http_session() -> requests.Session:
    """获取线程安全的共享 HTTP Session，并在关闭后按需重新创建。"""
    global _http_session
    with _http_session_lock:
        if _http_session is None:
            session = requests.Session()
            session.headers.update(
                {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Referer": "https://www.bilibili.com/",
                }
            )
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            _http_session = session
        return _http_session


def close_http_session() -> None:
    """关闭全局 HTTP Session，释放连接池内存（应用退出时调用）。"""
    global _http_session
    with _http_session_lock:
        if _http_session is None:
            return
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

    def __init__(self, conn: sqlite3.Connection, lock: Any) -> None:
        """初始化连接上下文

        Args:
            conn: SQLite 数据库连接对象
            lock: 线程锁，用于保证线程安全
        """
        self._conn = conn
        self._lock = lock

    def __enter__(self) -> sqlite3.Connection:
        """进入上下文：获取锁并返回数据库连接"""
        self._lock.acquire()
        return self._conn

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Literal[False]:
        """退出上下文：无异常则提交，有异常则回滚，最后释放锁"""
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._lock.release()
        return False

    def cursor(self) -> sqlite3.Cursor:
        """获取数据库游标"""
        return self._conn.cursor()
