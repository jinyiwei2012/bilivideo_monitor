"""
UP主追踪面板模块
===============

提供 ``UpTrackerWindow`` 类，用于查询 UP 主信息、追踪涨粉趋势、查看投稿列表。

功能：
  - 添加 UP 主：通过 UID 查询或用户名搜索
  - 已追踪列表（Treeview）：UID、名称、粉丝、投稿、总播放
  - 详情展示：等级、签名、粉丝趋势（近 10 条）、关联的已监控视频
  - 刷新单个 UP 主数据
  - 数据持久化：通过 ``UpDatabase`` 存储到 SQLite

.. note::
   依赖 ``core.up_database.UpDatabase`` 进行数据持久化。
   ``_fmt`` 静态方法用于将大数字格式化为中文单位。
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict

from ui.theme import C
from ui.dialog_base import DialogBase


class UpTrackerWindow:
    """UP主追踪面板 — 查询UP主信息、追踪涨粉趋势、查看投稿列表"""

    def __init__(self, parent=None, api=None):
        """
        初始化 UP 主追踪窗口。

        :param parent: 父窗口
        :param api: BilibiliAPI 实例，用于查询 UP 主信息
        """
        self.dlg = DialogBase(
            parent, "UP主追踪", DialogBase.calc_geometry(parent, 0.50, 0.68), resizable=(True, True), modal=False
        )
        self.window = self.dlg.window
        self.api = api

        from core.up_database import UpDatabase

        self.db = UpDatabase()  # UP 主数据库实例

        self._setup_ui()
        self._load_up_list()     # 初始化时加载已追踪列表

    def _setup_ui(self):
        """
        构建界面：
          添加 UP 主卡片（UID 输入 + 用户名搜索）
          已追踪列表（左） + 详情展示（右）
        """
        self.dlg.header("UP主追踪", "查询UP主信息、追踪涨粉与投稿趋势")

        # ── 添加UP主卡片（双行：UID 输入 + 用户名搜索）──
        add_sec = self.dlg.section(title="添加UP主", padding=8)

        # 第一行：UID 输入
        uid_row = tk.Frame(add_sec, bg=C["bg_elevated"])
        uid_row.pack(fill=tk.X, pady=(0, 4))
        tk.Label(uid_row, text="UID:", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 10)).pack(
            side=tk.LEFT
        )
        self._uid_entry = tk.Entry(
            uid_row,
            width=20,
            font=("Consolas", 10),
            bg=C["bg_base"],
            fg=C["text_1"],
            insertbackground=C["text_1"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=C["border"],
        )
        self._uid_entry.pack(side=tk.LEFT, padx=(8, 8))
        self._uid_entry.insert(0, "8047632")  # 默认示例 UID
        ttk.Button(uid_row, text="查询并添加", command=self._add_up, style="Primary.TButton").pack(side=tk.LEFT, padx=4)

        # 第二行：用户名搜索
        name_row = tk.Frame(add_sec, bg=C["bg_elevated"])
        name_row.pack(fill=tk.X)
        tk.Label(name_row, text="用户名:", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 10)).pack(
            side=tk.LEFT
        )
        self._name_entry = tk.Entry(
            name_row,
            width=20,
            font=("Microsoft YaHei UI", 10),
            bg=C["bg_base"],
            fg=C["text_1"],
            insertbackground=C["text_1"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=C["border"],
        )
        self._name_entry.pack(side=tk.LEFT, padx=(8, 8))
        self._name_entry.bind("<Return>", lambda e: self._search_by_name())  # 回车搜索
        ttk.Button(name_row, text="搜索UP主", command=self._search_by_name, style="Primary.TButton").pack(
            side=tk.LEFT, padx=4
        )

        # 状态提示标签
        self._up_status = tk.Label(
            add_sec, text="", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 9)
        )
        self._up_status.pack(anchor="w", padx=4, pady=(4, 0))

        # 搜索结果列表框（初始隐藏，搜索后显示）
        self._search_frame = tk.Frame(
            add_sec, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["accent"]
        )
        self._search_list = tk.Listbox(
            self._search_frame,
            height=4,
            bg=C["bg_base"],
            fg=C["text_1"],
            font=("Microsoft YaHei UI", 9),
            relief="flat",
            selectbackground=C["bilibili"],
            activestyle="none",
        )
        self._search_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._search_list.bind("<Double-Button-1>", lambda e: self._add_from_search())  # 双击添加

        # ── 已追踪列表 + 详情（水平分割）──
        mid = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        mid.pack(fill=tk.BOTH, expand=True, padx=24, pady=(10, 0))

        # 左侧：已追踪列表（Treeview）
        list_frame = tk.Frame(mid, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, ipadx=6, ipady=6)

        list_header = tk.Frame(list_frame, bg=C["bg_elevated"])
        list_header.pack(fill=tk.X, padx=6, pady=(4, 4))
        tk.Label(
            list_header,
            text="已追踪UP主",
            bg=C["bg_elevated"],
            fg=C["text_2"],
            font=("Microsoft YaHei UI", 8, "bold"),
            anchor="w",
        ).pack(side=tk.LEFT)
        ttk.Button(list_header, text="🔄 刷新", command=self._refresh_selected).pack(side=tk.RIGHT)

        cols = ("UID", "名称", "粉丝", "投稿", "总播放")
        self._tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=10, selectmode="browse")
        for col in cols:
            self._tree.heading(col, text=col)
        self._tree.column("UID", width=70)
        self._tree.column("名称", width=100)
        self._tree.column("粉丝", width=80, anchor="e")
        self._tree.column("投稿", width=60, anchor="e")
        self._tree.column("总播放", width=90, anchor="e")
        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_up_select)

        # 右侧：详情展示（只读 Text）
        detail_frame = tk.Frame(mid, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        detail_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0), ipadx=6, ipady=6)

        tk.Label(
            detail_frame,
            text="UP主详情",
            bg=C["bg_elevated"],
            fg=C["text_2"],
            font=("Microsoft YaHei UI", 8, "bold"),
            anchor="w",
        ).pack(fill=tk.X, padx=6, pady=(4, 4))

        self._detail_text = tk.Text(
            detail_frame,
            bg=C["bg_base"],
            fg=C["text_1"],
            font=("Consolas", 10),
            relief="flat",
            state="disabled",
            cursor="arrow",
            wrap="none",
            padx=8,
            pady=6,
        )
        self._detail_text.pack(fill=tk.BOTH, expand=True)
        # 详情文本样式标签
        self._detail_text.tag_config("head", foreground=C["bilibili"], font=("Consolas", 10, "bold"))
        self._detail_text.tag_config("val", foreground=C["text_1"], font=("Consolas", 10))
        self._detail_text.tag_config("accent", foreground=C["accent"], font=("Consolas", 10, "bold"))
        self._detail_text.tag_config("dim", foreground=C["text_3"], font=("Consolas", 9))

    def _load_up_list(self):
        """
        加载已追踪的 UP 主列表到 Treeview。
        从数据库读取 → 填充表格行（UID、名称、粉丝、投稿、总播放）。
        数值使用 _fmt 格式化为中文单位。
        """
        for item in self._tree.get_children():
            self._tree.delete(item)
        ups = self.db.get_all_ups()
        for up in ups:
            self._tree.insert(
                "",
                "end",
                values=(
                    up.get("uid", ""),
                    up.get("name", "")[:10],
                    self._fmt(up.get("follower_count", 0)),
                    up.get("video_count", 0),
                    self._fmt(up.get("total_views", 0)),
                ),
            )

    def _on_up_select(self, event):
        """
        UP 主列表选中事件 — 获取选中行的 UID → 从数据库查询详情 → 显示在右侧。

        :param event: Treeview 选中事件
        """
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
        """
        在详情区域格式化显示 UP 主的完整信息：
          名称、UID、等级、粉丝、投稿、总播放、总点赞、签名、更新时间
          关联的已监控视频（最多 8 条）
          粉丝历史趋势（近 10 条，倒序显示）

        :param up: UP 主信息字典
        """
        self._detail_text.config(state="normal")
        self._detail_text.delete("1.0", tk.END)

        uid = up.get("uid", 0)
        fc = up.get("follower_count", 0)
        vc = up.get("video_count", 0)
        tv = up.get("total_views", 0)
        tl = up.get("total_likes", 0)
        lines = [
            (f"=== {up.get('name', '未知')} ===\n", "head"),
            (f"UID: {uid}\n", "val"),
            (f"等级: Lv.{up.get('level', 0)}\n", "val"),
            (f"粉丝: {self._fmt(fc):>8}    {fc:,}\n", "accent"),
            (f"投稿: {vc:>8,}    总播放: {self._fmt(tv):>8}    {tv:,}\n", "val"),
            (f"总点赞: {self._fmt(tl):>8}    {tl:,}\n", "val"),
            (f"签名: {up.get('sign', '—')[:60]}\n", "dim"),
            (f"更新: {up.get('updated_at', '—')}\n", "dim"),
            ("\n", ""),
        ]
        for text, tag in lines:
            self._detail_text.insert(tk.END, text, tag)

        # 该 UP 主关联的已监控视频（最多 8 条）
        videos = self.db.get_up_videos(uid)
        if videos:
            self._detail_text.insert(tk.END, "=== 已监控视频 ===\n", "head")
            for v in videos[:8]:
                self._detail_text.insert(
                    tk.END,
                    f"  {v.get('bvid', '')}  {v.get('title', '')[:28]}  " f"{self._fmt(v.get('view_count', 0))}\n",
                    "val",
                )

        # 粉丝历史趋势（近 10 条，倒序显示为时间正序）
        history = self.db.get_history(uid, limit=10)
        if history:
            self._detail_text.insert(tk.END, "\n=== 粉丝趋势(近10条) ===\n", "head")
            for h in reversed(history):  # 倒序以便时间正序显示
                self._detail_text.insert(
                    tk.END, f"  {h.get('timestamp', '')[:16]}  粉丝 {self._fmt(h.get('follower_count', 0))}\n", "dim"
                )

        self._detail_text.config(state="disabled")

    def _refresh_selected(self):
        """
        刷新当前选中 UP 主的最新数据。
        调用 API 获取 UP 主信息和统计 → 更新数据库 → 刷新列表和详情。
        """
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选择一个UP主", parent=self.window)
            return
        item = self._tree.item(sel[0])
        uid = item["values"][0]

        if not self.api:
            self._up_status.config(text="API不可用", fg=C["danger"])
            return

        self._up_status.config(text=f"正在刷新 UID:{uid} 数据...", fg=C["text_2"])
        self.window.update()  # 强制刷新 UI

        info = self.api.get_up_info(uid)
        if not info:
            self._up_status.config(text="刷新失败，请检查网络", fg=C["danger"])
            return

        stat = self.api.get_up_stat(uid)
        if stat:
            info["total_views"] = stat.get("total_views", 0)
            info["total_likes"] = stat.get("total_likes", 0)

        # 持久化：upsert + 添加历史记录
        self.db.upsert_up(info)
        self.db.add_history(
            uid=uid,
            follower_count=info.get("follower_count", 0),
            video_count=info.get("video_count", 0),
            total_views=info.get("total_views", 0),
        )

        self._load_up_list()
        self._show_detail(info)
        self._up_status.config(
            text=f"刷新完成: {info.get('name', '')}  粉丝: {self._fmt(info.get('follower_count', 0))}", fg=C["success"]
        )

    def _search_by_name(self):
        """
        按用户名搜索 UP 主。
        调用 API 搜索 → 在搜索结果 Listbox 中展示结果（UID、名称、粉丝、投稿）。
        支持双击添加。
        """
        keyword = self._name_entry.get().strip()
        if not keyword:
            messagebox.showwarning("提示", "请输入要搜索的用户名", parent=self.window)
            return
        if not self.api:
            self._up_status.config(text="API不可用", fg=C["danger"])
            return

        self._up_status.config(text="正在搜索...", fg=C["text_2"])
        self.window.update()

        results = self.api.search_up_users(keyword)
        self._search_list.delete(0, tk.END)

        if not results:
            self._up_status.config(text="未找到匹配的UP主", fg=C["warning"])
            self._search_frame.pack_forget()
            return

        self._search_results = results
        for r in results:
            name = r.get("uname", "?")
            fans = self._fmt(r.get("fans", 0))
            videos = r.get("videos", 0)
            uid = r.get("mid", 0)
            self._search_list.insert(tk.END, f"[{uid}] {name}  粉丝:{fans}  投稿:{videos}")

        self._search_frame.pack(fill=tk.X, padx=26, pady=(0, 4), ipadx=6, ipady=4)  # 显示搜索结果面板
        self._up_status.config(text=f"找到 {len(results)} 个UP主，双击添加", fg=C["success"])

    def _add_from_search(self):
        """
        从搜索结果中添加 UP 主。
        获取选中行的 UID → 填入 UID 输入框 → 调用 _add_up。
        """
        sel = self._search_list.curselection()
        if not sel:
            return
        r = self._search_results[sel[0]]
        uid = r.get("mid", 0)
        self._uid_entry.delete(0, tk.END)
        self._uid_entry.insert(0, str(uid))
        self._add_up()

    def _add_up(self):
        """
        根据 UID 查询并添加 UP 主到追踪列表。
        验证 UID 格式 → 检查是否已添加 → 调用 API 获取信息 → 持久化 → 刷新列表。
        """
        uid_str = self._uid_entry.get().strip()
        if not uid_str.isdigit():
            messagebox.showwarning("提示", "请输入有效的UID（纯数字）", parent=self.window)
            return
        uid = int(uid_str)

        # 检查是否已存在
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

        # 持久化
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
            fg=C["success"],
        )

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
