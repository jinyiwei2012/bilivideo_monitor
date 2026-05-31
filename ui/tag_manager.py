"""
视频标签管理窗口
为监控视频添加/删除/筛选自定义标签
"""

import tkinter as tk
from tkinter import ttk, messagebox
from ui.theme import C
from ui.helpers import FONT, FONT_SM
from ui.dialog_base import DialogBase
from utils.tag_manager import get_tags, set_tags, all_tags, remove_tag


class TagManagerWindow:
    """视频标签管理窗口 — 支持为监控视频添加/删除/筛选自定义标签"""

    def __init__(self, parent, gui):
        """初始化标签管理窗口"""
        self.gui = gui
        self.dlg = DialogBase(parent, "🎫 视频标签管理", "600x500")
        self.dlg.header("视频标签管理", "为监控视频添加自定义标签，方便分类筛选")
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        """构建界面布局：左侧视频列表 + 标签输入，右侧当前标签 + 筛选"""
        main = tk.Frame(self.dlg.content_area(), bg=C["bg_base"])
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        left = tk.Frame(main, bg=C["bg_base"])
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 视频列表
        tk.Label(left, text="监控视频", bg=C["bg_base"], fg=C["text_1"], font=FONT).pack(anchor="w")
        self._video_listbox = tk.Listbox(
            left, bg=C["bg_elevated"], fg=C["text_1"], selectbackground=C["bilibili"],
            font=FONT, relief=tk.FLAT, borderwidth=0, highlightthickness=0
        )
        self._video_listbox.pack(fill=tk.BOTH, expand=True, pady=(4, 6))
        self._video_listbox.bind("<<ListboxSelect>>", self._on_select)

        # 标签输入框 + 添加按钮
        tag_frame = tk.Frame(left, bg=C["bg_base"])
        tag_frame.pack(fill=tk.X)
        self._tag_entry = tk.Entry(
            tag_frame, bg=C["bg_elevated"], fg=C["text_1"], insertbackground=C["text_1"],
            font=FONT, relief=tk.FLAT, bd=0
        )
        self._tag_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4), ipady=4)
        self._tag_entry.bind("<Return>", lambda e: self._add_tag())
        ttk.Button(tag_frame, text="添加标签", command=self._add_tag).pack(side=tk.RIGHT)

        # 右侧：当前标签展示
        right = tk.Frame(main, bg=C["bg_base"], width=200)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        right.pack_propagate(False)

        tk.Label(right, text="当前标签", bg=C["bg_base"], fg=C["text_1"], font=FONT).pack(anchor="w")
        self._tags_frame = tk.Frame(right, bg=C["bg_base"])
        self._tags_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 6))

        # 按标签筛选下拉框
        tk.Label(right, text="按标签筛选", bg=C["bg_base"], fg=C["text_1"], font=FONT).pack(anchor="w")
        self._filter_var = tk.StringVar(value="")
        self._filter_combo = ttk.Combobox(
            right, textvariable=self._filter_var, font=FONT, state="readonly"
        )
        self._filter_combo.pack(fill=tk.X, pady=(4, 0))
        self._filter_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh())

        btn_frame = tk.Frame(right, bg=C["bg_base"])
        btn_frame.pack(fill=tk.X, pady=6)
        ttk.Button(btn_frame, text="清除筛选", command=lambda: [self._filter_var.set(""), self._refresh()]).pack(
            fill=tk.X)

    def _refresh(self):
        """刷新视频列表和筛选下拉框"""
        self._video_listbox.delete(0, tk.END)
        self._bvid_map = []
        filter_tag = self._filter_var.get()
        # 遍历所有监控视频，按标签筛选后插入列表
        for v in self.gui.monitored_videos:
            bvid = v.get("bvid", "")
            title = v.get("title", bvid)[:30]
            tags = get_tags(bvid)
            if filter_tag and filter_tag not in tags:
                continue
            display = f"[{' '.join(tags)}] {title}" if tags else title
            self._video_listbox.insert(tk.END, display)
            self._bvid_map.append(bvid)

        # 刷新筛选下拉框的可选值
        all = sorted(all_tags())
        self._filter_combo["values"] = all
        if self._filter_var.get() not in all:
            self._filter_var.set("")

        self._selected_bvid = None

    def _on_select(self, event):
        """视频列表选中事件 — 更新选中视频并显示其标签"""
        sel = self._video_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self._bvid_map):
            self._selected_bvid = self._bvid_map[idx]
            self._refresh_tags()

    def _refresh_tags(self):
        """刷新当前选中视频的标签显示"""
        for w in self._tags_frame.winfo_children():
            w.destroy()
        if not self._selected_bvid:
            return
        # 遍历标签，为每个标签创建一行显示 + 删除按钮
        for tag in get_tags(self._selected_bvid):
            row = tk.Frame(self._tags_frame, bg=C["bg_surface"])
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text=f"  #{tag}", bg=C["bg_surface"], fg=C["accent"], font=FONT).pack(side=tk.LEFT)
            del_btn = tk.Label(row, text="✕", bg=C["bg_surface"], fg=C["danger"], font=FONT, cursor="hand2")
            del_btn.pack(side=tk.RIGHT, padx=4)
            del_btn.bind("<Button-1>", lambda e, t=tag: self._delete_tag(t))

    def _delete_tag(self, tag):
        """删除指定标签"""
        if self._selected_bvid:
            existing = get_tags(self._selected_bvid)
            if tag in existing:
                existing.remove(tag)
                set_tags(self._selected_bvid, existing)
            self._refresh_tags()

    def _add_tag(self):
        """为选中视频添加新标签"""
        if not self._selected_bvid:
            messagebox.showwarning("提示", "请先在左侧选择一个视频", parent=self.dlg.window)
            return
        tag = self._tag_entry.get().strip()
        if not tag:
            return
        if " " in tag:
            messagebox.showwarning("提示", "标签不能包含空格", parent=self.dlg.window)
            return
        existing = get_tags(self._selected_bvid)
        if tag not in existing:
            set_tags(self._selected_bvid, existing + [tag])
        self._tag_entry.delete(0, tk.END)
        self._refresh_tags()
        self._refresh()
