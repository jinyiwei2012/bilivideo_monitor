"""
数据对比界面（重构版）
- 标签1「趋势图」：折线图，多视频对比，支持 8 种指标切换
- 标签2「快照对比」：柱状图，任意选视频 × 任意选时间点，7 种指标，里程碑数据也可叠加
- 标签3「数据录入」：里程碑/快照数据录入
"""

import tkinter as tk
from tkinter import ttk, BOTH
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# ── 颜色表 ────────────────────────────────────────────────────────────────────
PALETTE = [
    "#fb7299",  # bilibili 粉
    "#23ade5",  # 蓝
    "#42b983",  # 绿
    "#f5a623",  # 橙
    "#9b59b6",  # 紫
    "#e74c3c",  # 红
    "#1abc9c",  # 青绿
    "#e67e22",  # 棕橙
    "#3498db",  # 浅蓝
    "#2ecc71",  # 亮绿
]

PALETTE_LIGHT = [
    "#ff8db5",
    "#4bbfea",
    "#66cba0",
    "#f7b84e",
    "#b07cc6",
    "#e57878",
    "#45d1b8",
    "#f0a35a",
    "#5aaee8",
    "#5ddda2",
]

# ── 指标定义 ──────────────────────────────────────────────────────────────────
METRICS = [
    ("view_count", "播放量"),
    ("like_count", "点赞"),
    ("coin_count", "硬币"),
    ("favorite_count", "收藏"),
    ("share_count", "分享"),
    ("danmaku_count", "弹幕"),
    ("reply_count", "评论"),
    ("like_view_ratio", "点赞率(%)"),
]

# 图表边距
_ML, _MR, _MT, _MB = 76, 20, 36, 48
_BAR_ML, _BAR_MR, _BAR_MT, _BAR_MB = 76, 20, 36, 60


def _fmt(n):
    """格式化大数字"""
    if n is None:
        return "N/A"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "N/A"
    if n >= 1e8:
        return f"{n/1e8:.2f}亿"
    if n >= 1e4:
        return f"{n/1e4:.1f}万"
    return str(int(n))


# ══════════════════════════════════════════════════════════════════════════════
class DataComparisonWindow:
    """数据对比窗口（趋势折线图 + 快照柱状图 + 数据录入）"""

    def __init__(
        self,
        parent=None,
        monitored_videos: Optional[List[Dict]] = None,
        history_data: Optional[Dict] = None,
        video_dbs: Optional[Dict] = None,
        on_add_monitor=None,
    ):
        self.window = tk.Toplevel(parent)
        self.window.title("数据对比")
        self.window.geometry("1100x780")
        self.window.minsize(850, 600)

        self.monitored_videos = monitored_videos or []
        self.history_data = history_data or {}
        self.video_dbs = video_dbs or {}
        self.on_add_monitor = on_add_monitor

        self._setup_ui()

    # ══════════════════════════════════════════════════════════════════════════
    # ── 整体布局 ──────────────────────────────────────────────────────────────
    def _setup_ui(self):
        nb = ttk.Notebook(self.window)
        nb.pack(fill=BOTH, expand=True, padx=8, pady=8)

        tab_trend = tk.Frame(nb)
        tab_snap = tk.Frame(nb)
        tab_entry = tk.Frame(nb)

        nb.add(tab_trend, text="  📈  趋势图  ")
        nb.add(tab_snap, text="  📊  快照对比  ")
        nb.add(tab_entry, text="  📥  数据录入  ")

        self.trend_tab = TrendTab(
            tab_trend,
            self.monitored_videos,
            self.history_data,
            self.video_dbs,
            self.window,
        )
        self.snapshot_tab = SnapshotTab(
            tab_snap,
            self.monitored_videos,
            self.video_dbs,
            self.window,
        )
        self.entry_tab = EntryTab(
            tab_entry,
            self.monitored_videos,
            self.video_dbs,
            self.on_add_monitor,
            self.window,
        )


# ══════════════════════════════════════════════════════════════════════════════
# ── 工具函数 ──────────────────────────────────────────────────────────────────


def _parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[: len(fmt)].strip(), fmt)
        except Exception as e:
            logger.debug("解析时间字符串失败: %s", e)
    return None


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{min(255, max(0, r)):02x}{min(255, max(0, g)):02x}{min(255, max(0, b)):02x}"


def _blend(c1: str, c2: str, t: float) -> str:
    """t=0 → c1, t=1 → c2"""
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex(int(r1 + (r2 - r1) * t), int(g1 + (g2 - g1) * t), int(b1 + (b2 - b1) * t))


def _darken(c1: str, factor: float) -> str:
    """factor < 1 → 变暗"""
    r, g, b = _hex_to_rgb(c1)
    return _rgb_to_hex(int(r * factor), int(g * factor), int(b * factor))


def _draw_bar(canvas: tk.Canvas, x0, y0, x1, y1, color_top, color_body):
    """绘制一根带顶部高亮和圆角的矩形柱"""
    if y0 >= y1:
        return
    # 圆角半径（不超过柱宽的1/4）
    r = min(3, max(1, (x1 - x0) * 0.15))
    # 主体（圆角矩形用 polygon 模拟）
    pts = [
        x0 + r,
        y0,
        x1 - r,
        y0,
        x1,
        y0 + r,
        x1,
        y1 - r,
        x1 - r,
        y1,
        x0 + r,
        y1,
        x0,
        y1 - r,
        x0,
        y0 + r,
    ]
    canvas.create_polygon(pts, fill=color_body, outline="", smooth=True, width=0)
    # 顶部高亮条（更细腻）
    top_h = max(2, (y1 - y0) * 0.08)
    top_pts = [
        x0 + r,
        y0,
        x1 - r,
        y0,
        x1,
        y0 + min(r, top_h),
        x1,
        y0 + top_h + r,
        x1 - r,
        y0 + top_h + r * 2,
        x0 + r,
        y0 + top_h + r * 2,
        x0,
        y0 + top_h + r,
        x0,
        y0 + min(r, top_h),
    ]
    canvas.create_polygon(top_pts, fill=color_top, outline="", smooth=True, width=0)


# ── 延迟导入标签页类（避免循环导入） ──────────────────────────────────────────
from .trend_tab import TrendTab  # noqa: E402
from .snapshot_tab import SnapshotTab  # noqa: E402
from .entry_tab import EntryTab  # noqa: E402
