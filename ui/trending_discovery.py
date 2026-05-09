"""
热门视频发现窗口 — 热门榜、每周必看、入站必刷
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, List, Optional, Callable

from ui.theme import C
from ui.dialog_base import DialogBase


class TrendingDiscoveryWindow:
    """热门视频发现窗口"""

    def __init__(self, parent=None, api=None, on_add_monitor: Optional[Callable] = None):
        self.dlg = DialogBase(parent, "热门视频发现", "880x660", resizable=(True, True), modal=False)
        self.window = self.dlg.window
        self.api = api
        self.on_add_monitor = on_add_monitor
        self._videos: List[Dict] = []
        self._setup_ui()

    def _setup_ui(self):
        self.dlg.header("热门视频发现", "浏览B站热门榜单，发现潜力视频一键添加监控")

        # 标签页
        tab_bar = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        tab_bar.pack(fill=tk.X, padx=24, pady=(10, 0))

        self._tab_btns = {}
        tabs = [("🔥 热门榜", "popular"), ("📅 每周必看", "weekly")]
        for label, key in tabs:
            b = tk.Label(
                tab_bar,
                text=label,
                bg=C["bg_surface"],
                fg=C["text_2"],
                font=("Microsoft YaHei UI", 10),
                cursor="hand2",
                padx=14,
                pady=6,
            )
            b.pack(side=tk.LEFT)
            b.bind("<Button-1>", lambda e, k=key: self._switch_tab(k, tabs))
            self._tab_btns[key] = b

        if self._tab_btns:
            list(self._tab_btns.values())[0].config(fg=C["bilibili"])

        # 刷新按钮
        self._tab_btns["popular"].pack_forget()
        refresh_frame = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        refresh_frame.pack(fill=tk.X, padx=24, pady=(4, 0))
        ttk.Button(refresh_frame, text="🔄 刷新", command=self._load_popular, style="Primary.TButton").pack(
            side=tk.RIGHT
        )
        # Re-pack the first tab
        self._tab_btns["popular"].pack(side=tk.LEFT)

        # 视频列表区
        list_frame = tk.Frame(
            self.dlg.container, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"]
        )
        list_frame.pack(fill=tk.BOTH, expand=True, padx=24, pady=(8, 16))

        sc = tk.Frame(list_frame, bg=C["bg_elevated"])
        sc.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(sc, bg=C["bg_elevated"], highlightthickness=0)
        vsb = ttk.Scrollbar(sc, orient="vertical", command=self._canvas.yview)
        self._canvas.config(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._card_frame = tk.Frame(self._canvas, bg=C["bg_elevated"])
        self._canvas.create_window((0, 0), window=self._card_frame, anchor="nw")
        self._card_frame.bind("<Configure>", lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))

        self._load_popular()

    def _switch_tab(self, key, tabs):
        for k, b in self._tab_btns.items():
            b.config(fg=C["bilibili"] if k == key else C["text_2"])
        if key == "popular":
            self._load_popular()
        elif key == "weekly":
            self._load_weekly()

    def _load_popular(self):
        if not self.api:
            return
        self._clear_cards()
        tk.Label(
            self._card_frame, text="加载中...", bg=C["bg_elevated"], fg=C["text_3"], font=("Microsoft YaHei UI", 10)
        ).pack()
        self.window.update_idletasks()

        videos = self.api.get_popular_videos()
        self._videos = videos
        self._display_videos(videos)

    def _load_weekly(self):
        if not self.api:
            return
        self._clear_cards()
        tk.Label(
            self._card_frame, text="加载中...", bg=C["bg_elevated"], fg=C["text_3"], font=("Microsoft YaHei UI", 10)
        ).pack()
        self.window.update_idletasks()

        videos = self.api.get_weekly_series()
        self._videos = videos
        self._display_videos(videos)

    def _clear_cards(self):
        for w in self._card_frame.winfo_children():
            w.destroy()

    def _display_videos(self, videos: List[Dict]):
        self._clear_cards()

        if not videos:
            msg = tk.Frame(self._card_frame, bg=C["bg_elevated"])
            msg.pack(pady=40)
            tk.Label(msg, text="暂无数据", bg=C["bg_elevated"], fg=C["text_3"], font=("Microsoft YaHei UI", 12)).pack()
            tk.Label(
                msg,
                text="提示：B站API可能需要配置Cookie才能获取数据",
                bg=C["bg_elevated"],
                fg=C["warning"],
                font=("Microsoft YaHei UI", 9),
            ).pack(pady=(8, 0))
            tk.Label(
                msg,
                text="请前往「设置 → 网络设置 → Cookie设置」配置SESSDATA",
                bg=C["bg_elevated"],
                fg=C["text_3"],
                font=("Microsoft YaHei UI", 9),
            ).pack()
            return

        for v in videos:
            stat = v.get("stat", v)
            owner_info = v.get("owner", {})
            bvid = v.get("bvid", "")
            title = v.get("title", "未知")[:40]
            author = owner_info.get("name", v.get("author", "未知"))
            views = stat.get("view", 0)
            likes = stat.get("like", 0)
            danmaku = stat.get("danmaku", 0)

            card = tk.Frame(
                self._card_frame, bg=C["bg_surface"], highlightthickness=1, highlightbackground=C["border_sub"]
            )
            card.pack(fill=tk.X, padx=6, pady=3, ipadx=10, ipady=6)

            top = tk.Frame(card, bg=C["bg_surface"])
            top.pack(fill=tk.X)
            tk.Label(
                top,
                text=title,
                bg=C["bg_surface"],
                fg=C["text_1"],
                font=("Microsoft YaHei UI", 10),
                anchor="w",
                wraplength=500,
                justify="left",
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)

            if bvid:
                ttk.Button(top, text="+ 监控", command=lambda b=bvid: self._add_monitor(b)).pack(
                    side=tk.RIGHT, padx=(8, 0)
                )

            meta = tk.Frame(card, bg=C["bg_surface"])
            meta.pack(fill=tk.X, pady=(4, 0))
            tk.Label(
                meta, text=f"👤 {author}", bg=C["bg_surface"], fg=C["text_2"], font=("Microsoft YaHei UI", 9)
            ).pack(side=tk.LEFT, padx=(0, 12))
            tk.Label(
                meta, text=f"▶ {self._fmt(views)}", bg=C["bg_surface"], fg=C["text_2"], font=("Microsoft YaHei UI", 9)
            ).pack(side=tk.LEFT, padx=(0, 12))
            tk.Label(
                meta, text=f"👍 {self._fmt(likes)}", bg=C["bg_surface"], fg=C["text_2"], font=("Microsoft YaHei UI", 9)
            ).pack(side=tk.LEFT, padx=(0, 12))
            tk.Label(
                meta,
                text=f"💬 {self._fmt(danmaku)}",
                bg=C["bg_surface"],
                fg=C["text_2"],
                font=("Microsoft YaHei UI", 9),
            ).pack(side=tk.LEFT)

    def _add_monitor(self, bvid: str):
        if self.on_add_monitor:
            self.on_add_monitor(bvid)
            messagebox.showinfo("提示", f"已添加 {bvid} 到监控列表", parent=self.window)

    @staticmethod
    def _fmt(n):
        if n >= 1_0000_0000:
            return f"{n / 1_0000_0000:.2f}亿"
        if n >= 1_0000:
            return f"{n / 1_0000:.1f}万"
        return str(n)
