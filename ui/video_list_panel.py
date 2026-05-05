"""
左侧视频列表面板模块 - CustomTkinter 版
负责监控视频卡片的展示、搜索、选择等交互
"""
import tkinter as tk
import customtkinter as ctk
import threading
import logging
import requests as _req
from io import BytesIO

# 模块级共享 Session + 信号量（限制封面并发数）
_cover_session = _req.Session()
_cover_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.com/",
})
_cover_semaphore = threading.Semaphore(4)  # 最多 4 个并发下载

logger = logging.getLogger(__name__)

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
        hdr = ctk.CTkFrame(p, fg_color=C["bg_surface"], corner_radius=0)
        hdr.pack(fill=tk.X, padx=12, pady=(10, 4))
        ctk.CTkLabel(hdr, text="监控视频", text_color=C["text_2"],
                     font=("Microsoft YaHei UI", 8, "bold"),
                     fg_color="transparent").pack(side=tk.LEFT)
        self._video_count_lbl = ctk.CTkLabel(hdr, text="0",
                                             fg_color=C["bg_elevated"],
                                             text_color=C["text_2"], font=FONT_SM,
                                             corner_radius=4)
        self._video_count_lbl.pack(side=tk.LEFT, padx=4)

        # 搜索框
        self._search_entry = ctk.CTkEntry(
            p, placeholder_text="搜索标题或BV号…",
            fg_color=C["bg_elevated"], text_color=C["text_1"],
            placeholder_text_color=C["text_3"],
            border_width=1, border_color=C["border"],
            font=FONT, corner_radius=6,
        )
        self._search_entry.pack(fill=tk.X, padx=10, pady=(0, 6))
        self._search_entry.configure(textvariable=self._search_var)
        self._search_var.trace_add("write", self._on_search)

        # 可滚动卡片容器
        self._card_frame = ctk.CTkScrollableFrame(
            p, fg_color=C["bg_surface"], corner_radius=0,
            scrollbar_button_color=C["bg_hover"],
            scrollbar_button_hover_color=C["border"],
        )
        self._card_frame.pack(fill=tk.BOTH, expand=True)

        # 底部操作按钮行
        bottom_f = ctk.CTkFrame(p, fg_color=C["bg_surface"], corner_radius=0)
        bottom_f.pack(fill=tk.X, padx=10, pady=8)

        add_btn = ctk.CTkButton(
            bottom_f, text="＋ 添加监控",
            fg_color=C["bg_surface"], text_color=C["text_2"],
            hover_color=C["bg_hover"], font=FONT,
            corner_radius=6, border_width=1, border_color=C["border"],
            command=self.gui._add_monitor,
        )
        add_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))

        search_btn = ctk.CTkButton(
            bottom_f, text="🔍 搜索视频",
            fg_color=C["bg_surface"], text_color=C["text_2"],
            hover_color=C["bg_hover"], font=FONT,
            corner_radius=6, border_width=1, border_color=C["border"],
            command=self.gui._open_video_search,
        )
        search_btn.pack(side=tk.LEFT, padx=(3, 0))

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

        card = ctk.CTkFrame(self._card_frame, fg_color=C["bg_surface"],
                            border_width=1, border_color=C["border_sub"],
                            corner_radius=6, cursor="hand2")
        card.pack(fill=tk.X, padx=6, pady=2)
        inner = ctk.CTkFrame(card, fg_color=C["bg_surface"], corner_radius=0)
        inner.pack(fill=tk.X, padx=10, pady=8)

        top = ctk.CTkFrame(inner, fg_color=C["bg_surface"], corner_radius=0)
        top.pack(fill=tk.X)
        thumb_frame = ctk.CTkFrame(top, fg_color=C["bg_elevated"],
                                   width=80, height=45, corner_radius=4)
        thumb_frame.pack(side=tk.LEFT)
        thumb_frame.pack_propagate(False)
        thumb = ctk.CTkLabel(thumb_frame, text="", fg_color=C["bg_elevated"])
        thumb.pack(expand=True)
        self._load_cover_thumb(video.get("pic", ""), bvid, thumb)
        info = ctk.CTkFrame(top, fg_color=C["bg_surface"], corner_radius=0)
        info.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        title_lbl = ctk.CTkLabel(info, text=title[:28] + ("…" if len(title) > 28 else ""),
                                 text_color=C["text_1"], font=FONT,
                                 fg_color="transparent", justify="left",
                                 anchor="w", wraplength=180)
        title_lbl.pack(fill=tk.X)
        author_lbl = ctk.CTkLabel(info, text=author[:16],
                                  text_color=C["text_2"], font=FONT_SM,
                                  fg_color="transparent", anchor="w")
        author_lbl.pack(fill=tk.X)

        mid = ctk.CTkFrame(inner, fg_color=C["bg_surface"], corner_radius=0)
        mid.pack(fill=tk.X, pady=(6, 0))
        views_lbl = ctk.CTkLabel(mid, text=fmt_num(views),
                                 text_color=C["text_1"],
                                 font=("Consolas", 12, "bold"),
                                 fg_color="transparent")
        views_lbl.pack(side=tk.LEFT)
        online_total = video.get("viewers_total", 0)
        online_text = f"👁 {fmt_num(online_total)}" if online_total > 0 else ""
        online_lbl = ctk.CTkLabel(mid, text=online_text,
                                  text_color=C["accent"],
                                  font=("Consolas", 9),
                                  fg_color="transparent")
        online_lbl.pack(side=tk.LEFT, padx=(10, 0))
        stag, stag_fg = card_status_tag(gap)
        tag_lbl = ctk.CTkLabel(mid, text=stag, text_color=stag_fg,
                               font=FONT_SM, fg_color="transparent")
        tag_lbl.pack(side=tk.RIGHT)

        prog_f = ctk.CTkFrame(inner, fg_color=C["bg_surface"], corner_radius=0)
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

        label_f = ctk.CTkFrame(inner, fg_color=C["bg_surface"], corner_radius=0)
        label_f.pack(fill=tk.X)
        if gap > 0:
            gap_text = f"距{THRESHOLD_NAMES[tidx]}：{fmt_num(gap)}"
            pct_text = f"{pct*100:.1f}%"
        else:
            gap_text, pct_text = "已全部达标 ✓", ""
        gap_lbl = ctk.CTkLabel(label_f, text=gap_text, text_color=C["text_3"],
                               font=FONT_SM, fg_color="transparent")
        gap_lbl.pack(side=tk.LEFT)
        pct_lbl = ctk.CTkLabel(label_f, text=pct_text, text_color=C["text_3"],
                               font=FONT_SM, fg_color="transparent")
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
        refs["title"].configure(text=video.get("title","")[:28] + ("…" if len(video.get("title","")) > 28 else ""))
        refs["author"].configure(text=video.get("author","")[:16])
        refs["views"].configure(text=fmt_num(views))
        online_total = video.get("viewers_total", 0)
        online_text = f"👁 {fmt_num(online_total)}" if online_total > 0 else ""
        refs["online"].configure(text=online_text)
        stag, stag_fg = card_status_tag(gap)
        refs["tag"].configure(text=stag, text_color=stag_fg)
        if tidx >= 0:
            thr = THRESHOLDS[tidx]
            pct = min(views / thr, 1.0)
            fill_c = THRESH_COLORS[tidx]
            refs["gap_lbl"].configure(text=f"距{THRESHOLD_NAMES[tidx]}：{fmt_num(gap)}")
            refs["pct_lbl"].configure(text=f"{pct*100:.1f}%")
        else:
            pct, fill_c = 1.0, C["success"]
            refs["gap_lbl"].configure(text="已全部达标 ✓")
            refs["pct_lbl"].configure(text="")
        refs["prog_fill"].config(bg=fill_c)
        refs["prog_fill"].place(relwidth=pct)
        is_sel = (bvid == self.gui.selected_bvid)
        hl_bg = C["bg_elevated"] if is_sel else C["border_sub"]
        refs["card"].configure(border_color=hl_bg)

    def highlight_card(self, bvid):
        """高亮指定卡片"""
        for bv, refs in self._video_card_widgets.items():
            border = C["bilibili"] if bv == bvid else C["border_sub"]
            refs["card"].configure(border_color=border)

    # ──────────────────────────────────────────
    # 搜索过滤
    # ──────────────────────────────────────────

    def _on_search(self, *args):
        q = self._search_var.get().strip().lower()
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
            label_widget.configure(image=self._cover_cache[cache_key], text="")
            return
        if not url:
            return
        def _fetch():
            acquired = _cover_semaphore.acquire()
            if not acquired:
                return
            try:
                from PIL import Image
                r = _cover_session.get(url, timeout=8)
                if r.status_code != 200:
                    return
                img = Image.open(BytesIO(r.content))
                w, h = img.size
                target_w, target_h = 80, 45
                ratio = min(target_w / w, target_h / h)
                new_w, new_h = int(w * ratio), int(h * ratio)
                img = img.resize((new_w, new_h), Image.LANCZOS)
                ph = ctk.CTkImage(light_image=img, size=(new_w, new_h))
                self._cover_cache[cache_key] = ph
                # 限制封面缓存上限 50 个，淘汰最久未使用项
                if len(self._cover_cache) > 50:
                    try:
                        self._cover_cache.pop(next(iter(self._cover_cache)))
                    except (StopIteration, KeyError):
                        pass
                self.gui.root.after(0, lambda: self._safe_set_image(label_widget, ph))
            except Exception as e:
                logger.warning("缩略图加载失败 %s: %s", bvid, e)
            finally:
                _cover_semaphore.release()
        threading.Thread(target=_fetch, daemon=True).start()

    def _safe_set_image(self, widget, ph):
        """安全地给 CTkLabel 设置图片"""
        try:
            if widget.winfo_exists():
                widget.configure(image=ph, text="")
        except tk.TclError:
            pass

    def update_video_count(self):
        """更新视频计数标签"""
        self._video_count_lbl.configure(text=str(len(self.gui.monitored_videos)))

    def get_card_widgets(self):
        return self._video_card_widgets

    def refresh_card(self, bvid):
        """根据 bvid 刷新卡片（被 monitor_service 回调调用）"""
        video = next((v for v in self.gui.monitored_videos if v.get("bvid") == bvid), None)
        if video:
            self.update_card(video)

    def remove_card(self, bvid):
        """删除指定卡片"""
        refs = self._video_card_widgets.pop(bvid, None)
        if refs:
            refs["card"].destroy()
