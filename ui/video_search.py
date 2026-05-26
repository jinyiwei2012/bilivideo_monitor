"""
现代化视频搜索界面
支持B站关键词搜索、批量导入到监控列表
"""

import io
import tkinter as tk
from tkinter import ttk, messagebox
from typing import List, Dict, Callable, Optional
import threading
import webbrowser

from core import get_bilibili_api
from ui.theme import C
from ui.helpers import FONT, FONT_SM
from ui.dialog_base import DialogBase


class VideoSearchWindow:
    """视频搜索窗口（现代化风格）"""

    def __init__(self, parent=None, on_import: Optional[Callable[[list], None]] = None):
        self.dlg = DialogBase(parent, "搜索视频 - B站", DialogBase.calc_geometry(parent, 0.48, 0.68), modal=True)
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

        tk.Label(row, text="关键词", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT, padx=(4, 8))
        self.kw_entry = ttk.Entry(row, width=40, font=FONT)
        self.kw_entry.pack(side=tk.LEFT, padx=(0, 8))
        self.kw_entry.bind("<Return>", lambda e: self._start_search())

        ttk.Button(row, text="搜索", command=self._start_search, style="Primary.TButton").pack(
            side=tk.LEFT, padx=(0, 12)
        )

        self.status_lbl = tk.Label(row, text="就绪", bg=C["bg_elevated"], fg=C["text_3"], font=FONT_SM)
        self.status_lbl.pack(side=tk.RIGHT, padx=8)

        # 结果表格 + 底部按钮（注意 packing 顺序：按钮先占底部，表格填剩余空间）
        bottom_bar = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        bottom_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=24, pady=(16, 20))
        ttk.Button(bottom_bar, text="全选", command=self._select_all).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(bottom_bar, text="取消全选", command=self._select_none).pack(side=tk.LEFT, padx=6)
        ttk.Button(bottom_bar, text="导入所选到监控", command=self._do_import, style="Primary.TButton").pack(
            side=tk.RIGHT, padx=(6, 0)
        )

        content = tk.Frame(self.dlg.container, bg=C["bg_base"])
        content.pack(fill=tk.BOTH, expand=True, padx=24, pady=(10, 0))
        cols = ("bvid", "title", "author", "play", "like")
        tree_frame = tk.Frame(content, bg=C["bg_base"])
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="extended", height=18)
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
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Button-3>", self._on_tree_right_click)
        self._context_menu = tk.Menu(
            self.tree,
            tearoff=0,
            bg=C["bg_elevated"],
            fg=C["text_1"],
            activebackground=C["bg_hover"],
            activeforeground=C["text_1"],
            font=("Microsoft YaHei UI", 9),
            bd=0,
        )

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
            results = get_bilibili_api().search_videos(kw, page=1, page_size=20)
            if not results:
                self.window.after(0, lambda: self.status_lbl.config(text="未找到结果", fg=C["text_2"]))
                return
            for v in results:
                bvid = v.get("bvid", "")
                if not bvid:
                    continue
                self.search_results.append(v)
                title = v.get("title", "").replace('<em class="keyword">', "").replace("</em>", "")
                self.window.after(
                    0,
                    lambda b=bvid, t=title, a=v.get("author", ""), p=v.get("play", 0), lk=v.get(
                        "like", 0
                    ): self.tree.insert(
                        "", "end", iid=b, values=(b, t[:60], a, f"{p:,}" if p else "0", f"{lk:,}" if lk else "0")
                    ),
                )
                self.window.after(
                    0,
                    lambda n=len(self.search_results): self.status_lbl.config(text=f"找到 {n} 个结果", fg=C["success"]),
                )
        except Exception as e:
            self.window.after(0, lambda e=e: self.status_lbl.config(text=f"搜索失败: {e}", fg=C["danger"]))
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

    def _on_tree_double_click(self, event):
        """双击单条结果快速导入"""
        sel = self.tree.selection()
        if not sel:
            return
        bvid = sel[0]
        video = next((v for v in self.search_results if v.get("bvid") == bvid), None)
        if not video:
            return
        self.window.destroy()
        if self.on_import:
            self.on_import([video])

    def _on_tree_right_click(self, event):
        """右键菜单：查看详情 / 复制BV号 / 浏览器打开 / 导入"""
        item = self.tree.identify_row(event.y)
        if not item:
            return
        self.tree.selection_set(item)
        bvid = item
        video = next((v for v in self.search_results if v.get("bvid") == bvid), None)
        if not video:
            return

        self._context_menu.delete(0, "end")
        self._context_menu.add_command(label="📋 查看详情", command=lambda: self._show_video_detail(video))
        self._context_menu.add_command(label="📑 复制BV号", command=lambda: self._copy_bvid(bvid))
        self._context_menu.add_command(
            label="🌐 在浏览器中打开", command=lambda: webbrowser.open(f"https://www.bilibili.com/video/{bvid}")
        )
        self._context_menu.add_separator()
        self._context_menu.add_command(label="➕ 导入该视频", command=lambda: self._import_single(video))
        self._context_menu.tk_popup(event.x_root, event.y_root)

    def _show_video_detail(self, video):
        """弹出详情对话框显示搜索结果的视频信息"""
        bvid = video.get("bvid", "")
        title = video.get("title", "").replace('<em class="keyword">', "").replace("</em>", "")
        author = video.get("author", "未知")
        play = video.get("play", 0)
        like = video.get("like", 0)
        pic = video.get("pic", "")

        top = tk.Toplevel(self.window)
        top.title(f"视频详情 - {bvid}")
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        top.geometry(f"{int(sw * 0.32)}x{int(sh * 0.48)}")
        top.configure(bg=C["bg_surface"])
        top.transient(self.window)
        top.grab_set()

        tk.Label(
            top, text="视频详情", bg=C["bg_surface"], fg=C["text_1"], font=("Microsoft YaHei UI", 14, "bold")
        ).pack(pady=(20, 4))

        if pic.startswith("http"):
            try:
                import requests
                from PIL import Image, ImageTk

                resp = requests.get(pic, timeout=5)
                img = Image.open(io.BytesIO(resp.content)).resize((320, 180))
                self._detail_img = ImageTk.PhotoImage(img)
                tk.Label(top, image=self._detail_img, bg=C["bg_surface"]).pack(pady=8)
            except Exception:
                pass

        info = tk.Frame(top, bg=C["bg_surface"])
        info.pack(pady=8, padx=30, fill=tk.X)
        rows = [
            ("BV号", bvid),
            ("标题", title),
            ("UP主", author),
            ("播放量", f"{play:,}" if play else "0"),
            ("点赞", f"{like:,}" if like else "0"),
        ]
        for label, value in rows:
            row = tk.Frame(info, bg=C["bg_surface"])
            row.pack(fill=tk.X, pady=2)
            tk.Label(
                row, text=label, bg=C["bg_surface"], fg=C["text_3"], font=("Microsoft YaHei UI", 9), width=8, anchor="w"
            ).pack(side=tk.LEFT)
            tk.Label(
                row, text=value, bg=C["bg_surface"], fg=C["text_1"], font=("Microsoft YaHei UI", 9), anchor="w"
            ).pack(side=tk.LEFT, padx=(8, 0))

        btn_row = tk.Frame(top, bg=C["bg_surface"])
        btn_row.pack(pady=(16, 20))
        ttk.Button(
            btn_row, text="🌐 浏览器打开", command=lambda: webbrowser.open(f"https://www.bilibili.com/video/{bvid}")
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="➕ 导入监控", command=lambda: [top.destroy(), self._import_single(video)]).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_row, text="关闭", command=top.destroy).pack(side=tk.LEFT, padx=4)

    def _copy_bvid(self, bvid):
        self.window.clipboard_clear()
        self.window.clipboard_append(bvid)
        self.status_lbl.config(text=f"已复制 {bvid}", fg=C["success"])

    def _import_single(self, video):
        """导入单个视频到监控"""
        self.window.destroy()
        if self.on_import:
            self.on_import([video])
