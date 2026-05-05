"""
UP主追踪面板 — 查询UP主信息、追踪涨粉趋势、查看投稿列表
"""
import tkinter as tk
from tkinter import ttk, messagebox
from typing import List, Dict, Optional
from datetime import datetime

from ui.theme import C
from ui.dialog_base import DialogBase


class UpTrackerWindow:
    """UP主追踪面板"""

    def __init__(self, parent=None, api=None):
        self.dlg = DialogBase(parent, "UP主追踪", "880x620",
                              resizable=(True, True))
        self.window = self.dlg.window
        self.api = api

        # 延迟导入避免循环
        from core.up_database import UpDatabase
        self.db = UpDatabase()

        self._setup_ui()
        self._load_up_list()

    def _setup_ui(self):
        self.dlg.header("UP主追踪", "查询UP主信息、追踪涨粉与投稿趋势")

        # 添加UP主卡片
        add_sec = self.dlg.section(title="添加UP主", padding=8)
        add_row = tk.Frame(add_sec, bg=C["bg_elevated"])
        add_row.pack(fill=tk.X)
        tk.Label(add_row, text="UID:", bg=C["bg_elevated"], fg=C["text_2"],
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        self._uid_entry = tk.Entry(add_row, width=20, font=("Consolas", 10),
                                   bg=C["bg_base"], fg=C["text_1"],
                                   insertbackground=C["text_1"],
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=C["border"])
        self._uid_entry.pack(side=tk.LEFT, padx=(8, 8))
        self._uid_entry.insert(0, "8047632")
        ttk.Button(add_row, text="查询并添加", command=self._add_up,
                   style="Primary.TButton").pack(side=tk.LEFT, padx=4)

        self._up_status = tk.Label(add_sec, text="", bg=C["bg_elevated"],
                                   fg=C["text_2"], font=("Microsoft YaHei UI", 9))
        self._up_status.pack(anchor="w", padx=4, pady=(4, 0))

        # UP主列表 + 详情（水平分割）
        mid = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        mid.pack(fill=tk.BOTH, expand=True, padx=24, pady=(10, 0))

        # 列表（左）
        list_frame = tk.Frame(mid, bg=C["bg_elevated"], highlightthickness=1,
                              highlightbackground=C["border_sub"])
        list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, ipadx=6, ipady=6)

        tk.Label(list_frame, text="已追踪UP主", bg=C["bg_elevated"], fg=C["text_2"],
                 font=("Microsoft YaHei UI", 8, "bold"), anchor="w").pack(fill=tk.X, padx=6, pady=(4, 4))

        cols = ("UID", "名称", "粉丝", "投稿", "总播放")
        self._tree = ttk.Treeview(list_frame, columns=cols, show="headings",
                                   height=10, selectmode="browse")
        for col in cols:
            self._tree.heading(col, text=col)
        self._tree.column("UID", width=70)
        self._tree.column("名称", width=100)
        self._tree.column("粉丝", width=80, anchor="e")
        self._tree.column("投稿", width=60, anchor="e")
        self._tree.column("总播放", width=90, anchor="e")
        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_up_select)

        # 详情（右）
        detail_frame = tk.Frame(mid, bg=C["bg_elevated"], highlightthickness=1,
                                highlightbackground=C["border_sub"])
        detail_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0), ipadx=6, ipady=6)

        tk.Label(detail_frame, text="UP主详情", bg=C["bg_elevated"], fg=C["text_2"],
                 font=("Microsoft YaHei UI", 8, "bold"), anchor="w").pack(fill=tk.X, padx=6, pady=(4, 4))

        self._detail_text = tk.Text(detail_frame, bg=C["bg_base"], fg=C["text_1"],
                                    font=("Consolas", 10), relief="flat",
                                    state="disabled", cursor="arrow",
                                    wrap="none", padx=8, pady=6)
        self._detail_text.pack(fill=tk.BOTH, expand=True)
        self._detail_text.tag_config("head", foreground=C["bilibili"],
                                     font=("Consolas", 10, "bold"))
        self._detail_text.tag_config("val", foreground=C["text_1"],
                                     font=("Consolas", 10))
        self._detail_text.tag_config("accent", foreground=C["accent"],
                                     font=("Consolas", 10, "bold"))
        self._detail_text.tag_config("dim", foreground=C["text_3"],
                                     font=("Consolas", 9))

    def _load_up_list(self):
        for item in self._tree.get_children():
            self._tree.delete(item)
        ups = self.db.get_all_ups()
        for up in ups:
            self._tree.insert("", "end", values=(
                up.get("uid", ""),
                up.get("name", "")[:10],
                self._fmt(up.get("follower_count", 0)),
                up.get("video_count", 0),
                self._fmt(up.get("total_views", 0)),
            ))

    def _on_up_select(self, event):
        sel = self._tree.selection()
        if not sel:
            return
        item = self._tree.item(sel[0])
        uid = item["values"][0]
        up = self.db.get_up(uid)
        if not up:
            return
        self._show_detail(up)

    def _show_detail(self, up: Dict):
        self._detail_text.config(state="normal")
        self._detail_text.delete("1.0", tk.END)

        uid = up.get("uid", 0)
        lines = [
            (f"=== {up.get('name', '未知')} ===\n", "head"),
            (f"UID: {uid}\n", "val"),
            (f"等级: Lv.{up.get('level', 0)}\n", "val"),
            (f"粉丝: {self._fmt(up.get('follower_count', 0))}\n", "accent"),
            (f"投稿: {up.get('video_count', 0)}  总播放: {self._fmt(up.get('total_views', 0))}\n", "val"),
            (f"签名: {up.get('sign', '—')[:60]}\n", "dim"),
            (f"更新: {up.get('updated_at', '—')}\n", "dim"),
            ("\n", ""),
        ]
        for text, tag in lines:
            self._detail_text.insert(tk.END, text, tag)

        # 已监控视频
        videos = self.db.get_up_videos(uid)
        if videos:
            self._detail_text.insert(tk.END, "=== 已监控视频 ===\n", "head")
            for v in videos[:8]:
                self._detail_text.insert(
                    tk.END,
                    f"  {v.get('bvid','')}  {v.get('title','')[:28]}  "
                    f"{self._fmt(v.get('view_count',0))}\n",
                    "val")

        # 历史趋势
        history = self.db.get_history(uid, limit=10)
        if history:
            self._detail_text.insert(tk.END, "\n=== 粉丝趋势(近10条) ===\n", "head")
            for h in reversed(history):
                self._detail_text.insert(
                    tk.END,
                    f"  {h.get('timestamp','')[:16]}  粉丝 {self._fmt(h.get('follower_count',0))}\n",
                    "dim")

        self._detail_text.config(state="disabled")

    def _add_up(self):
        uid_str = self._uid_entry.get().strip()
        if not uid_str.isdigit():
            messagebox.showwarning("提示", "请输入有效的UID（纯数字）", parent=self.window)
            return
        uid = int(uid_str)

        existing = self.db.get_up(uid)
        if existing and existing.get("is_tracking"):
            self._up_status.config(text=f"UP主 {existing['name']} 已在追踪列表中", fg=C["warning"])
            return

        if not self.api:
            self._up_status.config(text="API不可用", fg=C["danger"])
            return

        self._up_status.config(text="正在查询...", fg=C["text_2"])
        self.window.update()

        info = self.api.get_up_info(uid)
        if not info:
            self._up_status.config(text="查询失败，请检查UID或网络", fg=C["danger"])
            return

        stat = self.api.get_up_stat(uid)
        if stat:
            info["total_views"] = stat.get("total_views", 0)
            info["total_likes"] = stat.get("total_likes", 0)

        self.db.upsert_up(info)
        self.db.add_history(
            uid=uid,
            follower_count=info.get("follower_count", 0),
            video_count=info.get("video_count", 0),
            total_views=info.get("total_views", 0),
        )

        self._load_up_list()
        self._up_status.config(
            text=f"已添加: {info.get('name', '')} (UID: {uid})  粉丝: {self._fmt(info.get('follower_count', 0))}",
            fg=C["success"])

    @staticmethod
    def _fmt(n):
        if n >= 1_0000_0000:
            return f"{n / 1_0000_0000:.2f}亿"
        if n >= 1_0000:
            return f"{n / 1_0000:.1f}万"
        return str(n)
