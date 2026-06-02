"""
左侧视频列表面板模块 — CustomTkinter 版
=========================================

提供 ``VideoListPanel`` 类，负责监控视频卡片的展示、搜索、选择和封面异步加载。

功能：
  - 标题头：视频计数、全部推送按钮
  - 搜索框：实时过滤（匹配标题、BV 号、UP 主名）
  - 视频卡片列表（CTkScrollableFrame）：
    - 封面缩略图（异步加载 + LRU 缓存）
    - 标题、UP 主、播放量、在线人数
    - 阈值进度条 + 状态标签
    - 推送按钮
  - 底部操作栏：添加监控 / 搜索视频
  - 面板尺寸变化自适应（防抖 150ms）

.. note::
   封面加载使用模块级 ``_cover_session``（带 UA/Referer）和 ``_cover_semaphore``（最多 4 并发）。
   ``_cover_cache`` 为 OrderedDict，LRU 上限 50 张。
"""

import tkinter as tk
import customtkinter as ctk
import threading
import logging
import requests as _req
from io import BytesIO

from ui.theme import C
from ui.helpers import (
    FONT,
    FONT_SM,
    THRESHOLDS,
    THRESHOLD_NAMES,
    THRESH_COLORS,
    fmt_num,
    nearest_threshold_gap,
    card_status_tag,
)
from utils.cover_manager import get_valid_cover, save_cover

# ═══════════════════════════════════════════════════════════════════════════════
# 模块级共享资源：封面下载 Session + 并发信号量
# ═══════════════════════════════════════════════════════════════════════════════

_cover_session = _req.Session()
_cover_session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com/",  # B 站防盗链需要 Referer
    }
)
_cover_semaphore = threading.Semaphore(4)  # 最多 4 个并发封面下载

logger = logging.getLogger(__name__)


class VideoListPanel:
    """左侧视频列表面板 — 管理监控视频卡片的展示和交互"""

    def __init__(self, parent, gui):
        """
        初始化视频列表面板。

        :param parent: 父容器 Widget
        :param gui: 主界面实例（用于数据访问和回调）
        """
        self.gui = gui
        self._parent = parent
        self._video_card_widgets = {}  # bvid → 卡片控件引用字典
        from collections import OrderedDict

        self._cover_cache = OrderedDict()  # LRU 封面缓存（最大 50 张）
        self._search_var = tk.StringVar()
        self._card_wraplength = 180  # 卡片标题折行宽度（初始化默认值）
        self._screen_width = self.gui.root.winfo_screenwidth()  # 缓存屏幕宽度，避免重复调用
        self._build_left_panel()
        # 监听面板尺寸变化，动态调整卡片 wraplength
        parent.bind("<Configure>", self._on_panel_resize)

    # ──────────────────────────────────────────
    # UI 构建
    # ──────────────────────────────────────────

    def _build_left_panel(self):
        """
        构建左侧面板：
          标题头（标题 + 计数 + 全部推送按钮）
          搜索框
          可滚动卡片容器
          底部操作按钮行（添加监控 / 搜索视频）
        """
        p = self._parent
        # ── 标题头 ──
        hdr = ctk.CTkFrame(p, fg_color=C["bg_surface"], corner_radius=0)
        hdr.pack(fill=tk.X, padx=12, pady=(10, 4))
        ctk.CTkLabel(
            hdr, text="监控视频", text_color=C["text_2"], font=("Microsoft YaHei UI", 8, "bold"), fg_color="transparent"
        ).pack(side=tk.LEFT)
        self._video_count_lbl = ctk.CTkLabel(
            hdr, text="0", fg_color=C["bg_elevated"], text_color=C["text_2"], font=FONT_SM, corner_radius=4
        )
        self._video_count_lbl.pack(side=tk.LEFT, padx=4)
        # 全部推送按钮
        ctk.CTkButton(
            hdr,
            text="📤 全部推送",
            fg_color=C["bg_elevated"],
            text_color=C["text_2"],
            hover_color=C["bg_hover"],
            font=("Microsoft YaHei UI", 8),
            corner_radius=4,
            height=22,
            width=70,
            command=self.gui._manual_push,
        ).pack(side=tk.RIGHT, padx=4)

        # ── 搜索框 ──
        self._search_entry = ctk.CTkEntry(
            p,
            placeholder_text="搜索标题或BV号…",
            fg_color=C["bg_elevated"],
            text_color=C["text_1"],
            placeholder_text_color=C["text_3"],
            border_width=1,
            border_color=C["border"],
            font=FONT,
            corner_radius=6,
        )
        self._search_entry.pack(fill=tk.X, padx=10, pady=(0, 6))
        self._search_entry.configure(textvariable=self._search_var)
        self._search_var.trace_add("write", self._on_search)  # 每次输入变化触发搜索

        # ── 可滚动卡片容器 ──
        self._card_frame = ctk.CTkScrollableFrame(
            p,
            fg_color=C["bg_surface"],
            corner_radius=0,
            scrollbar_button_color=C["bg_hover"],
            scrollbar_button_hover_color=C["border"],
        )
        self._card_frame.pack(fill=tk.BOTH, expand=True)

        # ── 底部操作按钮行 ──
        bottom_f = ctk.CTkFrame(p, fg_color=C["bg_surface"], corner_radius=0)
        bottom_f.pack(fill=tk.X, padx=10, pady=8)

        add_btn = ctk.CTkButton(
            bottom_f,
            text="＋ 添加监控",
            fg_color=C["bg_surface"],
            text_color=C["text_2"],
            hover_color=C["bg_hover"],
            font=FONT,
            corner_radius=6,
            border_width=1,
            border_color=C["border"],
            command=self.gui._add_monitor,
        )
        add_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))

        search_btn = ctk.CTkButton(
            bottom_f,
            text="🔍 搜索视频",
            fg_color=C["bg_surface"],
            text_color=C["text_2"],
            hover_color=C["bg_hover"],
            font=FONT,
            corner_radius=6,
            border_width=1,
            border_color=C["border"],
            command=self.gui._open_video_search,
        )
        search_btn.pack(side=tk.LEFT, padx=(3, 0))

    # ──────────────────────────────────────────
    # 视频卡片
    # ──────────────────────────────────────────

    def make_card(self, video):
        """
        创建视频卡片（供外部调用）。

        卡片结构：
          ┌─────────────────────────────────────────┐
          │ [封面] 标题                              │
          │        UP主名                            │
          │ 播放量  👁 在线人数         状态标签       │
          │ ████████████░░░░░░  (进度条)             │
          │ 距100万：xx万       xx.x%                │
          │                              📤 推送    │
          └─────────────────────────────────────────┘

        :param video: 视频信息字典
        :returns: 创建的 card Frame
        """
        bvid = video.get("bvid", "")
        title = video.get("title", "未知标题")
        author = video.get("author", "未知UP主")
        views = video.get("view_count", 0)
        gap, tidx = nearest_threshold_gap(views)  # 距离最近阈值的差值和索引

        card = ctk.CTkFrame(
            self._card_frame,
            fg_color=C["bg_surface"],
            border_width=1,
            border_color=C["border_sub"],
            corner_radius=6,
            cursor="hand2",
        )
        card.pack(fill=tk.X, padx=6, pady=2)
        inner = ctk.CTkFrame(card, fg_color=C["bg_surface"], corner_radius=0)
        inner.pack(fill=tk.X, padx=10, pady=8)

        top = ctk.CTkFrame(inner, fg_color=C["bg_surface"], corner_radius=0)
        top.pack(fill=tk.X)
        # 自适应缩略图尺寸：按侧栏宽度缩放，最小 60×34
        _left_w = int(self._screen_width * 0.22)
        _thumb_w = max(60, min(100, _left_w // 4))
        _thumb_h = int(_thumb_w * 0.56)
        self._card_wraplength = max(100, _left_w - _thumb_w - 60)

        # 封面缩略图区域
        thumb_frame = ctk.CTkFrame(top, fg_color=C["bg_elevated"], width=_thumb_w, height=_thumb_h, corner_radius=4)
        thumb_frame.pack(side=tk.LEFT)
        thumb_frame.pack_propagate(False)
        thumb = ctk.CTkLabel(thumb_frame, text="", fg_color=C["bg_elevated"])
        thumb.pack(expand=True)
        # 异步加载封面缩略图
        self._load_cover_thumb(video.get("pic", ""), bvid, thumb, title, target_w=_thumb_w, target_h=_thumb_h)
        info = ctk.CTkFrame(top, fg_color=C["bg_surface"], corner_radius=0)
        info.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        # 标题（最多 28 字符 + 省略号）
        title_lbl = ctk.CTkLabel(
            info,
            text=title[:28] + ("…" if len(title) > 28 else ""),
            text_color=C["text_1"],
            font=FONT,
            fg_color="transparent",
            justify="left",
            anchor="w",
            wraplength=self._card_wraplength,
        )
        title_lbl.pack(fill=tk.X)
        # UP主名（最多 16 字符）
        author_lbl = ctk.CTkLabel(
            info, text=author[:16], text_color=C["text_2"], font=FONT_SM, fg_color="transparent", anchor="w"
        )
        author_lbl.pack(fill=tk.X)

        # 数据行：播放量 + 在线人数 + 状态标签
        mid = ctk.CTkFrame(inner, fg_color=C["bg_surface"], corner_radius=0)
        mid.pack(fill=tk.X, pady=(6, 0))
        views_lbl = ctk.CTkLabel(
            mid, text=fmt_num(views), text_color=C["text_1"], font=("Consolas", 12, "bold"), fg_color="transparent"
        )
        views_lbl.pack(side=tk.LEFT)
        online_total = video.get("viewers_total", 0)
        online_text = f"👁 {fmt_num(online_total)}" if online_total > 0 else ""
        online_lbl = ctk.CTkLabel(
            mid, text=online_text, text_color=C["accent"], font=("Consolas", 9), fg_color="transparent"
        )
        online_lbl.pack(side=tk.LEFT, padx=(10, 0))
        stag, stag_fg = card_status_tag(gap)  # 状态标签文本和颜色
        tag_lbl = ctk.CTkLabel(mid, text=stag, text_color=stag_fg, font=FONT_SM, fg_color="transparent")
        tag_lbl.pack(side=tk.RIGHT)

        # 进度条（直观展示距离最近阈值的进度）
        prog_f = ctk.CTkFrame(inner, fg_color=C["bg_surface"], corner_radius=0)
        prog_f.pack(fill=tk.X, pady=(5, 0))
        prog_bg = tk.Frame(prog_f, bg=C["bg_hover"], height=3)
        prog_bg.pack(fill=tk.X)
        prog_bg.pack_propagate(False)
        if tidx >= 0:
            _thr, pct, fill_c = THRESHOLDS[tidx], min(views / THRESHOLDS[tidx], 1.0), THRESH_COLORS[tidx]  # noqa: F841
        else:
            pct, fill_c = 1.0, C["success"]  # 已全部达标
        prog_fill = tk.Frame(prog_bg, bg=fill_c, height=3)
        prog_fill.place(x=0, y=0, relwidth=pct, relheight=1)

        # 阈值标签行：距离下一个阈值的差值 + 百分比
        label_f = ctk.CTkFrame(inner, fg_color=C["bg_surface"], corner_radius=0)
        label_f.pack(fill=tk.X)
        if gap > 0:
            gap_text = f"距{THRESHOLD_NAMES[tidx]}：{fmt_num(gap)}"
            pct_text = f"{pct * 100:.1f}%"
        else:
            gap_text, pct_text = "已全部达标 ✓", ""
        gap_lbl = ctk.CTkLabel(label_f, text=gap_text, text_color=C["text_3"], font=FONT_SM, fg_color="transparent")
        gap_lbl.pack(side=tk.LEFT)
        pct_lbl = ctk.CTkLabel(label_f, text=pct_text, text_color=C["text_3"], font=FONT_SM, fg_color="transparent")
        pct_lbl.pack(side=tk.RIGHT)

        # 推送按钮行
        push_row = ctk.CTkFrame(inner, fg_color=C["bg_surface"], corner_radius=0)
        push_row.pack(fill=tk.X, pady=(4, 0))
        push_btn = ctk.CTkButton(
            push_row,
            text="📤 推送",
            fg_color=C["bg_elevated"],
            text_color=C["text_2"],
            hover_color=C["bg_hover"],
            font=("Microsoft YaHei UI", 8),
            corner_radius=4,
            height=20,
            width=50,
            command=lambda b=bvid: self.gui._push_single(b),
        )
        push_btn.pack(side=tk.RIGHT)

        # 保存所有控件引用，供 update_card / highlight_card 使用
        self._video_card_widgets[bvid] = {
            "card": card,
            "inner": inner,
            "thumb": thumb,
            "title": title_lbl,
            "author": author_lbl,
            "views": views_lbl,
            "tag": tag_lbl,
            "online": online_lbl,
            "prog_fill": prog_fill,
            "gap_lbl": gap_lbl,
            "pct_lbl": pct_lbl,
        }

        def _select(e, bv=bvid):
            """点击卡片任一部分选中视频"""
            self.gui._select_video(bv)

        # 为卡片的所有子控件绑定点击事件
        for w in [card, inner, top, info, mid, prog_f, label_f, title_lbl, author_lbl, views_lbl, tag_lbl, thumb]:
            w.bind("<Button-1>", _select)
        return card

    def update_card(self, video):
        """
        更新卡片数据（播放量、阈值进度、在线人数等）。
        由 monitor_service 的数据更新回调调用。

        :param video: 视频信息字典
        """
        bvid = video.get("bvid", "")
        refs = self._video_card_widgets.get(bvid)
        if not refs:
            return
        views = video.get("view_count", 0)
        gap, tidx = nearest_threshold_gap(views)
        # 更新标题、UP主、播放量
        refs["title"].configure(text=video.get("title", "")[:28] + ("…" if len(video.get("title", "")) > 28 else ""))
        refs["author"].configure(text=video.get("author", "")[:16])
        refs["views"].configure(text=fmt_num(views))
        # 在线人数
        online_total = video.get("viewers_total", 0)
        online_text = f"👁 {fmt_num(online_total)}" if online_total > 0 else ""
        refs["online"].configure(text=online_text)
        # 状态标签
        stag, stag_fg = card_status_tag(gap)
        refs["tag"].configure(text=stag, text_color=stag_fg)
        # 阈值进度
        if tidx >= 0:
            thr = THRESHOLDS[tidx]
            pct = min(views / thr, 1.0)
            fill_c = THRESH_COLORS[tidx]
            refs["gap_lbl"].configure(text=f"距{THRESHOLD_NAMES[tidx]}：{fmt_num(gap)}")
            refs["pct_lbl"].configure(text=f"{pct * 100:.1f}%")
        else:
            pct, fill_c = 1.0, C["success"]
            refs["gap_lbl"].configure(text="已全部达标 ✓")
            refs["pct_lbl"].configure(text="")
        refs["prog_fill"].config(bg=fill_c)
        refs["prog_fill"].place(relwidth=pct)
        # 高亮当前选中的卡片边框
        is_sel = bvid == self.gui.selected_bvid
        hl_bg = C["bg_elevated"] if is_sel else C["border_sub"]
        refs["card"].configure(border_color=hl_bg)

    def highlight_card(self, bvid):
        """
        高亮指定卡片（选中态），其他卡片恢复默认边框色。

        :param bvid: 要选中的 BV 号
        """
        for bv, refs in self._video_card_widgets.items():
            border = C["bilibili"] if bv == bvid else C["border_sub"]
            refs["card"].configure(border_color=border)

    # ──────────────────────────────────────────
    # 搜索过滤
    # ──────────────────────────────────────────

    def _on_panel_resize(self, event=None):
        """
        面板尺寸变化时更新所有卡片标题折行宽度（防抖 150ms）。
        避免频繁 resize 导致性能问题。
        """
        if not hasattr(self, "_resize_job") or self._resize_job:
            try:
                self.gui.root.after_cancel(self._resize_job)
            except Exception as e:
                logger.debug("忽略异常: %s", e)
        self._resize_job = self.gui.root.after(150, self._do_update_wraplengths)

    def _do_update_wraplengths(self):
        """批量更新所有卡片标题折行宽度"""
        self._resize_job = None
        try:
            parent_w = self._parent.winfo_width()
            new_wl = max(100, parent_w - 100)
            for refs in self._video_card_widgets.values():
                refs["title"].configure(wraplength=new_wl)
        except Exception as e:
            logger.debug("忽略异常: %s", e)

    def _on_search(self, *args):
        """
        根据搜索关键词过滤卡片显示。
        匹配条件：标题（不区分大小写）、BV 号、UP 主名。

        :param args: Tkinter trace 回调参数
        """
        q = self._search_var.get().strip().lower()
        video_map = {v.get("bvid"): v for v in self.gui.monitored_videos}
        for bvid, refs in self._video_card_widgets.items():
            video = video_map.get(bvid)
            if not video:
                continue
            visible = (
                not q
                or q in video.get("title", "").lower()
                or q in bvid.lower()
                or q in video.get("author", "").lower()
            )
            # 匹配时显示，不匹配时隐藏
            refs["card"].pack(fill=tk.X, padx=6, pady=2) if visible else refs["card"].pack_forget()

    def copy_bvid(self, bvid):
        """
        复制 BV 号到剪贴板。

        :param bvid: BV 号字符串
        """
        self.gui.root.clipboard_clear()
        self.gui.root.clipboard_append(bvid)
        self.gui._sb("status", f"已复制 {bvid}", C["success"])

    # ──────────────────────────────────────────
    # 封面异步加载
    # ──────────────────────────────────────────

    @staticmethod
    def _make_thumb_photo(img, target_w=80, target_h=45):
        """
        将 PIL Image 缩放到自适应尺寸并包装为 CTkImage。

        :param img: PIL Image 对象
        :param target_w: 目标宽度
        :param target_h: 目标高度
        :returns: ctk.CTkImage 对象
        """
        from PIL import Image

        w, h = img.size
        ratio = min(target_w / w, target_h / h)  # 等比缩放
        new_w, new_h = int(w * ratio), int(h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        return ctk.CTkImage(light_image=img, size=(new_w, new_h))

    def _cache_and_show(self, cache_key, ph, label_widget):
        """
        缓存 CTkImage 并显示到控件（LRU 淘汰）。

        :param cache_key: 缓存键（如 (bvid, "thumb")）
        :param ph: CTkImage 对象
        :param label_widget: CTkLabel 控件
        """
        self._cover_cache[cache_key] = ph
        self._cover_cache.move_to_end(cache_key)  # 标记为最近使用
        if len(self._cover_cache) > 50:
            self._cover_cache.popitem(last=False)  # LRU 淘汰最久未使用
        self.gui.root.after(0, lambda: self._safe_set_image(label_widget, ph))

    def _load_cover_thumb(self, url, bvid, label_widget, title="", target_w=80, target_h=45):
        """
        异步加载卡片封面缩略图。

        优先级：缓存 → 本地文件 → 远程下载。
        通过信号量限制并发数（最多 4 个）。

        :param url: 封面图片 URL
        :param bvid: BV 号（作为缓存键）
        :param label_widget: CTkLabel 控件（用于显示图片）
        :param title: 视频标题（用于本地缓存查找）
        :param target_w: 目标宽度
        :param target_h: 目标高度
        """
        cache_key = (bvid, "thumb")
        if cache_key in self._cover_cache:
            self._cover_cache.move_to_end(cache_key)  # 刷新 LRU 位置
            label_widget.configure(image=self._cover_cache[cache_key], text="")
            return
        if not url:
            return

        def _fetch():
            """后台线程：下载并处理封面"""
            acquired = _cover_semaphore.acquire()
            if not acquired:
                return
            try:
                from PIL import Image

                # 优先从本地缓存加载
                local = get_valid_cover(bvid, title)
                if local is not None:
                    ph = self._make_thumb_photo(Image.open(local), target_w, target_h)
                    self._cache_and_show(cache_key, ph, label_widget)
                    return

                # 远程下载
                r = _cover_session.get(url, timeout=8)
                if r.status_code != 200:
                    return
                save_cover(bvid, r.content, title)  # 保存到本地缓存
                ph = self._make_thumb_photo(Image.open(BytesIO(r.content)), target_w, target_h)
                self._cache_and_show(cache_key, ph, label_widget)
            except Exception as e:
                logger.warning("缩略图加载失败 %s: %s", bvid, e)
            finally:
                _cover_semaphore.release()  # 释放信号量

        threading.Thread(target=_fetch, daemon=True).start()

    def _safe_set_image(self, widget, ph):
        """
        安全地给 CTkLabel 设置图片（防止控件已销毁时的 TclError）。

        :param widget: CTkLabel 控件
        :param ph: CTkImage 对象
        """
        try:
            if widget.winfo_exists():
                widget.configure(image=ph, text="")
        except tk.TclError:
            pass

    def update_video_count(self):
        """更新视频计数标签"""
        self._video_count_lbl.configure(text=str(len(self.gui.monitored_videos)))

    def get_card_widgets(self):
        """获取所有卡片控件引用"""
        return self._video_card_widgets

    def refresh_card(self, bvid):
        """
        根据 bvid 刷新指定卡片（被 monitor_service 回调调用）。

        :param bvid: BV 号
        """
        video_map = {v.get("bvid"): v for v in self.gui.monitored_videos}
        video = video_map.get(bvid)
        if video:
            self.update_card(video)

    def remove_card(self, bvid):
        """
        删除指定 bvid 的卡片。

        :param bvid: BV 号
        """
        refs = self._video_card_widgets.pop(bvid, None)
        if refs:
            refs["card"].destroy()
