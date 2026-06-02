"""
现代化对话框基类模块

提供统一的弹窗样式、间距规范、卡片布局和几何计算工具。

本模块是 ui 模块中所有弹窗窗口的基础组件，封装了以下可复用元素：
1. DialogBase 窗口基类 — 统一的外观、边距、模态控制
2. header() — 带分隔线的标题栏（主标题 + 副标题）
3. section() — 卡片风格的分段容器（带可选标题）
4. button_row() — 底部操作按钮栏（支持 primary/danger/default 样式）
5. field_row() — 标签式表单行（左标签 + 右控件）
6. content_area() — 填充剩余空间的内容区（适合 Text/Treeview）
7. calc_geometry() — 根据父窗口/屏幕尺寸计算居中几何字符串
"""

import tkinter as tk
from tkinter import ttk
from ui.theme import C                                     # 颜色主题常量


class DialogBase:
    """
    现代化对话框基类

    提供统一的窗口外观、间距控制和可复用布局组件。

    Attributes:
        window: Tkinter Toplevel 窗口对象
        container: 主容器 Frame（自带两侧安全边距）
    """

    def __init__(self, parent, title="", geometry="480x360", resizable=(True, True), modal=True):
        """
        初始化对话框窗口

        :param parent: 父窗口（Tk 或 Toplevel）
        :param title: 窗口标题
        :param geometry: 窗口尺寸字符串（如 "800x600"）
        :param resizable: (width_resizable, height_resizable) 是否可缩放
        :param modal: 是否为模态对话框（True 时 grab_set，阻塞父窗口交互）
        """
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.geometry(geometry)
        self.window.configure(bg=C["bg_surface"])
        if modal and parent:
            self.window.transient(parent)                   # 置顶在父窗口上
            self.window.grab_set()                          # 模态：阻塞父窗口交互
        self.window.resizable(*resizable)
        self.window.minsize(300, 200)                       # 最小窗口尺寸
        # ESC 键关闭对话框
        self.window.bind("<Escape>", lambda e: self.window.destroy())

        # 主容器（自带两侧安全边距）
        self.container = tk.Frame(self.window, bg=C["bg_surface"])
        self.container.pack(fill=tk.BOTH, expand=True)

    # ── 头部 ────────────────────────────────────────────────────────────────

    def header(self, title, subtitle=None):
        """
        创建带分隔线的标题栏

        用法::
            dlg.header("设置", "配置 API 密钥与通知参数")

        :param title: 主标题（14磅加粗）
        :param subtitle: 副标题（9磅灰色文字，可选）
        :return: 头部 Frame 对象
        """
        h = tk.Frame(self.container, bg=C["bg_surface"])
        h.pack(fill=tk.X, padx=24, pady=(20, 0))
        tk.Label(
            h, text=title, bg=C["bg_surface"], fg=C["text_1"], font=("Microsoft YaHei UI", 14, "bold"), anchor="w"
        ).pack(fill=tk.X)
        if subtitle:
            tk.Label(
                h, text=subtitle, bg=C["bg_surface"], fg=C["text_3"], font=("Microsoft YaHei UI", 9), anchor="w"
            ).pack(fill=tk.X, pady=(4, 0))
        # 分隔线
        sep = tk.Frame(self.container, bg=C["border"], height=1)
        sep.pack(fill=tk.X, padx=24, pady=(12, 0))
        return h

    # ── 卡片分段 ────────────────────────────────────────────────────────────

    def section(self, parent=None, title=None, padding=14, **kw):
        """
        创建一个卡片风格的 Frame 分段

        用法::
            sec = dlg.section(title="参数设置")
            tk.Label(sec, text="姓名:").pack()

        :param parent: 父容器（默认 self.container）
        :param title: 分段标题（8磅加粗，可选）
        :param padding: 垂直内边距
        :param kw: 其他传递给 Frame 的参数（如 bg, highlightbackground）
        :return: 分段 Frame 对象
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

    # ── 按钮栏 ──────────────────────────────────────────────────────────────

    def button_row(self, buttons, parent=None):
        """
        底部操作按钮行

        按钮按样式分组：default 靠左，其他（primary/danger/空）靠右倒序排列。

        用法::
            dlg.button_row([
                ("确定", on_ok, "primary"),
                ("取消", self.window.destroy, "default"),
                ("删除", on_delete, "danger"),
            ])

        :param buttons: [(text, command, style), ...]
            style: "primary" (高亮) | "danger" (红色) | "default" (默认左对齐)
        :param parent: 父容器
        :return: 按钮栏 Frame 对象
        """
        p = parent or self.container
        bar = tk.Frame(p, bg=C["bg_surface"])
        bar.pack(fill=tk.X, padx=24, pady=(16, 20))

        # 分离默认按钮（左对齐）和特殊按钮（右对齐）
        lefts = [b for b in buttons if b[2] == "default"]
        rights = [b for b in buttons if b[2] != "default"]

        # 左侧按钮依次排列
        for text, cmd, style in lefts:
            ttk.Button(bar, text=text, command=cmd).pack(side=tk.LEFT, padx=(0, 6))

        # 右侧按钮倒序排列（primary 使用高亮样式）
        for text, cmd, style in reversed(rights):
            if style == "primary":
                ttk.Button(bar, text=text, command=cmd, style="Primary.TButton").pack(side=tk.RIGHT, padx=(6, 0))
            elif style == "danger":
                ttk.Button(bar, text=text, command=cmd, style="Danger.TButton").pack(side=tk.RIGHT, padx=(6, 0))
            else:
                ttk.Button(bar, text=text, command=cmd).pack(side=tk.RIGHT, padx=(6, 0))
        return bar

    # ── 标签式行（字段 + 值） ───────────────────────────────────────────────

    def field_row(self, parent, label, value_widget, **kw):
        """
        一行：左侧标签 + 右侧控件，适合表单布局

        用法::
            entry = ttk.Entry()
            dlg.field_row(sec, "API密钥:", entry)

        :param parent: 父容器
        :param label: 标签文本
        :param value_widget: 右侧控件（Entry/Combobox 等）
        :param kw: 可选参数（fg=颜色, bg=背景, pady=间距, label_width=标签宽度）
        :return: 行 Frame 对象
        """
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

    # ── 几何辅助 ────────────────────────────────────────────────────────────

    @staticmethod
    def calc_geometry(parent, width_ratio=0.5, height_ratio=0.7):
        """
        根据父窗口/屏幕尺寸计算居中几何字符串

        无父窗口时（parent=None）使用默认分辨率 1920×1080。

        :param parent: 父窗口（用于获取屏幕尺寸），可为 None
        :param width_ratio: 宽度占屏幕比例（0~1）
        :param height_ratio: 高度占屏幕比例（0~1）
        :return: 几何字符串（如 "960x756+480+162"）
        """
        sw = parent.winfo_screenwidth() if parent else 1920
        sh = parent.winfo_screenheight() if parent else 1080
        w, h = int(sw * width_ratio), int(sh * height_ratio)
        x, y = (sw - w) // 2, (sh - h) // 2               # 居中计算
        return f"{w}x{h}+{x}+{y}"

    # ── 内容区（充满剩余空间） ──────────────────────────────────────────────

    def content_area(self, parent=None, **kw):
        """
        填充剩余空间的区域，适合放 Text / Treeview + Scrollbar

        用法::
            area = dlg.content_area()
            tree = ttk.Treeview(area)
            tree.pack(fill=tk.BOTH, expand=True)

        :param parent: 父容器
        :param kw: 可选参数（bg=背景, padding=内边距）
        :return: Frame 对象（如有 padding 则返回内层 Frame）
        """
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
