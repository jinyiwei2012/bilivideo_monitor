"""
趋势图标签页 - 多视频折线图对比
"""

import tkinter as tk
from tkinter import ttk, messagebox, LEFT, RIGHT, BOTH, X, Y
from typing import List, Dict
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

from ui.theme import C
from .data_comparison import _fmt, PALETTE, PALETTE_LIGHT, METRICS, _ML, _MR, _MT, _MB


class TrendTab:
    """趋势折线图标签页"""

    def __init__(self, parent_frame, monitored_videos, history_data, video_dbs, window):
        self._parent = parent_frame
        self._monitored_videos = monitored_videos
        self._history_data = history_data
        self._video_dbs = video_dbs
        self._window = window

        self._selected: List[Dict] = []
        self._metric = tk.StringVar(value="view_count")
        self._listbox = None
        self._canvas = None
        self._legend = None
        self._valid_videos_cache = None

        self._build()

    # ── 构建UI ──────────────────────────────────────────────────────────────────
    def _build(self):
        f = self._parent

        # 顶栏
        top = tk.Frame(f)
        top.pack(fill=X, padx=10, pady=(8, 4))

        # 左：视频列表
        left = tk.LabelFrame(
            top,
            text="  选择视频（可多选）  ",
            padx=8,
            pady=4,
            fg=C.get("accent", "#58a6ff"),
            bg=C.get("bg_surface", "#161b22"),
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        left.pack(side=LEFT, fill=BOTH, expand=True)

        lf = tk.Frame(left)
        lf.pack(fill=BOTH, expand=True)
        self._listbox = tk.Listbox(
            lf,
            selectmode=tk.MULTIPLE,
            height=4,
            exportselection=False,
            bg=C.get("bg_base", "#0d1117"),
            fg=C.get("text_1", "#e6edf3"),
            selectbackground=C.get("bilibili_dim", "#c45a79"),
            selectforeground="#ffffff",
            font=("Microsoft YaHei UI", 10),
        )
        sb = ttk.Scrollbar(lf, orient="vertical", command=self._listbox.yview)
        self._listbox.config(yscrollcommand=sb.set)
        self._listbox.pack(side=LEFT, fill=BOTH, expand=True)
        sb.pack(side=RIGHT, fill=Y)
        for v in self._monitored_videos:
            title = v.get("title", "未知")[:35]
            self._listbox.insert(tk.END, f"  {v.get('bvid', '')}  {title}")

        # 右：指标 + 按钮
        right = tk.Frame(top, padx=10, pady=4, bg=C.get("bg_surface", "#161b22"))
        right.pack(side=RIGHT, padx=(10, 0), fill=Y)

        tk.Label(
            right,
            text="对比指标",
            font=("Microsoft YaHei UI", 9, "bold"),
            fg=C.get("accent", "#58a6ff"),
            bg=C.get("bg_surface", "#161b22"),
        ).pack(anchor="w")
        for key, label in METRICS:
            ttk.Radiobutton(right, text=label, variable=self._metric, value=key, command=self._draw).pack(anchor="w")

        ttk.Button(right, text="开始对比", command=self._start).pack(pady=(10, 0), fill=X)

        # 图表（加入背景卡片感）
        mid = tk.Frame(f, bg=C.get("bg_elevated", "#21262d"), padx=1, pady=1)
        mid.pack(fill=BOTH, expand=True, padx=10, pady=4)

        self._canvas = tk.Canvas(mid, bg=C.get("canvas_bg", "#0d1117"), highlightthickness=0)
        self._canvas.pack(fill=BOTH, expand=True, padx=4, pady=4)
        self._canvas.bind("<Configure>", lambda e: self._draw())

        # 图例（带背景色更有层次）
        leg_bg = tk.Frame(f, bg=C.get("bg_surface", "#161b22"), pady=4)
        leg_bg.pack(fill=X, padx=10, pady=(2, 4))
        self._legend = leg_bg

        # 初始提示
        self._canvas.after(
            100,
            lambda: self._canvas.create_text(
                self._canvas.winfo_width() // 2 or 400,
                120,
                text="请在上方选择视频后点击「开始对比」",
                fill=C.get("text_2", "#8b949e"),
                font=("Microsoft YaHei UI", 12),
            ),
        )

    # ── 开始 ────────────────────────────────────────────────────────────────────
    def _start(self):
        sel = self._listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请至少选择 1 个视频", parent=self._window)
            return
        if len(sel) > 8:
            messagebox.showwarning("提示", "最多对比 8 个视频", parent=self._window)
            return

        self._selected = [self._monitored_videos[i] for i in sel if i < len(self._monitored_videos)]

        # 加载历史数据
        self._metric.get()
        for video in self._selected:
            bvid = video.get("bvid", "")
            if bvid in self._video_dbs:
                try:
                    records = self._video_dbs[bvid].get_all_records()
                    if records:
                        self._history_data[bvid] = [(row["timestamp"], row["view_count"]) for row in records]
                except Exception as e:
                    logger.warning("加载 %s 历史数据失败: %s", bvid, e)

        self._draw()

    # ── 绘制 ────────────────────────────────────────────────────────────────────
    def _draw(self):
        """主绘图函数 - 绘制趋势折线图"""
        c = self._canvas
        c.delete("all")
        for w in self._legend.winfo_children():
            w.destroy()

        # 检查前置条件
        if not self._check_preconditions(c):
            return

        # 收集数据
        result = self._collect_data()
        if result is None:
            return
        series_map, all_vals, all_ts = result

        # 计算布局和坐标函数
        layout = self._calculate_layout(c, series_map, all_vals, all_ts)
        if layout is None:
            return
        W, H, cw, ch, min_ts, max_ts, max_val, to_x, to_y = layout

        # 绘制网格和坐标轴
        self._draw_grid_and_axes(c, W, H, cw, ch, min_ts, max_ts, max_val, to_x, to_y)

        # 绘制所有折线
        self._draw_all_lines(c, series_map, to_x, to_y, W, H, cw, ch)

    def _check_preconditions(self, c):
        """检查绘图的前置条件"""
        if not self._selected:
            c.create_text(
                c.winfo_width() // 2 or 400,
                100,
                text="请选择视频后点击「开始对比」",
                fill=C.get("text_2", "#8b949e"),
                font=("Microsoft YaHei UI", 12),
            )
            return False
        return True

    def _collect_data(self):
        """收集历史数据"""
        metric = self._metric.get()
        series_map = {}
        all_vals, all_ts = [], []

        for video in self._selected:
            bvid = video.get("bvid", "")
            raw = self._history_data.get(bvid, [])
            pts = []
            for item in raw:
                # item 可能是 (ts, view) 旧格式，也可能是 dict
                if isinstance(item, dict):
                    ts = item.get("timestamp", "")
                    val = item.get(metric, 0) or 0
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    ts = item[0]
                    val = item[1] if metric == "view_count" else 0
                else:
                    continue

                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts)
                    except Exception:
                        continue
                if not isinstance(ts, datetime):
                    try:
                        ts = datetime.fromtimestamp(float(ts))
                    except Exception:
                        continue

                try:
                    val = float(val) if val is not None else 0
                except (TypeError, ValueError):
                    val = 0

                pts.append((ts, val))
                all_vals.append(val)
                all_ts.append(ts)

            if pts:
                pts.sort(key=lambda p: p[0])
                series_map[bvid] = pts

        valid = [v for v in self._selected if v.get("bvid", "") in series_map]
        if not valid:
            c = self._canvas
            metric_label = next((lb for k, lb in METRICS if k == metric), metric)
            c.create_text(
                c.winfo_width() // 2 or 400,
                c.winfo_height() // 2 or 200,
                text=f"所选视频暂无「{metric_label}」历史数据",
                fill=C.get("text_2", "#8b949e"),
                font=("Microsoft YaHei UI", 12),
            )
            return None

        self._valid_videos_cache = valid
        return series_map, all_vals, all_ts

    def _calculate_layout(self, c, series_map, all_vals, all_ts):
        """计算布局和坐标映射函数"""
        W, H = c.winfo_width(), c.winfo_height()
        if W < 100 or H < 100:
            return None

        self._metric.get()
        cw = W - _ML - _MR
        ch = H - _MT - _MB

        # 坐标范围
        min_ts = min(all_ts)
        max_ts = max(all_ts)
        max_val = max(all_vals) if all_vals else 1
        min_val = 0
        if max_val == min_val:
            max_val = min_val + 1

        ts_span = (max_ts - min_ts).total_seconds() or 1

        def to_x(ts):
            return _ML + (ts - min_ts).total_seconds() / ts_span * cw

        def to_y(v):
            return _MT + ch - (v - min_val) / (max_val - min_val) * ch

        return W, H, cw, ch, min_ts, max_ts, max_val, to_x, to_y

    def _draw_grid_and_axes(self, c, W, H, cw, ch, min_ts, max_ts, max_val, to_x, to_y):
        """绘制网格和坐标轴"""
        metric = self._metric.get()
        metric_label = next((lb for k, lb in METRICS if k == metric), metric)

        # 标题
        c.create_text(
            W // 2,
            _MT // 2,
            text=f"对比指标：{metric_label}",
            fill=C.get("text_1", "#e6edf3"),
            font=("Microsoft YaHei UI", 11, "bold"),
        )

        # 网格
        n_grid = 5
        for i in range(n_grid + 1):
            ratio = i / n_grid
            y = _MT + ch * (1 - ratio)
            val = max_val * ratio
            c.create_line(_ML, y, W - _MR, y, fill=C.get("grid_line", "#21262d"), dash=(2, 4))
            c.create_text(_ML - 6, y, text=_fmt(val), anchor="e", fill=C.get("text_2", "#8b949e"), font=("Consolas", 9))

        # X 轴
        n_ticks = min(6, max(2, cw // 100))
        for i in range(n_ticks):
            ratio = i / (n_ticks - 1) if n_ticks > 1 else 0
            ts = min_ts + timedelta(seconds=(max_ts - min_ts).total_seconds() * ratio)
            x = _ML + cw * ratio
            label = (
                ts.strftime("%m-%d %H:%M") if (max_ts - min_ts).total_seconds() < 86400 * 7 else ts.strftime("%m-%d")
            )
            c.create_text(x, H - _MB + 16, text=label, fill=C.get("text_2", "#8b949e"), font=("Consolas", 8))

    def _draw_all_lines(self, c, series_map, to_x, to_y, W, H, cw, ch):
        """绘制所有折线"""
        valid = self._valid_videos_cache

        for idx, video in enumerate(valid):
            bvid = video.get("bvid", "")
            title = video.get("title", bvid)[:18]
            pts = series_map.get(bvid, [])
            if not pts:
                continue

            self._draw_single_line(c, idx, bvid, title, pts, to_x, to_y, W, H, cw, ch)

    def _draw_single_line(self, c, idx, bvid, title, pts, to_x, to_y, W, H, cw, ch):
        """绘制单条折线"""
        color = PALETTE[idx % len(PALETTE)]
        color_light = PALETTE_LIGHT[idx % len(PALETTE_LIGHT)]

        coords = []
        for ts, val in pts:
            coords.extend([to_x(ts), to_y(val)])

        if len(coords) >= 4:
            c.create_line(*coords, fill=color, width=2.2, smooth=True)

        if len(pts) >= 2:
            area = list(coords)
            area.extend([coords[-2], _MT + ch, coords[0], _MT + ch])
            c.create_polygon(*area, fill=color_light, outline="", stipple="gray25")

        last_ts, last_v = pts[-1]
        lx, ly = to_x(last_ts), to_y(last_v)
        c.create_oval(lx - 4, ly - 4, lx + 4, ly + 4, fill=color, outline=C.get("bg_base", "#0d1117"), width=1)
        c.create_text(lx + 8, ly - 10, text=_fmt(last_v), anchor="w", fill=color, font=("Consolas", 9, "bold"))

        # 图例
        self._create_legend_item(idx, bvid, title, color)

    def _create_legend_item(self, idx, bvid, title, color):
        """创建图例项"""
        leg = tk.Frame(self._legend, bg=C.get("bg_surface", "#161b22"))
        leg.pack(side=tk.LEFT, padx=10)
        tk.Canvas(leg, width=14, height=14, bg=color, highlightthickness=0).pack(side=LEFT, padx=(0, 3))
        tk.Label(
            leg, text=f"{title} ({bvid})", font=("Microsoft YaHei UI", 9), fg=color, bg=C.get("bg_surface", "#161b22")
        ).pack(side=LEFT)
