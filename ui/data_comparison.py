"""
数据对比界面模块（重构版）

本模块提供三维数据对比功能，通过 Notebook 标签页组织：

1. TrendTab（趋势图标签页）：
   - 多视频折线图对比，支持 8 种指标切换
   - 指标包括：播放量、点赞、硬币、收藏、分享、弹幕、评论、点赞率

2. SnapshotTab（快照对比标签页）：
   - 柱状图对比，任意选视频 × 任意选时间点
   - 支持 7 种指标，里程碑数据可叠加展示

3. EntryTab（数据录入标签页）：
   - 里程碑数据录入（一周/月/年等周期的播放数据）
   - 历史快照录入（指定时间点的播放数据）
   - 支持批量 BV 号输入

共用工具函数：格式化大数字、时间解析、颜色混合、圆角柱状图绘制。
"""

import tkinter as tk
from tkinter import ttk, BOTH
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# ── 颜色调色板（10 色，支持最多 10 个视频的折线区分） ──
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

# ── 指标定义（字段名, 中文名） ──
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

# ── 图表边距 ──
_ML, _MR, _MT, _MB = 76, 20, 36, 48                         # 折线图边距
_BAR_ML, _BAR_MR, _BAR_MT, _BAR_MB = 76, 20, 36, 60         # 柱状图边距


def _fmt(n):
    """
    格式化大数字：超亿显示亿，超万显示万，空值显示 N/A

    :param n: 数值（支持 None）
    :return: 格式化字符串
    """
    if n is None:
        return "N/A"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "N/A"
    if n >= 1e8:
        return f"{n / 1e8:.2f}亿"
    if n >= 1e4:
        return f"{n / 1e4:.1f}万"
    return str(int(n))


class DataComparisonWindow:
    """
    数据对比窗口

    主容器使用 Notebook 组织三个标签页：
    1. TrendTab — 趋势折线图（多视频、多指标对比）
    2. SnapshotTab — 快照柱状图（选视频 × 选时间点）
    3. EntryTab — 数据录入（里程碑/快照数据批量录入）
    """

    def __init__(
        self,
        parent=None,
        monitored_videos: Optional[List[Dict]] = None,
        history_data: Optional[Dict] = None,
        video_dbs: Optional[Dict] = None,
        on_add_monitor=None,
    ):
        """
        初始化数据对比窗口

        :param parent: 父级 Tkinter 窗口
        :param monitored_videos: 监控视频列表
        :param history_data: 历史播放数据 {bvid: [(ts, views), ...]}
        :param video_dbs: 视频独立数据库 {bvid: VideoDatabase}
        :param on_add_monitor: 添加监控的回调函数
        """
        self.window = tk.Toplevel(parent)
        self.window.title("数据对比")
        sw = parent.winfo_screenwidth() if parent else 1920
        sh = parent.winfo_screenheight() if parent else 1080
        self.window.geometry(f"{int(sw * 0.58)}x{int(sh * 0.78)}")
        self.window.minsize(int(sw * 0.40), int(sh * 0.55))

        self.monitored_videos = monitored_videos or []
        self.history_data = history_data or {}
        self.video_dbs = video_dbs or {}
        self.on_add_monitor = on_add_monitor

        self._setup_ui()

    def _setup_ui(self):
        """
        构建三标签页 Notebook：趋势图 / 快照对比 / 数据录入
        """
        nb = ttk.Notebook(self.window)
        nb.pack(fill=BOTH, expand=True, padx=8, pady=8)

        tab_trend = tk.Frame(nb)
        tab_snap = tk.Frame(nb)
        tab_entry = tk.Frame(nb)

        nb.add(tab_trend, text="  📈  趋势图  ")
        nb.add(tab_snap, text="  📊  快照对比  ")
        nb.add(tab_entry, text="  📥  数据录入  ")

        # 延迟初始化各标签页（避免循环导入）
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
    """
    将时间字符串解析为 datetime 对象，支持多种格式：
    - 2026-04-22 12:00:00
    - 2026-04-22 12:00
    - 2026-04-22T12:00:00  (ISO 格式)

    :param s: 时间字符串
    :return: datetime 对象或 None
    """
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[: len(fmt)].strip(), fmt)
        except Exception as e:
            logger.debug("解析时间字符串失败: %s", e)
    return None


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """
    将十六进制颜色字符串转换为 RGB 三元组

    :param hex_color: 如 "#fb7299"
    :return: (R, G, B)
    """
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    """
    将 RGB 三元组转换为十六进制颜色字符串

    :param r, g, b: 0~255 的 RGB 值（自动裁剪）
    :return: 如 "#fb7299"
    """
    return f"#{min(255, max(0, r)):02x}{min(255, max(0, g)):02x}{min(255, max(0, b)):02x}"


def _blend(c1: str, c2: str, t: float) -> str:
    """
    颜色线性插值混合

    :param c1: 起始颜色
    :param c2: 终止颜色
    :param t: 混合系数（0 → c1, 1 → c2）
    :return: 混合后的颜色
    """
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex(int(r1 + (r2 - r1) * t), int(g1 + (g2 - g1) * t), int(b1 + (b2 - b1) * t))


def _darken(c1: str, factor: float) -> str:
    """
    颜色变暗

    :param c1: 原始颜色
    :param factor: 暗化因子（< 1 变暗）
    :return: 变暗后的颜色
    """
    r, g, b = _hex_to_rgb(c1)
    return _rgb_to_hex(int(r * factor), int(g * factor), int(b * factor))


def _draw_bar(canvas: tk.Canvas, x0, y0, x1, y1, color_top, color_body):
    """
    绘制一根带顶部高亮渐变和圆角的矩形柱

    使用多边形近似圆角矩形效果，顶部覆盖高亮渐变条增加立体感。

    :param canvas: Canvas 对象
    :param x0, y0: 左上角坐标
    :param x1, y1: 右下角坐标
    :param color_top: 顶部高亮颜色
    :param color_body: 柱体主色
    """
    if y0 >= y1:
        return
    # 圆角半径（不超过柱宽的 1/4）
    r = min(3, max(1, (x1 - x0) * 0.15))
    # 柱体主体（圆角矩形用 polygon 模拟）
    pts = [
        x0 + r, y0, x1 - r, y0,
        x1, y0 + r, x1, y1 - r,
        x1 - r, y1,
        x0 + r, y1,
        x0, y1 - r, x0, y0 + r,
    ]
    canvas.create_polygon(pts, fill=color_body, outline="", smooth=True, width=0)
    # 顶部高亮条
    top_h = max(2, (y1 - y0) * 0.08)
    top_pts = [
        x0 + r, y0, x1 - r, y0,
        x1, y0 + min(r, top_h), x1, y0 + top_h + r,
        x1 - r, y0 + top_h + r * 2,
        x0 + r, y0 + top_h + r * 2,
        x0, y0 + top_h + r, x0, y0 + min(r, top_h),
    ]
    canvas.create_polygon(top_pts, fill=color_top, outline="", smooth=True, width=0)


# ── 延迟导入标签页类（避免循环导入，同时保证模块级可访问） ──
from .trend_tab import TrendTab  # noqa: E402
from .snapshot_tab import SnapshotTab  # noqa: E402
from .entry_tab import EntryTab  # noqa: E402
