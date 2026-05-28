"""
右侧预测面板模块 - CustomTkinter 版
负责预测英雄卡 + 最近记录时间线
"""

import tkinter as tk
import customtkinter as ctk
from datetime import datetime, timedelta

from ui.theme import C
from ui.helpers import FONT, FONT_SM, FONT_MONO, THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS, fmt_num


class PredictionPanel:
    """右侧预测面板"""

    def __init__(self, parent, gui):
        self.gui = gui
        self._parent = parent
        self._hero_widgets = {}
        self._hero_has_data = False
        self._info_frame = None
        self._info_content = None
        self._build_right_panel()

    def _build_right_panel(self):
        p = self._parent
        self._pred_hero = ctk.CTkFrame(p, fg_color=C["bg_surface"], corner_radius=0)
        self._pred_hero.pack(fill=tk.X)
        tk.Frame(p, bg=C["border"], height=1).pack(fill=tk.X)
        self._build_pred_hero_empty()

        info_wrap = ctk.CTkFrame(p, fg_color=C["bg_surface"], corner_radius=0)
        info_wrap.pack(fill=tk.BOTH, expand=True)
        self._info_frame = ctk.CTkScrollableFrame(
            info_wrap,
            fg_color=C["bg_surface"],
            corner_radius=0,
            scrollbar_button_color=C["bg_hover"],
            scrollbar_button_hover_color=C["border"],
        )
        self._info_frame.pack(fill=tk.BOTH, expand=True)

    def _build_pred_hero_empty(self):
        if not self._hero_has_data and self._hero_widgets:
            return
        h = self._pred_hero
        for w in h.winfo_children():
            w.destroy()
        self._hero_widgets = {}
        self._hero_has_data = False
        ctk.CTkLabel(h, text="选择视频后显示预测", text_color=C["text_3"], font=FONT, fg_color="transparent").pack(
            padx=14, pady=14
        )

    def _build_pred_hero(self, weighted_pred, current_views, rate_per_sec):
        if self._hero_has_data and "outer" in self._hero_widgets:
            w = self._hero_widgets
            w["val_lbl"].configure(text=fmt_num(weighted_pred))
            delta = weighted_pred - current_views
            delta_text = f"▲ +{fmt_num(delta)}" if delta >= 0 else f"▼ {fmt_num(delta)}"
            delta_color = C["success"] if delta >= 0 else C["danger"]
            w["delta_lbl"].configure(text=delta_text, text_color=delta_color)
            if rate_per_sec > 0:
                per_min = rate_per_sec * 60
                per_hour = rate_per_sec * 3600
                if per_hour >= 1:
                    rate_str = f"📈 +{fmt_num(per_hour)}/h"
                elif per_min >= 0.1:
                    rate_str = f"📈 +{per_min:.1f}/min"
                else:
                    rate_str = f"📈 +{rate_per_sec:.2f}/s"
                w["rate_lbl"].configure(text=rate_str)
                w["rate_lbl"].pack(anchor="w", pady=(2, 0))
            else:
                if "rate_lbl" in w:
                    w["rate_lbl"].pack_forget()
            for i, (t, name, col) in enumerate(zip(THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS)):
                if i >= len(w["thr_rows"]):
                    break
                row_data = w["thr_rows"][i]
                pct = min(current_views / t, 1.0)
                row_data["fill_frame"].place(x=0, y=0, relwidth=pct, relheight=1)
                if t <= current_views:
                    eta_str, eta_c = "✓ 已达成", C["success"]
                elif rate_per_sec > 0:
                    need = t - current_views
                    seconds_left = need / rate_per_sec
                    arrive_dt = datetime.now() + timedelta(seconds=seconds_left)
                    eta_str = arrive_dt.strftime("%m-%d %H:%M")
                    eta_c = (
                        C["danger"] if seconds_left < 3600 else C["warning"] if seconds_left < 86400 else C["text_2"]
                    )
                else:
                    eta_str, eta_c = "—", C["text_3"]
                row_data["eta_lbl"].configure(text=eta_str, text_color=eta_c)
            return

        h = self._pred_hero
        for w in h.winfo_children():
            w.destroy()
        self._hero_widgets = {}
        outer = ctk.CTkFrame(h, fg_color=C["bg_surface"], corner_radius=0)
        outer.pack(fill=tk.X, padx=14, pady=12)
        ctk.CTkLabel(
            outer,
            text="🎯 综合加权预测",
            text_color=C["text_3"],
            font=("Microsoft YaHei UI", 8),
            fg_color="transparent",
        ).pack(anchor="w")
        val_lbl = ctk.CTkLabel(
            outer,
            text=fmt_num(weighted_pred),
            text_color=C["text_1"],
            font=("Consolas", 18, "bold"),
            fg_color="transparent",
        )
        val_lbl.pack(anchor="w", pady=(2, 0))
        delta = weighted_pred - current_views
        delta_text = f"▲ +{fmt_num(delta)}" if delta >= 0 else f"▼ {fmt_num(delta)}"
        delta_color = C["success"] if delta >= 0 else C["danger"]
        delta_lbl = ctk.CTkLabel(outer, text=delta_text, text_color=delta_color, font=FONT, fg_color="transparent")
        delta_lbl.pack(anchor="w")
        rate_lbl = None
        if rate_per_sec > 0:
            per_min = rate_per_sec * 60
            per_hour = rate_per_sec * 3600
            if per_hour >= 1:
                rate_str = f"📈 +{fmt_num(per_hour)}/h"
            elif per_min >= 0.1:
                rate_str = f"📈 +{per_min:.1f}/min"
            else:
                rate_str = f"📈 +{rate_per_sec:.2f}/s"
            rate_lbl = ctk.CTkLabel(outer, text=rate_str, text_color=C["accent"], font=FONT_SM, fg_color="transparent")
            rate_lbl.pack(anchor="w", pady=(2, 0))

        tk.Frame(outer, bg=C["border"], height=1).pack(fill=tk.X, pady=6)
        thr_rows = []
        for t, name, col in zip(THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS):
            row = ctk.CTkFrame(outer, fg_color=C["bg_surface"], corner_radius=0)
            row.pack(fill=tk.X, pady=2)
            ctk.CTkLabel(row, text=name, text_color=C["text_2"], font=FONT_SM, fg_color="transparent", width=38).pack(
                side=tk.LEFT
            )

            bg_bar = ctk.CTkFrame(row, fg_color=C["bg_hover"], height=4, corner_radius=2)
            bg_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
            bg_bar.pack_propagate(False)
            pct = min(current_views / t, 1.0)
            fill_frame = tk.Frame(bg_bar, bg=col, height=4)
            fill_frame.place(x=0, y=0, relwidth=pct, relheight=1)
            if t <= current_views:
                eta_str, eta_c = "✓ 已达成", C["success"]
            elif rate_per_sec > 0:
                need = t - current_views
                seconds_left = need / rate_per_sec
                arrive_dt = datetime.now() + timedelta(seconds=seconds_left)
                eta_str = arrive_dt.strftime("%m-%d %H:%M")
                eta_c = C["danger"] if seconds_left < 3600 else C["warning"] if seconds_left < 86400 else C["text_2"]
            else:
                eta_str, eta_c = "—", C["text_3"]
            eta_lbl = ctk.CTkLabel(
                row, text=eta_str, text_color=eta_c, font=FONT_MONO, fg_color="transparent", width=88, anchor="e"
            )
            eta_lbl.pack(side=tk.LEFT)
            thr_rows.append({"fill_frame": fill_frame, "eta_lbl": eta_lbl})

        self._hero_widgets = {
            "outer": outer,
            "val_lbl": val_lbl,
            "delta_lbl": delta_lbl,
            "rate_lbl": rate_lbl,
            "thr_rows": thr_rows,
        }
        self._hero_has_data = True

    def _clear_info(self):
        for w in self._info_frame.winfo_children():
            w.destroy()
        self._info_content = None

    def update_info(self, video, history, prediction_result):
        """更新右侧信息面板：互动率 + 数据健康 + 算法统计"""
        self._clear_info()
        f = self._info_frame

        # ── 互动率概览 ──
        self._section_title(f, "📊 互动率概览")
        views = max(video.get("view_count", 0), 1)
        likes = video.get("like_count", 0) or 0
        coins = video.get("coin_count", 0) or 0
        favorites = video.get("favorite_count", 0) or 0
        shares = video.get("share_count", 0) or 0
        danmaku = video.get("danmaku_count", 0) or 0

        stats = [
            ("👍 点赞率", f"{likes / views * 100:.2f}%"),
            ("🪙 投币率", f"{coins / views * 100:.2f}%"),
            ("⭐ 收藏率", f"{favorites / views * 100:.2f}%"),
            ("🔗 分享率", f"{shares / views * 100:.2f}%"),
            ("💬 弹幕率", f"{danmaku / views * 100:.2f}%"),
        ]
        grid = ctk.CTkFrame(f, fg_color=C["bg_surface"], corner_radius=0)
        grid.pack(fill=tk.X, padx=10, pady=(0, 6))
        for i, (label, val) in enumerate(stats):
            row, col = divmod(i, 2)
            cell = ctk.CTkFrame(grid, fg_color=C["bg_elevated"], corner_radius=4, height=28)
            cell.grid(row=row, column=col, padx=2, pady=1, sticky="ew")
            grid.grid_columnconfigure(col, weight=1, uniform="stats")
            ctk.CTkLabel(cell, text=label, text_color=C["text_3"], font=FONT_SM, fg_color="transparent").pack(
                side=tk.LEFT, padx=(6, 0)
            )
            ctk.CTkLabel(cell, text=val, text_color=C["text_1"], font=("Consolas", 9, "bold"),
                         fg_color="transparent").pack(side=tk.RIGHT, padx=(0, 6))

        # ── 在线人数 ──
        online_total = video.get("viewers_total", 0)
        online_web = video.get("viewers_web", 0)
        online_app = video.get("viewers_app", 0)
        if online_total > 0:
            online_frame = ctk.CTkFrame(f, fg_color=C["bg_surface"], corner_radius=0)
            online_frame.pack(fill=tk.X, padx=10, pady=(0, 6))
            row = ctk.CTkFrame(online_frame, fg_color=C["bg_elevated"], corner_radius=4, height=28)
            row.pack(fill=tk.X)
            ctk.CTkLabel(row, text="👁 在线人数", text_color=C["text_3"], font=FONT_SM,
                         fg_color="transparent").pack(side=tk.LEFT, padx=(6, 0))
            ctk.CTkLabel(row, text=f"{fmt_num(online_total)}  (网页{fmt_num(online_web)}/APP{fmt_num(online_app)})",
                         text_color=C["accent"], font=("Consolas", 9), fg_color="transparent").pack(side=tk.RIGHT,
                                                                                                    padx=(0, 6))

        # ── 最近记录 ──
        self._section_title(f, "📋 最近记录")
        hist_container = ctk.CTkFrame(f, fg_color=C["bg_surface"], corner_radius=0)
        hist_container.pack(fill=tk.X, padx=10, pady=(0, 6))
        if history and len(history) > 1:
            recent = history[-15:]
            prev_v = recent[0][1] if len(recent) > 1 else 0
            for ts, v in recent:
                dt_str = ts.strftime("%m-%d %H:%M") if isinstance(ts, datetime) else str(ts)[:-3] if len(
                    str(ts)) > 16 else str(ts)
                delta_v = v - prev_v if prev_v > 0 else 0
                delta_str = f"+{fmt_num(delta_v)}" if delta_v > 0 else "—"
                delta_c = C["success"] if delta_v > 0 else C["text_3"]
                prev_v = v
                row = ctk.CTkFrame(hist_container, fg_color=C["bg_surface"], corner_radius=0)
                row.pack(fill=tk.X, pady=1)
                ctk.CTkLabel(row, text=dt_str, text_color=C["text_3"], font=("Consolas", 8),
                             fg_color="transparent", width=60, anchor="w").pack(side=tk.LEFT)
                ctk.CTkLabel(row, text=fmt_num(v), text_color=C["text_1"], font=("Consolas", 9, "bold"),
                             fg_color="transparent", width=60, anchor="e").pack(side=tk.RIGHT)
                ctk.CTkLabel(row, text=delta_str, text_color=delta_c, font=("Consolas", 8),
                             fg_color="transparent", width=50, anchor="e").pack(side=tk.RIGHT)
        else:
            ctk.CTkLabel(hist_container, text="暂无历史数据", text_color=C["text_3"], font=FONT_SM,
                         fg_color="transparent", anchor="w").pack(fill=tk.X, pady=4)

        # ── 算法统计 ──
        self._section_title(f, "🧠 算法统计")
        algo_info = ctk.CTkFrame(f, fg_color=C["bg_surface"], corner_radius=0)
        algo_info.pack(fill=tk.X, padx=10, pady=(0, 6))
        if prediction_result:
            valid = prediction_result.get("valid", 0)
            total = prediction_result.get("total", 0)
            ensemble_conf = prediction_result.get("ensemble_confidence", 0)
            row = ctk.CTkFrame(algo_info, fg_color=C["bg_elevated"], corner_radius=4, height=28)
            row.pack(fill=tk.X)
            ctk.CTkLabel(row, text="有效算法", text_color=C["text_3"], font=FONT_SM,
                         fg_color="transparent").pack(side=tk.LEFT, padx=(6, 0))
            ctk.CTkLabel(row, text=f"{valid}/{total}", text_color=C["success"] if valid > 0 else C["danger"],
                         font=("Consolas", 9, "bold"), fg_color="transparent").pack(side=tk.RIGHT, padx=(0, 6))
            if ensemble_conf > 0:
                row2 = ctk.CTkFrame(algo_info, fg_color=C["bg_elevated"], corner_radius=4, height=28)
                row2.pack(fill=tk.X, pady=(2, 0))
                ctk.CTkLabel(row2, text="集成置信度", text_color=C["text_3"], font=FONT_SM,
                             fg_color="transparent").pack(side=tk.LEFT, padx=(6, 0))
                ctk.CTkLabel(row2, text=f"{ensemble_conf * 100:.1f}%",
                             text_color=C["accent"], font=("Consolas", 9, "bold"),
                             fg_color="transparent").pack(side=tk.RIGHT, padx=(0, 6))
        else:
            ctk.CTkLabel(algo_info, text="等待首次预测", text_color=C["text_3"], font=FONT_SM,
                         fg_color="transparent", anchor="w").pack(fill=tk.X, pady=4)

        # ── 数据健康 ──
        self._section_title(f, "📡 数据健康")
        health = ctk.CTkFrame(f, fg_color=C["bg_surface"], corner_radius=0)
        health.pack(fill=tk.X, padx=10, pady=(0, 6))
        n_records = len(history) if history else 0
        fetch_time = video.get("_last_fetch", "")
        row = ctk.CTkFrame(health, fg_color=C["bg_elevated"], corner_radius=4, height=28)
        row.pack(fill=tk.X)
        ctk.CTkLabel(row, text="数据点数", text_color=C["text_3"], font=FONT_SM,
                     fg_color="transparent").pack(side=tk.LEFT, padx=(6, 0))
        ctk.CTkLabel(row, text=str(n_records), text_color=C["text_1"], font=("Consolas", 9, "bold"),
                     fg_color="transparent").pack(side=tk.RIGHT, padx=(0, 6))

        self._info_content = True

    def _section_title(self, parent, text):
        row = ctk.CTkFrame(parent, fg_color=C["bg_surface"], corner_radius=0)
        row.pack(fill=tk.X, padx=10, pady=(8, 2))
        ctk.CTkLabel(row, text=text, text_color=C["text_3"],
                     font=("Microsoft YaHei UI", 8, "bold"), fg_color="transparent").pack(side=tk.LEFT)

    # 兼容旧接口 — 不再显示算法列表，转调 update_info
    def _update_algo_list(self, results, failed):
        bvid = self.gui.selected_bvid
        if not bvid:
            self._clear_info()
            return
        video = self.gui._get_video(bvid)
        if not video:
            self._clear_info()
            return
        history = self.gui.history_data.get(bvid, [])
        cached = self.gui.prediction_results.get(bvid, {})
        self.update_info(video, history, cached)

    @property
    def algo_frame(self):
        return self._info_frame
