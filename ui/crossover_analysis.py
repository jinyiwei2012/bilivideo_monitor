"""
播放量交叉计算界面模块

本模块基于多个视频的历史播放数据，使用最小二乘线性拟合或指定预测算法，
计算两两视频之间的播放量交会时间。

工作流程：
1. 用户选择 2-5 个视频和预测算法
2. 对每个视频的历史数据做线性拟合（或使用算法预测增长率）
3. 两两配对求两条直线的交点
4. 计算交会时间、预计播放量、置信度、剩余时间
5. 在 Canvas 上绘制趋势图（实际折线 + 预测虚线）并在表格中展示结果

交点计算基于公式：
  线A: y = slope_a * t + intercept_a
  线B: y = slope_b * (t - offset_hours) + intercept_b
"""

import tkinter as tk
from tkinter import ttk, messagebox, LEFT, RIGHT, BOTH, X, Y
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta

from ui.theme import C                                     # 颜色主题常量
from algorithms.registry import AlgorithmRegistry           # 算法注册器（获取预测算法）
from utils.time_utils import safe_datetime                  # 安全的时间解析工具

logger = logging.getLogger(__name__)

# ── 图表边距 ──
_ML, _MR, _MT, _MB = 72, 24, 32, 40                        # 左/右/上/下边距（像素）

# ── 折线颜色列表（每对 = 主色 + 浅色） ──
LINE_COLORS = [
    ("#fb7299", "#ff8db5"),    # 粉色系
    ("#23ade5", "#4bbfea"),    # 蓝色系
    ("#42b983", "#66cba0"),    # 绿色系
    ("#f5a623", "#f7b84e"),    # 橙色系
    ("#9b59b6", "#b07cc6"),    # 紫色系
]


def _fmt_num(n):
    """
    格式化大数字：超亿显示"亿"，超万显示"万"，其余原始显示

    :param n: 数值
    :return: 格式化字符串
    """
    if n >= 1_0000_0000:
        return f"{n / 1_0000_0000:.2f}亿"
    if n >= 1_0000:
        return f"{n / 1_0000:.1f}万"
    return str(int(n))


def _parse_ts(ts) -> Optional[datetime]:
    """
    将各种时间格式统一为 datetime 对象

    :param ts: 时间戳（字符串、datetime 或数值）
    :return: datetime 对象或 None
    """
    try:
        return safe_datetime(ts)
    except Exception:
        return None


def _linear_fit(points: List[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    """
    最小二乘线性拟合，返回 (斜率 k, 截距 b)

    公式推导：
    y = kx + b
    其中 x 为距第一个数据点的小时数，y 为播放量

    :param points: [(x_hours, views), ...]
    :return: (斜率, 截距) 或 None（数据不足）
    """
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


def _find_crossover(
    slope_a: float, intercept_a: float, slope_b: float, intercept_b: float, offset_hours: float
) -> Optional[float]:
    """
    求两条线的交点

    线A: y = slope_a * t + intercept_a  (t=0 对应视频A第一个数据点)
    线B: y = slope_b * (t - offset_hours) + intercept_b  (B 有偏移)
    
    推导：
    ka*t + ba = kb*(t - off) + bb
    (ka - kb)*t = bb - ba - kb*off
    t = (bb - ba - kb*off) / (ka - kb)

    :return: 交点距视频A第一个数据点的小时数，None 表示不相交（平行或交点在过去）
    """
    denom = slope_a - slope_b
    if abs(denom) < 1e-12:
        return None                                         # 平行线，无交点
    t = (intercept_b - intercept_a - slope_b * (-offset_hours)) / denom
    if t > 0:
        return t
    return None                                             # 交点在历史时间（过去），无效


class CrossoverAnalysisWindow:
    """
    交叉计算窗口

    功能：
    1. 视频多选列表（2-5 个）
    2. 算法选择（加权集成 / 线性回归 / 任意已注册算法）
    3. 趋势图表（Canvas 绘制实际折线 + 预测虚线 + "现在"参考线）
    4. 交会结果表格（视频A、视频B、预计交会时间、预计播放量、
       双方增长率、置信度、剩余时间）
    """

    def __init__(
        self,
        parent=None,
        monitored_videos: Optional[List[Dict]] = None,
        history_data: Optional[Dict] = None,
        video_dbs: Optional[Dict] = None,
    ):
        """
        初始化交叉计算窗口

        :param parent: 父窗口
        :param monitored_videos: 监控视频列表
        :param history_data: 历史播放数据 {bvid: [(ts, views), ...]}
        :param video_dbs: 视频独立数据库 {bvid: VideoDatabase}
        """
        self.window = tk.Toplevel(parent)
        self.window.title("播放量交叉计算")
        sw = parent.winfo_screenwidth() if parent else 1920
        sh = parent.winfo_screenheight() if parent else 1080
        self.window.geometry(f"{int(sw * 0.54)}x{int(sh * 0.72)}")

        self.monitored_videos = monitored_videos or []
        self.history_data = history_data or {}
        self.video_dbs = video_dbs or {}
        self._selected: List[Dict] = []                     # 用户选择的视频列表

        self._setup_ui()

    def _setup_ui(self):
        """
        构建界面：
        - 视频选择区（Listbox 多选 + 算法选择 + 分析按钮）
        - 趋势图表 Canvas
        - 交会结果表格
        """
        # ── 视频选择区 ──
        sel = tk.LabelFrame(self.window, text="选择视频（2-5个）", padx=8, pady=6)
        sel.pack(fill=X, padx=12, pady=(12, 4))

        lf = tk.Frame(sel)
        lf.pack(fill=X)
        self.listbox = tk.Listbox(lf, selectmode=tk.MULTIPLE, height=5, exportselection=False)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.listbox.yview)
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.pack(side=LEFT, fill=BOTH, expand=True)
        sb.pack(side=RIGHT, fill=Y)

        # 填充监控视频列表
        for v in self.monitored_videos:
            bvid = v.get("bvid", "")
            title = v.get("title", "未知")[:40]
            self.listbox.insert(tk.END, f"{bvid}  {title}")

        # ── 算法选择区 ──
        algo_frame = tk.Frame(sel)
        algo_frame.pack(fill=X, pady=(4, 0))
        tk.Label(algo_frame, text="预测算法:", fg=C["text_2"], font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        algo_names = ["加权集成(默认)", "线性回归(原方法)"]
        try:
            algo_names.extend(AlgorithmRegistry.get_algorithm_names())
        except Exception as e:
            logger.debug("获取算法列表失败: %s", e)
        self._algo_var = tk.StringVar(value="加权集成(默认)")
        self._algo_combo = ttk.Combobox(
            algo_frame,
            textvariable=self._algo_var,
            values=algo_names,
            width=50,
            state="readonly",
            font=("Microsoft YaHei UI", 9),
        )
        self._algo_combo.pack(side=tk.LEFT, padx=6)

        # 按钮 + 状态
        bb = tk.Frame(sel)
        bb.pack(fill=X, pady=(6, 0))
        ttk.Button(bb, text="开始分析", command=self._analyze).pack(side=tk.LEFT, padx=4)
        self.status_lbl = tk.Label(bb, text="", fg=C["text_2"], font=("Microsoft YaHei UI", 9))
        self.status_lbl.pack(side=tk.LEFT, padx=12)

        # ── 趋势图表 ──
        cf = tk.Frame(self.window)
        cf.pack(fill=BOTH, expand=True, padx=12, pady=6)
        self.canvas = tk.Canvas(cf, bg=C["canvas_bg"], highlightthickness=0)
        self.canvas.pack(fill=BOTH, expand=True)

        # ── 交会结果表格 ──
        rf = tk.LabelFrame(self.window, text="交会分析结果", padx=8, pady=6)
        rf.pack(fill=X, padx=12, pady=(0, 12))

        cols = ("视频A", "视频B", "预计交会时间", "预计播放量", "A增长率/h", "B增长率/h", "置信度", "剩余时间")
        self.tree = ttk.Treeview(rf, columns=cols, show="headings", height=5)
        for col in cols:
            self.tree.heading(col, text=col)
        self.tree.column("视频A", width=100)
        self.tree.column("视频B", width=100)
        self.tree.column("预计交会时间", width=130)
        self.tree.column("预计播放量", width=110, anchor="e")
        self.tree.column("A增长率/h", width=90, anchor="e")
        self.tree.column("B增长率/h", width=90, anchor="e")
        self.tree.column("置信度", width=80, anchor="center")
        self.tree.column("剩余时间", width=90, anchor="center")

        tsb = ttk.Scrollbar(rf, orient="vertical", command=self.tree.yview)
        self.tree.config(yscrollcommand=tsb.set)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        tsb.pack(side=RIGHT, fill=Y)

    # ── 分析流程 ────────────────────────────────────────────────────────────────

    def _analyze(self):
        """
        开始分析：校验选择 → 加载数据 → 拟合 → 计算交会 → 绘制趋势图
        """
        sel_idx = self.listbox.curselection()
        if len(sel_idx) < 2:
            messagebox.showwarning("提示", "请至少选择 2 个视频", parent=self.window)
            return
        if len(sel_idx) > 5:
            messagebox.showwarning("提示", "最多选择 5 个视频", parent=self.window)
            return

        self._selected = [self.monitored_videos[i] for i in sel_idx if i < len(self.monitored_videos)]

        self._load_history()                               # 从数据库补充历史数据
        fits = self._fit_videos()                           # 对每个视频做线性拟合

        # 清空旧结果
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.canvas.delete("all")

        # 筛选出拟合成功的视频
        valid = [v for v in self._selected if fits.get(v.get("bvid", ""))]
        if len(valid) < 2:
            self.status_lbl.config(text="所选视频历史数据不足（每个至少需要 2 条记录）", fg=C["danger"])
            messagebox.showwarning(
                "数据不足",
                "部分视频历史数据不足，无法进行交叉计算。\n" "每个视频至少需要 2 条历史记录。",
                parent=self.window,
            )
            return

        crossover_count = self._compute_crossovers(valid, fits)

        self.status_lbl.config(text=f"分析完成：{len(valid)} 个视频，找到 {crossover_count} 个交会点", fg=C["success"])

        self._draw_trend(fits)

        if crossover_count == 0 and len(valid) >= 2:
            messagebox.showinfo("结果", "所选视频在当前趋势下没有交会点", parent=self.window)

    def _load_history(self):
        """
        从视频独立数据库补充历史播放数据到 self.history_data
        （以防内存中的 history_data 不完整）
        """
        for v in self._selected:
            bvid = v.get("bvid", "")
            if bvid in self.video_dbs:
                try:
                    records = self.video_dbs[bvid].get_all_records()
                    if records:
                        self.history_data[bvid] = [(row["timestamp"], row["view_count"]) for row in records]
                except Exception as e:
                    logger.debug("加载视频历史数据失败: %s", e)

    def _fit_videos(self) -> dict:
        """
        对每个视频做拟合，返回 {bvid: (slope, intercept, base_ts, points)}

        :return: 拟合结果字典，None 表示数据不足
        """
        algo = self._algo_var.get()
        if algo == "线性回归(原方法)":
            return self._fit_linear()                       # 原始最小二乘线性回归
        return self._fit_with_algorithms(algo)              # 使用注册算法预测增长率

    def _fit_linear(self) -> dict:
        """
        原始最小二乘线性回归拟合方法

        :return: {bvid: (slope, intercept, base_ts, points)} 字典
        """
        fits = {}
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
            base_ts = pts_parsed[0][0]                      # 以第一个时间点为基准
            hours = [(p[0] - base_ts).total_seconds() / 3600 for p in pts_parsed]
            fit_pts = list(zip(hours, [p[1] for p in pts_parsed]))
            result = _linear_fit(fit_pts)
            fits[bvid] = (*result, base_ts, pts_parsed) if result else None
        return fits

    def _fit_with_algorithms(self, algo_name: str) -> dict:
        """
        使用注册算法预测增长率进行拟合

        通过算法预测从当前播放量到达阈值（默认 10 万）所需小时数，
        从而反推每小时的增长率（播放量/小时）。
        预测失败时自动回退到线性回归。

        :param algo_name: 算法名称
        :return: 拟合结果字典
        """
        threshold = 100000                                  # 算法统一使用 10 万阈值计算增长率
        fits = {}
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
            current_views = pts_parsed[-1][1]
            history_pts = [(p[0], p[1]) for p in pts_parsed]

            growth_rate = self._get_algo_growth_rate(history_pts, current_views, algo_name, threshold)

            if growth_rate is None or growth_rate <= 0:
                # 算法预测失败，回退到线性回归
                hours = [(p[0] - base_ts).total_seconds() / 3600 for p in pts_parsed]
                fit_pts = list(zip(hours, [p[1] for p in pts_parsed]))
                result = _linear_fit(fit_pts)
                fits[bvid] = (*result, base_ts, pts_parsed) if result else None
            else:
                # 以最新数据点为锚点，用算法增长率作为斜率
                last_hours = (pts_parsed[-1][0] - base_ts).total_seconds() / 3600
                intercept = current_views - growth_rate * last_hours
                fits[bvid] = (growth_rate, intercept, base_ts, pts_parsed)
        return fits

    def _get_algo_growth_rate(self, history_pts, current_views, algo_name, threshold):
        """
        获取算法预测的增长率（播放量/小时）

        增长率 = (阈值 - 当前播放量) / 预测到达阈值所需小时数

        :param history_pts: 历史数据点
        :param current_views: 当前播放量
        :param algo_name: 算法名称
        :param threshold: 目标阈值
        :return: 增长率 或 None
        """
        MAX_RATE = 50000                                    # 超过此值的增长率视为异常
        MIN_HOURS = 0.5                                     # 低于此值的预测时长视为不可信
        try:
            if algo_name == "加权集成(默认)":
                # 加权集成：遍历所有算法，按权重加权平均增长率
                results = AlgorithmRegistry.predict_all(history_pts, current_views, thresholds=[threshold])
                rates, weights = [], []
                for name, r in results.items():
                    if name == "_weighted" or r.get("weight", 0) <= 0:
                        continue
                    pred_h = r.get("metadata", {}).get("predicted_hours", None)
                    if pred_h and pred_h != float("inf") and pred_h > MIN_HOURS:
                        rate = (threshold - current_views) / pred_h
                        if 0 < rate <= MAX_RATE:
                            rates.append(rate)
                            weights.append(r["weight"] * max(r["confidence"], 0.1))
                if rates:
                    return sum(r * w for r, w in zip(rates, weights)) / sum(weights)
            else:
                # 单个算法预测
                algo = AlgorithmRegistry.get_algorithm(algo_name)
                if algo is None:
                    return None
                result = algo.predict(history_pts, current_views, thresholds=[threshold])
                if result:
                    pred_h = result.get("metadata", {}).get("predicted_hours", None)
                    if pred_h and pred_h != float("inf") and pred_h > MIN_HOURS:
                        rate = (threshold - current_views) / pred_h
                        if 0 < rate <= MAX_RATE:
                            return rate
        except Exception as e:
            logger.debug("计算预测速率失败: %s", e)
        return None

    def _compute_crossovers(self, valid: list, fits: dict) -> int:
        """
        两两配对计算交会点，返回找到的交会点总数

        :param valid: 拟合成功的视频列表
        :param fits: 拟合结果字典
        :return: 找到的交会点数量
        """
        crossover_count = 0
        now = datetime.now()

        for i in range(len(valid)):
            for j in range(i + 1, len(valid)):
                count = self._compute_pair(valid[i], valid[j], fits, now)
                if count:
                    crossover_count += count

        return crossover_count

    def _compute_pair(self, va: dict, vb: dict, fits: dict, now: datetime) -> int:
        """
        计算两个视频的交会点，成功则插入结果表格并返回 1

        :param va, vb: 两个视频信息字典
        :param fits: 拟合结果字典
        :param now: 当前时间
        :return: 1 若找到交点，0 否则
        """
        ba = va.get("bvid", "")
        bb = vb.get("bvid", "")
        fa = fits.get(ba)
        fb = fits.get(bb)
        if not fa or not fb:
            return 0

        slope_a, intercept_a, base_a, pts_a = fa
        slope_b, intercept_b, base_b, pts_b = fb
        offset_h = (base_b - base_a).total_seconds() / 3600    # B 相对于 A 的时间偏移（小时）

        # 找交点
        cross_h = _find_crossover(slope_a, intercept_a, slope_b, intercept_b, offset_h)
        if cross_h is None:
            return 0

        cross_views = slope_a * cross_h + intercept_a          # 交点处播放量
        if cross_views < 0:
            return 0

        # 计算时间、置信度、剩余时间
        cross_time = base_a + timedelta(hours=cross_h)
        confidence = self._compute_confidence(slope_a, intercept_a, pts_a, slope_b, intercept_b, pts_b)
        time_str = cross_time.strftime("%Y-%m-%d %H:%M")
        remaining = cross_time - now
        remaining_str = ""
        if remaining.total_seconds() > 0:
            days = remaining.days
            hours = int(remaining.total_seconds() // 3600 % 24)
            remaining_str = f"{days}天{hours}小时" if days else f"{hours}小时"

        self.tree.insert(
            "",
            "end",
            values=(
                ba[:14],
                bb[:14],
                time_str,
                _fmt_num(cross_views),
                f"{slope_a:,.1f}",
                f"{slope_b:,.1f}",
                f"{confidence:.0%}",
                remaining_str,
            ),
        )
        return 1

    def _compute_confidence(self, slope_a, intercept_a, pts_a, slope_b, intercept_b, pts_b) -> float:
        """
        基于 R² 拟合优度和数据点数量计算综合置信度

        :return: 0~1 之间的置信度值
        """
        pts_a_fit = [((p[0] - pts_a[0][0]).total_seconds() / 3600, p[1]) for p in pts_a]
        pts_b_fit = [((p[0] - pts_b[0][0]).total_seconds() / 3600, p[1]) for p in pts_b]
        r2_a = self._r_squared(slope_a, intercept_a, pts_a_fit)
        r2_b = self._r_squared(slope_b, intercept_b, pts_b_fit)
        r2_avg = (r2_a + r2_b) / 2
        data_penalty = min(1.0, (len(pts_a) + len(pts_b)) / 20)   # 数据点数惩罚（数据少则降低置信度）
        return r2_avg * data_penalty

    def _r_squared(self, k: float, b: float, points) -> float:
        """
        计算 R² 拟合优度（决定系数）

        R² = 1 - SS_res / SS_tot
        其中 SS_res 为残差平方和，SS_tot 为总离差平方和

        :param k: 斜率
        :param b: 截距
        :param points: 数据点列表
        :return: R² 值 (0~1)
        """
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

    # ── 趋势图绘制 ──────────────────────────────────────────────────────────────

    def _draw_trend(self, fits: dict):
        """
        绘制各视频的播放量趋势图（含实际数据折线 + 预测虚线）

        :param fits: 拟合结果字典
        """
        c = self.canvas
        W = c.winfo_width()
        H = c.winfo_height()
        if W < 100 or H < 100:
            # 如果 Canvas 还没渲染完成，延迟重绘
            self.window.after(100, lambda: self._draw_trend(fits))
            return

        cw = W - _ML - _MR
        ch = H - _MT - _MB
        if cw < 50 or ch < 50:
            return

        series, all_pts = self._collect_trend_series(fits)
        if not all_pts or not series:
            c.create_text(W // 2, H // 2, text="数据不足", fill=C["text_2"], font=("Microsoft YaHei UI", 12))
            return

        min_ts, max_ts, max_v, min_v, ts_span, v_span = self._compute_trend_ranges(all_pts)

        def tx(ts):
            """时间 → X 坐标"""
            return _ML + (ts - min_ts).total_seconds() / ts_span * cw

        def ty(v):
            """播放量 → Y 坐标"""
            return _MT + ch - (v - min_v) / v_span * ch

        self._draw_trend_grid(c, W, H, cw, ch, min_ts, max_ts, ts_span, max_v, min_v, v_span)
        self._draw_trend_now_line(c, tx, W, ch)
        self._draw_trend_series(c, series, tx, ty, max_ts)

    def _collect_trend_series(self, fits):
        """收集趋势图所需的数据系列：时间点、播放量、拟合参数"""
        all_pts = []
        series = {}
        for idx, v in enumerate(self._selected):
            bvid = v.get("bvid", "")
            fit_info = fits.get(bvid)
            if not fit_info:
                continue
            slope, intercept, base_ts, pts = fit_info
            series[bvid] = (slope, intercept, base_ts, pts, idx)
            for p in pts:
                all_pts.append((p[0], p[1]))
        return series, all_pts

    def _compute_trend_ranges(self, all_pts):
        """
        计算趋势图的坐标轴范围

        时间轴延长到未来 7 天（168 小时）以便展示预测趋势。

        :return: (min_ts, max_ts, max_v, min_v, ts_span, v_span)
        """
        all_ts_list = [p[0] for p in all_pts]
        all_v_list = [p[1] for p in all_pts]
        min_ts = min(all_ts_list)
        max_ts = max(all_ts_list)
        # 延长到未来 7 天做预测
        max_ts = max(max_ts, max_ts + timedelta(hours=168))
        max_v = max(all_v_list) * 1.2                        # 上留 20% 边距
        min_v = 0
        ts_span = (max_ts - min_ts).total_seconds() or 1     # 防除零
        v_span = max_v - min_v or 1
        return min_ts, max_ts, max_v, min_v, ts_span, v_span

    def _draw_trend_grid(self, c, W, H, cw, ch, min_ts, max_ts, ts_span, max_v, min_v, v_span):
        """绘制趋势图的网格线和坐标轴标签（Y 轴 5 条，X 轴 5 个刻度）"""
        # Y 轴网格线（5 条水平线）
        for i in range(5):
            ratio = i / 4
            y = _MT + ch * (1 - ratio)
            val = min_v + v_span * ratio
            c.create_line(_ML, y, W - _MR, y, fill=C["grid_line"], dash=(2, 4))
            c.create_text(_ML - 6, y, text=_fmt_num(val), anchor="e", fill=C["text_2"], font=("Consolas", 9))
        # X 轴时间标签（5 个刻度）
        for i in range(5):
            ratio = i / 4
            ts = min_ts + timedelta(seconds=ts_span * ratio)
            x = _ML + cw * ratio
            lbl = ts.strftime("%m-%d %H:%M") if ts_span < 86400 * 3 else ts.strftime("%m-%d")
            c.create_text(x, H - _MB + 16, text=lbl, fill=C["text_2"], font=("Consolas", 8))

    def _draw_trend_now_line(self, c, tx, W, ch):
        """
        绘制"现在"时间参考线（黄色虚线）
        如果"现在"落在图内则显示，否则不绘制
        """
        now_x = tx(datetime.now())
        if _ML < now_x < W - _MR:
            c.create_line(now_x, _MT, now_x, _MT + ch, fill=C["warning"], dash=(4, 4), width=1)
            c.create_text(now_x, _MT - 8, text="现在", fill=C["warning"], font=("Microsoft YaHei UI", 8))

    def _draw_trend_series(self, c, series, tx, ty, max_ts):
        """
        绘制所有视频的数据系列（实际折线 + 预测虚线 + 数据点 + 图例）

        :param series: {bvid: (slope, intercept, base_ts, pts, idx)}
        """
        for bvid, (slope, intercept, base_ts, pts, idx) in series.items():
            color = LINE_COLORS[idx % len(LINE_COLORS)][0]   # 折线颜色
            title = next((v.get("title", bvid) for v in self._selected if v.get("bvid") == bvid), bvid)[:16]

            # 实际数据折线
            real_coords = []
            for p in pts:
                real_coords.extend([tx(p[0]), ty(p[1])])
            if len(real_coords) >= 4:
                c.create_line(*real_coords, fill=color, width=2)

            # 预测虚线：从最后一个实际数据点延长到 max_ts（未来 7 天）
            future_hours = (max_ts - base_ts).total_seconds() / 3600
            future_v = slope * future_hours + intercept
            pred_coords = list(real_coords[-2:])              # 从最后一个实际点开始
            pred_coords.extend([tx(max_ts), ty(max(0, future_v))])
            if len(pred_coords) >= 4:
                c.create_line(*pred_coords, fill=color, width=1, dash=(6, 4))

            # 数据点（小圆点）
            for p in pts:
                px, py = tx(p[0]), ty(p[1])
                c.create_oval(px - 2, py - 2, px + 2, py + 2, fill=color, outline="")

            # 图例
            c.create_text(
                _ML + idx * 160, _MT - 12, text=f"━ {title}", fill=color, anchor="w", font=("Microsoft YaHei UI", 8)
            )
