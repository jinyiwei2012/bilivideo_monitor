"""
在线人数监控面板 — 实时查看所有监控视频的在线观看人数
"""

import tkinter as tk
from tkinter import ttk
import logging
from datetime import datetime

from ui.theme import C
from ui.helpers import FONT, FONT_SM, fmt_num

logger = logging.getLogger(__name__)

REFRESH_INTERVAL = 30000


class OnlineViewersPanel:
    def __init__(self, parent, main_gui):
        self.parent = parent
        self.gui = main_gui
        self.frame = tk.Frame(parent, bg=C["bg_base"])
        self._sort_col = "viewers_total"
        self._sort_rev = True
        self._timer_id = None
        self._build_ui()

    def _build_ui(self):
        """构建在线人数监控面板的 UI：表头、树形表格、状态栏"""
        header = tk.Frame(self.frame, bg=C["bg_surface"], height=48)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        tk.Label(
            header,
            text="👥 在线人数监控",
            bg=C["bg_surface"],
            fg=C["text_1"],
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(side=tk.LEFT, padx=(16, 4), pady=10)

        self._count_lbl = tk.Label(
            header,
            text="",
            bg=C["bg_surface"],
            fg=C["text_3"],
            font=FONT,
        )
        self._count_lbl.pack(side=tk.LEFT, padx=4, pady=10)

        self._time_lbl = tk.Label(
            header,
            text="",
            bg=C["bg_surface"],
            fg=C["text_3"],
            font=FONT_SM,
        )
        self._time_lbl.pack(side=tk.RIGHT, padx=16, pady=10)

        sep = tk.Frame(self.frame, bg=C["border"], height=1)
        sep.pack(fill=tk.X)

        tree_frame = tk.Frame(self.frame, bg=C["bg_base"])
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)

        columns = (
            "rank",
            "title",
            "bvid",
            "viewers_total",
            "viewers_web",
            "viewers_app",
            "view_count",
            "online_rate",
        )
        self._tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        col_cfgs = [
            ("rank", "#", 36, tk.CENTER),
            ("title", "视频标题", 320, tk.LEFT),
            ("bvid", "BV号", 130, tk.CENTER),
            ("viewers_total", "在线人数", 110, tk.CENTER),
            ("viewers_web", "Web端", 90, tk.CENTER),
            ("viewers_app", "App端", 90, tk.CENTER),
            ("view_count", "播放量", 110, tk.CENTER),
            ("online_rate", "在线率", 90, tk.CENTER),
        ]
        for col_id, heading, width, anchor in col_cfgs:
            self._tree.heading(
                col_id,
                text=heading,
                anchor=anchor,
                command=lambda c=col_id: self._sort_by(c),
            )
            self._tree.column(col_id, width=width, anchor=anchor, minwidth=36)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._tree.tag_configure("even", background=C["bg_surface"])
        self._tree.tag_configure("odd", background=C["bg_base"])
        self._tree.tag_configure("online_high", foreground=C["success"])
        self._tree.tag_configure("online_mid", foreground=C["warning"])
        self._tree.tag_configure("online_low", foreground=C["text_3"])

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        self._apply_tree_style()

        status_bar = tk.Frame(self.frame, bg=C["bg_surface"], height=32)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        status_bar.pack_propagate(False)

        self._status_lbl = tk.Label(
            status_bar,
            text="就绪",
            bg=C["bg_surface"],
            fg=C["text_3"],
            font=FONT_SM,
        )
        self._status_lbl.pack(side=tk.LEFT, padx=12, pady=6)

        ttk.Button(
            status_bar,
            text="🔄 刷新",
            command=self.refresh,
            style="Primary.TButton",
        ).pack(side=tk.RIGHT, padx=(4, 12), pady=3)

        ttk.Button(
            status_bar,
            text="跳转到视频",
            command=self._jump_to_video,
        ).pack(side=tk.RIGHT, padx=4, pady=3)

    def _apply_tree_style(self):
        """为树形视图应用自定义颜色样式"""
        style = ttk.Style()
        style.configure(
            "Treeview",
            background=C["bg_elevated"],
            fieldbackground=C["bg_elevated"],
            foreground=C["text_1"],
            rowheight=28,
            font=FONT,
        )
        style.configure(
            "Treeview.Heading",
            background=C["bg_surface"],
            foreground=C["text_2"],
            font=FONT,
            relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", C["bilibili_dim"])],
            foreground=[("selected", "#ffffff")],
        )

    def _sort_by(self, col):
        """切换排序字段或反转排序方向，然后刷新列表"""
        if self._sort_col == col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col
            self._sort_rev = col in ("viewers_total", "viewers_web", "viewers_app", "view_count", "online_rate", "rank")
        self._populate()

    def _on_select(self, event):
        pass

    def _jump_to_video(self):
        """选中视频后跳转到主界面的监控列表并定位到该视频"""
        sel = self._tree.selection()
        if not sel:
            return
        bvid = self._tree.item(sel[0], "values")[2]
        self.gui._switch_nav("监控列表")
        self.gui._select_video(bvid)

    def refresh(self):
        """手动刷新在线人数数据"""
        self._populate()
        self._time_lbl.config(text=f"上次刷新: {datetime.now().strftime('%H:%M:%S')}")

    def _populate(self):
        """填充树形表格数据：遍历所有监控视频，计算在线率并按当前排序方式排列"""
        for row in self._tree.get_children():
            self._tree.delete(row)

        rows = []
        for video in self.gui.monitored_videos:
            bvid = video.get("bvid", "")
            title = video.get("title", bvid)
            view_count = video.get("view_count", 0)
            viewers_total = video.get("viewers_total", 0)
            viewers_web = video.get("viewers_web", 0)
            viewers_app = video.get("viewers_app", 0)
            online_rate = (viewers_total / view_count * 100) if view_count > 0 else 0
            rows.append((bvid, title, view_count, viewers_total, viewers_web, viewers_app, online_rate))

        col_key = self._sort_col
        reverse = self._sort_rev

        def _sort_key(r):
            """根据当前排序列名返回排序键值"""
            idx_map = {
                "title": 1,
                "bvid": 0,
                "view_count": 2,
                "viewers_total": 3,
                "viewers_web": 4,
                "viewers_app": 5,
                "online_rate": 6,
                "rank": 3,
            }
            val = r[idx_map.get(col_key, 3)]
            if isinstance(val, str):
                return val.lower()
            return val

        rows.sort(key=_sort_key, reverse=reverse)

        self._count_lbl.config(text=f"共 {len(rows)} 个视频")

        for i, r in enumerate(rows):
            bvid, title, view_count, viewers_total, viewers_web, viewers_app, online_rate = r
            tag = "even" if i % 2 == 0 else "odd"
            if viewers_total >= 10000:
                rate_tag = "online_high"
            elif viewers_total >= 1000:
                rate_tag = "online_mid"
            else:
                rate_tag = "online_low"

            title_display = title[:40] + "…" if len(title) > 40 else title
            rate_display = f"{online_rate:.2f}%" if online_rate > 0 else "—"

            self._tree.insert(
                "",
                tk.END,
                values=(
                    i + 1,
                    title_display,
                    bvid,
                    fmt_num(viewers_total),
                    fmt_num(viewers_web),
                    fmt_num(viewers_app),
                    fmt_num(view_count),
                    rate_display,
                ),
                tags=(tag, rate_tag),
            )

        self._status_lbl.config(text=f"共 {len(rows)} 个视频 · 按在线人数排序")

    def on_show(self):
        """面板显示时刷新数据并启动自动刷新"""
        self.refresh()
        self._start_auto_refresh()

    def on_hide(self):
        """面板隐藏时停止自动刷新"""
        self._stop_auto_refresh()

    def _start_auto_refresh(self):
        """启动定时自动刷新（间隔 30 秒）"""
        self._stop_auto_refresh()
        self._timer_id = self.frame.after(REFRESH_INTERVAL, self._auto_refresh_tick)

    def _stop_auto_refresh(self):
        """停止自动刷新定时器"""
        if self._timer_id:
            self.frame.after_cancel(self._timer_id)
            self._timer_id = None

    def _auto_refresh_tick(self):
        """自动刷新定时器触发：刷新数据并重新排程"""
        self.refresh()
        self._timer_id = self.frame.after(REFRESH_INTERVAL, self._auto_refresh_tick)
