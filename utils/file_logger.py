"""
文件日志处理器 - 自动按天分文件写入日志

日志文件存储路径: data/log/
文件命名规则:   YYYYMMDD_HHmmss-结束时间.log
跨天处理:       到达当天 23:59:59 时自动关闭当前文件，创建新文件
"""

import os
import threading
from datetime import datetime, timedelta


class FileLogger:
    """线程安全的文件日志器，每天自动切换日志文件。"""

    def __init__(self, log_dir: str):
        """
        Parameters
        ----------
        log_dir : str
            日志文件存放目录，如 'data/log'
        """
        self._log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

        self._lock = threading.Lock()
        self._file = None
        self._current_date = None      # 当前日志文件对应的日期 (date 对象)
        self._start_dt = None          # 当前日志文件的起始时间 (datetime)
        self._midnight_timer = None    # 跨天切换的 after id (仅主线程)

        # 立即打开第一个日志文件
        self._open_file()

    # ── 公共接口 ───────────────────────────────────

    def write(self, level: str, message: str, ts: datetime = None):
        """
        写入一条日志。

        Parameters
        ----------
        level   : str               日志等级 (DEBUG/INFO/WARNING/ERROR)
        message : str               日志内容
        ts      : datetime | None   时间戳，默认 datetime.now()
        """
        if ts is None:
            ts = datetime.now()

        line = f"[{ts.strftime('%H:%M:%S')}] [{level:>7s}] {message}\n"

        with self._lock:
            self._ensure_date(ts)
            if self._file:
                try:
                    self._file.write(line)
                    self._file.flush()
                except Exception:
                    pass

    def close(self):
        """关闭当前日志文件（在退出时调用）。"""
        with self._lock:
            if self._file:
                self._rename_to_finished()
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None

    def start_midnight_checker(self, root, check_interval_ms=30000):
        """
        在 tkinter 主线程中启动跨天定时检查。

        Parameters
        ----------
        root              : tk.Tk          主窗口
        check_interval_ms : int            检查间隔（毫秒），默认 30 秒
        """
        def _check():
            now = datetime.now()
            with self._lock:
                if self._current_date and now.date() != self._current_date:
                    # 跨天了 —— 先把旧文件写好关闭
                    if self._file:
                        self._rename_to_finished()
                        try:
                            self._file.close()
                        except Exception:
                            pass
                        self._file = None
                    # 新文件
                    self._open_file(now)
            # 继续下次检查
            if root.winfo_exists():
                self._midnight_timer = root.after(check_interval_ms, _check)

        self._midnight_timer = root.after(check_interval_ms, _check)

    def cancel_midnight_checker(self, root):
        """取消跨天定时器（退出时调用）。"""
        if self._midnight_timer:
            try:
                root.after_cancel(self._midnight_timer)
            except Exception:
                pass
            self._midnight_timer = None

    # ── 内部方法 ───────────────────────────────────

    def _open_file(self, now: datetime = None):
        """打开一个新的日志文件（内部已持有锁）。"""
        if now is None:
            now = datetime.now()
        self._start_dt = now
        self._current_date = now.date()

        date_str = now.strftime("%Y%m%d")
        time_str = now.strftime("%H%M%S")
        filename = f"{date_str}_{time_str}-running.log"
        filepath = os.path.join(self._log_dir, filename)

        self._file = open(filepath, "a", encoding="utf-8")
        # 写入分隔头
        self._file.write(f"{'='*60}\n")
        self._file.write(f"  日志启动: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
        self._file.write(f"{'='*60}\n")

    def _ensure_date(self, now: datetime):
        """检查是否跨天（仅对非主线程的 write 调用做兜底）。"""
        if self._current_date and now.date() != self._current_date:
            if self._file:
                self._rename_to_finished()
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None
            self._open_file(now)

    def _rename_to_finished(self):
        """将 running.log 重命名为最终文件名（内部已持有锁）。"""
        if not self._file or not self._start_dt:
            return

        end_dt = datetime.now()
        # 如果跨天关闭，结束时间用 23:59:59
        if end_dt.date() != self._current_date:
            end_dt = datetime.combine(self._current_date,
                                      datetime.max.time().replace(microsecond=0))

        start_str = self._start_dt.strftime("%H%M%S")
        end_str = end_dt.strftime("%H%M%S")
        date_str = self._current_date.strftime("%Y%m%d")
        new_name = f"{date_str}_{start_str}-{end_str}.log"

        try:
            old_path = self._file.name
            new_path = os.path.join(self._log_dir, new_name)
            self._file.flush()
            self._file.close()
            os.rename(old_path, new_path)
            # 重新打开供后续使用（虽然 close 不会再写，但保险起见）
            self._file = open(new_path, "a", encoding="utf-8")
        except Exception:
            # 重命名失败不影响运行，文件内容仍在
            pass
