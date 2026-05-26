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
    """可垂直滚动的 Frame 容器"""

    def __init__(self, parent, *, height=None, bg=None, mousewheel=True, **kwargs):
        super().__init__(parent, **kwargs)

        self.vsb = ttk.Scrollbar(self, orient="vertical")
        self.vsb.pack(side=tk.RIGHT, fill=tk.Y)

        canvas_kw = {"highlightthickness": 0, "yscrollcommand": self.vsb.set}
        if height is not None:
            canvas_kw["height"] = height
        if bg is not None:
            canvas_kw["bg"] = bg
        self.canvas = tk.Canvas(self, **canvas_kw)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.vsb.config(command=self.canvas.yview)

        self.inner = tk.Frame(self.canvas, bg=bg)
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        if mousewheel:
            self.canvas.bind("<MouseWheel>", lambda ev: self.canvas.yview_scroll(int(-1 * (ev.delta / 120)), "units"))
