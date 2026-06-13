"""
日志面板模块 - CustomTkinter 版
"""

import tkinter as tk
from tkinter import ttk
from datetime import datetime
import queue
import logging
import customtkinter as ctk

from ui.theme import C

logger = logging.getLogger(__name__)


class LogPanelHandler(logging.Handler):
    """将 Python logging 标准库的日志接入 GUI 日志面板"""

    LEVEL_MAP = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARNING",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "ERROR",
    }

    def __init__(self, log_panel: "LogPanel"):
        super().__init__()
        self._log_panel = log_panel

    def emit(self, record: logging.LogRecord):
        """将日志记录转发到 GUI 日志面板"""
        level = self.LEVEL_MAP.get(record.levelno, "INFO")
        msg = self.format(record)
        try:
            self._log_panel.add_log(level, msg)
        except Exception as e:
            logger.debug("日志面板桥接写入失败: %s", e)


_LOGGER_HANDLER_INSTALLED = False


def install_logging_bridge(log_panel: "LogPanel", level=logging.INFO):
    """将核心模块的 logging 输出桥接到 GUI 日志面板

    调用一次即可，会自动附加到所有关心的 logger
    """
    global _LOGGER_HANDLER_INSTALLED
    if _LOGGER_HANDLER_INSTALLED:
        return

    handler = LogPanelHandler(log_panel)
    handler.setLevel(level)
    fmt = logging.Formatter("%(name)s:%(message)s")
    handler.setFormatter(fmt)

    for name in ("core.bilibili_api", "core.proxy_manager", "core.database", "algorithms", "utils"):
        logger = logging.getLogger(name)
        logger.addHandler(handler)
        logger.setLevel(level)

    _LOGGER_HANDLER_INSTALLED = True


class LogPanel:
    """日志面板 — 构建和管理应用日志显示，支持等级筛选、线程安全添加、增量渲染"""

    _MAX_ENTRIES = 1000         # 内存日志条目上限
    _MAX_TEXT_LINES = 3000      # Text widget 行数上限
    _QUEUE_MAXSIZE = 1000       # 日志队列容量上限
    _QUEUE_BATCH = 100          # 每 tick 最多处理条数

    def __init__(self, parent, file_logger):
        self.root = parent
        self._file_logger = file_logger
        self._log_entries = []  # [(level, timestamp_str, message), ...]
        self._log_level_var = tk.StringVar(value="ALL")
        self._log_refresh_job = None
        self._rendered_count = 0
        self._text_line_count = 0  # Text widget 当前行数
        self._dirty = False        # 自上次刷新以来是否有新日志
        # 线程安全日志队列（有界）
        self._log_queue = queue.Queue(maxsize=self._QUEUE_MAXSIZE)
        self._queue_processing = False

        self._build()

    def _build(self):
        """构建日志面板 UI"""
        self._log_frame = ctk.CTkFrame(self.root, fg_color=C["bg_base"], corner_radius=0)

        toolbar = ctk.CTkFrame(self._log_frame, fg_color=C["bg_surface"], corner_radius=0)
        toolbar.pack(fill=tk.X)

        ctk.CTkLabel(
            toolbar,
            text="应用日志",
            text_color=C["text_1"],
            font=("Microsoft YaHei UI", 10, "bold"),
            fg_color="transparent",
        ).pack(side=tk.LEFT, padx=14, pady=8)

        self._log_levels = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"]
        self._log_level_btns = {}
        level_colors = {
            "ALL": C["text_2"],
            "DEBUG": "#8b949e",
            "INFO": C["accent"],
            "WARNING": C["warning"],
            "ERROR": C["danger"],
        }
        for lvl in self._log_levels:
            fg = level_colors.get(lvl, C["text_2"])
            btn = ctk.CTkLabel(
                toolbar,
                text=lvl,
                fg_color=C["bg_elevated"] if lvl == "ALL" else C["bg_hover"],
                text_color=C["bilibili"] if lvl == "ALL" else fg,
                font=("Consolas", 9),
                cursor="hand2",
                corner_radius=4,
            )
            btn.pack(side=tk.LEFT, padx=(2, 0), pady=6)
            btn.bind("<Button-1>", lambda e, lvl_=lvl: self.set_log_level(lvl_))
            btn.bind("<Enter>", lambda e, b=btn: b.configure(fg_color=C["bg_elevated"]))
            btn.bind(
                "<Leave>",
                lambda e, b=btn, lvl_=lvl: b.configure(
                    fg_color=C["bg_elevated"] if lvl_ == self._log_level_var.get() else C["bg_hover"]
                ),
            )
            self._log_level_btns[lvl] = btn

        # 清空按钮
        clear_lbl = ctk.CTkLabel(
            toolbar,
            text="🗑 清空",
            text_color=C["text_3"],
            font=("Microsoft YaHei UI", 9),
            cursor="hand2",
            fg_color="transparent",
        )
        clear_lbl.pack(side=tk.RIGHT, padx=14, pady=6)
        clear_lbl.bind("<Button-1>", lambda e: self.clear_log())
        clear_lbl.bind("<Enter>", lambda e: clear_lbl.configure(text_color=C["danger"]))
        clear_lbl.bind("<Leave>", lambda e: clear_lbl.configure(text_color=C["text_3"]))

        tk.Frame(self._log_frame, bg=C["border"], height=1).pack(fill=tk.X)

        log_container = ctk.CTkFrame(self._log_frame, fg_color=C["bg_base"], corner_radius=0)
        log_container.pack(fill=tk.BOTH, expand=True)

        self._log_text = tk.Text(
            log_container,
            bg=C["canvas_bg"],
            fg=C["canvas_text"],
            font=("Consolas", 10),
            wrap=tk.WORD,
            bd=0,
            highlightthickness=0,
            insertbackground=C["text_1"],
            state=tk.DISABLED,
            cursor="arrow",
        )
        log_sb = ttk.Scrollbar(log_container, orient="vertical", command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_sb.set)
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        log_sb.pack(side=tk.RIGHT, fill=tk.Y)

        # 日志颜色标签
        self._log_text.tag_configure("DEBUG", foreground=C["log_debug"])
        self._log_text.tag_configure("INFO", foreground=C["log_info"])
        self._log_text.tag_configure("WARNING", foreground=C["log_warn"])
        self._log_text.tag_configure("ERROR", foreground=C["log_error"])
        self._log_text.tag_configure("TIME", foreground=C["log_time"])

        # 启动队列处理器
        self.root.after(200, self._process_log_queue)

    @property
    def frame(self):
        return self._log_frame

    def set_log_level(self, level):
        """设置日志过滤等级，更新按钮样式并刷新显示"""
        self._log_level_var.set(level)
        for lvl, btn in self._log_level_btns.items():
            is_active = lvl == level
            btn.configure(
                fg_color=C["bg_elevated"] if is_active else C["bg_hover"],
                text_color=C["bilibili"] if is_active else C["text_2"],
            )
        self._rendered_count = 0
        self.refresh_log_view()

    _LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}

    def _should_show(self, level: str) -> bool:
        """判断指定级别的日志是否应显示在当前过滤条件下"""
        filter_level = self._log_level_var.get()
        if filter_level == "ALL":
            return True
        # 比较级别数值，>= 过滤级别才显示
        min_severity = self._LEVEL_ORDER.get(filter_level, 0)
        msg_severity = self._LEVEL_ORDER.get(level, 0)
        return msg_severity >= min_severity

    def add_log(self, level: str, message: str):
        """线程安全地添加日志（可被任何线程调用）。"""
        ts = datetime.now()
        ts_str = ts.strftime("%H:%M:%S")
        # 超过上限时裁剪到 70%
        if len(self._log_entries) >= self._MAX_ENTRIES:
            removed = len(self._log_entries) - int(self._MAX_ENTRIES * 0.7)
            self._log_entries = self._log_entries[-int(self._MAX_ENTRIES * 0.7):]
            self._rendered_count = max(0, self._rendered_count - removed)
        self._log_entries.append((level, ts_str, message))
        try:
            self._file_logger.write(level, message, ts)
        except Exception:
            pass

        if self._should_show(level):
            try:
                self._log_queue.put_nowait((level, ts, message))
            except queue.Full:
                pass  # 队列满时丢弃，防止内存暴涨
            self._dirty = True
            if not self._queue_processing:
                self.root.after(0, self._process_log_queue)

    def _process_log_queue(self):
        """主线程：处理日志队列，每次最多处理 _QUEUE_BATCH 条。"""
        self._queue_processing = True
        processed = 0
        try:
            while processed < self._QUEUE_BATCH:
                level, ts, message = self._log_queue.get_nowait()
                self._append_log_line(level, ts, message)
                self._rendered_count += 1
                self._text_line_count += 1
                processed += 1
        except queue.Empty:
            pass
        finally:
            self._queue_processing = False
            if processed == self._QUEUE_BATCH and not self._log_queue.empty():
                self.root.after(50, self._process_log_queue)
            self._dirty = not self._log_queue.empty()
            # Text widget 行数上限裁剪
            self._trim_text_widget()

    def _append_log_line(self, level, ts, message):
        """主线程：追加一行日志到 Text widget。"""
        ts_str = ts.strftime("%H:%M:%S") if isinstance(ts, datetime) else str(ts)
        self._log_text.config(state=tk.NORMAL)
        self._log_text.insert(tk.END, f"[{ts_str}] ", "TIME")
        self._log_text.insert(tk.END, f"[{level:>7s}] ", level)
        self._log_text.insert(tk.END, f"{message}\n")
        self._log_text.see(tk.END)
        self._log_text.config(state=tk.DISABLED)

    def _trim_text_widget(self):
        """Text widget 行数超上限时从头部裁剪。"""
        if self._text_line_count <= self._MAX_TEXT_LINES:
            return
        trim = self._text_line_count - int(self._MAX_TEXT_LINES * 0.8)
        self._log_text.config(state=tk.NORMAL)
        # 删除前 trim 行：计算第 trim+1 行的字符位置
        pos = self._log_text.index(f"{trim + 1}.0")
        self._log_text.delete("1.0", pos)
        self._log_text.config(state=tk.DISABLED)
        self._text_line_count -= trim

    def refresh_log_view(self):
        """根据当前等级筛选全量刷新日志显示。"""
        self._log_text.config(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        self._text_line_count = 0
        for level, ts, msg in self._log_entries:
            if self._should_show(level):
                self._log_text.insert(tk.END, f"[{ts}] ", "TIME")
                self._log_text.insert(tk.END, f"[{level:>7s}] ", level)
                self._log_text.insert(tk.END, f"{msg}\n")
                self._text_line_count += 1
        self._rendered_count = len(self._log_entries)
        self._log_text.see(tk.END)
        self._log_text.config(state=tk.DISABLED)
        self._dirty = False

    def clear_log(self):
        """清空日志缓冲区和显示。"""
        self._log_entries.clear()
        self._rendered_count = 0
        self._text_line_count = 0
        self._dirty = False
        self._log_text.config(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        self._log_text.config(state=tk.DISABLED)

    def start_auto_refresh(self, root):
        """启动日志自动刷新定时器（每 5 秒，无变更时跳过）。"""
        self.stop_auto_refresh()
        self._log_refresh_job = root.after(5000, self._auto_refresh_tick)

    def _auto_refresh_tick(self):
        """定时器触发：仅在有新日志时刷新，否则跳过。"""
        if self._dirty:
            self.refresh_log_view()
        self._log_refresh_job = self.root.after(5000, self._auto_refresh_tick)

    def stop_auto_refresh(self):
        """停止自动刷新定时器"""
        if self._log_refresh_job:
            try:
                self.root.after_cancel(self._log_refresh_job)
            except Exception as e:
                logger.debug("取消自动刷新定时器失败: %s", e)
            self._log_refresh_job = None

    def cleanup(self):
        """清理资源：停止自动刷新"""
        self.stop_auto_refresh()
