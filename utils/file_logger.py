"""
文件日志处理器 — 自动按天分割日志文件

功能特性：
1. 线程安全：内部使用 threading.Lock 保护文件写入操作
2. 按天分割：每天自动切换日志文件，午夜跨天时无缝衔接
3. 文件命名：{date}_{start_time}-{end_time}.log（如 20250602_083000-235959.log）
4. 跨天检测：支持主动检查（主线程定时器）和被动检查（非主线程写入时兜底）
5. 运行中文件标记：正在写入的日志文件后缀为 -running.log，关闭时自动重命名

日志文件存储路径: data/log/

使用方式：
    from utils.file_logger import FileLogger

    logger = FileLogger("data/log")
    logger.write("INFO", "应用启动")
    logger.close()  # 退出时必须调用
"""

import os
import threading
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class FileLogger:
    """线程安全的文件日志器，每天自动切换日志文件。

    设计要点：
    - 当前正在写入的文件命名为 {date}_{start}-running.log
    - 关闭或跨天时将文件重命名为 {date}_{start}-{end}.log
    - 如果跨天关闭，结束时间自动设置为 23:59:59
    - 支持 tkinter 主线程定时器做跨天主动检查
    - 非主线程写入时通过 _ensure_date() 做被动兜底检测
    """

    def __init__(self, log_dir: str):
        """
        初始化文件日志器并立即创建第一个日志文件。

        Parameters
        ----------
        log_dir : str
            日志文件存放目录，如 'data/log'。目录不存在时自动创建。
        """
        self._log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

        self._lock = threading.Lock()  # 写文件互斥锁
        self._file = None  # 当前打开的文件句柄
        self._current_date = None  # 当前日志文件对应的日期 (datetime.date 对象)
        self._start_dt = None  # 当前日志文件的起始时间 (datetime)
        self._midnight_timer = None  # 跨天切换的 tkinter after id（仅主线程）

        # 立即打开第一个日志文件
        self._open_file()

    # ── 公共接口 ────────────────────────────────────────

    def write(self, level: str, message: str, ts: datetime = None):
        """
        写入一条日志到当前日期对应的日志文件。

        单条日志格式: [YYYY-MM-DD HH:MM:SS.毫秒] [   LEVEL] message

        Parameters
        ----------
        level   : str
            日志等级 (DEBUG/INFO/WARNING/ERROR)，自动右对齐到 7 字符宽度
        message : str
            日志内容，不需要手动加换行符
        ts      : datetime | None
            时间戳，默认为当前时间 datetime.now()
        """
        if ts is None:
            ts = datetime.now()

        # 构造带毫秒的时间戳前缀
        line = f"[{ts.strftime('%Y-%m-%d %H:%M:%S')}.{ts.microsecond // 1000:03d}] [{level:>7s}] {message}\n"

        with self._lock:
            self._ensure_date(ts)  # 先检查是否跨天需要切换文件
            if self._file:
                try:
                    self._file.write(line)
                    self._file.flush()  # 实时刷盘，防止意外崩溃丢日志
                except Exception as e:
                    logger.debug("写入日志文件失败: %s", e)

    def close(self):
        """关闭当前日志文件（程序退出时必须调用）。

        将当前 -running.log 文件重命名为最终文件名（带结束时间），
        然后安全关闭文件句柄。
        """
        with self._lock:
            if self._file:
                self._rename_to_finished()
                try:
                    self._file.close()
                except Exception as e:
                    logger.debug("关闭日志文件失败: %s", e)
                self._file = None

    def start_midnight_checker(self, root, check_interval_ms=30000):
        """
        在 tkinter 主线程中启动跨天定时检查。

        每隔 check_interval_ms 毫秒检查一次是否跨天，
        如果检测到日期变更，自动关闭旧文件并创建新文件。

        必须在主线程（tkinter 事件循环所在线程）调用，
        因为使用了 root.after() 来调度定时器。

        Parameters
        ----------
        root              : tk.Tk
            主窗口对象，用于调用 .after() 和 .winfo_exists()
        check_interval_ms : int
            检查间隔（毫秒），默认 30 秒（30000 ms）
        """

        def _check():
            """定时检查函数，通过 .after() 递归调度自身"""
            now = datetime.now()
            with self._lock:
                if self._current_date and now.date() != self._current_date:
                    # 跨天了 —— 先把旧文件写好并关闭
                    if self._file:
                        self._rename_to_finished()
                        try:
                            self._file.close()
                        except Exception as e:
                            logger.debug("跨天检查时关闭旧日志文件失败: %s", e)
                        self._file = None
                    # 创建新日期的日志文件
                    self._open_file(now)
            # 继续调度下次检查（窗口仍存在时）
            if root.winfo_exists():
                self._midnight_timer = root.after(check_interval_ms, _check)

        self._midnight_timer = root.after(check_interval_ms, _check)

    def cancel_midnight_checker(self, root):
        """取消跨天定时器（程序退出时调用，避免残留定时器）。

        Parameters
        ----------
        root : tk.Tk
            主窗口对象，用于调用 .after_cancel()
        """
        if self._midnight_timer:
            try:
                root.after_cancel(self._midnight_timer)
            except Exception as e:
                logger.debug("取消跨天定时器失败: %s", e)
            self._midnight_timer = None

    # ── 内部方法 ────────────────────────────────────────

    def _open_file(self, now: datetime = None):
        """打开一个新的日志文件（调用方需已持有锁）。

        文件格式: {date}_{time}-running.log
        写入日志启动分隔头。

        Parameters
        ----------
        now : datetime | None
            当前时间，为 None 时使用 datetime.now()
        """
        if now is None:
            now = datetime.now()
        self._start_dt = now
        self._current_date = now.date()

        date_str = now.strftime("%Y%m%d")
        time_str = now.strftime("%H%M%S")
        filename = f"{date_str}_{time_str}-running.log"
        filepath = os.path.join(self._log_dir, filename)

        self._file = open(filepath, "a", encoding="utf-8")
        # 写入日志分隔头，方便在文本编辑器中区分不同运行会话
        self._file.write(f"{'=' * 60}\n")
        self._file.write(f"  日志启动: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
        self._file.write(f"{'=' * 60}\n")

    def _ensure_date(self, now: datetime):
        """检查是否跨天（对非主线程的 write 调用做兜底检测）。

        如果检测到当前日期与日志文件日期不一致，自动关闭旧文件并创建新文件。
        这是主线程跨天定时器之外的被动防护手段。

        Parameters
        ----------
        now : datetime
            当前的日志写入时间
        """
        if self._current_date and now.date() != self._current_date:
            if self._file:
                self._rename_to_finished()
                try:
                    self._file.close()
                except Exception as e:
                    logger.debug("日志日期切换时关闭旧文件失败: %s", e)
                self._file = None
            self._open_file(now)

    def _rename_to_finished(self):
        """将 -running.log 重命名为最终文件名（调用方需已持有锁）。

        重命名后重新打开新路径的文件以保持 self._file 有效。
        如果已跨天，结束时间自动设置为当天 23:59:59。
        """
        if not self._file or not self._start_dt:
            return

        end_dt = datetime.now()
        # 如果跨天关闭，结束时间设置为当天 23:59:59
        if end_dt.date() != self._current_date:
            end_dt = datetime.combine(self._current_date, datetime.max.time().replace(microsecond=0))

        start_str = self._start_dt.strftime("%H%M%S")
        end_str = end_dt.strftime("%H%M%S")
        date_str = self._current_date.strftime("%Y%m%d")
        new_name = f"{date_str}_{start_str}-{end_str}.log"

        try:
            old_path = self._file.name
            new_path = os.path.join(self._log_dir, new_name)
            self._file.flush()
            self._file.close()
            os.replace(old_path, new_path)  # 原子重命名（Windows 上等同于 os.rename）
            # 重新打开供后续使用（虽然 close 后不会再用，但保险起见）
            self._file = open(new_path, "a", encoding="utf-8")
        except Exception as e:
            # 重命名失败后重新打开原文件（防止 self._file 处于已关闭状态）
            logger.debug("重命名日志文件失败: %s", e)
            try:
                self._file = open(old_path, "a", encoding="utf-8")
            except Exception:
                pass
