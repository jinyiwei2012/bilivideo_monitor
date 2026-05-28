"""
视频排行榜面板
按增速/互动率/播放量/在线人数等维度对所有监控视频排序
"""

import tkinter as tk
from tkinter import ttk
from datetime import datetime
from ui.theme import C
from ui.helpers import FONT, FONT_SM, FONT_MONO, fmt_num
from ui.dialog_base import DialogBase


class RankingPanel:
    SORT_OPTIONS = [
        ("📈 增速 (每小时)", "velocity"),
        ("👁 播放量", "views"),
        ("👍 点赞率", "like_rate"),
        ("🪙 投币率", "coin_rate"),
        ("📊 互动率", "engagement"),
        ("👥 在线人数", "online"),
        ("📅 发布天数", "age"),
    ]

    def __init__(self, parent, gui):
        self.gui = gui
        self.dlg = DialogBase(parent, "🏆 视频排行榜", "800x540")
        self.dlg.header("视频排行榜", "按多种维度对所有监控视频排序")
        self._build_ui()

    def _build_ui(self):
        top = tk.Frame(self.dlg.content_area(), bg=C["bg_base"])
        top.pack(fill=tk.X, padx=10, pady=4)

        tk.Label(top, text="排序维度:", bg=C["bg_base"], fg=C["text_1"], font=FONT).pack(side=tk.LEFT)
        self._sort_var = tk.StringVar(value=self.SORT_OPTIONS[0][1])
        combo = ttk.Combobox(top, textvariable=self._sort_var, values=[s[0] for s in self.SORT_OPTIONS], state="readonly", font=FONT, width=20)
        combo.pack(side=tk.LEFT, padx=6)
        combo.bind("<<ComboboxSelected>>", lambda e: self._refresh())

        self._status_lbl = tk.Label(top, text="", bg=C["bg_base"], fg=C["text_3"], font=FONT_SM)
        self._status_lbl.pack(side=tk.RIGHT)

        columns = ("rank", "bvid", "title", "author", "views", "velocity", "engagement", "online")
        self._tree = ttk.Treeview(
            self.dlg.content_area(), columns=columns, show="headings", height=20
        )
        self._tree.heading("rank", text="#")
        self._tree.heading("bvid", text="BV号")
        self._tree.heading("title", text="标题")
        self._tree.heading("author", text="UP主")
        self._tree.heading("views", text="播放量")
        self._tree.heading("velocity", text="增速/h")
        self._tree.heading("engagement", text="互动率")
        self._tree.heading("online", text="在线")
        self._tree.column("rank", width=30, anchor="center")
        self._tree.column("bvid", width=100)
        self._tree.column("title", width=220)
        self._tree.column("author", width=100)
        self._tree.column("views", width=90, anchor="e")
        self._tree.column("velocity", width=80, anchor="e")
        self._tree.column("engagement", width=70, anchor="e")
        self._tree.column("online", width=70, anchor="e")
        self._tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        scroll = ttk.Scrollbar(self._tree, command=self._tree.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.configure(yscrollcommand=scroll.set)

        self._refresh()

    def _compute_velocity(self, bvid):
        history = self.gui.history_data.get(bvid, [])
        if len(history) < 2:
            return 0
        t1, v1 = history[-2]
        t0, v0 = history[-1]
        t1 = t1 if isinstance(t1, datetime) else datetime.fromisoformat(str(t1)) if isinstance(t1, str) else datetime.fromtimestamp(float(t1))
        t0 = t0 if isinstance(t0, datetime) else datetime.fromisoformat(str(t0)) if isinstance(t0, str) else datetime.fromtimestamp(float(t0))
        dt = (t0 - t1).total_seconds() / 3600
        if dt <= 0 or v0 < v1:
            return 0
        return (v0 - v1) / dt

    def _refresh(self):
        for row in self._tree.get_children():
            self._tree.delete(row)

        sort_key = self._sort_var.get()
        items = []
        for v in self.gui.monitored_videos:
            bvid = v.get("bvid", "")
            views = v.get("view_count", 0)
            likes = v.get("like_count", 0)
            coins = v.get("coin_count", 0)
            online = v.get("viewers_total", 0)
            velocity = self._compute_velocity(bvid)
            like_rate = likes / max(views, 1)
            coin_rate = coins / max(views, 1)
            engagement = (likes + coins + v.get("favorite_count", 0) + v.get("share_count", 0)) / max(views, 1)
            pubdate = v.get("pubdate", 0)
            age = (datetime.now().timestamp() - pubdate) / 86400 if pubdate > 0 else 0

            if sort_key == "velocity":
                sort_val = velocity
            elif sort_key == "views":
                sort_val = views
            elif sort_key == "like_rate":
                sort_val = like_rate
            elif sort_key == "coin_rate":
                sort_val = coin_rate
            elif sort_key == "engagement":
                sort_val = engagement
            elif sort_key == "online":
                sort_val = online
            elif sort_key == "age":
                sort_val = age
            else:
                sort_val = 0

            items.append((sort_val, bvid, v.get("title", bvid)[:30], v.get("author", ""), views, velocity, engagement, online))

        items.sort(key=lambda x: -abs(x[0]))

        for i, (_, bvid, title, author, views, velocity, engagement, online) in enumerate(items, 1):
            vel_str = fmt_num(int(velocity)) if velocity > 0 else "—"
            eng_str = f"{engagement * 100:.1f}%" if engagement > 0 else "—"
            online_str = fmt_num(online) if online > 0 else "—"
            self._tree.insert("", tk.END, values=(i, bvid, title, author, fmt_num(views), vel_str, eng_str, online_str))

        self._status_lbl.config(text=f"{len(items)} 个视频")
