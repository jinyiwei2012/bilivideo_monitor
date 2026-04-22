"""
底部状态栏模块
负责底部操作栏和状态栏
"""
import tkinter as tk
from tkinter import ttk

from ui.theme import C
from ui.helpers import FONT, rounded_rect


class BottomBar:
    """底部操作栏 + 状态栏"""

    def __init__(self, root, gui):
        self.gui = gui
        self._root = root
        self._sb_labels = {}
        self._build_bottom_bar()
        self._build_status_bar()

    def _build_bottom_bar(self):
        tk.Frame(self._root, bg=C["border"], height=1).pack(fill=tk.X)
        bar = tk.Frame(self._root, bg=C["bg_surface"], height=46)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)
        ttk.Button(bar, text="＋ 添加监控", style="Primary.TButton",
                   command=self.gui._add_monitor).pack(side=tk.LEFT, padx=(12, 4), pady=8)
        ttk.Button(bar, text="🔄 立即刷新",
                   command=self.gui._refresh_data).pack(side=tk.LEFT, padx=4, pady=8)
        ttk.Button(bar, text="🗑 删除监控", style="Danger.TButton",
                   command=self.gui._remove_monitor).pack(side=tk.LEFT, padx=4, pady=8)
        ar_f = tk.Frame(bar, bg=C["bg_surface"])
        ar_f.pack(side=tk.RIGHT, padx=14)
        self._ar_toggle = tk.Canvas(ar_f, width=36, height=18, bg=C["bg_surface"],
                                     bd=0, highlightthickness=0, cursor="hand2")
        self._ar_toggle.pack(side=tk.LEFT)
        self._ar_toggle.bind("<Button-1>", self.gui._toggle_auto_refresh)
        tk.Label(ar_f, text="自动刷新", bg=C["bg_surface"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT, padx=4)
        self._draw_toggle(True)

    def _build_status_bar(self):
        tk.Frame(self._root, bg=C["border"], height=1).pack(fill=tk.X)
        bar = tk.Frame(self._root, bg=C["bg_surface"], height=22)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)
        items = [("videos", "监控: 0 个"), ("interval", "刷新间隔: —"),
                 ("algo", "算法: —"), ("last_ref", "上次刷新: —"), ("status", "就绪")]
        for key, text in items:
            anchor = "e" if key == "status" else "w"
            side = tk.RIGHT if key == "status" else tk.LEFT
            lbl = tk.Label(bar, text=text, bg=C["bg_surface"], fg=C["text_3"],
                           font=("Microsoft YaHei UI", 8))
            lbl.pack(side=side, padx=10)
            self._sb_labels[key] = lbl

    def _draw_toggle(self, on):
        c = self._ar_toggle
        c.delete("all")
        bg = C["success"] if on else C["bg_hover"]
        rounded_rect(c, 0, 0, 36, 18, 9, fill=bg, outline="")
        cx = 26 if on else 10
        c.create_oval(cx-7, 2, cx+7, 16, fill="#ffffff", outline="")

    def update_sb(self, key, text, color=None):
        """更新状态栏标签"""
        lbl = self._sb_labels.get(key)
        if lbl:
            lbl.config(text=text, fg=color or C["text_3"])

    @property
    def ar_toggle(self):
        return self._ar_toggle
