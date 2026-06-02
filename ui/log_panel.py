"""
日志面板模块

提供应用级别的 GUI 日志显示面板，支持:
  - 将 Python logging 标准库的输出桥接到 GUI 文本控件
  - 按日志等级（DEBUG/INFO/WARNING/ERROR）筛选显示
  - 线程安全的日志添加（通过队列 + 主线程轮询处理）
  - 增量渲染优化（只追加新条目，避免全量重建）
  - 自动裁剪（超过 2000 条时裁剪到 1500 条）
  - 5 秒自动刷新定时器

主要组件:
    LogPanelHandler     — 将 logging 模块日志转发到 LogPanel
    install_logging_bridge — 一键安装日志桥接
    LogPanel            — 日志面板 UI 组件
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
    """将 Python logging 标准库的日志接入 GUI 日志面板

    继承自 logging.Handler，重写 emit() 方法，
    将日志记录转发到 LogPanel.add_log()。
    """

    # 日志等级名称映射表
    LEVEL_MAP = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARNING",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "ERROR",
    }

    def __init__(self, log_panel: "LogPanel"):
        """
        Args:
            log_panel: 目标 LogPanel 实例
        """
        super().__init__()
        self._log_panel = log_panel

    def emit(self, record: logging.LogRecord):
        """将日志记录转发到 GUI 日志面板

        Args:
            record: Python logging 模块的 LogRecord 对象
        """
        level = self.LEVEL_MAP.get(record.levelno, "INFO")
        msg = self.format(record)
        try:
            self._log_panel.add_log(level, msg)
        except Exception as e:
            # 桥接自身写入失败时使用标准 logger 输出（避免递归）
            logger.debug("日志面板桥接写入失败: %s", e)


# 全局标记：防止重复安装日志桥接
_LOGGER_HANDLER_INSTALLED = False


def install_logging_bridge(log_panel: "LogPanel", level=logging.INFO):
    """将核心模块的 logging 输出桥接到 GUI 日志面板

    调用一次即可，会自动附加到所有关心的模块 logger。
    内置防重复安装保护。

    Args:
        log_panel: LogPanel 实例
        level: 最低日志级别（默认 INFO）
    """
    global _LOGGER_HANDLER_INSTALLED
    if _LOGGER_HANDLER_INSTALLED:
        return

    handler = LogPanelHandler(log_panel)
    handler.setLevel(level)
    fmt = logging.Formatter("%(name)s:%(message)s")
    handler.setFormatter(fmt)

    # 挂载到核心模块的 logger 上
    for name in ("core.bilibili_api", "core.proxy_manager", "core.database", "algorithms", "utils"):
        mod_logger = logging.getLogger(name)
        mod_logger.addHandler(handler)
        mod_logger.setLevel(level)

    _LOGGER_HANDLER_INSTALLED = True


class LogPanel:
    """日志面板 — 构建和管理应用日志显示，支持等级筛选、线程安全添加、增量渲染

    核心设计:
      - 日志缓冲区 _log_entries: 存储 (level, timestamp_str, message) 三元组
      - 队列 _log_queue: 线程安全的消息队列，工作线程通过 add_log() 写入
      - 主线程轮询 _process_log_queue: 每 200ms 处理队列中的消息并追加到 Text 控件
      - 增量渲染: _rendered_count 记录已渲染条目，只追加新条目
      - 等级筛选: _should_show() 根据当前选中的最小可见级别过滤
    """

    def __init__(self, parent, file_logger):
        """
        Args:
            parent: 父 Tkinter 容器
            file_logger: FileLogger 实例，用于同时写入文件日志
        """
        self.root = parent
        self._file_logger = file_logger
        self._log_entries = []  # 日志缓冲区: [(level, timestamp_str, message), ...]
        self._log_level_var = tk.StringVar(value="ALL")  # 当前筛选等级
        self._log_refresh_job = None  # 自动刷新定时器 ID
        self._rendered_count = 0  # 已渲染的条目数，用于增量刷新
        # 线程安全日志队列（工作者线程写入，主线程消费）
        self._log_queue = queue.Queue()
        self._queue_processing = False  # 防止并发处理队列

        self._build()

    def _build(self):
        """构建日志面板 UI：工具栏（等级筛选 + 清空按钮）+ 日志文本区域 + 滚动条"""
        self._log_frame = ctk.CTkFrame(self.root, fg_color=C["bg_base"], corner_radius=0)

        # ── 工具栏 ──
        toolbar = ctk.CTkFrame(self._log_frame, fg_color=C["bg_surface"], corner_radius=0)
        toolbar.pack(fill=tk.X)

        ctk.CTkLabel(
            toolbar,
            text="应用日志",
            text_color=C["text_1"],
            font=("Microsoft YaHei UI", 10, "bold"),
            fg_color="transparent",
        ).pack(side=tk.LEFT, padx=14, pady=8)

        # 日志等级筛选按钮
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
            # 绑定点击事件：切换筛选等级
            btn.bind("<Button-1>", lambda e, lvl_=lvl: self.set_log_level(lvl_))
            # 鼠标悬浮高亮效果
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

        # 分隔线
        tk.Frame(self._log_frame, bg=C["border"], height=1).pack(fill=tk.X)

        # ── 日志文本区域 ──
        log_container = ctk.CTkFrame(self._log_frame, fg_color=C["bg_base"], corner_radius=0)
        log_container.pack(fill=tk.BOTH, expand=True)

        # 使用原生 tk.Text 以获得更好的性能和灵活性
        self._log_text = tk.Text(
            log_container,
            bg=C["canvas_bg"],
            fg=C["canvas_text"],
            font=("Consolas", 10),
            wrap=tk.WORD,
            bd=0,
            highlightthickness=0,
            insertbackground=C["text_1"],
            state=tk.DISABLED,  # 只读模式，防止用户编辑
            cursor="arrow",
        )
        log_sb = ttk.Scrollbar(log_container, orient="vertical", command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_sb.set)
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        log_sb.pack(side=tk.RIGHT, fill=tk.Y)

        # 配置 Text 控件的文本标签样式（不同等级不同颜色）
        self._log_text.tag_configure("DEBUG", foreground=C["log_debug"])
        self._log_text.tag_configure("INFO", foreground=C["log_info"])
        self._log_text.tag_configure("WARNING", foreground=C["log_warn"])
        self._log_text.tag_configure("ERROR", foreground=C["log_error"])
        self._log_text.tag_configure("TIME", foreground=C["log_time"])

        # 启动队列处理器（每 200ms 轮询一次日志队列）
        self.root.after(200, self._process_log_queue)

    @property
    def frame(self):
        """获取日志面板的 Tkinter Frame 对象，用于布局管理"""
        return self._log_frame

    def set_log_level(self, level):
        """设置日志过滤等级，更新按钮样式并刷新显示

        Args:
            level: 日志等级字符串（"ALL"/"DEBUG"/"INFO"/"WARNING"/"ERROR"）
        """
        self._log_level_var.set(level)
        # 更新按钮的高亮/普通样式
        for lvl, btn in self._log_level_btns.items():
            is_active = lvl == level
            btn.configure(
                fg_color=C["bg_elevated"] if is_active else C["bg_hover"],
                text_color=C["bilibili"] if is_active else C["text_2"],
            )
        # 重置渲染计数，触发全量重建
        self._rendered_count = 0
        self.refresh_log_view()

    # 日志等级的数字序数映射（用于判断 "是否应该显示此等级的日志"）
    _LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}

    def _should_show(self, level: str) -> bool:
        """判断指定级别的日志是否应显示在当前过滤条件下

        Args:
            level: 日志等级字符串

        Returns:
            bool: 是否应该显示（当前筛选等级为 ALL 时始终显示）
        """
        filter_level = self._log_level_var.get()
        if filter_level == "ALL":
            return True
        # 比较级别数值：只有 >= 过滤级别的才显示（如选 WARNING 则不显示 INFO）
        min_severity = self._LEVEL_ORDER.get(filter_level, 0)
        msg_severity = self._LEVEL_ORDER.get(level, 0)
        return msg_severity >= min_severity

    def add_log(self, level: str, message: str):
        """线程安全地添加日志（可被任何线程调用）

        内部流程:
          1. 追加到 _log_entries 缓冲区
          2. 同时写入文件日志
          3. 超过 2000 条时自动裁剪到 1500 条
          4. 通过队列放入待渲染消息

        Args:
            level: 日志等级（"DEBUG"/"INFO"/"WARNING"/"ERROR"）
            message: 日志消息文本
        """
        ts = datetime.now()
        ts_str = ts.strftime("%H:%M:%S")
        self._log_entries.append((level, ts_str, message))
        # 同步写入文件日志
        try:
            self._file_logger.write(level, message, ts)
        except Exception as e:
            logger.debug("写文件日志失败: %s", e)
        # 日志超过 2000 条时裁剪到 1500 条（防止内存无限增长）
        if len(self._log_entries) > 2000:
            removed = len(self._log_entries) - 1500
            self._log_entries = self._log_entries[-1500:]
            self._rendered_count = max(0, self._rendered_count - removed)
            if self._rendered_count == 0 and removed > 0:
                self.root.after(0, self.refresh_log_view)

        # 若当前过滤等级满足条件，放入队列等待主线程渲染
        if self._should_show(level):
            self._log_queue.put((level, ts, message))
            if not self._queue_processing:
                self.root.after(0, self._process_log_queue)

    def _process_log_queue(self):
        """主线程：处理日志队列（由 root.after 调度），每次最多处理 100 条

        使用批量处理减少 UI 刷新次数，同时限制单次处理量避免阻塞主线程。
        若队列中仍有待处理消息，通过 root.after 重新调度。
        """
        self._queue_processing = True
        processed = 0
        try:
            while processed < 100:
                level, ts, message = self._log_queue.get_nowait()
                self._append_log_line(level, ts, message)
                self._rendered_count += 1
                processed += 1
        except queue.Empty:
            pass
        finally:
            self._queue_processing = False
            # 还有剩余日志，延迟 50ms 后再处理
            if processed == 100 and not self._log_queue.empty():
                self.root.after(50, self._process_log_queue)

    def _append_log_line(self, level, ts, message):
        """主线程：实际追加日志到文本控件

        将时间戳、等级标签、消息内容分别以不同 tag 插入 Text 控件

        Args:
            level: 日志等级字符串
            ts: datetime 时间戳
            message: 日志消息
        """
        ts_str = ts.strftime("%H:%M:%S") if isinstance(ts, datetime) else str(ts)
        self._log_text.config(state=tk.NORMAL)
        self._log_text.insert(tk.END, f"[{ts_str}] ", "TIME")       # 时间戳（灰色）
        self._log_text.insert(tk.END, f"[{level:>7s}] ", level)     # 等级标签（彩色）
        self._log_text.insert(tk.END, f"{message}\n")               # 消息内容
        self._log_text.see(tk.END)  # 自动滚动到最新
        self._log_text.config(state=tk.DISABLED)

    def refresh_log_view(self):
        """根据当前等级筛选刷新日志显示（增量追加，避免全量重建）

        首次渲染或过滤条件切换时全量重建 Text 控件内容；
        之后只追加新增条目，大幅减少 UI 刷新开销。
        """
        current_count = len(self._log_entries)
        if current_count == 0:
            return

        # 首次渲染或过滤条件切换时全量重建
        if self._rendered_count == 0:
            self._log_text.config(state=tk.NORMAL)
            self._log_text.delete("1.0", tk.END)
            for level, ts, msg in self._log_entries:
                if self._should_show(level):
                    self._log_text.insert(tk.END, f"[{ts}] ", "TIME")
                    self._log_text.insert(tk.END, f"[{level:>7s}] ", level)
                    self._log_text.insert(tk.END, f"{msg}\n")
            self._rendered_count = current_count
            self._log_text.see(tk.END)
            self._log_text.config(state=tk.DISABLED)
            return

        # 增量追加：只添加新增的条目（优化性能）
        if current_count > self._rendered_count:
            self._log_text.config(state=tk.NORMAL)
            for level, ts, msg in self._log_entries[self._rendered_count :]:
                if self._should_show(level):
                    self._log_text.insert(tk.END, f"[{ts}] ", "TIME")
                    self._log_text.insert(tk.END, f"[{level:>7s}] ", level)
                    self._log_text.insert(tk.END, f"{msg}\n")
            self._rendered_count = current_count
            self._log_text.see(tk.END)
            self._log_text.config(state=tk.DISABLED)

    def clear_log(self):
        """清空日志缓冲区和显示内容"""
        self._log_entries.clear()
        self._rendered_count = 0
        self._log_text.config(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        self._log_text.config(state=tk.DISABLED)

    def start_auto_refresh(self, root):
        """启动日志自动刷新定时器（每 5 秒执行一次）

        Args:
            root: Tkinter 根窗口（用于 after 调度）
        """
        self.stop_auto_refresh()
        self._log_refresh_job = root.after(5000, self._auto_refresh_tick)

    def _auto_refresh_tick(self):
        """定时器触发：刷新日志并重新调度下一次"""
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
        """清理资源：停止自动刷新定时器"""
        self.stop_auto_refresh()
