"""
可滚动 Frame 工具

封装 Canvas + Scrollbar + Frame 模式，消除 12+ 处重复代码。
用法::

    sf = ScrollableFrame(parent, height=200)
    sf.pack(fill=tk.BOTH, expand=True)
    tk.Label(sf.inner, text="Hello").pack()
"""

import tkinter as tk
from tkinter import ttk


class ScrollableFrame(tk.Frame):
    """可垂直滚动的 Frame 容器，用于在有限空间内展示大量子控件"""

    def __init__(self, parent, *, height=None, bg=None, mousewheel=True, **kwargs):
        """
        初始化可滚动 Frame

        :param parent: 父容器
        :param height: Canvas 高度（可选）
        :param bg: 背景色（可选）
        :param mousewheel: 是否启用鼠标滚轮滚动
        """
        super().__init__(parent, **kwargs)

        # 垂直滚动条：置于右侧
        self.vsb = ttk.Scrollbar(self, orient="vertical")
        self.vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # 画布配置：无边框 + 绑定滚动条
        canvas_kw = {"highlightthickness": 0, "yscrollcommand": self.vsb.set}
        if height is not None:
            canvas_kw["height"] = height
        if bg is not None:
            canvas_kw["bg"] = bg
        self.canvas = tk.Canvas(self, **canvas_kw)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.vsb.config(command=self.canvas.yview)

        # 内部容器：挂在 Canvas 上以实现滚动
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        # 内部容器尺寸变化时自动更新 Canvas 滚动区域
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        # 可选：鼠标滚轮支持
        if mousewheel:
            self.canvas.bind("<MouseWheel>", lambda ev: self.canvas.yview_scroll(int(-1 * (ev.delta / 120)), "units"))
