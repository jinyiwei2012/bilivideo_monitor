"""
里程碑统计窗口（现代化版）
投稿一周/月/年后数据录入与对比
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import List, Dict, Optional, Callable

from core.database import db
from ui.theme import C
from ui.scrollable_frame import ScrollableFrame
from ui.helpers import FONT, FONT_BOLD, FONT_SM, fmt_num
from ui.dialog_base import DialogBase

PERIODS = ["1周", "1月", "1年"]
PERIOD_COLORS = {"1周": "#58a6ff", "1月": "#3fb950", "1年": "#f5a623"}
FIELDS = [
    ("view_count", "播放量", True, "必填"),
    ("like_count", "点赞数", False, ""),
    ("coin_count", "投币数", False, ""),
    ("share_count", "分享数", False, ""),
    ("favorite_count", "收藏数", False, ""),
    ("danmaku_count", "弹幕数", False, ""),
    ("reply_count", "评论数", False, ""),
    ("note", "备注", False, ""),
]


def _valid_bvid(s: str) -> bool:
    from ui.helpers import is_valid_bvid

    return is_valid_bvid(s)


class _EntryRow:
    """单行输入控件——BV号 × 周期"""

    def __init__(self, parent, bvid: str, period: str, existing: dict = None):
        self.bvid = bvid
        self.period = period
        self._vars: Dict[str, tk.StringVar] = {}

        frame = tk.Frame(parent, bg=C["bg_surface"], highlightthickness=1, highlightbackground=C["border_sub"])
        frame.pack(fill=tk.X, pady=2, ipady=2)

        tk.Label(frame, text=bvid, bg=C["bg_surface"], fg=C["accent"], font=FONT_BOLD, width=14, anchor="w").grid(
            row=0, column=0, padx=(6, 4)
        )
        tk.Label(
            frame, text=period, bg=C["bg_surface"], fg=PERIOD_COLORS[period], font=FONT_BOLD, width=4, anchor="w"
        ).grid(row=0, column=1, padx=(0, 8))

        col = 2
        for key, label, required, hint in FIELDS:
            tk.Label(
                frame,
                text=label + ("*" if required else ""),
                bg=C["bg_surface"],
                fg=C["danger"] if required else C["text_2"],
                font=FONT_SM,
                anchor="e",
                width=6,
            ).grid(row=0, column=col, padx=(4, 2))
            var = tk.StringVar()
            if existing and key in existing and existing[key] is not None:
                var.set(str(existing[key]))
            self._vars[key] = var
            w = 20 if key == "note" else 9
            entry = tk.Entry(
                frame,
                textvariable=var,
                font=FONT_SM,
                bg=C["bg_elevated"],
                fg=C["text_1"],
                insertbackground=C["text_1"],
                relief="flat",
                bd=1,
                width=w,
                highlightthickness=1,
                highlightcolor=C["accent"],
                highlightbackground=C["border"],
            )
            entry.grid(row=0, column=col + 1, padx=(0, 4))
            col += 2

    def collect(self) -> Optional[dict]:
        raw = self._vars["view_count"].get().strip().replace(",", "")
        if not raw:
            return None
        try:
            view = int(float(raw))
        except ValueError:
            return None
        data = {"view_count": view}
        for key, *_ in FIELDS[1:]:
            val = self._vars[key].get().strip()
            if key == "note":
                data[key] = val if val else None
            elif val:
                try:
                    data[key] = int(float(val.replace(",", "")))
                except ValueError:
                    pass
        return data


class MilestoneStatsWindow:
    """投稿里程碑统计与对比窗口（现代化风格）"""

    def __init__(
        self,
        parent=None,
        monitored_videos: Optional[List[Dict]] = None,
        on_add_monitor: Optional[Callable[[str], None]] = None,
    ):
        self.dlg = DialogBase(parent, "投稿里程碑 — 一周 / 月 / 年后数据", "1200x760", resizable=(True, True), modal=True)
        self.window = self.dlg.window

        self.monitored_videos = monitored_videos or []
        self.on_add_monitor = on_add_monitor
        self._monitored_set: set = {v.get("bvid", "") for v in self.monitored_videos}
        self._entry_rows: List[_EntryRow] = []

        self._setup_ui()
        self._reload_comparison()

    def _setup_ui(self):
        nb = ttk.Notebook(self.dlg.container)
        nb.pack(fill=tk.BOTH, expand=True, padx=24, pady=(12, 0))

        self._tab_entry = tk.Frame(nb, bg=C["bg_base"])
        nb.add(self._tab_entry, text="  📥 录入数据  ")
        self._tab_compare = tk.Frame(nb, bg=C["bg_base"])
        nb.add(self._tab_compare, text="  📊 对比视图  ")
        nb.bind("<<NotebookTabChanged>>", lambda e: self._reload_comparison() if nb.index("current") == 1 else None)

        self._build_entry_tab()
        self._build_compare_tab()

    # ── 录入标签页 ──────────────────────────────────────
    def _build_entry_tab(self):
        tab = self._tab_entry

        # 顶部卡片
        top = tk.Frame(tab, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        top.pack(fill=tk.X, padx=16, pady=(12, 6), ipadx=10, ipady=8)

        # 三列布局
        cols_frame = tk.Frame(top, bg=C["bg_elevated"])
        cols_frame.pack(fill=tk.X)

        # 左：BV号输入
        bv_col = tk.Frame(cols_frame, bg=C["bg_elevated"])
        bv_col.pack(side=tk.LEFT, padx=(0, 24))
        tk.Label(bv_col, text="BV号（每行一个，可批量）", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(anchor="w")
        self._bvid_text = tk.Text(
            bv_col,
            width=22,
            height=4,
            bg=C["bg_base"],
            fg=C["text_1"],
            insertbackground=C["text_1"],
            font=FONT_SM,
            relief="flat",
            bd=1,
            highlightthickness=1,
            highlightcolor=C["accent"],
            highlightbackground=C["border"],
        )
        self._bvid_text.pack()

        # 中：周期勾选
        period_col = tk.Frame(cols_frame, bg=C["bg_elevated"])
        period_col.pack(side=tk.LEFT, padx=(0, 24))
        tk.Label(period_col, text="统计周期", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(anchor="w")
        self._period_vars: Dict[str, tk.BooleanVar] = {}
        for p in PERIODS:
            var = tk.BooleanVar(value=True)
            self._period_vars[p] = var
            tk.Checkbutton(
                period_col,
                text=p,
                variable=var,
                bg=C["bg_elevated"],
                fg=PERIOD_COLORS[p],
                activebackground=C["bg_elevated"],
                selectcolor=C["bg_base"],
                font=FONT_BOLD,
            ).pack(anchor="w")

        # 右：按钮
        btn_col = tk.Frame(cols_frame, bg=C["bg_elevated"])
        btn_col.pack(side=tk.LEFT)
        ttk.Button(btn_col, text="生成输入表", command=self._generate_entry_rows).pack(fill=tk.X, pady=3)
        ttk.Button(btn_col, text="💾 保存全部", style="Primary.TButton", command=self._save_all).pack(fill=tk.X, pady=3)

        # 输入行区域
        mid = tk.Frame(tab, bg=C["bg_base"])
        mid.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        # 列头
        header = tk.Frame(mid, bg=C["bg_surface"], height=24)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        cols = ["BV号", "周期", "播放量*", "点赞数", "投币数", "分享数", "收藏数", "弹幕数", "评论数", "备注"]
        widths = [14, 4, 9, 9, 9, 9, 9, 9, 9, 20]
        x = 6
        for ct, w in zip(cols, widths):
            tk.Label(header, text=ct, bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM, width=w, anchor="w").place(
                x=x, y=3
            )
            x += w * 7

        # 可滚动容器
        sf = ScrollableFrame(mid, bg=C["bg_base"])
        sf.pack(fill=tk.BOTH, expand=True)
        self._entry_container = sf.inner

        self._entry_status = tk.Label(
            tab,
            text="请输入 BV 号并选择周期，然后点击「生成输入表」",
            bg=C["bg_base"],
            fg=C["text_2"],
            font=FONT_SM,
            anchor="w",
        )
        self._entry_status.pack(fill=tk.X, padx=16, pady=(4, 8))

    def _generate_entry_rows(self):
        raw = self._bvid_text.get("1.0", tk.END).strip()
        if not raw:
            messagebox.showwarning("提示", "请先输入 BV 号", parent=self.window)
            return

        bvids = self._parse_and_validate_bvids(raw)
        if not bvids:
            return

        self._prompt_not_monitored_bvids(bvids)

        periods = [p for p, v in self._period_vars.items() if v.get()]
        if not periods:
            messagebox.showwarning("提示", "请至少选择一个统计周期", parent=self.window)
            return

        self._populate_milestone_entry_rows(bvids, periods)

    def _parse_and_validate_bvids(self, raw):
        """解析并验证 BV 号。返回有效 BV 号列表，或 None（无有效 BV 号）。"""
        bvids, invalid = [], []
        for line in raw.splitlines():
            bv = line.strip()
            if not bv:
                continue
            if _valid_bvid(bv):
                if bv not in bvids:
                    bvids.append(bv)
            else:
                invalid.append(bv)
        if invalid:
            messagebox.showwarning("格式错误", "以下 BV 号格式不合法，已跳过：\n" + "\n".join(invalid), parent=self.window)
        if not bvids:
            return None
        return bvids

    def _prompt_not_monitored_bvids(self, bvids):
        """提示将不在监控列表的 BV 号加入监控。"""
        not_monitored = [b for b in bvids if b not in self._monitored_set]
        if not_monitored:
            msg = "以下 BV 号不在监控列表中：\n" + "\n".join(not_monitored[:10])
            if len(not_monitored) > 10:
                msg += f"\n...共 {len(not_monitored)} 个"
            msg += "\n\n是否加入监控列表？"
            if messagebox.askyesno("加入监控", msg, parent=self.window):
                for bv in not_monitored:
                    if self.on_add_monitor:
                        self.on_add_monitor(bv)
                    self._monitored_set.add(bv)

    def _populate_milestone_entry_rows(self, bvids, periods):
        """生成里程碑输入行 UI。"""
        for w in self._entry_container.winfo_children():
            w.destroy()
        self._entry_rows.clear()
        existing_map = {}
        for row in db.get_milestones():
            existing_map[(row["bvid"], row["period"])] = row
        for bv in bvids:
            for p in periods:
                row = _EntryRow(self._entry_container, bv, p, existing_map.get((bv, p)))
                self._entry_rows.append(row)
        total = len(self._entry_rows)
        self._entry_status.config(text=f"共生成 {total} 行（{len(bvids)} 视频 × {len(periods)} 周期），填写后点击「保存全部」")

    def _save_all(self):
        if not self._entry_rows:
            messagebox.showwarning("提示", "请先生成输入表", parent=self.window)
            return
        saved = skipped = errors = 0
        for row in self._entry_rows:
            data = row.collect()
            if data is None:
                skipped += 1
                continue
            ok = db.upsert_milestone(row.bvid, row.period, data)
            if ok:
                saved += 1
            else:
                errors += 1
        msg = f"✅ 已保存 {saved} 条"
        if skipped:
            msg += f"，跳过 {skipped} 条（播放量为空）"
        if errors:
            msg += f"，失败 {errors} 条"
        self._entry_status.config(text=msg, fg=C["success"] if not errors else C["warning"])
        if saved:
            self._reload_comparison()
            messagebox.showinfo("保存完成", msg, parent=self.window)

    # ── 对比标签页 ──────────────────────────────────────
    def _build_compare_tab(self):
        tab = self._tab_compare

        ctrl = tk.Frame(tab, bg=C["bg_surface"])
        ctrl.pack(fill=tk.X, padx=12, pady=6)

        tk.Label(ctrl, text="展示指标：", bg=C["bg_surface"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)
        self._metric_var = tk.StringVar(value="view_count")
        for label, val in [
            ("播放量", "view_count"),
            ("点赞数", "like_count"),
            ("投币数", "coin_count"),
            ("收藏数", "favorite_count"),
            ("分享数", "share_count"),
            ("弹幕数", "danmaku_count"),
            ("评论数", "reply_count"),
        ]:
            tk.Radiobutton(
                ctrl,
                text=label,
                variable=self._metric_var,
                value=val,
                bg=C["bg_surface"],
                fg=C["text_1"],
                activebackground=C["bg_surface"],
                selectcolor=C["bg_base"],
                font=FONT_SM,
                command=self._redraw_compare,
            ).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="🔄 刷新", command=self._reload_comparison).pack(side=tk.RIGHT, padx=6)

        # 筛选
        ff = tk.Frame(tab, bg=C["bg_base"])
        ff.pack(fill=tk.X, padx=12, pady=(4, 0))
        tk.Label(ff, text="筛选视频：", bg=C["bg_base"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT)
        self._filter_entry = tk.Entry(
            ff,
            font=FONT_SM,
            width=60,
            bg=C["bg_elevated"],
            fg=C["text_1"],
            insertbackground=C["text_1"],
            relief="flat",
            bd=1,
        )
        self._filter_entry.pack(side=tk.LEFT, padx=4)
        tk.Label(ff, text="（BV号关键词，逗号分隔）", bg=C["bg_base"], fg=C["text_3"], font=FONT_SM).pack(side=tk.LEFT)
        ttk.Button(ff, text="应用筛选", command=self._redraw_compare).pack(side=tk.LEFT, padx=6)

        # 图表
        co = tk.Frame(tab, bg=C["bg_base"])
        co.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self._cmp_canvas = tk.Canvas(co, bg=C["canvas_bg"], highlightthickness=0)
        hsb = ttk.Scrollbar(co, orient="horizontal", command=self._cmp_canvas.xview)
        self._cmp_canvas.configure(xscrollcommand=hsb.set)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._cmp_canvas.pack(fill=tk.BOTH, expand=True)
        self._cmp_canvas.bind("<Configure>", lambda e: self._redraw_compare())
        self._cmp_canvas.bind("<MouseWheel>", lambda e: self._cmp_canvas.xview_scroll(-1 * (e.delta // 120), "units"))

        # 明细表
        tbl_frame = tk.Frame(tab, bg=C["bg_base"])
        tbl_frame.pack(fill=tk.X, padx=8, pady=(0, 8))
        tk.Label(tbl_frame, text="明细数据", bg=C["bg_base"], fg=C["text_3"], font=FONT_SM).pack(anchor="w")
        cols = ("bvid", "标题", "1周播放", "1月播放", "1年播放", "1周点赞", "1月点赞", "1年点赞", "记录时间")
        self._tbl = ttk.Treeview(tbl_frame, columns=cols, show="headings", height=5)
        wsb = ttk.Scrollbar(tbl_frame, orient="vertical", command=self._tbl.yview)
        self._tbl.configure(yscrollcommand=wsb.set)
        wsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tbl.pack(fill=tk.X, expand=True, pady=(2, 0))
        for col, w in zip(cols, [110, 220, 80, 80, 80, 70, 70, 70, 130]):
            self._tbl.heading(col, text=col)
            self._tbl.column(col, width=w, minwidth=50, anchor="center")

        self._tbl_menu = tk.Menu(self.window, tearoff=0)
        self._tbl_menu.add_command(label="删除选中行所有里程碑", command=self._delete_selected)
        self._tbl.bind("<Button-3>", lambda e: self._tbl_menu.tk_popup(e.x_root, e.y_root))

        self._cmp_status = tk.Label(tab, text="", bg=C["bg_base"], fg=C["text_2"], font=FONT_SM, anchor="w")
        self._cmp_status.pack(fill=tk.X, padx=12, pady=2)
        self._all_data: dict = {}

    def _reload_comparison(self):
        self._all_data = db.get_all_milestones_grouped()
        self._fill_table()
        self._redraw_compare()

    def _get_video_title(self, bvid: str) -> str:
        for v in self.monitored_videos:
            if v.get("bvid") == bvid:
                t = v.get("title", "")
                return t[:20] if t else bvid
        return bvid

    def _fill_table(self):
        for item in self._tbl.get_children():
            self._tbl.delete(item)
        for bvid, periods in sorted(self._all_data.items()):
            title = self._get_video_title(bvid)

            def _v(p, key):
                r = periods.get(p, {})
                val = r.get(key)
                return fmt_num(val) if val is not None else "—"

            times = [periods[p].get("recorded_at", "") for p in PERIODS if p in periods]
            latest = max(times)[:16] if times else "—"
            self._tbl.insert(
                "",
                tk.END,
                iid=bvid,
                values=(
                    bvid,
                    title,
                    _v("1周", "view_count"),
                    _v("1月", "view_count"),
                    _v("1年", "view_count"),
                    _v("1周", "like_count"),
                    _v("1月", "like_count"),
                    _v("1年", "like_count"),
                    latest,
                ),
            )

    def _delete_selected(self):
        sel = self._tbl.selection()
        if not sel:
            return
        msg = f"确认删除 {len(sel)} 个视频的所有里程碑记录？"
        if not messagebox.askyesno("确认", msg, parent=self.window):
            return
        for bv in sel:
            for p in PERIODS:
                db.delete_milestone(bv, p)
        self._reload_comparison()

    def _redraw_compare(self):
        c = self._cmp_canvas
        c.delete("all")

        ft = self._filter_entry.get().strip()
        if ft:
            ks = [k.strip() for k in ft.split(",") if k.strip()]
            data = {bv: pd for bv, pd in self._all_data.items() if any(k.upper() in bv.upper() for k in ks)}
        else:
            data = self._all_data

        if not data:
            c.create_text(
                (c.winfo_width() or 600) // 2,
                (c.winfo_height() or 300) // 2,
                text="暂无里程碑数据，请在「录入数据」标签页添加",
                fill=C["text_2"],
                font=("Microsoft YaHei UI", 12),
            )
            self._cmp_status.config(text="无数据")
            return

        metric = self._metric_var.get()
        bvids = sorted(data.keys())
        n_videos = len(bvids)
        n_periods = len(PERIODS)

        CW = c.winfo_width() or 800
        CH = c.winfo_height() or 360
        ML, MR, MT, MB = 70, 20, 30, 80
        cw = max(CW - ML - MR, n_videos * (n_periods + 1) * 18)
        ch = CH - MT - MB
        c.configure(scrollregion=(0, 0, cw + ML + MR, CH))

        max_val = 1
        for bv in bvids:
            for p in PERIODS:
                v = (data[bv].get(p) or {}).get(metric)
                if v:
                    max_val = max(max_val, v)

        def to_y(v):
            return MT + ch - (v / max_val) * ch * 0.92 if v else MT + ch

        for i in range(6):
            ratio = i / 5
            y = MT + ch * (1 - ratio * 0.92)
            val = max_val * ratio
            c.create_line(ML, y, ML + cw, y, fill=C["border"], dash=(2, 4))
            c.create_text(
                ML - 6,
                y,
                text=f"{val / 10000:.0f}w" if val >= 10000 else str(int(val)),
                anchor="e",
                fill=C["text_2"],
                font=("Consolas", 8),
            )

        group_w = cw / max(n_videos, 1)
        bar_total_w = group_w * 0.75
        bar_w = bar_total_w / n_periods
        gap_w = group_w * 0.125

        for vi, bv in enumerate(bvids):
            gx = ML + vi * group_w + gap_w
            title = self._get_video_title(bv)
            for pi, period in enumerate(PERIODS):
                row = data[bv].get(period) or {}
                val = row.get(metric)
                color = PERIOD_COLORS[period]
                bx = gx + pi * bar_w
                by = to_y(val)
                bx2 = bx + bar_w - 2
                if val:
                    c.create_rectangle(bx, by, bx2, MT + ch, fill=color, outline="")
                    if by < MT + ch - 14:
                        c.create_text(
                            (bx + bx2) / 2,
                            by - 4,
                            text=f"{val / 10000:.0f}w" if val >= 10000 else str(int(val)),
                            anchor="s",
                            fill=color,
                            font=("Consolas", 7, "bold"),
                        )
                else:
                    c.create_rectangle(bx, MT + ch - 4, bx2, MT + ch, fill=C["border"], outline="")
            lx = gx + bar_total_w / 2
            c.create_text(lx, MT + ch + 6, text=title, anchor="n", fill=C["text_1"], font=("Microsoft YaHei UI", 8))
            c.create_text(lx, MT + ch + 22, text=bv, anchor="n", fill=C["text_3"], font=("Consolas", 7))

        lgx = ML + 6
        for p in PERIODS:
            c.create_rectangle(lgx, MT + ch + 52, lgx + 10, MT + ch + 62, fill=PERIOD_COLORS[p], outline="")
            c.create_text(
                lgx + 14,
                MT + ch + 57,
                text=f"投稿{p}后",
                anchor="w",
                fill=PERIOD_COLORS[p],
                font=("Microsoft YaHei UI", 8),
            )
            lgx += 90

        ml = next((lb for key, lb, *_ in FIELDS if key == metric), metric)
        c.create_text(
            ML + cw // 2,
            14,
            text=f"投稿里程碑对比 — {ml}",
            fill=C["text_1"],
            font=("Microsoft YaHei UI", 10, "bold"),
            anchor="n",
        )
        self._cmp_status.config(text=f"共 {n_videos} 个视频 · 展示指标：{ml}")
