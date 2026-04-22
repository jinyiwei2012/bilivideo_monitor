"""
左侧视频列表面板模块
负责监控视频卡片的展示、搜索、选择等交互
"""
import tkinter as tk
from tkinter import ttk
import threading
from io import BytesIO

from ui.theme import C
from ui.helpers import (
    FONT, FONT_SM, FONT_MONO,
    THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS,
    fmt_num, nearest_threshold_gap, card_status_tag,
)


class VideoListPanel:
    """左侧视频列表面板"""

    def __init__(self, parent, gui):
        self.gui = gui
        self._parent = parent
        self._video_card_widgets = {}
        self._cover_cache = {}
        self._search_var = tk.StringVar()
        self._build_left_panel()

    # ──────────────────────────────────────────
    # UI 构建
    # ──────────────────────────────────────────

    def _build_left_panel(self):
        p = self._parent
        hdr = tk.Frame(p, bg=C["bg_surface"])
        hdr.pack(fill=tk.X, padx=12, pady=(10, 4))
        tk.Label(hdr, text="监控视频", bg=C["bg_surface"], fg=C["text_2"],
                 font=("Microsoft YaHei UI", 8, "bold")).pack(side=tk.LEFT)
        self._video_count_lbl = tk.Label(hdr, text="0", bg=C["bg_elevated"],
                                          fg=C["text_2"], font=FONT_SM, padx=6, pady=1)
        self._video_count_lbl.pack(side=tk.LEFT, padx=4)

        # 搜索框
        sf = tk.Frame(p, bg=C["bg_elevated"], bd=1, relief="flat",
                      highlightthickness=1, highlightbackground=C["border"],
                      highlightcolor=C["bilibili"])
        sf.pack(fill=tk.X, padx=10, pady=(0, 6))
        tk.Label(sf, text="🔍", bg=C["bg_elevated"], fg=C["text_3"],
                 font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(6, 0))
        self._search_var.trace_add("write", self._on_search)
        se = tk.Entry(sf, textvariable=self._search_var,
                      bg=C["bg_elevated"], fg=C["text_1"],
                      insertbackground=C["text_1"],
                      relief="flat", font=FONT, bd=0)
        se.pack(fill=tk.X, padx=4, pady=5)
        se.insert(0, "搜索标题或BV号…")
        se.config(fg=C["text_3"])
        self._search_entry = se

        def _focus_in(e):
            if se.get() == "搜索标题或BV号…":
                se.delete(0, tk.END)
                se.config(fg=C["text_1"])

        def _focus_out(e):
            if not se.get():
                se.insert(0, "搜索标题或BV号…")
                se.config(fg=C["text_3"])

        se.bind("<FocusIn>",  _focus_in)
        se.bind("<FocusOut>", _focus_out)

        # 滚动容器
        wrap = tk.Frame(p, bg=C["bg_surface"])
        wrap.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(wrap, bg=C["bg_surface"], bd=0,
                           highlightthickness=0, yscrollincrement=1)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._card_frame = tk.Frame(canvas, bg=C["bg_surface"])
        cwin = canvas.create_window((0, 0), window=self._card_frame, anchor="nw")
        self._list_canvas = canvas

        def _on_cf_resize(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(cwin, width=canvas.winfo_width())

        self._card_frame.bind("<Configure>", _on_cf_resize)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cwin, width=e.width))

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # 底部操作按钮行
        bottom_f = tk.Frame(p, bg=C["bg_surface"])
        bottom_f.pack(fill=tk.X, padx=10, pady=8)
        btn = tk.Label(bottom_f, text="＋  添加监控",
                       bg=C["bg_surface"], fg=C["text_2"],
                       font=FONT, cursor="hand2", pady=6,
                       relief="flat", highlightthickness=1,
                       highlightbackground=C["border"], highlightcolor=C["bilibili"])
        btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        btn.bind("<Button-1>", lambda e: self.gui._add_monitor())
        btn.bind("<Enter>", lambda e: btn.config(fg=C["bilibili"], highlightbackground=C["bilibili"]))
        btn.bind("<Leave>", lambda e: btn.config(fg=C["text_2"], highlightbackground=C["border"]))

        search_btn = tk.Label(bottom_f, text="🔍 搜索视频",
                              bg=C["bg_surface"], fg=C["text_2"],
                              font=FONT, cursor="hand2", pady=6, padx=8,
                              relief="flat", highlightthickness=1,
                              highlightbackground=C["border"], highlightcolor=C["accent"])
        search_btn.pack(side=tk.LEFT, padx=(3, 0))
        search_btn.bind("<Button-1>", lambda e: self.gui._open_video_search())
        search_btn.bind("<Enter>", lambda e: search_btn.config(fg=C["accent"], highlightbackground=C["accent"]))
        search_btn.bind("<Leave>", lambda e: search_btn.config(fg=C["text_2"], highlightbackground=C["border"]))

    # ──────────────────────────────────────────
    # 视频卡片
    # ──────────────────────────────────────────

    def make_card(self, video):
        """创建视频卡片（供外部调用）"""
        bvid   = video.get("bvid", "")
        title  = video.get("title", "未知标题")
        author = video.get("author", "未知UP主")
        views  = video.get("view_count", 0)
        gap, tidx = nearest_threshold_gap(views)

        card = tk.Frame(self._card_frame, bg=C["bg_surface"], cursor="hand2",
                        highlightthickness=1, highlightbackground=C["border_sub"])
        card.pack(fill=tk.X, padx=6, pady=2)
        inner = tk.Frame(card, bg=C["bg_surface"], padx=10, pady=8)
        inner.pack(fill=tk.X)

        top = tk.Frame(inner, bg=C["bg_surface"])
        top.pack(fill=tk.X)
        thumb_frame = tk.Frame(top, bg=C["bg_elevated"], width=80, height=45)
        thumb_frame.pack(side=tk.LEFT)
        thumb_frame.pack_propagate(False)
        thumb = tk.Label(thumb_frame, bg=C["bg_elevated"], text="")
        thumb.pack(expand=True)
        self._load_cover_thumb(video.get("pic", ""), bvid, thumb)
        info = tk.Frame(top, bg=C["bg_surface"])
        info.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        title_lbl = tk.Label(info, text=title[:28] + ("…" if len(title) > 28 else ""),
                              bg=C["bg_surface"], fg=C["text_1"],
                              font=FONT, justify="left", anchor="w", wraplength=180)
        title_lbl.pack(fill=tk.X)
        author_lbl = tk.Label(info, text=author[:16], bg=C["bg_surface"],
                               fg=C["text_2"], font=FONT_SM, anchor="w")
        author_lbl.pack(fill=tk.X)

        mid = tk.Frame(inner, bg=C["bg_surface"])
        mid.pack(fill=tk.X, pady=(6, 0))
        views_lbl = tk.Label(mid, text=fmt_num(views),
                              bg=C["bg_surface"], fg=C["text_1"],
                              font=("Consolas", 12, "bold"))
        views_lbl.pack(side=tk.LEFT)
        online_total = video.get("viewers_total", 0)
        online_text = f"👁 {fmt_num(online_total)}" if online_total > 0 else ""
        online_lbl = tk.Label(mid, text=online_text, bg=C["bg_surface"],
                               fg=C["accent"], font=("Consolas", 9))
        online_lbl.pack(side=tk.LEFT, padx=(10, 0))
        stag, stag_fg = card_status_tag(gap)
        tag_lbl = tk.Label(mid, text=stag, bg=C["bg_surface"], fg=stag_fg, font=FONT_SM)
        tag_lbl.pack(side=tk.RIGHT)

        prog_f = tk.Frame(inner, bg=C["bg_surface"])
        prog_f.pack(fill=tk.X, pady=(5, 0))
        prog_bg = tk.Frame(prog_f, bg=C["bg_hover"], height=3)
        prog_bg.pack(fill=tk.X)
        prog_bg.pack_propagate(False)
        if tidx >= 0:
            thr, pct, fill_c = THRESHOLDS[tidx], min(views / THRESHOLDS[tidx], 1.0), THRESH_COLORS[tidx]
        else:
            pct, fill_c = 1.0, C["success"]
        prog_fill = tk.Frame(prog_bg, bg=fill_c, height=3)
        prog_fill.place(x=0, y=0, relwidth=pct, relheight=1)

        label_f = tk.Frame(inner, bg=C["bg_surface"])
        label_f.pack(fill=tk.X)
        if gap > 0:
            gap_text = f"距{THRESHOLD_NAMES[tidx]}：{fmt_num(gap)}"
            pct_text = f"{pct*100:.1f}%"
        else:
            gap_text, pct_text = "已全部达标 ✓", ""
        gap_lbl = tk.Label(label_f, text=gap_text, bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM)
        gap_lbl.pack(side=tk.LEFT)
        pct_lbl = tk.Label(label_f, text=pct_text, bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM)
        pct_lbl.pack(side=tk.RIGHT)

        self._video_card_widgets[bvid] = {
            "card": card, "inner": inner, "thumb": thumb,
            "title": title_lbl, "author": author_lbl,
            "views": views_lbl, "tag": tag_lbl, "online": online_lbl,
            "prog_fill": prog_fill, "gap_lbl": gap_lbl, "pct_lbl": pct_lbl,
        }

        def _select(e, bv=bvid):
            self.gui._select_video(bv)

        for w in [card, inner, top, info, mid, prog_f, label_f,
                  title_lbl, author_lbl, views_lbl, tag_lbl, thumb]:
            w.bind("<Button-1>", _select)
        return card

    def update_card(self, video):
        """更新卡片数据"""
        bvid  = video.get("bvid", "")
        refs  = self._video_card_widgets.get(bvid)
        if not refs:
            return
        views = video.get("view_count", 0)
        gap, tidx = nearest_threshold_gap(views)
        refs["title"].config(text=video.get("title","")[:28] + ("…" if len(video.get("title","")) > 28 else ""))
        refs["author"].config(text=video.get("author","")[:16])
        refs["views"].config(text=fmt_num(views))
        online_total = video.get("viewers_total", 0)
        online_text = f"👁 {fmt_num(online_total)}" if online_total > 0 else ""
        refs["online"].config(text=online_text)
        stag, stag_fg = card_status_tag(gap)
        refs["tag"].config(text=stag, fg=stag_fg)
        if tidx >= 0:
            thr = THRESHOLDS[tidx]
            pct = min(views / thr, 1.0)
            fill_c = THRESH_COLORS[tidx]
            refs["gap_lbl"].config(text=f"距{THRESHOLD_NAMES[tidx]}：{fmt_num(gap)}")
            refs["pct_lbl"].config(text=f"{pct*100:.1f}%")
        else:
            pct, fill_c = 1.0, C["success"]
            refs["gap_lbl"].config(text="已全部达标 ✓")
            refs["pct_lbl"].config(text="")
        refs["prog_fill"].config(bg=fill_c)
        refs["prog_fill"].place(relwidth=pct)
        is_sel = (bvid == self.gui.selected_bvid)
        hl_bg = C["bg_elevated"] if is_sel else C["border_sub"]
        refs["card"].config(highlightbackground=hl_bg)

    def highlight_card(self, bvid):
        """高亮指定卡片"""
        for bv, refs in self._video_card_widgets.items():
            hl_bg = C["bilibili"] if bv == bvid else C["border_sub"]
            refs["card"].config(highlightbackground=hl_bg)

    # ──────────────────────────────────────────
    # 搜索过滤
    # ──────────────────────────────────────────

    def _on_search(self, *args):
        q = self._search_var.get().strip().lower()
        if q == "搜索标题或bv号…" or q == "":
            q = ""
        for bvid, refs in self._video_card_widgets.items():
            video = next((v for v in self.gui.monitored_videos if v.get("bvid") == bvid), None)
            if not video:
                continue
            visible = (not q or q in video.get("title", "").lower() or
                       q in bvid.lower() or q in video.get("author", "").lower())
            refs["card"].pack(fill=tk.X, padx=6, pady=2) if visible else refs["card"].pack_forget()

    def copy_bvid(self, bvid):
        """复制 BV 号"""
        self.gui.root.clipboard_clear()
        self.gui.root.clipboard_append(bvid)
        self.gui._sb("status", f"已复制 {bvid}", C["success"])

    # ──────────────────────────────────────────
    # 封面异步加载
    # ──────────────────────────────────────────

    def _load_cover_thumb(self, url, bvid, label_widget):
        """异步加载卡片封面缩略图（80×45）"""
        cache_key = (bvid, "thumb")
        if cache_key in self._cover_cache:
            label_widget.config(image=self._cover_cache[cache_key], text="")
            return
        if not url:
            return
        def _fetch():
            try:
                import requests as req
                from PIL import Image, ImageTk
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                          "Referer": "https://www.bilibili.com/"}
                r = req.get(url, timeout=8, headers=headers)
                if r.status_code != 200:
                    return
                img = Image.open(BytesIO(r.content))
                w, h = img.size
                target_w, target_h = 80, 45
                ratio = min(target_w / w, target_h / h)
                new_w, new_h = int(w * ratio), int(h * ratio)
                img = img.resize((new_w, new_h), Image.LANCZOS)
                ph = ImageTk.PhotoImage(img)
                self._cover_cache[cache_key] = ph
                self.gui.root.after(0, lambda: self._safe_set_image(label_widget, ph))
            except Exception as e:
                print(f"缩略图加载失败 {bvid}: {e}")
        threading.Thread(target=_fetch, daemon=True).start()

    def _safe_set_image(self, widget, ph):
        """安全地给 widget 设置图片"""
        try:
            if widget.winfo_exists():
                widget.config(image=ph, text="")
        except tk.TclError:
            pass

    def update_video_count(self):
        """更新视频计数标签"""
        self._video_count_lbl.config(text=str(len(self.gui.monitored_videos)))

    def get_card_widgets(self):
        return self._video_card_widgets

    def remove_card(self, bvid):
        """删除指定卡片"""
        refs = self._video_card_widgets.pop(bvid, None)
        if refs:
            refs["card"].destroy()
