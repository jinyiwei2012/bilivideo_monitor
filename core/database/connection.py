"""
数据库连接管理及全局 HTTP 会话
==============================

本模块提供两个核心基础设施：
1. _http_session: 模块级共享的 HTTP Session，用于封面图片下载等网络请求，
   复用 TCP 连接以减少握手开销
2. _ConnectionCtx: 线程安全的数据库连接上下文管理器，
   封装了锁获取/释放和事务提交/回滚逻辑
"""

import requests

# ════════════════════════════════════════════════════════════════════
# 全局 HTTP 会话
# ════════════════════════════════════════════════════════════════════

# 模块级共享 Session，复用 TCP 连接，提升封面下载性能
# 使用 requests.Session() 保持连接池和 Cookie 持久化
_http_session = requests.Session()
_http_session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",  # 伪造 Referer，模拟从 B 站页面发起请求
    }
)


class _ConnectionCtx:
    """线程安全的数据库连接上下文管理器

    封装 SQLite 连接的线程安全访问模式：
    - 进入时自动获取可重入锁，返回数据库连接
    - 退出时无异常则提交事务，有异常则回滚
    - 始终释放锁，防止死锁
    - 使用 RLock 允许同一线程重入，避免嵌套读取时死锁

    配合 Python 的 with 语句使用：
        with _ConnectionCtx(conn, lock) as conn:
            conn.execute("...")

    注意：本类不主动关闭连接，连接生命周期由外层 Database 管理。
    """

    # __slots__ 优化内存使用，限制实例属性只能为 _conn 和 _lock
    __slots__ = ("_conn", "_lock")

    def __init__(self, conn, lock):
        """初始化连接上下文

        Args:
            conn: SQLite 数据库连接对象（sqlite3.Connection）
            lock: threading.RLock 可重入线程锁，用于保证多线程互斥访问
        """
        self._conn = conn
        self._lock = lock

    def __enter__(self):
        """进入上下文：获取锁并返回数据库连接

        调用方在 with 语句中对返回的连接执行数据库操作。

        Returns:
            SQLite 数据库连接对象
        """
        self._lock.acquire()  # 获取互斥锁，阻塞等待直到锁可用
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文：无异常则提交，有异常则回滚，最后释放锁

        Args:
            exc_type: 异常类型（无异常时为 None）
            exc_val: 异常值
            exc_tb: 异常 traceback

        Returns:
            False: 不抑制异常，让异常向上传播
        """
        try:
            if exc_type is None:
                self._conn.commit()   # 无异常 → 提交事务
            else:
                self._conn.rollback()  # 有异常 → 回滚事务
        finally:
            self._lock.release()      # 无论是否异常，始终释放锁
        return False  # 返回 False 表示不抑制异常

    def cursor(self):
        """获取数据库游标

        从封装的连接对象创建新游标，供 SQL 执行使用。

        Returns:
            sqlite3.Cursor 游标对象
        """
        return self._conn.cursor()
