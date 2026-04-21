"""
数据对比界面
选择2-5个已监控视频，在同一图表上对比播放量趋势
"""
import tkinter as tk
from tkinter import ttk, messagebox, LEFT, RIGHT, BOTH, X, Y
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from core.database import db
from ui.main_gui import C


CHART_COLORS = [
    ("#fb7299", "#ff8db5"),   # bilibili 粉
    ("#23ade5", "#4bbfea"),   # 蓝
    ("#42b983", "#66cba0"),   # 绿
    ("#f5a623", "#f7b84e"),   # 橙
    ("#9b59b6", "#b07cc6"),   # 紫
]

# 保留在末尾的区域 (像素)
_ML, _MR, _MT, _MB = 72, 24, 32, 40


class DataComparisonWindow:
    """数据对比窗口"""

    def __init__(self, parent=None,
                 monitored_videos: Optional[List[Dict]] = None,
                 history_data: Optional[Dict] = None,
                 video_dbs: Optional[Dict] = None):
        self.window = tk.Toplevel(parent)
        self.window.title("数据对比")
        self.window.geometry("960x680")
        self.window.transient(parent)

        self.monitored_videos = monitored_videos or []
        self.history_data     = history_data     or {}
        self.video_dbs        = video_dbs        or {}

        self._color_idx = 0
        self._chart_items = []       # canvas item ids for redraw
        self._selected: List[Dict] = []   # 选中的视频 dict 列表

        self._setup_ui()

    # ── UI ────────────────────────────────────────────
    def _setup_ui(self):
        # 顶部视频选择
        sel_frame = tk.LabelFrame(self.window, text="选择对比视频（2-5个）",
                                  padx=8, pady=6)
        sel_frame.pack(fill=X, padx=12, pady=(12, 4))

        list_frame = tk.Frame(sel_frame)
        list_frame.pack(fill=X)

        self.listbox = tk.Listbox(list_frame, selectmode=tk.MULTIPLE,
                                  height=5, exportselection=False)
        sb = ttk.Scrollbar(list_frame, orient="vertical",
                           command=self.listbox.yview)
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.pack(side=LEFT, fill=BOTH, expand=True)
        sb.pack(side=RIGHT, fill=Y)

        # 填充监控列表
        for v in self.monitored_videos:
            bvid  = v.get("bvid", "")
            title = v.get("title", "未知")[:40]
            self.listbox.insert(tk.END, f"{bvid}  {title}")

        btn_bar = tk.Frame(sel_frame)
        btn_bar.pack(fill=X, pady=(6, 0))
        ttk.Button(btn_bar, text="开始对比",
                   command=self._start_compare).pack(side=tk.LEFT, padx=4)

        # 图表
        chart_frame = tk.Frame(self.window)
        chart_frame.pack(fill=BOTH, expand=True, padx=12, pady=8)

        self.canvas = tk.Canvas(chart_frame, bg=C["canvas_bg"], highlightthickness=0)
        self.canvas.pack(fill=BOTH, expand=True)
        self.canvas.bind("<Configure>", lambda e: self._draw())

        # 图例
        self.legend_frame = tk.Frame(self.window)
        self.legend_frame.pack(fill=X, padx=16, pady=(0, 8))

    # ── 对比 ──────────────────────────────────────────
    def _start_compare(self):
        sel = self.listbox.curselection()
        if len(sel) < 2:
            messagebox.showwarning("提示", "请至少选择 2 个视频",
                                   parent=self.window)
            return
        if len(sel) > 5:
            messagebox.showwarning("提示", "最多选择 5 个视频",
                                   parent=self.window)
            return

        self._selected = [self.monitored_videos[i] for i in sel
                          if i < len(self.monitored_videos)]
        if len(self._selected) < 2:
            return

        # 尝试从 video_dbs 获取完整历史（比 history_data 更全）
        for video in self._selected:
            bvid = video.get("bvid", "")
            if bvid in self.video_dbs:
                try:
                    records = self.video_dbs[bvid].get_all_records()
                    if records:
                        self.history_data[bvid] = [
                            (row["timestamp"], row["view_count"])
                            for row in records
                        ]
                except Exception:
                    pass

        self._color_idx = 0
        self._draw()

    # ── 绘图 ──────────────────────────────────────────
    def _draw(self):
        c = self.canvas
        c.delete("all")
        # 清空图例
        for w in self.legend_frame.winfo_children():
            w.destroy()

        if len(self._selected) < 2:
            c.create_text(c.winfo_reqwidth() // 2 or 400, 40,
                          text="请选择至少 2 个视频后点击「开始对比」",
                          fill=C["text_2"], font=("Microsoft YaHei UI", 12))
            return

        W = c.winfo_width()
        H = c.winfo_height()
        if W < 100 or H < 100:
            return

        cw = W - _ML - _MR
        ch = H - _MT - _MB
        if cw < 50 or ch < 50:
            return

        # 收集所有数据点，统一时间轴
        series_map = {}   # bvid -> [(ts, views), ...]
        all_views = []
        all_ts = []

        for idx, video in enumerate(self._selected):
            bvid = video.get("bvid", "")
            raw = self.history_data.get(bvid, [])
            pts = []
            for item in raw:
                ts = item[0]
                views = item[1] if isinstance(item[1], (int, float)) else 0
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
                pts.append((ts, views))
                all_views.append(views)
                all_ts.append(ts)
            if pts:
                pts.sort(key=lambda p: p[0])
                series_map[bvid] = pts

        valid = [v for v in self._selected if v.get("bvid") in series_map]
        if len(valid) < 2:
            c.create_text(W // 2, H // 2,
                          text="所选视频的历史数据不足，无法对比",
                          fill=C["text_2"], font=("Microsoft YaHei UI", 12))
            return

        # 计算坐标范围
        min_ts = min(all_ts)
        max_ts = max(all_ts)
        max_view = max(all_views) if all_views else 1
        min_view = 0
        if max_view == min_view:
            max_view = min_view + 1

        ts_span = (max_ts - min_ts).total_seconds() or 1

        def to_x(ts):
            return _ML + (ts - min_ts).total_seconds() / ts_span * cw

        def to_y(v):
            return _MT + ch - (v - min_view) / (max_view - min_view) * ch

        def fmt_num(n):
            if n >= 1_0000_0000:
                return f"{n/1_0000_0000:.1f}亿"
            if n >= 1_0000:
                return f"{n/1_0000:.1f}万"
            return str(int(n))

        # 网格线
        for i in range(5):
            ratio = i / 4
            y = _MT + ch * (1 - ratio)
            val = min_view + (max_view - min_view) * ratio
            c.create_line(_ML, y, W - _MR, y, fill=C["grid_line"], dash=(2, 4))
            c.create_text(_ML - 6, y, text=fmt_num(val), anchor="e",
                          fill=C["text_2"], font=("Consolas", 9))

        # X 轴时间标签
        for i in range(5):
            ratio = i / 4
            ts = min_ts + timedelta(seconds=ts_span * ratio)
            x = _ML + cw * ratio
            label = ts.strftime("%m-%d %H:%M") if ts_span < 86400 * 7 \
                    else ts.strftime("%m-%d")
            c.create_text(x, H - _MB + 16, text=label,
                          fill=C["text_2"], font=("Consolas", 8))

        # 绘制每条线
        for idx, video in enumerate(valid):
            bvid  = video.get("bvid", "")
            title = video.get("title", bvid)[:20]
            pts   = series_map.get(bvid, [])
            if not pts:
                continue

            color = CHART_COLORS[idx % len(CHART_COLORS)][0]
            color_light = CHART_COLORS[idx % len(CHART_COLORS)][1]

            # 折线
            coords = []
            for ts, views in pts:
                coords.extend([to_x(ts), to_y(views)])
            if len(coords) >= 4:
                c.create_line(*coords, fill=color, width=2, smooth=True)

            # 面积填充
            if len(pts) >= 2:
                area_coords = list(coords)
                area_coords.extend([coords[-2], _MT + ch,
                                    coords[0], _MT + ch])
                c.create_polygon(*area_coords, fill=color_light,
                                 outline="", stipple="gray25")

            # 末端点 + 数值标签
            last_ts, last_v = pts[-1]
            lx, ly = to_x(last_ts), to_y(last_v)
            c.create_oval(lx - 4, ly - 4, lx + 4, ly + 4,
                          fill=color, outline=C["bg_base"], width=1)
            c.create_text(lx + 8, ly - 10, text=f"{fmt_num(last_v)}",
                          anchor="w", fill=color,
                          font=("Consolas", 9, "bold"))

            # 图例
            leg = tk.Frame(self.legend_frame)
            leg.pack(side=tk.LEFT, padx=12)
            tk.Canvas(leg, width=12, height=12, bg=color,
                      highlightthickness=0).pack(side=tk.LEFT, padx=(0, 4))
            tk.Label(leg, text=f"{title} ({bvid})",
                     font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
