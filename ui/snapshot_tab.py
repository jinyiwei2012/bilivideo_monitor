"""
快照对比标签页 - 柱状图对比
"""

import tkinter as tk
from tkinter import ttk, messagebox, LEFT, RIGHT, BOTH, X, Y, BOTTOM
from typing import List, Dict
from datetime import datetime, timedelta
from collections import defaultdict
import logging

from core.database import get_db
from ui.theme import C
from .data_comparison import (
    _fmt,
    _parse_dt,
    PALETTE,
    METRICS,
    _BAR_ML,
    _BAR_MR,
    _BAR_MT,
    _BAR_MB,
    _blend,
    _darken,
    _draw_bar,
)

# 快照模块日志记录器
_snap_logger = logging.getLogger("data_comparison.snapshot")


class SnapshotTab:
    """快照对比标签页"""

    def __init__(self, parent_frame, monitored_videos, video_dbs, window):
        self._parent = parent_frame
        self._monitored_videos = monitored_videos
        self._video_dbs = video_dbs
        self._window = window

        self._selected: List[Dict] = []
        self._points: Dict[str, List] = {}  # bvid -> sorted records
        self._chosen_ts: Dict[str, List[str]] = {}  # bvid -> [ts_str, ...]
        self._ts_avail: List[str] = []  # 当前可用时间点列表
        self._ts_displayed: List[str] = []
        self._chosen_metrics_cache = None

        # 快照指标多选
        self._metric_vars = {key: tk.BooleanVar(value=(key == "view_count")) for key, _ in METRICS}
        self._use_milestone = tk.BooleanVar(value=True)

        # UI elements（先声明，_build 中赋值）
        self._listbox = None
        self._ts_listbox = None
        self._canvas = None
        self._legend = None
        self._status = None
        self._start_entry = None
        self._end_entry = None
        self._custom_btn = None
        self._quick_filter_btns = []

        self._build()

    # ── UI 构建 ──────────────────────────────────────────────────────────────────
    def _build(self):
        """构建快照对比标签页的完整 UI：控制区、视频选择、时间点选择、图表区"""
        f = self._parent
        f = self._parent

        # ── 顶部控制区 ──
        ctrl = tk.Frame(f)
        ctrl.pack(fill=X, padx=10, pady=(8, 4))

        # 左1：视频选择
        vbox = tk.LabelFrame(
            ctrl,
            text="  选择视频（可多选）  ",
            padx=8,
            pady=6,
            fg=C.get("accent", "#58a6ff"),
            bg=C.get("bg_surface", "#161b22"),
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        vbox.pack(side=LEFT, fill=BOTH, expand=True)

        vf = tk.Frame(vbox)
        vf.pack(fill=BOTH, expand=True)
        self._listbox = tk.Listbox(
            vf,
            selectmode=tk.MULTIPLE,
            height=4,
            exportselection=False,
            bg=C.get("bg_base", "#0d1117"),
            fg=C.get("text_1", "#e6edf3"),
            selectbackground=C.get("bilibili_dim", "#c45a79"),
            selectforeground="#ffffff",
            font=("Microsoft YaHei UI", 10),
        )
        sb2 = ttk.Scrollbar(vf, orient="vertical", command=self._listbox.yview)
        self._listbox.config(yscrollcommand=sb2.set)
        self._listbox.pack(side=LEFT, fill=BOTH, expand=True)
        sb2.pack(side=RIGHT, fill=Y)
        for v in self._monitored_videos:
            title = v.get("title", "未知")[:32]
            self._listbox.insert(tk.END, f"  {v.get('bvid', '')}  {title}")
        self._listbox.bind("<<ListboxSelect>>", self._on_video_select)

        # 左2：时间点选择
        tbox = tk.LabelFrame(
            ctrl,
            text="  选择时间点（可多选）  ",
            padx=8,
            pady=4,
            fg=C.get("accent", "#58a6ff"),
            bg=C.get("bg_surface", "#161b22"),
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        tbox.pack(side=LEFT, fill=BOTH, expand=True, padx=(8, 0))

        # 快捷筛选按钮行（胶囊风格）
        qf = tk.Frame(tbox, bg=C.get("bg_surface", "#161b22"))
        qf.pack(fill=X, pady=(0, 4))
        self._quick_filter_btns = []
        for label, key in [("最近1h", "1h"), ("今天", "today"), ("最近3天", "3d"), ("全部", "all")]:
            btn = tk.Label(
                qf,
                text=f"  {label}  ",
                font=("Microsoft YaHei UI", 8),
                fg=C.get("text_2", "#8b949e"),
                bg=C.get("bg_elevated", "#21262d"),
                cursor="hand2",
                relief="flat",
            )
            btn.pack(side=LEFT, padx=2)
            btn.bind("<Button-1>", lambda e, k=key: self._quick_filter(k))
            btn.bind("<Enter>", lambda e, b=btn: self._hover_btn(b, True))
            btn.bind("<Leave>", lambda e, b=btn: self._hover_btn(b, False))
            self._quick_filter_btns.append(btn)

        # 自定义时间范围输入
        cf = tk.Frame(tbox, bg=C.get("bg_surface", "#161b22"))
        cf.pack(fill=X, pady=(4, 4))

        tk.Label(
            cf,
            text="自定义范围:",
            font=("Microsoft YaHei UI", 8),
            fg=C.get("text_2", "#8b949e"),
            bg=C.get("bg_surface", "#161b22"),
        ).pack(side=LEFT, padx=(0, 4))

        self._start_entry = ttk.Entry(cf, width=16, font=("Consolas", 9))
        self._start_entry.insert(0, "YYYY-MM-DD HH:MM")
        self._start_entry.pack(side=LEFT, padx=2)
        self._start_entry.bind("<FocusIn>", lambda e: self._clear_placeholder(e, "YYYY-MM-DD HH:MM"))
        self._start_entry.bind("<FocusOut>", lambda e: self._add_placeholder(e, "YYYY-MM-DD HH:MM"))

        tk.Label(
            cf,
            text="至",
            font=("Microsoft YaHei UI", 8),
            fg=C.get("text_2", "#8b949e"),
            bg=C.get("bg_surface", "#161b22"),
        ).pack(side=LEFT, padx=4)

        self._end_entry = ttk.Entry(cf, width=16, font=("Consolas", 9))
        self._end_entry.insert(0, "YYYY-MM-DD HH:MM")
        self._end_entry.pack(side=LEFT, padx=2)
        self._end_entry.bind("<FocusIn>", lambda e: self._clear_placeholder(e, "YYYY-MM-DD HH:MM"))
        self._end_entry.bind("<FocusOut>", lambda e: self._add_placeholder(e, "YYYY-MM-DD HH:MM"))

        self._custom_btn = ttk.Button(cf, text="应用", width=6, command=self._apply_custom_range)
        self._custom_btn.pack(side=LEFT, padx=4)

        tf = tk.Frame(tbox)
        tf.pack(fill=BOTH, expand=True)
        self._ts_listbox = tk.Listbox(
            tf,
            selectmode=tk.MULTIPLE,
            height=4,
            exportselection=False,
            bg=C.get("bg_base", "#0d1117"),
            fg=C.get("text_1", "#e6edf3"),
            selectbackground=C.get("bilibili_dim", "#c45a79"),
            selectforeground="#ffffff",
            font=("Consolas", 10),
        )
        sb3 = ttk.Scrollbar(tf, orient="vertical", command=self._ts_listbox.yview)
        self._ts_listbox.config(yscrollcommand=sb3.set)
        self._ts_listbox.pack(side=LEFT, fill=BOTH, expand=True)
        sb3.pack(side=RIGHT, fill=Y)

        tip = tk.Label(
            tbox,
            text="↑ 选视频后自动加载（智能采样）  |  快捷按钮可快速筛选  |  或自行输入范围筛选",
            font=("Microsoft YaHei UI", 8),
            fg=C.get("text_3", "#484f58"),
        )
        tip.pack(anchor="w")

        # 右：指标 + 按钮
        rbox = tk.Frame(ctrl, padx=10, pady=4, bg=C.get("bg_surface", "#161b22"))
        rbox.pack(side=RIGHT, padx=(10, 0), fill=Y)

        tk.Label(
            rbox,
            text="对比指标（可多选）",
            font=("Microsoft YaHei UI", 9, "bold"),
            fg=C.get("accent", "#58a6ff"),
            bg=C.get("bg_surface", "#161b22"),
        ).pack(anchor="w")
        for key, label in METRICS:
            ttk.Checkbutton(rbox, text=label, variable=self._metric_vars[key], command=self._draw).pack(anchor="w")

        # 里程碑来源选项
        ttk.Checkbutton(rbox, text="叠加里程碑数据", variable=self._use_milestone, command=self._draw).pack(
            anchor="w", pady=(4, 0)
        )

        ttk.Button(rbox, text="生成对比图", command=self._compare).pack(pady=(10, 4), fill=X)
        ttk.Button(rbox, text="清空选择", command=self._clear).pack(fill=X)

        # ── 图表区（加入内边距和背景卡片感）───
        chart_area = tk.Frame(f, bg=C.get("bg_elevated", "#21262d"), padx=1, pady=1)
        chart_area.pack(fill=BOTH, expand=True, padx=10, pady=4)

        # 横向滚动
        h_scroll = ttk.Scrollbar(chart_area, orient="horizontal")
        h_scroll.pack(side=BOTTOM, fill=X)

        self._canvas = tk.Canvas(
            chart_area, bg=C.get("canvas_bg", "#0d1117"), highlightthickness=0, xscrollcommand=h_scroll.set
        )
        self._canvas.pack(fill=BOTH, expand=True, padx=4, pady=4)
        h_scroll.config(command=self._canvas.xview)
        self._canvas.bind("<Configure>", lambda e: self._draw())

        # 图例区（带底部分隔线，更有层次）
        leg_bg = tk.Frame(f, bg=C.get("bg_surface", "#161b22"), pady=4)
        leg_bg.pack(fill=X, padx=10, pady=(2, 4))
        self._legend = leg_bg

        # 状态标签
        self._status = tk.Label(
            f, text="", font=("Microsoft YaHei UI", 9), fg=C.get("text_2", "#8b949e"), bg=C.get("bg_base", "#0d1117")
        )
        self._status.pack(anchor="w", padx=12, pady=(0, 4))

    # ── 快捷按钮悬停效果 ────────────────────────────────────────────────────
    @staticmethod
    def _hover_btn(btn: tk.Label, enter: bool):
        """鼠标悬停/离开快捷筛选按钮时的颜色变化效果"""
        if enter:
        if enter:
            btn.configure(fg=C.get("bilibili", "#fb7299"), bg=C.get("bg_hover", "#30363d"))
        else:
            btn.configure(fg=C.get("text_2", "#8b949e"), bg=C.get("bg_elevated", "#21262d"))

    # ── 视频选中回调 ────────────────────────────────────────────────────────
    def _on_video_select(self, event=None):
        """选中视频后加载历史时间点到下拉列表，超过 50 个点则智能采样"""
        sel = self._listbox.curselection()
        sel = self._listbox.curselection()
        if not sel:
            return

        # 加载所有被选视频的历史记录
        all_ts_set = set()
        for i in sel:
            if i >= len(self._monitored_videos):
                continue
            bvid = self._monitored_videos[i].get("bvid", "")
            if bvid not in self._points:
                self._load_records(bvid)
            for rec in self._points.get(bvid, []):
                ts = rec.get("timestamp", "")
                if ts:
                    all_ts_set.add(str(ts)[:16])

        # 智能采样：按日期分组，每组保留关键时间点
        ts_list = sorted(all_ts_set, reverse=True)

        self._ts_listbox.delete(0, tk.END)
        self._ts_avail = ts_list  # 全量（供快捷筛选用）

        # 不再默认全选，由用户自行选择
        self._ts_displayed = self._smart_sample(ts_list) if len(ts_list) > 50 else ts_list

        for ts in self._ts_displayed:
            self._ts_listbox.insert(tk.END, ts)

    def _clear_placeholder(self, event, placeholder):
        """清除自定义时间输入框的占位符文本"""
        entry = event.widget
        if entry.get() == placeholder:
            entry.delete(0, tk.END)
            entry.configure(foreground=C.get("text_1", "#e6edf3"))

    def _add_placeholder(self, event, placeholder):
        """输入框中无内容时恢复占位符"""
        entry = event.widget
        if not entry.get().strip():
            entry.insert(0, placeholder)
            entry.configure(foreground=C.get("text_3", "#484f58"))

    def _apply_custom_range(self):
        """应用自定义时间范围筛选"""
        all_ts = self._ts_avail
        if not all_ts:
            messagebox.showwarning("提示", "请先选择视频加载时间点", parent=self._window)
            return

        start_str, end_str = self._get_range_input()
        if not start_str and not end_str:
            messagebox.showwarning("提示", "请输入至少一个时间范围", parent=self._window)
            return

        start_dt, end_dt = self._parse_custom_range_dates(start_str, end_str)

        self._validate_custom_range_bounds(start_dt, end_dt, all_ts)

        filtered = self._filter_custom_timestamps(all_ts, start_dt, end_dt)
        if not filtered:
            messagebox.showwarning("提示", "没有符合条件的时间点", parent=self._window)
            return

        self._ts_listbox.delete(0, tk.END)
        self._ts_displayed = filtered
        for ts in filtered:
            self._ts_listbox.insert(tk.END, ts)

        _snap_logger.info(f"[快照-自定义范围] 筛选结果: {len(filtered)} 个时间点")

    def _get_range_input(self):
        """获取并清洗用户输入的时间范围。返回 (start_str, end_str)。"""
        start_str = self._start_entry.get().strip()
        end_str = self._end_entry.get().strip()
        if start_str in ("YYYY-MM-DD HH:MM", ""):
            start_str = None
        if end_str in ("YYYY-MM-DD HH:MM", ""):
            end_str = None
        return start_str, end_str

    def _parse_custom_range_dates(self, start_str, end_str):
        """解析起始/结束时间字符串为 datetime 对象。返回 (start_dt, end_dt)。"""
        start_dt = None
        end_dt = None
        try:
            if start_str:
                start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M")
        except ValueError:
            try:
                start_dt = datetime.strptime(start_str, "%Y-%m-%d")
            except ValueError:
                pass

        try:
            if end_str:
                end_dt = datetime.strptime(end_str, "%Y-%m-%d %H:%M")
        except ValueError:
            try:
                end_dt = datetime.strptime(end_str, "%Y-%m-%d")
            except ValueError:
                pass
        return start_dt, end_dt

    def _validate_custom_range_bounds(self, start_dt, end_dt, all_ts):
        """校验输入范围是否在数据范围内，超限时弹出警告。"""
        first_ts = _parse_dt(all_ts[0]) if all_ts else None
        last_ts = _parse_dt(all_ts[-1]) if all_ts else None

        out_of_range = []
        if start_dt and first_ts and start_dt < first_ts:
            start_str = self._start_entry.get().strip()
            out_of_range.append(f"起始时间 {start_str} 早于数据最早时间 {all_ts[-1]}")
            _snap_logger.warning(f"[快照-自定义范围] 起始时间超出范围: 输入={start_str}, 数据最小={all_ts[-1]}")
        if end_dt and last_ts and end_dt > last_ts:
            end_str = self._end_entry.get().strip()
            out_of_range.append(f"结束时间 {end_str} 晚于数据最新时间 {all_ts[0]}")
            _snap_logger.warning(f"[快照-自定义范围] 结束时间超出范围: 输入={end_str}, 数据最大={all_ts[0]}")

        if out_of_range:
            warning_msg = "输入时间超出数据范围，已自动调整为有效范围：\n\n"
            warning_msg += "\n".join(out_of_range)
            warning_msg += f"\n\n有效范围: {all_ts[-1]} ~ {all_ts[0]}"
            messagebox.showwarning("⚠️ 范围超限", warning_msg, parent=self._window)

    def _filter_custom_timestamps(self, all_ts, start_dt, end_dt):
        """根据时间范围筛选时间点列表。返回筛选后的列表。"""
        filtered = []
        for ts_str in all_ts:
            ts_dt = _parse_dt(ts_str)
            if not ts_dt:
                continue
            if start_dt and ts_dt < start_dt:
                continue
            if end_dt and ts_dt > end_dt:
                continue
            filtered.append(ts_str)
        return filtered

    def _smart_sample(self, ts_list, max_per_day=8):
        """智能采样：每天最多保留 max_per_day 个时间点，均匀抽取"""
        if len(ts_list) <= 20:
        if len(ts_list) <= 20:
            return ts_list

        # 按日期分组
        day_groups = defaultdict(list)
        for ts in ts_list:
            day = ts[:10]
            day_groups[day].append(ts)

        result = []
        for day in sorted(day_groups.keys(), reverse=True):
            day_ts = day_groups[day]
            if len(day_ts) <= max_per_day:
                result.extend(day_ts)
            else:
                # 均匀采样
                step = len(day_ts) / max_per_day
                sampled = [day_ts[int(i * step)] for i in range(max_per_day)]
                # 确保首尾都有
                if day_ts[0] not in sampled:
                    sampled[0] = day_ts[0]
                if day_ts[-1] not in sampled:
                    sampled[-1] = day_ts[-1]
                result.extend(sorted(sampled, reverse=True))

        return result

    def _resolve_quick_filter_ref(self, all_ts):
        """解析快捷筛选的参考时间（取最新时间点的解析结果）"""
        now = _parse_dt(all_ts[0])
        if not now:
            _snap_logger.warning("无法解析时间戳: %s，使用当前时间", all_ts[0])
            now = datetime.now()
        return now

    def _apply_quick_filter(self, mode, all_ts, now):
        """根据快捷筛选模式过滤时间点列表（最近1h/今天/最近3天/全部）"""
        filters = {
            "1h": lambda: [ts for ts in all_ts if _parse_dt(ts) and _parse_dt(ts) >= now - timedelta(hours=1)],
            "3d": lambda: [ts for ts in all_ts if _parse_dt(ts) and _parse_dt(ts) >= now - timedelta(days=3)],
            "today": lambda: [ts for ts in all_ts if ts.startswith(now.strftime("%Y-%m-%d"))],
        }
        fn = filters.get(mode)
        if fn:
            return fn()
        return self._smart_sample(all_ts) if len(all_ts) > 50 else all_ts

    def _quick_filter(self, mode):
        """应用快捷时间筛选按钮，更新时间点列表"""
        all_ts = self._ts_avail
        if not all_ts:
            return

        now = self._resolve_quick_filter_ref(all_ts)
        filtered = self._apply_quick_filter(mode, all_ts, now)

        if not filtered:
            return

        self._ts_listbox.delete(0, tk.END)
        self._ts_displayed = filtered
        for ts in filtered:
            self._ts_listbox.insert(tk.END, ts)

    def _load_records(self, bvid: str):
        """从 video_dbs 加载某视频的完整历史记录，存入 _points"""
        if bvid in self._video_dbs:
        if bvid in self._video_dbs:
            try:
                records = self._video_dbs[bvid].get_all_records()
                if records:
                    self._points[bvid] = sorted([dict(r) for r in records], key=lambda r: r.get("timestamp", ""))
                    return
            except Exception as e:
                _snap_logger.warning("加载 %s 历史记录失败: %s", bvid, e)
        self._points[bvid] = []

    # ── 生成对比图 ──────────────────────────────────────────────────────────────
    def _compare(self):
        """从当前选中项生成快照对比图"""
        sel_v = self._listbox.curselection()
        sel_ts = self._ts_listbox.curselection()

        if not sel_v:
            messagebox.showwarning("提示", "请选择至少 1 个视频", parent=self._window)
            return
        if not sel_ts:
            messagebox.showwarning("提示", "请选择至少 1 个时间点", parent=self._window)
            return

        chosen_videos = [self._monitored_videos[i] for i in sel_v if i < len(self._monitored_videos)]
        chosen_ts = [self._ts_listbox.get(i) for i in sel_ts]

        self._selected = chosen_videos
        self._chosen_ts = {v.get("bvid", ""): chosen_ts for v in chosen_videos}

        self._draw()

    # ── 清空 ────────────────────────────────────────────────────────────────────
    def _clear(self):
        """清空所有选择和数据"""
        self._selected = []
        self._chosen_ts = {}
        self._ts_listbox.selection_clear(0, tk.END)
        self._listbox.selection_clear(0, tk.END)
        self._draw()

    # ── 绘图 ────────────────────────────────────────────────────────────────────
    def _draw(self):
        """主绘图函数：清空画布、收集数据、计算布局、绘制所有指标和状态"""
        c = self._canvas
        c = self._canvas
        c.delete("all")
        for w in self._legend.winfo_children():
            w.destroy()
        self._status.config(text="")

        # 检查前置条件
        if not self._check_preconditions(c):
            return

        # 收集数据
        all_metric_bars, total_data = self._collect_data()
        if total_data == 0:
            cw = c.winfo_width() or 500
            c.create_text(
                cw // 2,
                120,
                text="所选视频/时间点下无数据",
                fill=C.get("text_2", "#8b949e"),
                font=("Microsoft YaHei UI", 12),
            )
            return

        # 计算布局
        chosen_metrics, section_H, all_section_widths, max_section_W, real_W = self._calculate_layout(all_metric_bars)

        # 绘制所有指标
        use_milestone = self._use_milestone.get()
        self._draw_all_metrics(c, chosen_metrics, all_metric_bars, section_H, max_section_W, real_W, use_milestone)

        # 更新状态
        self._update_status(chosen_metrics)

    def _check_preconditions(self, c):
        """检查绘图的前置条件"""
        if not self._selected:
            cw = c.winfo_width() or 500
            c.create_text(
                cw // 2,
                120,
                text="请选择视频和时间点后点击「生成对比图」",
                fill=C.get("text_2", "#8b949e"),
                font=("Microsoft YaHei UI", 12),
            )
            return False

        # 获取所有勾选的指标
        chosen_metrics = [key for key, var in self._metric_vars.items() if var.get()]
        if not chosen_metrics:
            cw = c.winfo_width() or 500
            c.create_text(
                cw // 2,
                120,
                text="请至少选择一个对比指标",
                fill=C.get("text_2", "#8b949e"),
                font=("Microsoft YaHei UI", 12),
            )
            return False

        self._chosen_metrics_cache = chosen_metrics
        return True

    def _collect_data(self):
        """收集所有已选视频的历史数据和里程碑数据，返回 (all_metric_bars, total_data)"""
        use_milestone = self._use_milestone.get()
        use_milestone = self._use_milestone.get()
        milestone_data = get_db().get_all_milestones_grouped() if use_milestone else {}

        # 对每个视频×每个指标收集 bars
        all_metric_bars = {}  # metric_key -> [ {bvid, title, ts, value, source} ]
        for video in self._selected:
            bvid = video.get("bvid", "")
            title = video.get("title", bvid)[:14]
            recs = self._points.get(bvid, [])
            chosen_ts = self._chosen_ts.get(bvid, [])

            # 收集历史数据
            self._collect_history_data(video, bvid, title, recs, chosen_ts, all_metric_bars)

            # 收集里程碑数据
            if use_milestone and bvid in milestone_data:
                self._collect_milestone_data(bvid, title, milestone_data[bvid], all_metric_bars)

        # 检查是否有数据
        total_data = sum(len(v) for v in all_metric_bars.values())
        return all_metric_bars, total_data

    def _collect_history_data(self, video, bvid, title, recs, chosen_ts, all_metric_bars):
        """收集历史记录中各时间点的指标数据"""
        chosen_metrics = self._chosen_metrics_cache
        chosen_metrics = self._chosen_metrics_cache
        for ts_str in sorted(chosen_ts):
            best_rec = self._find_best_record(recs, ts_str)

            if best_rec is not None:
                for metric in chosen_metrics:
                    raw_val = best_rec.get(metric, None)
                    try:
                        val = float(raw_val) if raw_val is not None else 0
                    except (TypeError, ValueError):
                        val = 0
                    all_metric_bars.setdefault(metric, []).append(
                        {"bvid": bvid, "title": title, "ts": ts_str, "value": val, "source": "history"}
                    )

    def _find_best_record(self, recs, ts_str):
        """找到与目标时间最匹配的记录：先精确匹配，再找 5 分钟内的最近记录"""
        best_rec = None
        best_rec = None
        for rec in recs:
            rec_ts = str(rec.get("timestamp", ""))[:16]
            if rec_ts == ts_str[:16]:
                best_rec = rec
                break
        if best_rec is None:
            target_dt = _parse_dt(ts_str)
            if target_dt:
                best, best_diff = None, float("inf")
                for rec in recs:
                    rdt = _parse_dt(str(rec.get("timestamp", "")))
                    if rdt:
                        diff = abs((rdt - target_dt).total_seconds())
                        if diff < best_diff:
                            best_diff, best = diff, rec
                if best and best_diff < 300:
                    best_rec = best
        return best_rec

    def _collect_milestone_data(self, bvid, title, milestone_periods, all_metric_bars):
        """收集里程碑各周期的指标数据"""
        chosen_metrics = self._chosen_metrics_cache
        chosen_metrics = self._chosen_metrics_cache
        for period, row in milestone_periods.items():
            for metric in chosen_metrics:
                raw_val = row.get(metric, None)
                try:
                    val = float(raw_val) if raw_val is not None else 0
                except (TypeError, ValueError):
                    val = 0
                if val and val > 0:
                    all_metric_bars.setdefault(metric, []).append(
                        {"bvid": bvid, "title": title, "ts": f"里程碑·{period}", "value": val, "source": "milestone"}
                    )

    def _calculate_layout(self, all_metric_bars):
        """计算画布布局和每组柱状图的绘制参数"""
        c = self._canvas
        c = self._canvas
        chosen_metrics = self._chosen_metrics_cache

        canvas_H = c.winfo_height() or 400
        if canvas_H < 150:
            canvas_H = 400

        n_metrics = len(chosen_metrics)
        section_H = canvas_H / n_metrics  # 每个指标的垂直分区

        all_section_widths = []  # 每个指标区的宽度

        for m_idx, metric in enumerate(chosen_metrics):
            bars = all_metric_bars.get(metric, [])
            if not bars:
                all_section_widths.append(0)
                continue

            # 按 bvid 分组
            bvid_order = [v.get("bvid", "") for v in self._selected]
            groups = []
            seen = set()
            for bv in bvid_order:
                if bv in seen:
                    continue
                seen.add(bv)
                g_bars = [b for b in bars if b["bvid"] == bv]
                if g_bars:
                    groups.append({"bvid": bv, "title": g_bars[0]["title"], "bars": g_bars})

            total_bars = len(bars)
            BAR_W = max(20, min(50, 700 // max(total_bars, 1)))
            GROUP_GAP = max(BAR_W, 20)
            inner_gap = max(2, BAR_W // 8)

            group_widths = [len(g["bars"]) * (BAR_W + inner_gap) - inner_gap for g in groups]
            sec_W = sum(group_widths) + GROUP_GAP * (len(groups) - 1) + GROUP_GAP + _BAR_MR
            all_section_widths.append(sec_W)

            # 保存绘图参数
            all_metric_bars[metric] = {
                "groups": groups,
                "BAR_W": BAR_W,
                "GROUP_GAP": GROUP_GAP,
                "inner_gap": inner_gap,
                "group_widths": group_widths,
                "total_bars": total_bars,
            }

        max_section_W = max(all_section_widths) if all_section_widths else 500
        real_W = max(_BAR_ML + max_section_W + 10, c.winfo_width() or 500)
        c.config(scrollregion=(0, 0, real_W, canvas_H))

        return chosen_metrics, section_H, all_section_widths, max_section_W, real_W

    def _draw_all_metrics(self, c, chosen_metrics, all_metric_bars, section_H, max_section_W, real_W, use_milestone):
        """绘制所有选定指标的柱状图"""
        for m_idx, metric in enumerate(chosen_metrics):
        for m_idx, metric in enumerate(chosen_metrics):
            metric_label = next((lb for k, lb in METRICS if k == metric), metric)
            data = all_metric_bars.get(metric)
            if not isinstance(data, dict):
                continue

            groups = data["groups"]
            BAR_W = data["BAR_W"]
            GROUP_GAP = data["GROUP_GAP"]
            inner_gap = data["inner_gap"]
            data["total_bars"]

            if not groups:
                continue

            sec_y0 = m_idx * section_H
            chart_H = section_H - _BAR_MT - _BAR_MB
            if chart_H < 60:
                chart_H = 60

            all_vals = [b["value"] for g in groups for b in g["bars"] if b["value"] is not None]
            if not all_vals:
                continue
            max_val = max(all_vals) * 1.12 or 1

            def val_to_y(v, _sec_y0=sec_y0, _chart_H=chart_H, _max_val=max_val):
                return _sec_y0 + _BAR_MT + _chart_H - max(0, v) / _max_val * _chart_H

            # 绘制网格和坐标轴
            self._draw_grid_and_axes(c, m_idx, sec_y0, chart_H, max_val, max_section_W, metric_label)

            # 绘制条形图
            x_cursor = _BAR_ML + GROUP_GAP // 2
            legend_added = set()
            x_cursor = self._draw_bars(
                c,
                groups,
                x_cursor,
                BAR_W,
                GROUP_GAP,
                inner_gap,
                sec_y0,
                section_H,
                chart_H,
                val_to_y,
                max_section_W,
                m_idx,
                legend_added,
            )

        # 绘制里程碑图例
        if use_milestone:
            self._create_milestone_legend()

    def _draw_grid_and_axes(self, c, m_idx, sec_y0, chart_H, max_val, max_section_W, metric_label):
        """绘制当前指标区的网格线、Y 轴刻度和指标标题"""
        # 分隔线
        if m_idx > 0:
        # 分隔线
        if m_idx > 0:
            c.create_line(
                _BAR_ML, sec_y0, max_section_W - _BAR_MR, sec_y0, fill=C.get("border", "#30363d"), dash=(6, 4), width=1
            )

        # 网格 + Y轴刻度
        n_grid = 4
        for i in range(n_grid + 1):
            ratio = i / n_grid
            y = sec_y0 + _BAR_MT + chart_H * (1 - ratio)
            val = max_val * ratio
            c.create_line(_BAR_ML, y, _BAR_ML + max_section_W, y, fill=C.get("grid_line", "#21262d"), dash=(2, 4))
            c.create_text(
                _BAR_ML - 6, y, text=_fmt(val), anchor="e", fill=C.get("text_2", "#8b949e"), font=("Consolas", 8)
            )

        # 指标标题
        c.create_text(
            _BAR_ML + 10,
            sec_y0 + _BAR_MT // 2 + 4,
            text=metric_label,
            anchor="w",
            fill=C.get("text_1", "#e6edf3"),
            font=("Microsoft YaHei UI", 10, "bold"),
        )

        # X 轴线
        c.create_line(
            _BAR_ML,
            sec_y0 + _BAR_MT + chart_H,
            _BAR_ML + max_section_W,
            sec_y0 + _BAR_MT + chart_H,
            fill=C.get("text_2", "#8b949e"),
        )

    def _draw_bars(
        self,
        c,
        groups,
        x_cursor,
        BAR_W,
        GROUP_GAP,
        inner_gap,
        sec_y0,
        section_H,
        chart_H,
        val_to_y,
        max_section_W,
        m_idx,
        legend_added,
    ):
        """遍历所有分组绘制柱状条、数值标签和图例"""
        for g_idx, group in enumerate(groups):
        for g_idx, group in enumerate(groups):
            bvid = group["bvid"]
            title = group["title"]
            bars = group["bars"]
            g_color = PALETTE[g_idx % len(PALETTE)]

            g_center = x_cursor + (len(bars) * (BAR_W + inner_gap) - inner_gap) // 2
            c.create_text(
                g_center,
                sec_y0 + section_H - _BAR_MB + 20,
                text=f"{title}",
                fill=g_color,
                font=("Microsoft YaHei UI", 8, "bold"),
            )

            for b_idx, bar in enumerate(bars):
                val = bar["value"] or 0
                ts_lbl = bar["ts"]
                source = bar["source"]

                # 里程碑数据使用深色柱，历史数据使用渐变色柱
                if source == "milestone":
                    bar_color = _darken(g_color, 0.75)
                    bar_color2 = _darken(g_color, 0.55)
                else:
                    ratio = b_idx / max(len(bars) - 1, 1)
                    bar_color = _blend(g_color, "#ffffff", 0.15 + ratio * 0.2)
                    bar_color2 = g_color

                x0 = x_cursor
                x1 = x0 + BAR_W
                y0 = val_to_y(val)
                y1 = sec_y0 + _BAR_MT + chart_H

                _draw_bar(c, x0, y0, x1, y1, bar_color, bar_color2)

                if val > 0:
                    c.create_text(
                        (x0 + x1) // 2,
                        max(y0 - 5, sec_y0 + _BAR_MT + 8),
                        text=_fmt(val),
                        anchor="s",
                        fill=C.get("text_1", "#e6edf3"),
                        font=("Consolas", 7, "bold"),
                    )

                short_ts = ts_lbl[-5:] if len(ts_lbl) > 5 else ts_lbl
                if source == "milestone":
                    short_ts = ts_lbl.replace("里程碑·", "")
                c.create_text(
                    (x0 + x1) // 2,
                    sec_y0 + _BAR_MT + chart_H + 8,
                    text=short_ts,
                    fill=C.get("text_2", "#8b949e"),
                    font=("Consolas", 7),
                )

                x_cursor += BAR_W + inner_gap

            x_cursor += GROUP_GAP

            # 图例
            if m_idx == 0 and bvid not in legend_added:
                legend_added.add(bvid)
                self._create_legend_item(bvid, title, g_color)

        return x_cursor

    def _create_legend_item(self, bvid, title, g_color):
        """创建单个视频的图例项（色块 + 标题 + BV 号）"""
        leg = tk.Frame(self._legend, bg=C.get("bg_surface", "#161b22"))
        leg = tk.Frame(self._legend, bg=C.get("bg_surface", "#161b22"))
        leg.pack(side=LEFT, padx=10)
        tk.Canvas(leg, width=14, height=14, bg=g_color, highlightthickness=0).pack(side=LEFT, padx=(0, 3))
        tk.Label(
            leg, text=f"{title} ({bvid})", font=("Microsoft YaHei UI", 9), fg=g_color, bg=C.get("bg_surface", "#161b22")
        ).pack(side=LEFT)

    def _create_milestone_legend(self):
        """创建「里程碑（深色柱）」图例项"""
        leg2 = tk.Frame(self._legend, bg=C.get("bg_surface", "#161b22"))
        leg2 = tk.Frame(self._legend, bg=C.get("bg_surface", "#161b22"))
        leg2.pack(side=LEFT, padx=10)
        c2 = tk.Canvas(leg2, width=14, height=14, bg=C.get("bg_surface", "#161b22"), highlightthickness=0)
        c2.pack(side=LEFT, padx=(0, 3))
        c2.create_rectangle(2, 4, 12, 12, fill="#888888", outline="")
        tk.Label(
            leg2,
            text="里程碑（深色柱）",
            font=("Microsoft YaHei UI", 9),
            fg=C.get("text_2", "#8b949e"),
            bg=C.get("bg_surface", "#161b22"),
        ).pack(side=LEFT)

    def _update_status(self, chosen_metrics):
        """更新状态栏显示：视频数、数据条数、当前指标"""
        collected, _ = self._collect_data()
        collected, _ = self._collect_data()
        total_data = sum(len(v) for v in collected.values())
        metric_labels = ", ".join(next((lb for k, lb in METRICS if k == m), m) for m in chosen_metrics)
        self._status.config(text=f"共 {len(self._selected)} 个视频，{total_data} 条数据，指标：{metric_labels}")
