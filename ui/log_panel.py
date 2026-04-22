"""
日志面板模块
"""
import tkinter as tk
from tkinter import ttk
from datetime import datetime
from ui.theme import C, _recolor_text_tags


class LogPanel:
    """日志面板 - 构建和管理应用日志显示"""

    def __init__(self, parent, file_logger):
        """
        Args:
            parent: 父容器（通常是 root）
            file_logger: FileLogger 实例
        """
        self.root = parent
        self._file_logger = file_logger
        self._log_entries = []   # [(level, timestamp_str, message), ...]
        self._log_level_var = tk.StringVar(value="ALL")
        self._log_refresh_job = None

        self._build()

    def _build(self):
        """构建日志面板 UI"""
        self._log_frame = tk.Frame(self.root, bg=C["bg_base"])

        toolbar = tk.Frame(self._log_frame, bg=C["bg_surface"])
        toolbar.pack(fill=tk.X)

        tk.Label(toolbar, text="应用日志", bg=C["bg_surface"], fg=C["text_1"],
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side=tk.LEFT, padx=14, pady=8)

        self._log_levels = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"]
        self._log_level_btns = {}
        level_colors = {
            "ALL": C["text_2"], "DEBUG": "#8b949e",
            "INFO": C["accent"], "WARNING": C["warning"], "ERROR": C["danger"],
        }
        for lvl in self._log_levels:
            fg = level_colors.get(lvl, C["text_2"])
            btn = tk.Label(toolbar, text=lvl, bg=C["bg_elevated"] if lvl == "ALL" else C["bg_hover"],
                           fg=C["bilibili"] if lvl == "ALL" else fg,
                           font=("Consolas", 9), cursor="hand2", padx=8, pady=3)
            btn.pack(side=tk.LEFT, padx=(2, 0), pady=6)
            btn.bind("<Button-1>", lambda e, l=lvl: self.set_log_level(l))
            btn.bind("<Enter>", lambda e, b=btn: b.config(bg=C["bg_elevated"]))
            btn.bind("<Leave>", lambda e, b=btn, l=lvl:
                     b.config(bg=C["bg_elevated"] if l == self._log_level_var.get() else C["bg_hover"]))
            self._log_level_btns[lvl] = btn

        # 清空按钮
        clear_lbl = tk.Label(toolbar, text="🗑 清空", bg=C["bg_surface"], fg=C["text_3"],
                             font=("Microsoft YaHei UI", 9), cursor="hand2", padx=8, pady=3)
        clear_lbl.pack(side=tk.RIGHT, padx=14, pady=6)
        clear_lbl.bind("<Button-1>", lambda e: self.clear_log())
        clear_lbl.bind("<Enter>", lambda e: clear_lbl.config(fg=C["danger"]))
        clear_lbl.bind("<Leave>", lambda e: clear_lbl.config(fg=C["text_3"]))

        tk.Frame(self._log_frame, bg=C["border"], height=1).pack(fill=tk.X)

        log_container = tk.Frame(self._log_frame, bg=C["bg_base"])
        log_container.pack(fill=tk.BOTH, expand=True)

        self._log_text = tk.Text(log_container, bg=C["canvas_bg"], fg=C["canvas_text"],
                                  font=("Consolas", 10), wrap=tk.WORD,
                                  bd=0, highlightthickness=0,
                                  insertbackground=C["text_1"],
                                  state=tk.DISABLED, cursor="arrow")
        log_sb = ttk.Scrollbar(log_container, orient="vertical",
                                command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_sb.set)
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        log_sb.pack(side=tk.RIGHT, fill=tk.Y)

        # 日志颜色标签
        self._log_text.tag_configure("DEBUG", foreground="#8b949e")
        self._log_text.tag_configure("INFO",  foreground="#58a6ff")
        self._log_text.tag_configure("WARNING", foreground="#d29922")
        self._log_text.tag_configure("ERROR", foreground="#f85149")
        self._log_text.tag_configure("TIME",  foreground="#6e7681")

    @property
    def frame(self):
        """返回日志面板的 Frame（用于 pack/pack_forget 切换）"""
        return self._log_frame

    def set_log_level(self, level):
        self._log_level_var.set(level)
        for l, btn in self._log_level_btns.items():
            is_active = (l == level)
            btn.config(
                bg=C["bg_elevated"] if is_active else C["bg_hover"],
                fg=C["bilibili"] if is_active else C["text_2"],
            )
        self.refresh_log_view()

    # 日志级别优先级：数字越大越严重
    _LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}

    def _should_show(self, level: str) -> bool:
        """根据当前过滤级别判断该条日志是否应显示"""
        filter_level = self._log_level_var.get()
        if filter_level == "ALL":
            return True
        min_severity = self._LEVEL_ORDER.get(filter_level, 0)
        msg_severity = self._LEVEL_ORDER.get(level, 0)
        return msg_severity >= min_severity

    def add_log(self, level: str, message: str):
        """添加日志条目"""
        ts = datetime.now()
        ts_str = ts.strftime("%H:%M:%S")
        self._log_entries.append((level, ts_str, message))
        try:
            self._file_logger.write(level, message, ts)
        except Exception:
            pass
        if len(self._log_entries) > 2000:
            self._log_entries = self._log_entries[-1500:]
        # 如果日志面板可见且等级匹配，实时追加
        if self._log_frame.winfo_ismapped() and self._should_show(level):
            self._append_log_line(level, ts, message)

    def _append_log_line(self, level, ts, message):
        self._log_text.config(state=tk.NORMAL)
        self._log_text.insert(tk.END, f"[{ts}] ", "TIME")
        self._log_text.insert(tk.END, f"[{level:>7s}] ", level)
        self._log_text.insert(tk.END, f"{message}\n")
        self._log_text.see(tk.END)
        self._log_text.config(state=tk.DISABLED)

    def refresh_log_view(self):
        """根据当前等级筛选刷新日志"""
        self._log_text.config(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        for level, ts, msg in self._log_entries:
            if self._should_show(level):
                self._log_text.insert(tk.END, f"[{ts}] ", "TIME")
                self._log_text.insert(tk.END, f"[{level:>7s}] ", level)
                self._log_text.insert(tk.END, f"{msg}\n")
        self._log_text.see(tk.END)
        self._log_text.config(state=tk.DISABLED)

    def clear_log(self):
        self._log_entries.clear()
        self._log_text.config(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        self._log_text.config(state=tk.DISABLED)

    def start_auto_refresh(self, root):
        """日志页面打开时，每3秒自动刷新日志视图"""
        self.stop_auto_refresh()
        self._log_refresh_job = root.after(3000, self._auto_refresh_tick)

    def _auto_refresh_tick(self):
        if self._log_frame.winfo_ismapped():
            self.refresh_log_view()
            self._log_refresh_job = self.root.after(3000, self._auto_refresh_tick)

    def stop_auto_refresh(self):
        if self._log_refresh_job:
            try:
                self.root.after_cancel(self._log_refresh_job)
            except Exception:
                pass
            self._log_refresh_job = None

    def recolor(self):
        """主题切换时刷新日志面板颜色"""
        _recolor_text_tags(self._log_text)
        self._log_text.config(bg=C["canvas_bg"], fg=C["canvas_text"],
                              insertbackground=C["text_1"])

    def cleanup(self):
        """退出时清理定时器"""
        self.stop_auto_refresh()
