"""
播放量交叉计算界面
基于历史数据预测多个视频播放量的交会时间
"""
import tkinter as tk
from tkinter import ttk, messagebox, LEFT, RIGHT, BOTH, X, Y, W
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import math

from core.database import db

# 图表边距
_ML, _MR, _MT, _MB = 72, 24, 32, 40

LINE_COLORS = [
    ("#fb7299", "#ff8db5"),
    ("#23ade5", "#4bbfea"),
    ("#42b983", "#66cba0"),
    ("#f5a623", "#f7b84e"),
    ("#9b59b6", "#b07cc6"),
]


def _fmt_num(n):
    if n >= 1_0000_0000:
        return f"{n / 1_0000_0000:.2f}亿"
    if n >= 1_0000:
        return f"{n / 1_0000:.1f}万"
    return str(int(n))


def _parse_ts(ts) -> Optional[datetime]:
    """将各种时间格式统一为 datetime"""
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            pass
        try:
            return datetime.fromtimestamp(float(ts))
        except Exception:
            pass
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts))
        except Exception:
            pass
    return None


def _linear_fit(points: List[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    """最小二乘线性拟合，返回 (斜率k, 截距b)，x 为距第一个点的小时数"""
    n = len(points)
    if n < 2:
        return None
    sx = sy = sxx = sxy = 0
    for x, y in points:
        sx += x
        sy += y
        sxx += x * x
        sxy += x * y
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-12:
        return None
    k = (n * sxy - sx * sy) / denom
    b = (sy - k * sx) / n
    return (k, b)


def _find_crossover(slope_a: float, intercept_a: float,
                    slope_b: float, intercept_b: float,
                    offset_hours: float) -> Optional[float]:
    """
    求两条线的交点。
    线A: y = slope_a * t + intercept_a  (t=0 对应视频A第一个数据点)
    线B: y = slope_b * (t - offset_hours) + intercept_b  (有偏移)
    返回交点距视频A第一个数据点的小时数，None 表示不相交。
    """
    # y = ka*t + ba = kb*(t - off) + bb
    # ka*t + ba = kb*t - kb*off + bb
    # (ka - kb)*t = bb - ba - kb*off
    denom = slope_a - slope_b
    if abs(denom) < 1e-12:
        return None
    t = (intercept_b - intercept_a - slope_b * (-offset_hours)) / denom
    if t > 0:
        return t
    return None


class CrossoverAnalysisWindow:
    """交叉计算窗口"""

    def __init__(self, parent=None,
                 monitored_videos: Optional[List[Dict]] = None,
                 history_data: Optional[Dict] = None,
                 video_dbs: Optional[Dict] = None):
        self.window = tk.Toplevel(parent)
        self.window.title("播放量交叉计算")
        self.window.geometry("1020x720")
        self.window.transient(parent)

        self.monitored_videos = monitored_videos or []
        self.history_data     = history_data     or {}
        self.video_dbs        = video_dbs        or {}
        self._selected: List[Dict] = []

        self._setup_ui()

    def _setup_ui(self):
        # 视频选择
        sel = tk.LabelFrame(self.window, text="选择视频（2-5个）", padx=8, pady=6)
        sel.pack(fill=X, padx=12, pady=(12, 4))

        lf = tk.Frame(sel)
        lf.pack(fill=X)
        self.listbox = tk.Listbox(lf, selectmode=tk.MULTIPLE, height=5,
                                  exportselection=False)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.listbox.yview)
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.pack(side=LEFT, fill=BOTH, expand=True)
        sb.pack(side=RIGHT, fill=Y)

        for v in self.monitored_videos:
            bvid  = v.get("bvid", "")
            title = v.get("title", "未知")[:40]
            self.listbox.insert(tk.END, f"{bvid}  {title}")

        bb = tk.Frame(sel)
        bb.pack(fill=X, pady=(6, 0))
        ttk.Button(bb, text="开始分析", command=self._analyze).pack(side=tk.LEFT, padx=4)
        self.status_lbl = tk.Label(bb, text="", fg="gray",
                                   font=("Microsoft YaHei UI", 9))
        self.status_lbl.pack(side=tk.LEFT, padx=12)

        # 图表
        cf = tk.Frame(self.window)
        cf.pack(fill=BOTH, expand=True, padx=12, pady=6)
        self.canvas = tk.Canvas(cf, bg="#0d1117", highlightthickness=0)
        self.canvas.pack(fill=BOTH, expand=True)

        # 结果表格
        rf = tk.LabelFrame(self.window, text="交会分析结果", padx=8, pady=6)
        rf.pack(fill=X, padx=12, pady=(0, 12))

        cols = ("视频A", "视频B", "预计交会时间", "预计播放量", "A增长率/h", "B增长率/h", "置信度")
        self.tree = ttk.Treeview(rf, columns=cols, show="headings", height=5)
        for col in cols:
            self.tree.heading(col, text=col)
        self.tree.column("视频A",       width=100)
        self.tree.column("视频B",       width=100)
        self.tree.column("预计交会时间", width=130)
        self.tree.column("预计播放量",   width=110, anchor="e")
        self.tree.column("A增长率/h",   width=90,  anchor="e")
        self.tree.column("B增长率/h",   width=90,  anchor="e")
        self.tree.column("置信度",       width=80,  anchor="center")

        tsb = ttk.Scrollbar(rf, orient="vertical", command=self.tree.yview)
        self.tree.config(yscrollcommand=tsb.set)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        tsb.pack(side=RIGHT, fill=Y)

    # ── 分析 ──────────────────────────────────────────
    def _analyze(self):
        sel_idx = self.listbox.curselection()
        if len(sel_idx) < 2:
            messagebox.showwarning("提示", "请至少选择 2 个视频", parent=self.window)
            return
        if len(sel_idx) > 5:
            messagebox.showwarning("提示", "最多选择 5 个视频", parent=self.window)
            return

        self._selected = [self.monitored_videos[i] for i in sel_idx
                          if i < len(self.monitored_videos)]

        # 补充历史数据
        for v in self._selected:
            bvid = v.get("bvid", "")
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

        # 对每个视频做线性拟合
        fits = {}  # bvid -> (slope, intercept, base_ts, points)
        for v in self._selected:
            bvid = v.get("bvid", "")
            raw = self.history_data.get(bvid, [])
            pts_parsed = []
            for item in raw:
                ts = _parse_ts(item[0])
                views = item[1] if isinstance(item[1], (int, float)) else 0
                if ts and views >= 0:
                    pts_parsed.append((ts, views))
            if len(pts_parsed) < 2:
                fits[bvid] = None
                continue
            pts_parsed.sort(key=lambda p: p[0])
            base_ts = pts_parsed[0][0]
            hours = [(p[0] - base_ts).total_seconds() / 3600 for p in pts_parsed]
            fit_pts = list(zip(hours, [p[1] for p in pts_parsed]))
            result = _linear_fit(fit_pts)
            fits[bvid] = (*result, base_ts, pts_parsed) if result else None

        # 清空旧结果
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.canvas.delete("all")

        valid = [v for v in self._selected if fits.get(v.get("bvid", ""))]
        if len(valid) < 2:
            self.status_lbl.config(text="所选视频历史数据不足（每个至少需要 2 条记录）",
                                   fg="red")
            messagebox.showwarning("数据不足",
                                   "部分视频历史数据不足，无法进行交叉计算。\n"
                                   "每个视频至少需要 2 条历史记录。",
                                   parent=self.window)
            return

        # 两两配对计算交会点
        crossover_count = 0
        now = datetime.now()

        for i in range(len(valid)):
            for j in range(i + 1, len(valid)):
                va = valid[i]
                vb = valid[j]
                ba = va.get("bvid", "")
                bb = vb.get("bvid", "")
                fa = fits[ba]
                fb = fits[bb]
                if not fa or not fb:
                    continue

                slope_a, intercept_a, base_a, pts_a = fa
                slope_b, intercept_b, base_b, pts_b = fb
                offset_h = (base_b - base_a).total_seconds() / 3600

                cross_h = _find_crossover(slope_a, intercept_a,
                                          slope_b, intercept_b, offset_h)
                if cross_h is not None:
                    cross_views = slope_a * cross_h + intercept_a
                    cross_time = base_a + timedelta(hours=cross_h)

                    # 置信度：基于 R² 和数据点数量
                    pts_a_fit = [((p[0] - base_a).total_seconds() / 3600, p[1]) for p in pts_a]
                    pts_b_fit = [((p[0] - base_b).total_seconds() / 3600, p[1]) for p in pts_b]
                    r2_a = self._r_squared(slope_a, intercept_a, pts_a_fit)
                    r2_b = self._r_squared(slope_b, intercept_b, pts_b_fit)
                    # 简单综合置信度
                    r2_avg = (r2_a + r2_b) / 2
                    data_penalty = min(1.0, (len(pts_a) + len(pts_b)) / 20)
                    confidence = r2_avg * data_penalty

                    if cross_views < 0:
                        continue

                    time_str = cross_time.strftime("%Y-%m-%d %H:%M")
                    remaining = cross_time - now
                    if remaining.total_seconds() > 0:
                        days = remaining.days
                        hours = int(remaining.total_seconds() // 3600 % 24)
                        remain_str = f"{days}天{hours}小时" if days else f"{hours}小时"
                    else:
                        remain_str = "已交会"

                    self.tree.insert("", "end", values=(
                        ba[:14],
                        bb[:14],
                        time_str,
                        _fmt_num(cross_views),
                        f"{slope_a:,.1f}",
                        f"{slope_b:,.1f}",
                        f"{confidence:.0%}",
                    ))
                    crossover_count += 1

        self.status_lbl.config(
            text=f"分析完成：{len(valid)} 个视频，找到 {crossover_count} 个交会点",
            fg="#42b983")

        # 绘制趋势图
        self._draw_trend(fits)

        if crossover_count == 0 and len(valid) >= 2:
            messagebox.showinfo("结果", "所选视频在当前趋势下没有交会点", parent=self.window)

    def _r_squared(self, k: float, b: float, points) -> float:
        """计算 R² 拟合优度"""
        pts = list(points)
        if len(pts) < 2:
            return 0
        n = len(pts)
        y_mean = sum(p[1] for p in pts) / n
        ss_tot = sum((p[1] - y_mean) ** 2 for p in pts)
        ss_res = sum((p[1] - (k * p[0] + b)) ** 2 for p in pts)
        if ss_tot < 1e-12:
            return 1.0
        return max(0, 1 - ss_res / ss_tot)

    # ── 趋势图 ────────────────────────────────────────
    def _draw_trend(self, fits: dict):
        c = self.canvas
        W = c.winfo_width()
        H = c.winfo_height()
        if W < 100 or H < 100:
            # 延迟重绘
            self.window.after(100, lambda: self._draw_trend(fits))
            return

        cw = W - _ML - _MR
        ch = H - _MT - _MB
        if cw < 50 or ch < 50:
            return

        # 收集实际数据范围
        all_pts = []
        series = {}
        base_min = None
        for idx, v in enumerate(self._selected):
            bvid = v.get("bvid", "")
            fit_info = fits.get(bvid)
            if not fit_info:
                continue
            slope, intercept, base_ts, pts = fit_info
            series[bvid] = (slope, intercept, base_ts, pts, idx)
            for p in pts:
                all_pts.append((p[0], p[1]))
            if base_min is None or base_ts < base_min:
                base_min = base_ts

        if not all_pts or not series or base_min is None:
            c.create_text(W // 2, H // 2, text="数据不足",
                          fill="#8b949e", font=("Microsoft YaHei UI", 12))
            return

        all_ts_list = [p[0] for p in all_pts]
        all_v_list  = [p[1] for p in all_pts]
        min_ts = min(all_ts_list)
        max_ts = max(all_ts_list)
        # 延长到未来 7 天做预测
        max_ts = max(max_ts, max_ts + timedelta(hours=168))
        max_v = max(all_v_list) * 1.2
        min_v = 0

        ts_span = (max_ts - min_ts).total_seconds() or 1
        v_span = max_v - min_v or 1

        def tx(ts):
            return _ML + (ts - min_ts).total_seconds() / ts_span * cw

        def ty(v):
            return _MT + ch - (v - min_v) / v_span * ch

        # 网格
        for i in range(5):
            ratio = i / 4
            y = _MT + ch * (1 - ratio)
            val = min_v + v_span * ratio
            c.create_line(_ML, y, W - _MR, y, fill="#21262d", dash=(2, 4))
            c.create_text(_ML - 6, y, text=_fmt_num(val), anchor="e",
                          fill="#8b949e", font=("Consolas", 9))

        for i in range(5):
            ratio = i / 4
            ts = min_ts + timedelta(seconds=ts_span * ratio)
            x = _ML + cw * ratio
            lbl = ts.strftime("%m-%d %H:%M") if ts_span < 86400 * 3 \
                  else ts.strftime("%m-%d")
            c.create_text(x, H - _MB + 16, text=lbl,
                          fill="#8b949e", font=("Consolas", 8))

        # 当前时间线
        now_x = tx(datetime.now())
        if _ML < now_x < W - _MR:
            c.create_line(now_x, _MT, now_x, _MT + ch,
                          fill="#f5a623", dash=(4, 4), width=1)
            c.create_text(now_x, _MT - 8, text="现在", fill="#f5a623",
                          font=("Microsoft YaHei UI", 8))

        # 绘制每条线
        for bvid, (slope, intercept, base_ts, pts, idx) in series.items():
            color = LINE_COLORS[idx % len(LINE_COLORS)][0]
            color_light = LINE_COLORS[idx % len(LINE_COLORS)][1]
            title = next((v.get("title", bvid) for v in self._selected
                          if v.get("bvid") == bvid), bvid)[:16]

            # 实际数据折线
            real_coords = []
            for p in pts:
                real_coords.extend([tx(p[0]), ty(p[1])])
            if len(real_coords) >= 4:
                c.create_line(*real_coords, fill=color, width=2)

            # 预测虚线
            last_ts = pts[-1][0]
            last_v  = pts[-1][1]
            # 延长到 max_ts
            future_hours = (max_ts - base_ts).total_seconds() / 3600
            future_v = slope * future_hours + intercept
            pred_coords = list(real_coords[-2:])  # 从最后一个实际点
            pred_coords.extend([tx(max_ts), ty(max(0, future_v))])
            if len(pred_coords) >= 4:
                c.create_line(*pred_coords, fill=color, width=1,
                              dash=(6, 4))

            # 数据点
            for p in pts:
                px, py = tx(p[0]), ty(p[1])
                c.create_oval(px - 2, py - 2, px + 2, py + 2,
                              fill=color, outline="")

            # 图例
            leg = tk.Frame(self.window)
            # 在 canvas 下方用文字代替
            c.create_text(_ML + idx * 160, _MT - 12,
                          text=f"━ {title}",
                          fill=color, anchor="w",
                          font=("Microsoft YaHei UI", 8))
