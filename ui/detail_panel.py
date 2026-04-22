"""
中间详情面板模块
负责视频详情头部、统计栏、图表切换、详细数据文本
"""
import tkinter as tk
from tkinter import ttk
from datetime import datetime

from ui.theme import C
from ui.helpers import (
    FONT, FONT_SM, FONT_MONO,
    THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS,
    fmt_num,
)
from ui.chart import draw_chart, draw_chart_placeholder


class DetailPanel:
    """中间详情面板"""

    def __init__(self, parent, gui):
        self.gui = gui
        self._parent = parent
        self._stat_labels = {}
        self._tab_btns = {}
        self._current_tab = "📈 播放量趋势"
        self._chart_resize_job = None
        self._build()

    def _build(self):
        self._build_center_panel()

    def _build_center_panel(self):
        p = self._parent
        self._detail_header = tk.Frame(p, bg=C["bg_surface"])
        self._detail_header.pack(fill=tk.X)
        tk.Frame(p, bg=C["border"], height=1).pack(fill=tk.X)
        self._build_center_header_empty()

        self._stat_bar = tk.Frame(p, bg=C["bg_surface"])
        self._stat_bar.pack(fill=tk.X)
        tk.Frame(p, bg=C["border"], height=1).pack(fill=tk.X)

        tab_bar = tk.Frame(p, bg=C["bg_surface"])
        tab_bar.pack(fill=tk.X)
        tk.Frame(p, bg=C["border"], height=1).pack(fill=tk.X)
        for name in ["📈 播放量趋势", "📋 详细数据", "🔄 互动率"]:
            b = tk.Label(tab_bar, text=name, bg=C["bg_surface"], fg=C["text_2"],
                         font=FONT, cursor="hand2", padx=14, pady=8)
            b.pack(side=tk.LEFT)
            b.bind("<Button-1>", lambda e, n=name: self._switch_tab(n))
            b.bind("<Enter>", lambda e, b=b: b.config(fg=C["text_1"])
                   if b.cget("fg") != C["bilibili"] else None)
            b.bind("<Leave>", lambda e, b=b: b.config(fg=C["text_2"])
                   if b.cget("fg") != C["bilibili"] else None)
            self._tab_btns[name] = b
        self._tab_btns["📈 播放量趋势"].config(fg=C["bilibili"])

        self._content_area = tk.Frame(p, bg=C["bg_base"])
        self._content_area.pack(fill=tk.BOTH, expand=True)

        self._chart_canvas = tk.Canvas(self._content_area, bg=C["bg_base"],
                                       bd=0, highlightthickness=0)
        self._chart_canvas.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
        self._chart_canvas.bind("<Configure>", self._on_chart_resize)

        self._detail_text_frame = tk.Frame(self._content_area, bg=C["bg_base"])
        detail_vsb = ttk.Scrollbar(self._detail_text_frame)
        detail_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._detail_text = tk.Text(self._detail_text_frame, bg=C["bg_elevated"],
                                     fg=C["text_1"], font=FONT_MONO,
                                     relief="flat", bd=0, padx=12, pady=10,
                                     yscrollcommand=detail_vsb.set,
                                     state="disabled", cursor="arrow")
        self._detail_text.pack(fill=tk.BOTH, expand=True)
        detail_vsb.config(command=self._detail_text.yview)

        self._ratio_frame = tk.Frame(self._content_area, bg=C["bg_base"])

        draw_chart_placeholder(self._chart_canvas)
        self._rebuild_stat_bar({})

    def _build_center_header_empty(self):
        h = self._detail_header
        for w in h.winfo_children():
            w.destroy()
        tk.Label(h, text="← 从左侧选择一个视频", bg=C["bg_surface"],
                 fg=C["text_3"], font=FONT, padx=20, pady=18).pack(side=tk.LEFT)

    def _build_center_header(self, video):
        h = self._detail_header
        for w in h.winfo_children():
            w.destroy()
        bvid    = video.get("bvid", "")
        title   = video.get("title", "未知标题")
        author  = video.get("author", "未知UP主")
        dur_sec = video.get("duration", 0)
        pub_ts  = video.get("pubdate", 0)
        dur_str = f"{dur_sec//60}:{dur_sec%60:02d}" if dur_sec else "—"
        pub_str = datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d") if pub_ts else "—"

        info = tk.Frame(h, bg=C["bg_surface"])
        info.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=14, pady=10)
        tk.Label(info, text=title, bg=C["bg_surface"], fg=C["text_1"],
                 font=("Microsoft YaHei UI", 12, "bold"),
                 anchor="w", wraplength=500, justify="left").pack(fill=tk.X)
        meta = tk.Frame(info, bg=C["bg_surface"])
        meta.pack(fill=tk.X, pady=(4, 0))
        for icon, val in [("👤", author), ("⏱️", dur_str), ("📅", pub_str)]:
            tf = tk.Frame(meta, bg=C["bg_surface"])
            tf.pack(side=tk.LEFT, padx=(0, 14))
            tk.Label(tf, text=icon, bg=C["bg_surface"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)
            tk.Label(tf, text=" " + val, bg=C["bg_surface"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)

        bv_lbl = tk.Label(meta, text=bvid, bg=C["bg_elevated"], fg=C["text_3"],
                           font=FONT_MONO, padx=6, pady=2, cursor="hand2")
        bv_lbl.pack(side=tk.LEFT, padx=6)
        bv_lbl.bind("<Button-1>", lambda e: self.gui._copy_bvid(bvid))
        bv_lbl.bind("<Enter>", lambda e: bv_lbl.config(fg=C["accent"]))
        bv_lbl.bind("<Leave>", lambda e: bv_lbl.config(fg=C["text_3"]))

    def _rebuild_stat_bar(self, video):
        bar = self._stat_bar
        for w in bar.winfo_children():
            w.destroy()
        self._stat_labels = {}
        fields = [
            ("播放量", "view_count",      C["bilibili"]),
            ("点赞",   "like_count",      C["text_1"]),
            ("投币",   "coin_count",      C["text_1"]),
            ("收藏",   "favorite_count",  C["text_1"]),
            ("弹幕",   "danmaku_count",   C["text_1"]),
            ("评论",   "reply_count",      C["text_1"]),
            ("在线人数", "_online_viewers", C["accent"]),
            ("点赞率", "_like_rate",      C["success"]),
            ("周刊分数", "_weekly_score",  C["accent"]),
            ("年刊分数", "_yearly_score",  C["warning"]),
        ]
        for label, key, color in fields:
            card = tk.Frame(bar, bg=C["bg_elevated"], highlightthickness=1,
                            highlightbackground=C["border_sub"])
            card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, pady=8, ipady=4)
            tk.Label(card, text=label, bg=C["bg_elevated"], fg=C["text_3"],
                     font=FONT_SM).pack(anchor="w", padx=8, pady=(4, 0))
            if key == "_like_rate":
                views = video.get("view_count", 1) or 1
                val = f"{video.get('like_count',0)/views*100:.2f}%"
            elif key == "_weekly_score":
                val = self._calc_weekly_score_text(video)
            elif key == "_yearly_score":
                val = self._calc_yearly_score_text(video)
            elif key == "_online_viewers":
                total = video.get("viewers_total", 0)
                val = f"{fmt_num(total)}" if total > 0 else "—"
            else:
                val = fmt_num(video.get(key, 0)) if video else "—"
            val_lbl = tk.Label(card, text=val, bg=C["bg_elevated"], fg=color,
                                font=("Consolas", 13, "bold"))
            val_lbl.pack(anchor="w", padx=8)
            delta_lbl = tk.Label(card, text="", bg=C["bg_elevated"],
                                  fg=C["success"], font=FONT_SM)
            delta_lbl.pack(anchor="w", padx=8, pady=(0, 4))
            self._stat_labels[key] = (val_lbl, delta_lbl)

    def update_stat_bar(self, video):
        fields = [
            ("view_count",      C["bilibili"]),
            ("like_count",      C["text_1"]),
            ("coin_count",      C["text_1"]),
            ("favorite_count",  C["text_1"]),
            ("danmaku_count",   C["text_1"]),
            ("reply_count",     C["text_1"]),
            ("_online_viewers", C["accent"]),
            ("_like_rate",      C["success"]),
            ("_weekly_score",   C["accent"]),
            ("_yearly_score",   C["warning"]),
        ]
        views = video.get("view_count", 1) or 1
        for key, color in fields:
            pair = self._stat_labels.get(key)
            if not pair:
                continue
            val_lbl, _ = pair
            if key == "_like_rate":
                val_lbl.config(text=f"{video.get('like_count',0)/views*100:.2f}%")
            elif key == "_weekly_score":
                val_lbl.config(text=self._calc_weekly_score_text(video))
            elif key == "_yearly_score":
                val_lbl.config(text=self._calc_yearly_score_text(video))
            elif key == "_online_viewers":
                total = video.get("viewers_total", 0)
                val_lbl.config(text=fmt_num(total) if total > 0 else "—")
            else:
                val_lbl.config(text=fmt_num(video.get(key, 0)))

    def _switch_tab(self, name):
        for k, b in self._tab_btns.items():
            b.config(fg=C["bilibili"] if k == name else C["text_2"])
        self._current_tab = name
        self._chart_canvas.pack_forget()
        self._detail_text_frame.pack_forget()
        self._ratio_frame.pack_forget()
        if name == "📈 播放量趋势":
            self._chart_canvas.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
            if self.gui.selected_bvid:
                video = next((v for v in self.gui.monitored_videos
                              if v.get("bvid") == self.gui.selected_bvid), None)
                if video:
                    draw_chart(self._chart_canvas, self.gui.history_data,
                               self.gui.selected_bvid, video, FONT)
                    return
            draw_chart_placeholder(self._chart_canvas)
        elif name == "📋 详细数据":
            self._detail_text_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
            if self.gui.selected_bvid:
                video = next((v for v in self.gui.monitored_videos
                              if v.get("bvid") == self.gui.selected_bvid), None)
                if video:
                    self._fill_detail_text(video)
        elif name == "🔄 互动率":
            self._ratio_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
            if self.gui.selected_bvid:
                video = next((v for v in self.gui.monitored_videos
                              if v.get("bvid") == self.gui.selected_bvid), None)
                if video:
                    self._fill_ratio_frame(video)

    def _on_chart_resize(self, event=None):
        if self._chart_resize_job:
            self.gui.root.after_cancel(self._chart_resize_job)
        self._chart_resize_job = self.gui.root.after(200, self._do_chart_redraw)

    def _do_chart_redraw(self):
        self._chart_resize_job = None
        if self.gui.selected_bvid:
            video = next((v for v in self.gui.monitored_videos
                          if v.get("bvid") == self.gui.selected_bvid), None)
            if video:
                draw_chart(self._chart_canvas, self.gui.history_data,
                           self.gui.selected_bvid, video, FONT)
                return
        draw_chart_placeholder(self._chart_canvas)

    def _fill_detail_text(self, video):
        self._detail_text.config(state="normal")
        self._detail_text.delete("1.0", tk.END)
        bvid    = video.get("bvid", "")
        title   = video.get("title", "N/A")
        author  = video.get("author", "未知")
        views   = video.get("view_count", 0)
        pub_ts  = video.get("pubdate", 0)
        dur     = video.get("duration", 0)
        pub_str = datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d %H:%M") if pub_ts else "—"
        dur_str = f"{dur//60}:{dur%60:02d}" if dur else "—"

        lines = [
            ("=== 视频信息 ===", "head"),
            (f"BV号    {bvid}", "mono"),
            (f"标题    {title}", "mono"),
            (f"UP主    {author}", "mono"),
            (f"时长    {dur_str}", "mono"),
            (f"发布    {pub_str}", "mono"),
            ("", ""),
            ("=== 播放数据 ===", "head"),
            (f"播放量  {fmt_num(views)}", "mono_b"),
            (f"点赞    {fmt_num(video.get('like_count', 0))}", "mono"),
            (f"投币    {fmt_num(video.get('coin_count', 0))}", "mono"),
            (f"分享    {fmt_num(video.get('share_count', 0))}", "mono"),
            (f"收藏    {fmt_num(video.get('favorite_count', 0))}", "mono"),
            (f"弹幕    {fmt_num(video.get('danmaku_count', 0))}", "mono"),
            (f"评论    {fmt_num(video.get('reply_count', 0))}", "mono"),
            ("", ""),
            ("=== 互动率 ===", "head"),
            (f"点赞率  {video.get('like_count',0)/max(views,1)*100:.2f}%", "mono"),
            (f"投币率  {video.get('coin_count',0)/max(views,1)*100:.2f}%", "mono"),
            (f"收藏率  {video.get('favorite_count',0)/max(views,1)*100:.2f}%", "mono"),
            ("", ""),
            ("=== 在线人数 ===", "head"),
        ]
        viewers_total = video.get("viewers_total", 0)
        viewers_web   = video.get("viewers_web", 0)
        viewers_app   = video.get("viewers_app", 0)
        viewers_raw   = video.get("viewers_total_raw", "")
        if viewers_total > 0:
            lines.append((f"总在线  {fmt_num(viewers_total)}  ({viewers_raw})", "mono_accent"))
            lines.append((f"Web端   {fmt_num(viewers_web)}", "mono"))
            lines.append((f"APP端   {fmt_num(viewers_app)}", "mono"))
        else:
            lines.append(("暂无在线人数数据", "mono"))
        lines.append(("", ""))
        lines.append(("=== 阈值进度 ===", "head"))
        for t, name in zip(THRESHOLDS, THRESHOLD_NAMES):
            p = min(100, views/t*100)
            g = t - views
            if g > 0:
                lines.append((f"{name}  {p:.1f}%  (还差 {fmt_num(g)})", "mono"))
            else:
                lines.append((f"{name}  已达成 ✓", "mono_ok"))

        self._detail_text.tag_config("head", foreground=C["bilibili"], font=("Consolas", 10, "bold"))
        self._detail_text.tag_config("mono",    foreground=C["text_1"],  font=FONT_MONO)
        self._detail_text.tag_config("mono_b",  foreground=C["bilibili"],font=("Consolas",10,"bold"))
        self._detail_text.tag_config("mono_ok", foreground=C["success"], font=FONT_MONO)
        self._detail_text.tag_config("mono_accent", foreground=C["accent"], font=("Consolas", 10, "bold"))

        for text, tag in lines:
            self._detail_text.insert(tk.END, text + "\n", tag if tag else ())

        ws = self._calc_weekly_score(video)
        if ws:
            self._detail_text.insert(tk.END, "\n", ())
            self._detail_text.insert(tk.END, "=== 周刊分数 ===\n", "head")
            self._detail_text.insert(tk.END, f"最终得点  {ws.total_score:>10,.2f}\n", "mono_accent")
            self._detail_text.insert(tk.END, "\n", ())
            self._detail_text.insert(tk.END, f"播放得点  {ws.view_score:>10,.2f}  (基础 {ws.base_view_score:,.0f} × 修正D {ws.correction_d:.4f})\n", "mono")
            self._detail_text.insert(tk.END, f"互动得点  {ws.interaction_score:>10,.2f}  (修正A {ws.correction_a:.4f})\n", "mono")
            self._detail_text.insert(tk.END, f"收藏得点  {ws.favorite_score:>10,.2f}  ({video.get('favorite_count',0):,} × 修正B {ws.correction_b:.4f})\n", "mono")
            self._detail_text.insert(tk.END, f"硬币得点  {ws.coin_score:>10,.2f}  ({video.get('coin_count',0):,} × 修正C {ws.correction_c:.4f})\n", "mono")
            self._detail_text.insert(tk.END, f"点赞得点  {ws.like_score:>10,.2f}\n", "mono")

        ys = self._calc_yearly_score(video)
        if ys:
            self._detail_text.insert(tk.END, "\n", ())
            self._detail_text.insert(tk.END, "=== 年刊分数 ===\n", "head")
            self._detail_text.insert(tk.END, f"最终得点  {ys.total_score:>10,.2f}\n", "mono_accent")
            self._detail_text.insert(tk.END, "\n", ())
            self._detail_text.insert(tk.END, f"播放得点  {ys.view_score:>10,.2f}\n", "mono")
            self._detail_text.insert(tk.END, f"互动得点  {ys.interaction_score:>10,.2f}  (修正A {ys.correction_a:.4f})\n", "mono")
            self._detail_text.insert(tk.END, f"收藏得点  {ys.favorite_score:>10,.2f}  ({video.get('favorite_count',0):,} × 修正B {ys.correction_b:.4f})\n", "mono")
            self._detail_text.insert(tk.END, f"硬币得点  {ys.coin_score:>10,.2f}  ({video.get('coin_count',0):,} × 修正C {ys.correction_c:.4f})\n", "mono")
            self._detail_text.insert(tk.END, f"点赞得点  {ys.like_score:>10,.2f}\n", "mono")

        if bvid in self.gui.video_dbs:
            history_scores = self.gui.video_dbs[bvid].get_weekly_scores(limit=5)
            if len(history_scores) > 1:
                self._detail_text.insert(tk.END, "\n", ())
                self._detail_text.insert(tk.END, "=== 历史周刊分数 ===\n", "head")
                for row in history_scores:
                    ts_str = row.get("timestamp", "")[:16]
                    total = row.get("total_score", 0)
                    self._detail_text.insert(tk.END, f"  {ts_str}  {total:>10,.2f}\n", "mono")
            yearly_scores = self.gui.video_dbs[bvid].get_yearly_scores(limit=5)
            if len(yearly_scores) > 1:
                self._detail_text.insert(tk.END, "\n", ())
                self._detail_text.insert(tk.END, "=== 历史年刊分数 ===\n", "head")
                for row in yearly_scores:
                    ts_str = row.get("timestamp", "")[:16]
                    total = row.get("total_score", 0)
                    self._detail_text.insert(tk.END, f"  {ts_str}  {total:>10,.2f}\n", "mono")
        self._detail_text.config(state="disabled")

    def _calc_weekly_score(self, video):
        try:
            from utils.weekly_score import calculate_from_dict
            return calculate_from_dict(video)
        except Exception:
            return None

    def _calc_weekly_score_text(self, video):
        ws = self._calc_weekly_score(video)
        return f"{ws.total_score:,.0f}" if ws else "—"

    def _calc_yearly_score(self, video):
        try:
            from utils.yearly_score import calculate_yearly_from_dict
            return calculate_yearly_from_dict(video)
        except Exception:
            return None

    def _calc_yearly_score_text(self, video):
        ys = self._calc_yearly_score(video)
        return f"{ys.total_score:,.0f}" if ys else "—"

    def _fill_ratio_frame(self, video):
        for w in self._ratio_frame.winfo_children():
            w.destroy()
        views = video.get("view_count", 1) or 1
        ratios = [
            ("点赞率", video.get("like_count",0)/views*100, C["bilibili"]),
            ("投币率", video.get("coin_count",0)/views*100, C["accent"]),
            ("收藏率", video.get("favorite_count",0)/views*100, C["success"]),
            ("弹幕率", video.get("danmaku_count",0)/views*100, C["warning"]),
        ]
        for label, pct, color in ratios:
            row = tk.Frame(self._ratio_frame, bg=C["bg_base"])
            row.pack(fill=tk.X, pady=6)
            tk.Label(row, text=label, bg=C["bg_base"], fg=C["text_2"],
                     font=FONT, width=6).pack(side=tk.LEFT)
            bg_bar = tk.Frame(row, bg=C["bg_elevated"], height=12)
            bg_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
            bg_bar.pack_propagate(False)
            fill_pct = min(pct / 20, 1.0)
            tk.Frame(bg_bar, bg=color, height=12).place(x=0, y=0, relwidth=fill_pct, relheight=1)
            tk.Label(row, text=f"{pct:.3f}%", bg=C["bg_base"], fg=color,
                     font=FONT_MONO, width=8).pack(side=tk.LEFT)

    def recolor_text_tags(self):
        from ui.theme import _recolor_text_tags
        _recolor_text_tags(self._detail_text)
        self._detail_text.config(bg=C["bg_elevated"], fg=C["text_1"], insertbackground=C["text_1"])

    @property
    def chart_canvas(self):
        return self._chart_canvas

    @property
    def current_tab(self):
        return self._current_tab
