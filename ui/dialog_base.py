"""
现代化对话框基类 — 统一的弹窗样式、间距、卡片布局
"""

import tkinter as tk
from tkinter import ttk
from ui.theme import C


class DialogBase:
    """现代化对话框基类

    提供统一的头部、卡片分段、按钮栏与间距控制。
    """

    def __init__(self, parent, title="", geometry="480x360", resizable=(True, True), modal=True):
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.geometry(geometry)
        self.window.configure(bg=C["bg_surface"])
        if modal and parent:
            self.window.transient(parent)
            self.window.grab_set()
        self.window.resizable(*resizable)
        self.window.minsize(300, 200)
        self.window.bind("<Escape>", lambda e: self.window.destroy())

        # 主容器（自带两侧安全边距）
        self.container = tk.Frame(self.window, bg=C["bg_surface"])
        self.container.pack(fill=tk.BOTH, expand=True)

    # ── 头部 ────────────────────────────────────────────
    def header(self, title, subtitle=None):
        """带分隔线的标题栏"""
        h = tk.Frame(self.container, bg=C["bg_surface"])
        h.pack(fill=tk.X, padx=24, pady=(20, 0))
        tk.Label(
            h, text=title, bg=C["bg_surface"], fg=C["text_1"], font=("Microsoft YaHei UI", 14, "bold"), anchor="w"
        ).pack(fill=tk.X)
        if subtitle:
            tk.Label(
                h, text=subtitle, bg=C["bg_surface"], fg=C["text_3"], font=("Microsoft YaHei UI", 9), anchor="w"
            ).pack(fill=tk.X, pady=(4, 0))
        sep = tk.Frame(self.container, bg=C["border"], height=1)
        sep.pack(fill=tk.X, padx=24, pady=(12, 0))
        return h

    # ── 卡片分段 ─────────────────────────────────────────
    def section(self, parent=None, title=None, padding=14, **kw):
        """创建一个卡片风格的 Frame 分段

        用法::
            sec = dlg.section(title="参数设置")
            tk.Label(sec, text=...).pack()
        """
        p = parent or self.container
        bg = kw.pop("bg", C["bg_elevated"])
        border = kw.pop("highlightbackground", C["border_sub"])
        sec = tk.Frame(p, bg=bg, highlightthickness=1, highlightbackground=border, **kw)
        sec.pack(fill=tk.X, padx=24, pady=(10, 0), ipadx=14, ipady=padding)

        if title:
            lbl = tk.Label(sec, text=title, bg=bg, fg=C["text_2"], font=("Microsoft YaHei UI", 8, "bold"), anchor="w")
            lbl.pack(fill=tk.X, padx=4, pady=(4, 8))
        return sec

    # ── 按钮栏 ───────────────────────────────────────────
    def button_row(self, buttons, parent=None):
        """底部操作按钮行

        buttons: [(text, command, style), ...]
            style: "primary" | "danger" | "" (default Flat)
        """
        p = parent or self.container
        bar = tk.Frame(p, bg=C["bg_surface"])
        bar.pack(fill=tk.X, padx=24, pady=(16, 20))

        lefts = [b for b in buttons if b[2] == "default"]
        rights = [b for b in buttons if b[2] != "default"]

        for text, cmd, style in lefts:
            ttk.Button(bar, text=text, command=cmd).pack(side=tk.LEFT, padx=(0, 6))

        for text, cmd, style in reversed(rights):
            if style == "primary":
                ttk.Button(bar, text=text, command=cmd, style="Primary.TButton").pack(side=tk.RIGHT, padx=(6, 0))
            elif style == "danger":
                ttk.Button(bar, text=text, command=cmd, style="Danger.TButton").pack(side=tk.RIGHT, padx=(6, 0))
            else:
                ttk.Button(bar, text=text, command=cmd).pack(side=tk.RIGHT, padx=(6, 0))
        return bar

    # ── 标签式行（字段+值）─────────────────────────────
    def field_row(self, parent, label, value_widget, **kw):
        """一行：左标签 + 右控件，适合表单"""
        fg = kw.pop("fg", C["text_2"])
        row = tk.Frame(parent, bg=kw.pop("bg", parent.cget("bg")))
        row.pack(fill=tk.X, pady=kw.pop("pady", 4))
        tk.Label(
            row,
            text=label,
            bg=row.cget("bg"),
            fg=fg,
            font=("Microsoft YaHei UI", 9),
            anchor="w",
            width=kw.pop("label_width", 14),
        ).pack(side=tk.LEFT)
        value_widget.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
        return row

    # ── 几何辅助 ──────────────────────────────────────────
    @staticmethod
    def calc_geometry(parent, width_ratio=0.5, height_ratio=0.7):
        """根据父窗口/屏幕尺寸计算居中几何字符串 'WxH+X+Y'"""
        sw = parent.winfo_screenwidth() if parent else 1920
        sh = parent.winfo_screenheight() if parent else 1080
        w, h = int(sw * width_ratio), int(sh * height_ratio)
        x, y = (sw - w) // 2, (sh - h) // 2
        return f"{w}x{h}+{x}+{y}"

    # ── 内容区（充满剩余空间，用于 Text / Treeview）────────
    def content_area(self, parent=None, **kw):
        """填充分段，适合放 Text / Treeview + Scrollbar"""
        p = parent or self.container
        bg = kw.pop("bg", C["bg_base"])
        padding = kw.pop("padding", 0)
        f = tk.Frame(p, bg=bg, **kw)
        f.pack(fill=tk.BOTH, expand=True, padx=24, pady=(10, 0))
        if padding:
            inner = tk.Frame(f, bg=bg)
            inner.pack(fill=tk.BOTH, expand=True, padx=padding, pady=padding)
            return inner
        return f
