"""
右侧预测面板模块
负责预测英雄卡、算法列表展示
"""
import tkinter as tk
from tkinter import ttk
from datetime import datetime, timedelta

from ui.theme import C
from ui.helpers import FONT, FONT_SM, FONT_MONO, THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS, fmt_num

ALGO_COLORS = [C["bilibili"], C["accent"], C["success"], C["warning"], "#a78bfa", "#22d3ee"]


class PredictionPanel:
    """右侧预测面板"""

    def __init__(self, parent, gui):
        self.gui = gui
        self._parent = parent
        self._hero_refs = {}
        self._algo_success_refs = []
        self._algo_fail_refs = []
        self._algo_headers = {}
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
        self._hero_refs.clear()
        h = self._pred_hero
        for w in h.winfo_children():
            w.destroy()
        lbl = tk.Label(h, text="数据刷新后自动预测", bg=C["bg_surface"], fg=C["text_3"],
                       font=FONT, padx=14, pady=14)
        lbl.pack()
        self._hero_refs['empty'] = lbl

    def _build_pred_hero(self, weighted_pred, current_views, rate_per_sec):
        h = self._pred_hero

        # 首次构建完整结构
        if not self._hero_refs or 'empty' in self._hero_refs:
            for w in h.winfo_children():
                w.destroy()
            self._hero_refs.clear()

            outer = tk.Frame(h, bg=C["bg_surface"], padx=14, pady=12)
            outer.pack(fill=tk.X)
            self._hero_refs['outer'] = outer

            tk.Label(outer, text="🎯 综合加权预测", bg=C["bg_surface"], fg=C["text_3"],
                     font=("Microsoft YaHei UI", 8)).pack(anchor="w")
            val_lbl = tk.Label(outer, text="", bg=C["bg_surface"], fg=C["text_1"],
                               font=("Consolas", 18, "bold"))
            val_lbl.pack(anchor="w", pady=(2, 0))
            self._hero_refs['val'] = val_lbl

            delta_lbl = tk.Label(outer, text="", bg=C["bg_surface"], font=FONT)
            delta_lbl.pack(anchor="w")
            self._hero_refs['delta'] = delta_lbl

            rate_lbl = tk.Label(outer, text="", bg=C["bg_surface"], fg=C["accent"], font=FONT_SM)
            rate_lbl.pack(anchor="w", pady=(2, 0))
            self._hero_refs['rate'] = rate_lbl

            sep = tk.Frame(outer, bg=C["border"], height=1)
            sep.pack(fill=tk.X, pady=6)
            self._hero_refs['sep'] = sep

            thr_rows = []
            for t, name, col in zip(THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS):
                row = tk.Frame(outer, bg=C["bg_surface"])
                row.pack(fill=tk.X, pady=2)
                name_lbl = tk.Label(row, text=name, bg=C["bg_surface"], fg=C["text_2"],
                                    font=FONT_SM, width=5)
                name_lbl.pack(side=tk.LEFT)

                bg_bar = tk.Frame(row, bg=C["bg_hover"], height=4)
                bg_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
                bg_bar.pack_propagate(False)
                fill_bar = tk.Frame(bg_bar, bg=col, height=4)
                fill_bar.place(x=0, y=0, relwidth=0, relheight=1)

                eta_lbl = tk.Label(row, text="", bg=C["bg_surface"], fg=C["text_3"],
                                   font=FONT_MONO, width=11, anchor="e")
                eta_lbl.pack(side=tk.LEFT)
                thr_rows.append({
                    'row': row, 'name': name, 'fill': fill_bar, 'eta': eta_lbl,
                    'bar': bg_bar, 'threshold': t, 'color': col,
                })
            self._hero_refs['thr_rows'] = thr_rows

        # ── 原地更新值 ─────────────────────────────
        self._hero_refs['val'].config(text=fmt_num(weighted_pred))
        delta = weighted_pred - current_views
        delta_text = f"▲ +{fmt_num(delta)}" if delta >= 0 else f"▼ {fmt_num(delta)}"
        delta_color = C["success"] if delta >= 0 else C["danger"]
        self._hero_refs['delta'].config(text=delta_text, fg=delta_color)

        if rate_per_sec > 0:
            per_min = rate_per_sec * 60
            per_hour = rate_per_sec * 3600
            if per_hour >= 1:
                rate_str = f"📈 +{fmt_num(per_hour)}/h"
            elif per_min >= 0.1:
                rate_str = f"📈 +{per_min:.1f}/min"
            else:
                rate_str = f"📈 +{rate_per_sec:.2f}/s"
            self._hero_refs['rate'].config(text=rate_str)
            self._hero_refs['rate'].pack(anchor="w", pady=(2, 0))
        else:
            self._hero_refs['rate'].pack_forget()

        for tr in self._hero_refs['thr_rows']:
            pct = min(current_views / tr['threshold'], 1.0)
            tr['fill'].place(relwidth=pct)
            if tr['threshold'] <= current_views:
                tr['eta'].config(text="✓ 已达成", fg=C["success"])
            elif rate_per_sec > 0:
                need = tr['threshold'] - current_views
                seconds_left = need / rate_per_sec
                arrive_dt = datetime.now() + timedelta(seconds=seconds_left)
                eta_str = arrive_dt.strftime("%m-%d %H:%M")
                eta_c = C["danger"] if seconds_left < 3600 else C["warning"] if seconds_left < 86400 else C["text_2"]
                tr['eta'].config(text=eta_str, fg=eta_c)
            else:
                tr['eta'].config(text="—", fg=C["text_3"])

    def _update_algo_list(self, results, failed):
        """增量更新算法列表，只更新值不销毁重建"""
        f = self._algo_frame
        n = len(results) if results else 0

        # ── 成功算法标题 ────────────────────────
        if results:
            if 'success' not in self._algo_headers:
                hdr = tk.Frame(f, bg=C["bg_surface"])
                hdr.pack(fill=tk.X, padx=8, pady=(6, 2))
                tk.Label(hdr, text="✅ 成功算法", bg=C["bg_surface"], fg=C["text_3"],
                         font=("Microsoft YaHei UI", 8, "bold")).pack(side=tk.LEFT)
                cnt_lbl = tk.Label(hdr, text="", bg=C["bg_elevated"], fg=C["text_2"],
                                   font=FONT_SM, padx=5, pady=1)
                cnt_lbl.pack(side=tk.LEFT, padx=4)
                self._algo_headers['success'] = {'frame': hdr, 'count': cnt_lbl}
            self._algo_headers['success']['count'].config(text=str(n))
            self._algo_headers['success']['frame'].pack(fill=tk.X, padx=8, pady=(6, 2))
        elif 'success' in self._algo_headers:
            self._algo_headers['success']['frame'].pack_forget()

        # ── 同步成功算法条目 ────────────────────
        old_n = len(self._algo_success_refs)
        if n > old_n:
            for i in range(old_n, n):
                refs = self._create_algo_entry(f)
                self._algo_success_refs.append(refs)
        elif n < old_n:
            for i in range(n, old_n):
                refs = self._algo_success_refs.pop()
                refs['card'].destroy()

        for i, (name, pred, weight, conf) in enumerate(results or []):
            refs = self._algo_success_refs[i]
            refs['name'].config(text=" " + name[:18])
            refs['pred'].config(text=fmt_num(pred))
            refs['conf'].config(text=f"{conf*100:.0f}%")
            refs['bar'].place(relwidth=conf)
            # Hover 效果
            refs['card'].bind("<Enter>", lambda e, c=refs['card']: c.config(highlightbackground=C["border"]))
            refs['card'].bind("<Leave>", lambda e, c=refs['card']: c.config(highlightbackground=C["border_sub"]))

        # ── 失败算法标题 ────────────────────────
        nf = len(failed) if failed else 0
        if failed:
            if 'fail' not in self._algo_headers:
                hdr2 = tk.Frame(f, bg=C["bg_surface"])
                hdr2.pack(fill=tk.X, padx=8, pady=(10, 2))
                tk.Label(hdr2, text="❌ 失败算法", bg=C["bg_surface"], fg=C["text_3"],
                         font=("Microsoft YaHei UI", 8, "bold")).pack(side=tk.LEFT)
                cnt_lbl2 = tk.Label(hdr2, text="", bg=C["bg_elevated"], fg=C["danger"],
                                    font=FONT_SM, padx=5, pady=1)
                cnt_lbl2.pack(side=tk.LEFT, padx=4)
                self._algo_headers['fail'] = {'frame': hdr2, 'count': cnt_lbl2}
            self._algo_headers['fail']['count'].config(text=str(nf))
            self._algo_headers['fail']['frame'].pack(fill=tk.X, padx=8, pady=(10, 2))
        elif 'fail' in self._algo_headers:
            self._algo_headers['fail']['frame'].pack_forget()

        # ── 同步失败条目 ────────────────────────
        old_nf = len(self._algo_fail_refs)
        if nf > old_nf:
            for i in range(old_nf, nf):
                refs = self._create_fail_entry(f)
                self._algo_fail_refs.append(refs)
        elif nf < old_nf:
            for i in range(nf, old_nf):
                refs = self._algo_fail_refs.pop()
                refs['row'].destroy()

        for i, (name, err) in enumerate(failed or []):
            refs = self._algo_fail_refs[i]
            refs['name'].config(text=name[:20])
            refs['err'].config(text=str(err)[:30])

        self._algo_canvas.yview_moveto(0)

    def _create_algo_entry(self, parent):
        """创建单个算法条目控件，返回引用字典"""
        dot_c = ALGO_COLORS[len(self._algo_success_refs) % len(ALGO_COLORS)]
        card = tk.Frame(parent, bg=C["bg_surface"], highlightthickness=1,
                        highlightbackground=C["border_sub"])
        card.pack(fill=tk.X, padx=6, pady=2)
        inner = tk.Frame(card, bg=C["bg_surface"], padx=10, pady=7)
        inner.pack(fill=tk.X)
        top_row = tk.Frame(inner, bg=C["bg_surface"])
        top_row.pack(fill=tk.X)
        tk.Label(top_row, text="●", bg=C["bg_surface"], fg=dot_c, font=FONT_SM).pack(side=tk.LEFT)
        name_lbl = tk.Label(top_row, text="", bg=C["bg_surface"], fg=C["text_1"], font=FONT)
        name_lbl.pack(side=tk.LEFT)
        pred_lbl = tk.Label(top_row, text="", bg=C["bg_surface"], fg=C["accent"],
                            font=("Consolas", 10, "bold"))
        pred_lbl.pack(side=tk.RIGHT)
        bar_row = tk.Frame(inner, bg=C["bg_surface"])
        bar_row.pack(fill=tk.X, pady=(4, 0))
        bg_bar = tk.Frame(bar_row, bg=C["bg_hover"], height=3)
        bg_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        bg_bar.pack_propagate(False)
        fill_bar = tk.Frame(bg_bar, bg=C["accent"], height=3)
        fill_bar.place(x=0, y=0, relwidth=0, relheight=1)
        conf_lbl = tk.Label(bar_row, text="", bg=C["bg_surface"], fg=C["text_3"],
                            font=("Consolas", 8), width=4)
        conf_lbl.pack(side=tk.LEFT, padx=3)
        return {'card': card, 'name': name_lbl, 'pred': pred_lbl,
                'bar': fill_bar, 'conf': conf_lbl}

    def _create_fail_entry(self, parent):
        """创建单个失败条目控件"""
        row = tk.Frame(parent, bg=C["bg_surface"], padx=10, pady=5)
        row.pack(fill=tk.X, padx=6)
        name_lbl = tk.Label(row, text="", bg=C["bg_surface"], fg=C["text_3"], font=FONT)
        name_lbl.pack(side=tk.LEFT)
        err_lbl = tk.Label(row, text="", bg=C["bg_surface"], fg=C["danger"], font=FONT_SM)
        err_lbl.pack(side=tk.RIGHT)
        return {'row': row, 'name': name_lbl, 'err': err_lbl}

    @property
    def algo_frame(self):
        return self._algo_frame
