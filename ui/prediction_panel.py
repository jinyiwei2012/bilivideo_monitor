"""
右侧预测面板模块
负责预测英雄卡、算法列表展示
"""
import tkinter as tk
from tkinter import ttk
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
        self._pred_hero = tk.Frame(p, bg=C["bg_surface"])
        self._pred_hero.pack(fill=tk.X)
        tk.Frame(p, bg=C["border"], height=1).pack(fill=tk.X)
        self._build_pred_hero_empty()

        algo_wrap = tk.Frame(p, bg=C["bg_surface"])
        algo_wrap.pack(fill=tk.BOTH, expand=True)
        self._algo_canvas = tk.Canvas(algo_wrap, bg=C["bg_surface"], bd=0, highlightthickness=0)
        algo_vsb = ttk.Scrollbar(algo_wrap, orient="vertical", command=self._algo_canvas.yview)
        self._algo_canvas.configure(yscrollcommand=algo_vsb.set)
        algo_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._algo_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._algo_frame = tk.Frame(self._algo_canvas, bg=C["bg_surface"])
        self._algo_cwin = self._algo_canvas.create_window((0, 0), window=self._algo_frame, anchor="nw")
        self._algo_frame.bind("<Configure>", lambda e: (
            self._algo_canvas.configure(scrollregion=self._algo_canvas.bbox("all")),
            self._algo_canvas.itemconfig(self._algo_cwin, width=self._algo_canvas.winfo_width())))
        self._algo_canvas.bind("<Configure>", lambda e:
            self._algo_canvas.itemconfig(self._algo_cwin, width=e.width))

    def _build_pred_hero_empty(self):
        h = self._pred_hero
        for w in h.winfo_children():
            w.destroy()
        tk.Label(h, text="数据刷新后自动预测", bg=C["bg_surface"], fg=C["text_3"],
                 font=FONT, padx=14, pady=14).pack()

    def _build_pred_hero(self, weighted_pred, current_views, rate_per_sec):
        h = self._pred_hero
        for w in h.winfo_children():
            w.destroy()
        outer = tk.Frame(h, bg=C["bg_surface"], padx=14, pady=12)
        outer.pack(fill=tk.X)
        tk.Label(outer, text="🎯 综合加权预测", bg=C["bg_surface"], fg=C["text_3"],
                 font=("Microsoft YaHei UI", 8)).pack(anchor="w")
        val_lbl = tk.Label(outer, text=fmt_num(weighted_pred), bg=C["bg_surface"], fg=C["text_1"],
                            font=("Consolas", 18, "bold"))
        val_lbl.pack(anchor="w", pady=(2, 0))
        delta = weighted_pred - current_views
        delta_text = f"▲ +{fmt_num(delta)}" if delta >= 0 else f"▼ {fmt_num(delta)}"
        delta_color = C["success"] if delta >= 0 else C["danger"]
        tk.Label(outer, text=delta_text, bg=C["bg_surface"], fg=delta_color, font=FONT).pack(anchor="w")
        if rate_per_sec > 0:
            per_min = rate_per_sec * 60
            per_hour = rate_per_sec * 3600
            if per_hour >= 1:
                rate_str = f"📈 +{fmt_num(per_hour)}/h"
            elif per_min >= 0.1:
                rate_str = f"📈 +{per_min:.1f}/min"
            else:
                rate_str = f"📈 +{rate_per_sec:.2f}/s"
            tk.Label(outer, text=rate_str, bg=C["bg_surface"], fg=C["accent"],
                     font=FONT_SM).pack(anchor="w", pady=(2, 0))

        tk.Frame(outer, bg=C["border"], height=1).pack(fill=tk.X, pady=6)
        for t, name, col in zip(THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS):
            row = tk.Frame(outer, bg=C["bg_surface"])
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=name, bg=C["bg_surface"], fg=C["text_2"],
                     font=FONT_SM, width=5).pack(side=tk.LEFT)

            bg_bar = tk.Frame(row, bg=C["bg_hover"], height=4)
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
            tk.Label(row, text=eta_str, bg=C["bg_surface"], fg=eta_c,
                     font=FONT_MONO, width=11, anchor="e").pack(side=tk.LEFT)

    def _update_algo_list(self, results, failed):
        f = self._algo_frame
        for w in f.winfo_children():
            w.destroy()
        if results:
            hdr = tk.Frame(f, bg=C["bg_surface"])
            hdr.pack(fill=tk.X, padx=8, pady=(6, 2))

            tk.Label(hdr, text="✅ 成功算法", bg=C["bg_surface"], fg=C["text_3"],
                     font=("Microsoft YaHei UI", 8, "bold")).pack(side=tk.LEFT)
            tk.Label(hdr, text=str(len(results)), bg=C["bg_elevated"], fg=C["text_2"],
                     font=FONT_SM, padx=5, pady=1).pack(side=tk.LEFT, padx=4)

            ALGO_COLORS = [C["bilibili"], C["accent"], C["success"], C["warning"], "#a78bfa", "#22d3ee"]
            for i, (name, pred, weight, conf) in enumerate(results):
                card = tk.Frame(f, bg=C["bg_surface"], highlightthickness=1,
                                highlightbackground=C["border_sub"])
                card.pack(fill=tk.X, padx=6, pady=2)
                inner = tk.Frame(card, bg=C["bg_surface"], padx=10, pady=7)
                inner.pack(fill=tk.X)
                top_row = tk.Frame(inner, bg=C["bg_surface"])
                top_row.pack(fill=tk.X)
                dot_c = ALGO_COLORS[i % len(ALGO_COLORS)]
                tk.Label(top_row, text="●", bg=C["bg_surface"], fg=dot_c, font=FONT_SM).pack(side=tk.LEFT)
                tk.Label(top_row, text=" " + name[:18], bg=C["bg_surface"], fg=C["text_1"], font=FONT).pack(side=tk.LEFT)
                tk.Label(top_row, text=fmt_num(pred), bg=C["bg_surface"], fg=C["accent"],
                         font=("Consolas", 10, "bold")).pack(side=tk.RIGHT)
                bar_row = tk.Frame(inner, bg=C["bg_surface"])
                bar_row.pack(fill=tk.X, pady=(4, 0))
                bg_bar = tk.Frame(bar_row, bg=C["bg_hover"], height=3)
                bg_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
                bg_bar.pack_propagate(False)
                tk.Frame(bg_bar, bg=C["accent"], height=3).place(x=0, y=0, relwidth=conf, relheight=1)
                tk.Label(bar_row, text=f"{conf*100:.0f}%", bg=C["bg_surface"], fg=C["text_3"],
                         font=("Consolas", 8), width=4).pack(side=tk.LEFT, padx=3)
                card.bind("<Enter>", lambda e, c=card: c.config(highlightbackground=C["border"]))
                card.bind("<Leave>", lambda e, c=card: c.config(highlightbackground=C["border_sub"]))

        if failed:
            hdr2 = tk.Frame(f, bg=C["bg_surface"])
            hdr2.pack(fill=tk.X, padx=8, pady=(10, 2))
            tk.Label(hdr2, text="❌ 失败算法", bg=C["bg_surface"], fg=C["text_3"],
                     font=("Microsoft YaHei UI", 8, "bold")).pack(side=tk.LEFT)
            tk.Label(hdr2, text=str(len(failed)), bg=C["bg_elevated"], fg=C["danger"],
                     font=FONT_SM, padx=5, pady=1).pack(side=tk.LEFT, padx=4)
            for name, err in failed:
                row = tk.Frame(f, bg=C["bg_surface"], padx=10, pady=5)
                row.pack(fill=tk.X, padx=6)
                tk.Label(row, text=name[:20], bg=C["bg_surface"], fg=C["text_3"], font=FONT).pack(side=tk.LEFT)
                tk.Label(row, text=str(err)[:30], bg=C["bg_surface"], fg=C["danger"], font=FONT_SM).pack(side=tk.RIGHT)
        self._algo_canvas.yview_moveto(0)

    @property
    def algo_frame(self):
        return self._algo_frame
