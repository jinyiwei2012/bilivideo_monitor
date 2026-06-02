"""
热门视频发现窗口模块
===================

提供 ``TrendingDiscoveryWindow`` 类，用于浏览 B 站热门榜单并一键添加监控。

功能：
  - 两个标签页：热门榜（popular）/ 每周必看（weekly）
  - 异步加载数据（后台线程 + after 回调）
  - 视频卡片列表：标题、UP 主、播放量、点赞、弹幕
  - 一键添加监控按钮
  - 刷新按钮

.. note::
   需要传入 ``api`` 参数（BilibiliAPI 实例）以调用 B 站 API。
   若 API 返回空结果，会提示配置 Cookie。
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, List, Optional, Callable

from ui.theme import C
from ui.scrollable_frame import ScrollableFrame
from ui.dialog_base import DialogBase


class TrendingDiscoveryWindow:
    """热门视频发现窗口 — 浏览热门榜、每周必看，一键添加监控"""

    def __init__(self, parent=None, api=None, on_add_monitor: Optional[Callable] = None):
        """
        初始化热门视频发现窗口。

        :param parent: 父窗口
        :param api: BilibiliAPI 实例，用于调用热门榜/每周必看 API
        :param on_add_monitor: 添加监控的回调函数，签名为 f(bvid: str)
        """
        self.dlg = DialogBase(
            parent, "热门视频发现", DialogBase.calc_geometry(parent, 0.48, 0.68), resizable=(True, True), modal=False
        )
        self.window = self.dlg.window
        self.api = api
        self.on_add_monitor = on_add_monitor
        self._videos: List[Dict] = []  # 当前加载的视频列表
        self._setup_ui()

    def _setup_ui(self):
        """
        构建窗口界面：
          标签页切换（热门榜 / 每周必看） + 刷新按钮
          视频卡片列表（可滚动）
        """
        self.dlg.header("热门视频发现", "浏览B站热门榜单，发现潜力视频一键添加监控")

        # ── 标签页切换行 ──
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

        # 默认选中第一个标签页
        if self._tab_btns:
            list(self._tab_btns.values())[0].config(fg=C["bilibili"])

        # 刷新按钮（插入到标签页行最右侧）
        self._tab_btns["popular"].pack_forget()  # 临时移除，调整位置
        refresh_frame = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        refresh_frame.pack(fill=tk.X, padx=24, pady=(4, 0))
        ttk.Button(refresh_frame, text="🔄 刷新", command=self._load_popular, style="Primary.TButton").pack(
            side=tk.RIGHT
        )
        self._tab_btns["popular"].pack(side=tk.LEFT)  # 恢复

        # ── 视频列表区（可滚动卡片）──
        list_frame = tk.Frame(
            self.dlg.container, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"]
        )
        list_frame.pack(fill=tk.BOTH, expand=True, padx=24, pady=(8, 16))

        sf = ScrollableFrame(list_frame, bg=C["bg_elevated"])
        sf.pack(fill=tk.BOTH, expand=True)
        self._card_frame = sf.inner

        # 默认加载热门榜数据
        self._load_popular()

    def _switch_tab(self, key, tabs):
        """
        切换标签页：高亮选中标签，加载对应数据。

        :param key: 标签页标识 ("popular" | "weekly")
        :param tabs: 标签页定义列表
        """
        for k, b in self._tab_btns.items():
            b.config(fg=C["bilibili"] if k == key else C["text_2"])
        if key == "popular":
            self._load_popular()
        elif key == "weekly":
            self._load_weekly()

    def _load_popular(self):
        """
        异步加载热门榜数据。
        清空现有卡片 → 显示加载提示 → 后台线程请求 API → 回到主线程显示。
        """
        if not self.api:
            return
        self._clear_cards()
        tk.Label(
            self._card_frame, text="加载中...", bg=C["bg_elevated"], fg=C["text_3"], font=("Microsoft YaHei UI", 10)
        ).pack()

        def _fetch():
            videos = self.api.get_popular_videos()
            self.window.after(0, lambda: self._display_videos(videos))

        import threading

        threading.Thread(target=_fetch, daemon=True).start()

    def _load_weekly(self):
        """
        异步加载每周必看数据。
        流程同 _load_popular。
        """
        if not self.api:
            return
        self._clear_cards()
        tk.Label(
            self._card_frame, text="加载中...", bg=C["bg_elevated"], fg=C["text_3"], font=("Microsoft YaHei UI", 10)
        ).pack()

        def _fetch():
            videos = self.api.get_weekly_series()
            self.window.after(0, lambda: self._display_videos(videos))

        import threading

        threading.Thread(target=_fetch, daemon=True).start()

    def _clear_cards(self):
        """清空视频卡片列表（销毁所有子控件）"""
        for w in self._card_frame.winfo_children():
            w.destroy()

    def _display_videos(self, videos: List[Dict]):
        """
        显示视频卡片列表。

        每个卡片显示：
          - 标题（最多 40 字符）
          - UP 主名称
          - 播放量、点赞、弹幕
          - "+ 监控" 按钮

        若结果为空的提示：可能需要配置 Cookie。

        :param videos: 视频信息列表 [{"bvid": ..., "title": ..., ...}, ...]
        """
        self._clear_cards()

        if not videos:
            # 空结果提示
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

        # 遍历视频列表，为每个视频创建信息卡片
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

            # 上部：标题 + 监控按钮
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

            # 下部：UP 主 / 播放量 / 点赞 / 弹幕
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
        """
        将视频添加到监控列表，通过回调函数通知外部。

        :param bvid: 视频 BV 号
        """
        if self.on_add_monitor:
            self.on_add_monitor(bvid)
            messagebox.showinfo("提示", f"已添加 {bvid} 到监控列表", parent=self.window)

    @staticmethod
    def _fmt(n):
        """
        格式化大数字为中文单位（万/亿）。

        :param n: 原始数字
        :returns: 格式化后的字符串（如 "12.5万"、"3.14亿"）
        """
        if n >= 1_0000_0000:
            return f"{n / 1_0000_0000:.2f}亿"
        if n >= 1_0000:
            return f"{n / 1_0000:.1f}万"
        return str(n)
