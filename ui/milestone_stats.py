"""
里程碑统计窗口 — 投稿一周/月/年后数据录入与对比
=========================================================
功能：
  - 选择/输入 BV 号（可批量粘贴，每行一个）
  - 必填：播放量；选填：点赞/投币/分享/收藏/弹幕/评论/备注
  - 数据写入总数据库 video_milestones 表（bvid+period 唯一）
  - 若 BV 号不在监控列表，询问是否加入监控
  - 对比面板：多视频 × 三个周期的柱状对比图（Canvas）
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import re
import threading
from datetime import datetime
from typing import List, Dict, Optional, Callable

from core.database import db
from ui.theme import C
from ui.helpers import FONT, FONT_BOLD, FONT_SM, FONT_LG, fmt_num

# ── 常量 ──────────────────────────────────────────────────────────────────────
PERIODS = ["1周", "1月", "1年"]
PERIOD_COLORS = {
    "1周":  "#58a6ff",   # 蓝
    "1月":  "#3fb950",   # 绿
    "1年":  "#f5a623",   # 橙
}

_BVID_RE = re.compile(r'^BV[A-Za-z0-9]{10}$')

FIELDS = [
    ("view_count",     "播放量",  True,  "必填"),
    ("like_count",     "点赞数",  False, ""),
    ("coin_count",     "投币数",  False, ""),
    ("share_count",    "分享数",  False, ""),
    ("favorite_count", "收藏数",  False, ""),
    ("danmaku_count",  "弹幕数",  False, ""),
    ("reply_count",    "评论数",  False, ""),
    ("note",           "备注",    False, ""),
]


def _valid_bvid(s: str) -> bool:
    return bool(_BVID_RE.match(s.strip()))


# ── 单视频录入行 ──────────────────────────────────────────────────────────────
class _EntryRow:
    """一行输入控件，对应一个 BV号 × 一个周期的数据。"""

    def __init__(self, parent, bvid: str, period: str, existing: dict = None):
        self.bvid   = bvid
        self.period = period
        self._vars: Dict[str, tk.StringVar] = {}

        frame = tk.Frame(parent, bg=C["bg_elevated"], bd=0)
        frame.pack(fill=tk.X, pady=2, padx=4)

        # BV号 + 周期标签
        tk.Label(frame, text=f"{bvid}", bg=C["bg_elevated"], fg=C["accent"],
                 font=FONT_BOLD, width=14, anchor="w").grid(row=0, column=0, padx=(6, 4))
        tk.Label(frame, text=period, bg=C["bg_elevated"],
                 fg=PERIOD_COLORS[period], font=FONT_BOLD, width=4,
                 anchor="w").grid(row=0, column=1, padx=(0, 8))

        # 字段输入框
        col = 2
        for key, label, required, hint in FIELDS:
            tk.Label(frame, text=label + ("*" if required else ""),
                     bg=C["bg_elevated"],
                     fg=C["danger"] if required else C["text_2"],
                     font=FONT_SM, anchor="e", width=6).grid(row=0, column=col, padx=(4, 2))
            var = tk.StringVar()
            if existing and key in existing and existing[key] is not None:
                var.set(str(existing[key]))
            self._vars[key] = var
            width = 20 if key == "note" else 9
            entry = tk.Entry(frame, textvariable=var, font=FONT_SM,
                             bg=C["bg_base"], fg=C["text_1"],
                             insertbackground=C["text_1"],
                             relief="flat", bd=1, width=width,
                             highlightthickness=1,
                             highlightcolor=C["accent"],
                             highlightbackground=C["border"])
            entry.grid(row=0, column=col + 1, padx=(0, 4))
            col += 2

    def collect(self) -> Optional[dict]:
        """收集数据；view_count 为空则返回 None（用于跳过）。"""
        raw_view = self._vars["view_count"].get().strip().replace(",", "")
        if not raw_view:
            return None
        try:
            view = int(float(raw_view))
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


# ── 主窗口 ────────────────────────────────────────────────────────────────────
class MilestoneStatsWindow:
    """投稿里程碑统计与对比窗口"""

    def __init__(self, parent=None,
                 monitored_videos: Optional[List[Dict]] = None,
                 on_add_monitor: Optional[Callable[[str], None]] = None):
        self.window = tk.Toplevel(parent)
        self.window.title("投稿里程碑 — 一周 / 月 / 年后数据")
        self.window.geometry("1200x760")
        self.window.minsize(900, 600)
        self.window.transient(parent)
        self.window.configure(bg=C["bg_base"])

        self.monitored_videos = monitored_videos or []
        self.on_add_monitor   = on_add_monitor   # 回调：将 bvid 加入监控

        # 已监控 BV 号集合（快速查询）
        self._monitored_set: set = {v.get("bvid", "") for v in self.monitored_videos}
        self._entry_rows: List[_EntryRow] = []   # 当前输入行

        self._setup_ui()
        self._reload_comparison()

    # ═════════════════════ UI 构建 ═══════════════════════════════════════════

    def _setup_ui(self):
        # 顶部标签页
        nb = ttk.Notebook(self.window)
        nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 标签页 1：录入
        self._tab_entry = tk.Frame(nb, bg=C["bg_base"])
        nb.add(self._tab_entry, text="  📥 录入数据  ")

        # 标签页 2：对比
        self._tab_compare = tk.Frame(nb, bg=C["bg_base"])
        nb.add(self._tab_compare, text="  📊 对比视图  ")

        nb.bind("<<NotebookTabChanged>>",
                lambda e: self._reload_comparison() if nb.index("current") == 1 else None)

        self._build_entry_tab()
        self._build_compare_tab()

    # ── 录入标签页 ──────────────────────────────────────────────────────────

    def _build_entry_tab(self):
        tab = self._tab_entry

        # 顶部：BV号输入 + 周期选择 + 操作按钮
        top = tk.Frame(tab, bg=C["bg_surface"], padx=10, pady=8)
        top.pack(fill=tk.X)

        # 左列：BV 号输入框
        bv_col = tk.Frame(top, bg=C["bg_surface"])
        bv_col.pack(side=tk.LEFT, padx=(0, 20))

        tk.Label(bv_col, text="BV号（每行一个，可批量）",
                 bg=C["bg_surface"], fg=C["text_2"], font=FONT_SM).pack(anchor="w")
        self._bvid_text = tk.Text(bv_col, width=22, height=4,
                                  bg=C["bg_base"], fg=C["text_1"],
                                  insertbackground=C["text_1"],
                                  font=FONT_SM, relief="flat", bd=1,
                                  highlightthickness=1,
                                  highlightcolor=C["accent"],
                                  highlightbackground=C["border"])
        self._bvid_text.pack()

        # 中列：周期勾选
        period_col = tk.Frame(top, bg=C["bg_surface"])
        period_col.pack(side=tk.LEFT, padx=(0, 20))
        tk.Label(period_col, text="统计周期",
                 bg=C["bg_surface"], fg=C["text_2"], font=FONT_SM).pack(anchor="w")
        self._period_vars: Dict[str, tk.BooleanVar] = {}
        for p in PERIODS:
            var = tk.BooleanVar(value=True)
            self._period_vars[p] = var
            cb = tk.Checkbutton(period_col, text=p, variable=var,
                                bg=C["bg_surface"], fg=PERIOD_COLORS[p],
                                activebackground=C["bg_surface"],
                                selectcolor=C["bg_base"],
                                font=FONT_BOLD)
            cb.pack(anchor="w")

        # 右列：按钮
        btn_col = tk.Frame(top, bg=C["bg_surface"])
        btn_col.pack(side=tk.LEFT)
        ttk.Button(btn_col, text="生成输入表",
                   command=self._generate_entry_rows).pack(fill=tk.X, pady=3)
        ttk.Button(btn_col, text="💾 保存全部",
                   command=self._save_all).pack(fill=tk.X, pady=3)

        # 中间：可滚动的输入行区域
        mid = tk.Frame(tab, bg=C["bg_base"])
        mid.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        # 列头说明
        header = tk.Frame(mid, bg=C["bg_surface"], height=22)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        cols = ["BV号", "周期",
                "播放量*", "点赞数", "投币数", "分享数",
                "收藏数", "弹幕数", "评论数", "备注"]
        widths = [14, 4, 9, 9, 9, 9, 9, 9, 9, 20]
        x = 6
        for col_text, w in zip(cols, widths):
            tk.Label(header, text=col_text, bg=C["bg_surface"],
                     fg=C["text_2"], font=FONT_SM,
                     width=w, anchor="w").place(x=x, y=3)
            x += w * 7   # 近似像素宽度

        # 滚动容器
        canvas_frame = tk.Frame(mid, bg=C["bg_base"])
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self._scroll_canvas = tk.Canvas(canvas_frame, bg=C["bg_base"],
                                        highlightthickness=0)
        vsb = ttk.Scrollbar(canvas_frame, orient="vertical",
                             command=self._scroll_canvas.yview)
        self._scroll_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._scroll_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._entry_container = tk.Frame(self._scroll_canvas, bg=C["bg_base"])
        self._scroll_canvas.create_window((0, 0), window=self._entry_container,
                                          anchor="nw", tags="inner")
        self._entry_container.bind("<Configure>",
            lambda e: self._scroll_canvas.configure(
                scrollregion=self._scroll_canvas.bbox("all")))

        self._scroll_canvas.bind("<MouseWheel>",
            lambda e: self._scroll_canvas.yview_scroll(
                -1 * (e.delta // 120), "units"))

        # 底部状态栏
        self._entry_status = tk.Label(tab, text="请输入 BV 号并选择周期，然后点击「生成输入表」",
                                      bg=C["bg_base"], fg=C["text_2"], font=FONT_SM,
                                      anchor="w")
        self._entry_status.pack(fill=tk.X, padx=8, pady=4)

    def _generate_entry_rows(self):
        """根据 BV 号文本框和周期选择，生成输入行。"""
        raw = self._bvid_text.get("1.0", tk.END).strip()
        if not raw:
            messagebox.showwarning("提示", "请先输入 BV 号", parent=self.window)
            return

        bvids = []
        invalid = []
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
            messagebox.showwarning(
                "格式错误",
                f"以下 BV 号格式不合法，已跳过：\n" + "\n".join(invalid),
                parent=self.window)

        if not bvids:
            return

        # 检查哪些不在监控列表
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

        periods = [p for p, v in self._period_vars.items() if v.get()]
        if not periods:
            messagebox.showwarning("提示", "请至少选择一个统计周期", parent=self.window)
            return

        # 清空旧行
        for w in self._entry_container.winfo_children():
            w.destroy()
        self._entry_rows.clear()

        # 读取已存在的数据，预填写
        existing_map = {}  # (bvid, period) -> row dict
        for row in db.get_milestones():
            existing_map[(row["bvid"], row["period"])] = row

        for bv in bvids:
            for p in periods:
                existing = existing_map.get((bv, p))
                row = _EntryRow(self._entry_container, bv, p, existing)
                self._entry_rows.append(row)

        total = len(self._entry_rows)
        self._entry_status.config(
            text=f"共生成 {total} 行（{len(bvids)} 个视频 × {len(periods)} 个周期），填写后点击「保存全部」")

    def _save_all(self):
        """保存所有非空输入行到数据库。"""
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

    # ── 对比标签页 ──────────────────────────────────────────────────────────

    def _build_compare_tab(self):
        tab = self._tab_compare

        # 顶部控制栏
        ctrl = tk.Frame(tab, bg=C["bg_surface"], padx=10, pady=6)
        ctrl.pack(fill=tk.X)

        tk.Label(ctrl, text="展示指标：",
                 bg=C["bg_surface"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)

        self._metric_var = tk.StringVar(value="view_count")
        metric_map = [
            ("播放量", "view_count"),
            ("点赞数", "like_count"),
            ("投币数", "coin_count"),
            ("收藏数", "favorite_count"),
            ("分享数", "share_count"),
            ("弹幕数", "danmaku_count"),
            ("评论数", "reply_count"),
        ]
        for label, val in metric_map:
            tk.Radiobutton(ctrl, text=label, variable=self._metric_var, value=val,
                           bg=C["bg_surface"], fg=C["text_1"],
                           activebackground=C["bg_surface"],
                           selectcolor=C["bg_base"],
                           font=FONT_SM,
                           command=self._redraw_compare).pack(side=tk.LEFT, padx=4)

        ttk.Button(ctrl, text="🔄 刷新",
                   command=self._reload_comparison).pack(side=tk.RIGHT, padx=6)

        # 视频筛选多选
        filter_f = tk.Frame(tab, bg=C["bg_base"])
        filter_f.pack(fill=tk.X, padx=8, pady=(4, 0))
        tk.Label(filter_f, text="筛选视频（空=全部）：",
                 bg=C["bg_base"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT)
        self._filter_entry = tk.Entry(filter_f, font=FONT_SM, width=60,
                                      bg=C["bg_elevated"], fg=C["text_1"],
                                      insertbackground=C["text_1"],
                                      relief="flat", bd=1)
        self._filter_entry.pack(side=tk.LEFT, padx=4)
        tk.Label(filter_f, text="（BV号关键词，逗号分隔）",
                 bg=C["bg_base"], fg=C["text_3"], font=FONT_SM).pack(side=tk.LEFT)
        ttk.Button(filter_f, text="应用筛选",
                   command=self._redraw_compare).pack(side=tk.LEFT, padx=6)

        # 图表 Canvas
        chart_outer = tk.Frame(tab, bg=C["bg_base"])
        chart_outer.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self._cmp_canvas = tk.Canvas(chart_outer, bg=C.get("canvas_bg", C["bg_elevated"]),
                                     highlightthickness=0)
        hsb = ttk.Scrollbar(chart_outer, orient="horizontal",
                             command=self._cmp_canvas.xview)
        self._cmp_canvas.configure(xscrollcommand=hsb.set)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._cmp_canvas.pack(fill=tk.BOTH, expand=True)
        self._cmp_canvas.bind("<Configure>", lambda e: self._redraw_compare())
        self._cmp_canvas.bind("<MouseWheel>",
            lambda e: self._cmp_canvas.xview_scroll(-1*(e.delta//120), "units"))

        # 数据表格区
        tbl_frame = tk.LabelFrame(tab, text="明细数据",
                                  bg=C["bg_base"], fg=C["text_2"], font=FONT_SM,
                                  padx=6, pady=4)
        tbl_frame.pack(fill=tk.X, padx=8, pady=(0, 8))

        cols = ("bvid", "标题", "1周播放", "1月播放", "1年播放",
                "1周点赞", "1月点赞", "1年点赞", "记录时间")
        self._tbl = ttk.Treeview(tbl_frame, columns=cols, show="headings",
                                  height=6)
        wsb = ttk.Scrollbar(tbl_frame, orient="vertical",
                             command=self._tbl.yview)
        self._tbl.configure(yscrollcommand=wsb.set)
        wsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tbl.pack(fill=tk.X, expand=True)

        col_widths = [110, 220, 80, 80, 80, 70, 70, 70, 130]
        for col, w in zip(cols, col_widths):
            self._tbl.heading(col, text=col)
            self._tbl.column(col, width=w, minwidth=50, anchor="center")

        # 右键菜单：删除
        self._tbl_menu = tk.Menu(self.window, tearoff=0,
                                  bg=C["bg_elevated"], fg=C["text_1"],
                                  activebackground=C["bg_hover"],
                                  activeforeground=C["text_1"])
        self._tbl_menu.add_command(label="删除选中行所有里程碑",
                                   command=self._delete_selected)
        self._tbl.bind("<Button-3>",
                       lambda e: self._tbl_menu.tk_popup(e.x_root, e.y_root))

        # 状态栏
        self._cmp_status = tk.Label(tab, text="",
                                    bg=C["bg_base"], fg=C["text_2"], font=FONT_SM,
                                    anchor="w")
        self._cmp_status.pack(fill=tk.X, padx=8, pady=2)

        # 缓存
        self._all_data: dict = {}  # bvid -> {period -> row}

    def _reload_comparison(self):
        """从数据库重新加载所有里程碑，并刷新对比视图。"""
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
        """填充明细表格。"""
        for item in self._tbl.get_children():
            self._tbl.delete(item)

        for bvid, periods in sorted(self._all_data.items()):
            title = self._get_video_title(bvid)

            def _v(p, key):
                row = periods.get(p, {})
                val = row.get(key)
                return fmt_num(val) if val is not None else "—"

            # 记录时间取最新一个周期的
            times = [periods[p].get("recorded_at", "") for p in PERIODS if p in periods]
            latest_time = max(times) if times else "—"
            if latest_time and len(latest_time) > 16:
                latest_time = latest_time[:16]

            self._tbl.insert("", tk.END, iid=bvid, values=(
                bvid, title,
                _v("1周", "view_count"),
                _v("1月", "view_count"),
                _v("1年", "view_count"),
                _v("1周", "like_count"),
                _v("1月", "like_count"),
                _v("1年", "like_count"),
                latest_time,
            ))

    def _delete_selected(self):
        selected = self._tbl.selection()
        if not selected:
            return
        bvids = list(selected)
        msg = f"确认删除 {len(bvids)} 个视频的所有里程碑记录？"
        if not messagebox.askyesno("确认", msg, parent=self.window):
            return
        for bv in bvids:
            for p in PERIODS:
                db.delete_milestone(bv, p)
        self._reload_comparison()

    # ── 图表绘制 ─────────────────────────────────────────────────────────────

    def _redraw_compare(self):
        c = self._cmp_canvas
        c.delete("all")

        # 筛选
        filter_text = self._filter_entry.get().strip()
        if filter_text:
            keywords = [k.strip() for k in filter_text.split(",") if k.strip()]
            data = {bv: pdata for bv, pdata in self._all_data.items()
                    if any(k.upper() in bv.upper() for k in keywords)}
        else:
            data = self._all_data

        if not data:
            c.create_text(
                (c.winfo_width() or 600) // 2,
                (c.winfo_height() or 300) // 2,
                text="暂无里程碑数据，请在「录入数据」标签页添加",
                fill=C["text_2"], font=("Microsoft YaHei UI", 12))
            self._cmp_status.config(text="无数据")
            return

        metric   = self._metric_var.get()
        bvids    = sorted(data.keys())
        n_videos = len(bvids)
        n_periods = len(PERIODS)

        CW = c.winfo_width()  or 800
        CH = c.winfo_height() or 360

        ML, MR, MT, MB = 70, 20, 30, 80
        cw = max(CW - ML - MR, n_videos * (n_periods + 1) * 18)
        ch = CH - MT - MB

        # 动态滚动宽度
        c.configure(scrollregion=(0, 0, cw + ML + MR, CH))

        # 收集最大值
        max_val = 1
        for bv in bvids:
            for p in PERIODS:
                v = (data[bv].get(p) or {}).get(metric)
                if v:
                    max_val = max(max_val, v)

        def to_y(v):
            if not v:
                return MT + ch
            return MT + ch - (v / max_val) * ch * 0.92

        def fmt_axis(n):
            if n >= 100_000_000:
                return f"{n/100_000_000:.1f}亿"
            if n >= 10_000:
                return f"{n/10_000:.0f}w"
            return str(int(n))

        # Y 轴刻度
        for i in range(6):
            ratio = i / 5
            y = MT + ch * (1 - ratio * 0.92)
            val = max_val * ratio
            c.create_line(ML, y, ML + cw, y, fill=C["border"], dash=(2, 4))
            c.create_text(ML - 6, y, text=fmt_axis(val), anchor="e",
                          fill=C["text_2"], font=("Consolas", 8))

        # 每个视频的柱子组
        group_w = cw / max(n_videos, 1)
        bar_total_w = group_w * 0.75
        bar_w = bar_total_w / n_periods
        gap_w = group_w * 0.125

        metric_label = next((lab for key, lab, *_ in FIELDS if key == metric), metric)

        for vi, bv in enumerate(bvids):
            gx = ML + vi * group_w + gap_w
            title = self._get_video_title(bv)

            for pi, period in enumerate(PERIODS):
                row   = (data[bv].get(period) or {})
                val   = row.get(metric)
                color = PERIOD_COLORS[period]
                bx    = gx + pi * bar_w
                by    = to_y(val)
                bx2   = bx + bar_w - 2

                if val:
                    # 柱体
                    c.create_rectangle(bx, by, bx2, MT + ch,
                                       fill=color, outline="", stipple="")
                    # 数值标签
                    if by < MT + ch - 14:
                        c.create_text((bx + bx2) / 2, by - 4,
                                      text=fmt_axis(val),
                                      anchor="s", fill=color,
                                      font=("Consolas", 7, "bold"))
                else:
                    # 无数据占位
                    c.create_rectangle(bx, MT + ch - 4, bx2, MT + ch,
                                       fill=C["border"], outline="")

            # X 轴：视频标签
            label_x = gx + bar_total_w / 2
            c.create_text(label_x, MT + ch + 6, text=title,
                          anchor="n", fill=C["text_1"],
                          font=("Microsoft YaHei UI", 8), angle=30 if n_videos > 6 else 0)
            c.create_text(label_x, MT + ch + 22, text=bv,
                          anchor="n", fill=C["text_3"],
                          font=("Consolas", 7))

        # 图例
        legend_x = ML + 6
        for p in PERIODS:
            c.create_rectangle(legend_x, MT + ch + 52, legend_x + 10, MT + ch + 62,
                               fill=PERIOD_COLORS[p], outline="")
            c.create_text(legend_x + 14, MT + ch + 57,
                          text=f"投稿{p}后", anchor="w",
                          fill=PERIOD_COLORS[p], font=("Microsoft YaHei UI", 8))
            legend_x += 90

        # 图标题
        c.create_text(ML + cw // 2, 14,
                      text=f"投稿里程碑对比 — {metric_label}",
                      fill=C["text_1"], font=("Microsoft YaHei UI", 10, "bold"),
                      anchor="n")

        self._cmp_status.config(
            text=f"共 {n_videos} 个视频 · 展示指标：{metric_label}")
