"""
现代化视频搜索界面
支持B站关键词搜索、批量导入到监控列表
"""
import tkinter as tk
from tkinter import ttk, messagebox
from typing import List, Dict, Callable, Optional
import threading

from core import bilibili_api
from ui.theme import C
from ui.helpers import FONT, FONT_SM
from ui.dialog_base import DialogBase


class VideoSearchWindow:
    """视频搜索窗口（现代化风格）"""

    def __init__(self, parent=None, on_import: Optional[Callable[[list], None]] = None):
        self.dlg = DialogBase(parent, "搜索视频 - B站", "920x660",
                              modal=True)
        self.window = self.dlg.window
        self.on_import = on_import
        self.search_results: List[Dict] = []
        self.searching = False

        self._setup_ui()

    def _setup_ui(self):
        self.dlg.header("搜索视频", "在B站搜索视频并批量导入到监控列表")

        # 搜索栏卡片
        sec = self.dlg.section(padding=10)
        row = tk.Frame(sec, bg=C["bg_elevated"])
        row.pack(fill=tk.X)

        tk.Label(row, text="关键词", bg=C["bg_elevated"], fg=C["text_2"],
                 font=FONT).pack(side=tk.LEFT, padx=(4, 8))
        self.kw_entry = ttk.Entry(row, width=40, font=FONT)
        self.kw_entry.pack(side=tk.LEFT, padx=(0, 8))
        self.kw_entry.bind("<Return>", lambda e: self._start_search())

        ttk.Button(row, text="搜索", command=self._start_search,
                   style="Primary.TButton").pack(side=tk.LEFT, padx=(0, 12))

        self.status_lbl = tk.Label(row, text="就绪", bg=C["bg_elevated"],
                                   fg=C["text_3"], font=FONT_SM)
        self.status_lbl.pack(side=tk.RIGHT, padx=8)

        # 结果表格
        content = self.dlg.content_area(padding=0)
        cols = ("bvid", "title", "author", "play", "like")
        tree_frame = tk.Frame(content, bg=C["bg_base"])
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                 selectmode="extended", height=18)
        self.tree.heading("bvid", text="BV号")
        self.tree.heading("title", text="标题")
        self.tree.heading("author", text="UP主")
        self.tree.heading("play", text="播放量")
        self.tree.heading("like", text="点赞")
        self.tree.column("bvid", width=120, anchor="center")
        self.tree.column("title", width=320)
        self.tree.column("author", width=120)
        self.tree.column("play", width=90, anchor="e")
        self.tree.column("like", width=80, anchor="e")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # 底部按钮
        self.dlg.button_row([
            ("全选", self._select_all, ""),
            ("取消全选", self._select_none, ""),
            ("导入所选到监控", self._do_import, "primary"),
        ])

    def _start_search(self):
        kw = self.kw_entry.get().strip()
        if not kw:
            messagebox.showwarning("提示", "请输入搜索关键词", parent=self.window)
            return
        if self.searching:
            return

        for item in self.tree.get_children():
            self.tree.delete(item)
        self.search_results.clear()
        self.searching = True
        self.status_lbl.config(text="搜索中…", fg=C["warning"])

        threading.Thread(target=self._worker, args=(kw,), daemon=True).start()

    def _worker(self, kw: str):
        try:
            results = bilibili_api.search_videos(kw, page=1, page_size=20)
            if not results:
                self.window.after(0, lambda: self.status_lbl.config(
                    text="未找到结果", fg=C["text_2"]))
                return
            for v in results:
                bvid = v.get("bvid", "")
                if not bvid:
                    continue
                self.search_results.append(v)
                title = (v.get("title", "")
                         .replace("<em class=\"keyword\">", "")
                         .replace("</em>", ""))
                self.window.after(0, lambda b=bvid, t=title, a=v.get("author", ""),
                                  p=v.get("play", 0), l=v.get("like", 0):
                self.tree.insert("", "end", iid=b,
                                 values=(b, t[:60], a,
                                         f"{p:,}" if p else "0",
                                         f"{l:,}" if l else "0")))
                self.window.after(0, lambda n=len(self.search_results):
                self.status_lbl.config(text=f"找到 {n} 个结果", fg=C["success"]))
        except Exception as e:
            self.window.after(0, lambda: self.status_lbl.config(
                text=f"搜索失败: {e}", fg=C["danger"]))
        finally:
            self.searching = False

    def _select_all(self):
        self.tree.selection_set(self.tree.get_children())

    def _select_none(self):
        self.tree.selection_remove(self.tree.get_children())

    def _do_import(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择要导入的视频", parent=self.window)
            return
        videos = [v for v in self.search_results if v.get("bvid") in sel]
        if not videos:
            return
        self.window.destroy()
        if self.on_import:
            self.on_import(videos)
