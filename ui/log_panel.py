"""
日志面板模块 - CustomTkinter 版
"""
import tkinter as tk
from tkinter import ttk
from datetime import datetime
import customtkinter as ctk
from ui.theme import C, _recolor_text_tags


class LogPanel:
    """日志面板 - 构建和管理应用日志显示"""

    def __init__(self, parent, file_logger):
        self.root = parent
        self._file_logger = file_logger
        self._log_entries = []   # [(level, timestamp_str, message), ...]
        self._log_level_var = tk.StringVar(value="ALL")
        self._log_refresh_job = None

        self._build()

    def _build(self):
        """构建日志面板 UI"""
        self._log_frame = ctk.CTkFrame(self.root, fg_color=C["bg_base"], corner_radius=0)

        toolbar = ctk.CTkFrame(self._log_frame, fg_color=C["bg_surface"], corner_radius=0)
        toolbar.pack(fill=tk.X)

        ctk.CTkLabel(toolbar, text="应用日志", text_color=C["text_1"],
                     font=("Microsoft YaHei UI", 10, "bold"),
                     fg_color="transparent").pack(side=tk.LEFT, padx=14, pady=8)

        self._log_levels = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"]
        self._log_level_btns = {}
        level_colors = {
            "ALL": C["text_2"], "DEBUG": "#8b949e",
            "INFO": C["accent"], "WARNING": C["warning"], "ERROR": C["danger"],
        }
        for lvl in self._log_levels:
            fg = level_colors.get(lvl, C["text_2"])
            btn = ctk.CTkLabel(toolbar, text=lvl,
                               fg_color=C["bg_elevated"] if lvl == "ALL" else C["bg_hover"],
                               text_color=C["bilibili"] if lvl == "ALL" else fg,
                               font=("Consolas", 9), cursor="hand2",
                               corner_radius=4)
            btn.pack(side=tk.LEFT, padx=(2, 0), pady=6)
            btn.bind("<Button-1>", lambda e, l=lvl: self.set_log_level(l))
            btn.bind("<Enter>", lambda e, b=btn: b.configure(fg_color=C["bg_elevated"]))
            btn.bind("<Leave>", lambda e, b=btn, l=lvl:
                     b.configure(fg_color=C["bg_elevated"] if l == self._log_level_var.get() else C["bg_hover"]))
            self._log_level_btns[lvl] = btn

        # 清空按钮
        clear_lbl = ctk.CTkLabel(toolbar, text="🗑 清空", text_color=C["text_3"],
                                 font=("Microsoft YaHei UI", 9), cursor="hand2",
                                 fg_color="transparent")
        clear_lbl.pack(side=tk.RIGHT, padx=14, pady=6)
        clear_lbl.bind("<Button-1>", lambda e: self.clear_log())
        clear_lbl.bind("<Enter>", lambda e: clear_lbl.configure(text_color=C["danger"]))
        clear_lbl.bind("<Leave>", lambda e: clear_lbl.configure(text_color=C["text_3"]))

        tk.Frame(self._log_frame, bg=C["border"], height=1).pack(fill=tk.X)

        log_container = ctk.CTkFrame(self._log_frame, fg_color=C["bg_base"], corner_radius=0)
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
        return self._log_frame

    def set_log_level(self, level):
        self._log_level_var.set(level)
        for l, btn in self._log_level_btns.items():
            is_active = (l == level)
            btn.configure(
                fg_color=C["bg_elevated"] if is_active else C["bg_hover"],
                text_color=C["bilibili"] if is_active else C["text_2"],
            )
        self.refresh_log_view()

    _LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}

    def _should_show(self, level: str) -> bool:
        filter_level = self._log_level_var.get()
        if filter_level == "ALL":
            return True
        min_severity = self._LEVEL_ORDER.get(filter_level, 0)
        msg_severity = self._LEVEL_ORDER.get(level, 0)
        return msg_severity >= min_severity

    def add_log(self, level: str, message: str):
        ts = datetime.now()
        ts_str = ts.strftime("%H:%M:%S")
        self._log_entries.append((level, ts_str, message))
        try:
            self._file_logger.write(level, message, ts)
        except Exception:
            pass
        if len(self._log_entries) > 2000:
            self._log_entries = self._log_entries[-1500:]
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
        _recolor_text_tags(self._log_text)
        self._log_text.config(bg=C["canvas_bg"], fg=C["canvas_text"],
                              insertbackground=C["text_1"])

    def cleanup(self):
        self.stop_auto_refresh()
