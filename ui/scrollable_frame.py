"""
可滚动 Frame 工具模块

封装 Canvas + Scrollbar + Frame 的组合模式，消除项目中 12+ 处重复代码。

设计说明:
  - 使用 tk.Canvas 作为滚动容器，内部挂载一个 tk.Frame 作为内容区
  - 通过 Canvas.create_window 将内容 Frame 嵌入 Canvas
  - 绑定 <Configure> 事件自动更新滚动区域
  - 可选鼠标滚轮支持（默认启用，Windows 下 <MouseWheel> 事件）

用法示例::

    sf = ScrollableFrame(parent, height=200)
    sf.pack(fill=tk.BOTH, expand=True)
    tk.Label(sf.inner, text="Hello").pack()

主要组件:
    ScrollableFrame — 可垂直滚动的 Frame 容器
"""

import tkinter as tk
from tkinter import ttk


class ScrollableFrame(tk.Frame):
    """可垂直滚动的 Frame 容器，用于在有限空间内展示大量子控件

    通过 Canvas + Scrollbar 实现平滑滚动，内部 Frame (sf.inner) 作为实际的内容容器。
    子控件的 pack/grid 操作应在 sf.inner 上执行。

    Attributes:
        inner: 内部内容 Frame，所有子控件应添加到此容器
        canvas: Canvas 画布对象
        vsb: 垂直滚动条
    """

    def __init__(self, parent, *, height=None, bg=None, mousewheel=True, **kwargs):
        """初始化可滚动 Frame

        Args:
            parent: 父容器（Tkinter Frame 或 TopLevel）
            height: Canvas 的初始高度（可选），为 None 时自动适应
            bg: 背景色（可选），同时应用于 Canvas 和内部 Frame
            mousewheel: 是否启用鼠标滚轮滚动（默认 True）
            **kwargs: 传递给 tk.Frame 的额外参数
        """
        super().__init__(parent, **kwargs)

        # ── 垂直滚动条：置于右侧 ──
        self.vsb = ttk.Scrollbar(self, orient="vertical")
        self.vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # ── 画布配置：无边框 + 绑定滚动条 ──
        canvas_kw = {"highlightthickness": 0, "yscrollcommand": self.vsb.set}
        if height is not None:
            canvas_kw["height"] = height
        if bg is not None:
            canvas_kw["bg"] = bg
        self.canvas = tk.Canvas(self, **canvas_kw)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.vsb.config(command=self.canvas.yview)

        # ── 内部容器：挂在 Canvas 上以实现滚动 ──
        self.inner = tk.Frame(self.canvas, bg=bg)
        # create_window 将 inner 嵌入 Canvas 成为一个可滚动的"画布窗口"
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        # 内部容器尺寸变化时自动更新 Canvas 滚动区域
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        # ── 可选：鼠标滚轮支持 ──
        # Windows 下 delta 通常为 120/-120，除以 120 得到 "行数"
        if mousewheel:
            self.canvas.bind("<MouseWheel>", lambda ev: self.canvas.yview_scroll(int(-1 * (ev.delta / 120)), "units"))
