"""
右侧预测面板模块 - CustomTkinter 版
负责预测英雄卡、算法列表展示
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
        self._build_right_panel()

    def _build_right_panel(self):
        p = self._parent
        self._pred_hero = ctk.CTkFrame(p, fg_color=C["bg_surface"], corner_radius=0)
        self._pred_hero.pack(fill=tk.X)
        tk.Frame(p, bg=C["border"], height=1).pack(fill=tk.X)
        self._build_pred_hero_empty()

        algo_wrap = ctk.CTkFrame(p, fg_color=C["bg_surface"], corner_radius=0)
        algo_wrap.pack(fill=tk.BOTH, expand=True)
        self._algo_frame = ctk.CTkScrollableFrame(
            algo_wrap, fg_color=C["bg_surface"], corner_radius=0,
            scrollbar_button_color=C["bg_hover"],
            scrollbar_button_hover_color=C["border"],
        )
        self._algo_frame.pack(fill=tk.BOTH, expand=True)

    def _build_pred_hero_empty(self):
        h = self._pred_hero
        for w in h.winfo_children():
            w.destroy()
        ctk.CTkLabel(h, text="数据刷新后自动预测", text_color=C["text_3"],
                     font=FONT, fg_color="transparent").pack(padx=14, pady=14)

    def _build_pred_hero(self, weighted_pred, current_views, rate_per_sec):
        h = self._pred_hero
        for w in h.winfo_children():
            w.destroy()
        outer = ctk.CTkFrame(h, fg_color=C["bg_surface"], corner_radius=0)
        outer.pack(fill=tk.X, padx=14, pady=12)
        ctk.CTkLabel(outer, text="🎯 综合加权预测", text_color=C["text_3"],
                     font=("Microsoft YaHei UI", 8),
                     fg_color="transparent").pack(anchor="w")
        val_lbl = ctk.CTkLabel(outer, text=fmt_num(weighted_pred), text_color=C["text_1"],
                               font=("Consolas", 18, "bold"),
                               fg_color="transparent")
        val_lbl.pack(anchor="w", pady=(2, 0))
        delta = weighted_pred - current_views
        delta_text = f"▲ +{fmt_num(delta)}" if delta >= 0 else f"▼ {fmt_num(delta)}"
        delta_color = C["success"] if delta >= 0 else C["danger"]
        ctk.CTkLabel(outer, text=delta_text, text_color=delta_color,
                     font=FONT, fg_color="transparent").pack(anchor="w")
        if rate_per_sec > 0:
            per_min = rate_per_sec * 60
            per_hour = rate_per_sec * 3600
            if per_hour >= 1:
                rate_str = f"📈 +{fmt_num(per_hour)}/h"
            elif per_min >= 0.1:
                rate_str = f"📈 +{per_min:.1f}/min"
            else:
                rate_str = f"📈 +{rate_per_sec:.2f}/s"
            ctk.CTkLabel(outer, text=rate_str, text_color=C["accent"],
                         font=FONT_SM, fg_color="transparent").pack(anchor="w", pady=(2, 0))

        tk.Frame(outer, bg=C["border"], height=1).pack(fill=tk.X, pady=6)
        for t, name, col in zip(THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS):
            row = ctk.CTkFrame(outer, fg_color=C["bg_surface"], corner_radius=0)
            row.pack(fill=tk.X, pady=2)
            ctk.CTkLabel(row, text=name, text_color=C["text_2"],
                         font=FONT_SM, fg_color="transparent", width=38).pack(side=tk.LEFT)

            bg_bar = ctk.CTkFrame(row, fg_color=C["bg_hover"], height=4, corner_radius=2)
            bg_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
            bg_bar.pack_propagate(False)
            pct = min(current_views / t, 1.0)
            tk.Frame(bg_bar, bg=col, height=4).place(x=0, y=0, relwidth=pct, relheight=1)
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
            ctk.CTkLabel(row, text=eta_str, text_color=eta_c,
                         font=FONT_MONO, fg_color="transparent",
                         width=88, anchor="e").pack(side=tk.LEFT)

    def _update_algo_list(self, results, failed):
        f = self._algo_frame
        for w in f.winfo_children():
            w.destroy()
        if results:
            hdr = ctk.CTkFrame(f, fg_color=C["bg_surface"], corner_radius=0)
            hdr.pack(fill=tk.X, padx=8, pady=(6, 2))

            ctk.CTkLabel(hdr, text="✅ 成功算法", text_color=C["text_3"],
                         font=("Microsoft YaHei UI", 8, "bold"),
                         fg_color="transparent").pack(side=tk.LEFT)
            ctk.CTkLabel(hdr, text=str(len(results)),
                         fg_color=C["bg_elevated"], text_color=C["text_2"],
                         font=FONT_SM, corner_radius=4).pack(side=tk.LEFT, padx=4)

            ALGO_COLORS = [C["bilibili"], C["accent"], C["success"], C["warning"], "#a78bfa", "#22d3ee"]
            for i, (name, pred, weight, conf) in enumerate(results):
                card = ctk.CTkFrame(f, fg_color=C["bg_surface"],
                                    border_width=1, border_color=C["border_sub"],
                                    corner_radius=6)
                card.pack(fill=tk.X, padx=6, pady=2)
                inner = ctk.CTkFrame(card, fg_color=C["bg_surface"], corner_radius=0)
                inner.pack(fill=tk.X, padx=10, pady=7)
                top_row = ctk.CTkFrame(inner, fg_color=C["bg_surface"], corner_radius=0)
                top_row.pack(fill=tk.X)
                dot_c = ALGO_COLORS[i % len(ALGO_COLORS)]
                ctk.CTkLabel(top_row, text="●", text_color=dot_c,
                             font=FONT_SM, fg_color="transparent").pack(side=tk.LEFT)
                ctk.CTkLabel(top_row, text=" " + name[:18], text_color=C["text_1"],
                             font=FONT, fg_color="transparent").pack(side=tk.LEFT)
                ctk.CTkLabel(top_row, text=fmt_num(pred), text_color=C["accent"],
                             font=("Consolas", 10, "bold"),
                             fg_color="transparent").pack(side=tk.RIGHT)
                bar_row = ctk.CTkFrame(inner, fg_color=C["bg_surface"], corner_radius=0)
                bar_row.pack(fill=tk.X, pady=(4, 0))
                bg_bar = ctk.CTkFrame(bar_row, fg_color=C["bg_hover"], height=3, corner_radius=2)
                bg_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
                bg_bar.pack_propagate(False)
                tk.Frame(bg_bar, bg=C["accent"], height=3).place(x=0, y=0, relwidth=conf, relheight=1)
                ctk.CTkLabel(bar_row, text=f"{conf*100:.0f}%", text_color=C["text_3"],
                             font=("Consolas", 8), fg_color="transparent",
                             width=30).pack(side=tk.LEFT, padx=3)

        if failed:
            hdr2 = ctk.CTkFrame(f, fg_color=C["bg_surface"], corner_radius=0)
            hdr2.pack(fill=tk.X, padx=8, pady=(10, 2))
            ctk.CTkLabel(hdr2, text="❌ 失败算法", text_color=C["text_3"],
                         font=("Microsoft YaHei UI", 8, "bold"),
                         fg_color="transparent").pack(side=tk.LEFT)
            ctk.CTkLabel(hdr2, text=str(len(failed)),
                         fg_color=C["bg_elevated"], text_color=C["danger"],
                         font=FONT_SM, corner_radius=4).pack(side=tk.LEFT, padx=4)
            for name, err in failed:
                row = ctk.CTkFrame(f, fg_color=C["bg_surface"], corner_radius=0)
                row.pack(fill=tk.X, padx=10, pady=5)
                ctk.CTkLabel(row, text=name[:20], text_color=C["text_3"],
                             font=FONT, fg_color="transparent").pack(side=tk.LEFT)
                ctk.CTkLabel(row, text=str(err)[:30], text_color=C["danger"],
                             font=FONT_SM, fg_color="transparent").pack(side=tk.RIGHT)

    @property
    def algo_frame(self):
        return self._algo_frame
