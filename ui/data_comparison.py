"""
数据对比界面（PyQt6 版）
- 标签1「趋势图」：折线图，多视频对比，支持 8 种指标切换
- 标签2「快照对比」：柱状图，任意选视频 × 任意选时间点，7 种指标，里程碑数据也可叠加
- 标签3「数据录入」：里程碑/快照数据录入
"""

import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from PyQt6.QtWidgets import (
    QDialog, QTabWidget, QVBoxLayout,
)

from ui.theme import C

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

# 图表边距（用于 matplotlib 图表）
_ML, _MR, _MT, _MB = 76, 20, 36, 48
_BAR_ML, _BAR_MR, _BAR_MT, _BAR_MB = 76, 20, 36, 60


def _fmt(n):
    """格式化大数字：超亿显示亿，超万显示万，空值显示 N/A"""
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


# ══════════════════════════════════════════════════════════════════════════════
class DataComparisonWindow(QDialog):
    """数据对比窗口：趋势折线图（TrendTab）+ 快照柱状图（SnapshotTab）+ 数据录入（EntryTab）"""

    def __init__(
        self,
        parent=None,
        monitored_videos: Optional[List[Dict]] = None,
        history_data: Optional[Dict] = None,
        video_dbs: Optional[Dict] = None,
        on_add_monitor=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("数据对比")
        # 必须传 parent 否则 PyQt6 无 screen 属性
        if parent:
            screen = parent.screen()
            if screen:
                geo = screen.geometry()
                sw, sh = geo.width(), geo.height()
            else:
                sw, sh = 1920, 1080
        else:
            sw, sh = 1920, 1080
        self.resize(int(sw * 0.58), int(sh * 0.78))
        self.setMinimumSize(int(sw * 0.40), int(sh * 0.55))

        self.monitored_videos = monitored_videos or []
        self.history_data = history_data or {}
        self.video_dbs = video_dbs or {}
        self.on_add_monitor = on_add_monitor

        self._setup_ui()

    # ══════════════════════════════════════════════════════════════════════════
    # ── 整体布局 ──────────────────────────────────────────────────────────────
    def _setup_ui(self):
        """构建三标签页 QTabWidget：趋势图 / 快照对比 / 数据录入"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {C['border']};
                border-top: none;
                background-color: {C['bg_base']};
            }}
            QTabBar::tab {{
                background-color: {C['bg_surface']};
                color: {C['text_2']};
                border: 1px solid {C['border']};
                border-bottom: none;
                padding: 6px 16px;
                margin-right: 2px;
                border-top-left-radius: {C['radius_sm']}px;
                border-top-right-radius: {C['radius_sm']}px;
            }}
            QTabBar::tab:selected {{
                background-color: {C['bg_base']};
                color: {C['text_1']};
                border-bottom-color: {C['bg_base']};
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {C['bg_hover']};
            }}
        """)
        layout.addWidget(self._tabs)

        # 延迟初始化各标签页（避免循环导入）
        from .trend_tab import TrendTab  # type: ignore[import-type]
        from .snapshot_tab import SnapshotTab  # type: ignore[import-type]
        from .entry_tab import EntryTab  # type: ignore[import-type]

        self.trend_tab: TrendTab = TrendTab(
            self,
            self.monitored_videos,
            self.history_data,
            self.video_dbs,
        )
        self.snapshot_tab: SnapshotTab = SnapshotTab(
            self,
            self.monitored_videos,
            self.video_dbs,
        )
        self.entry_tab: EntryTab = EntryTab(
            self,
            self.monitored_videos,
            self.video_dbs,
            self.on_add_monitor,
        )

        self._tabs.addTab(self.trend_tab, "  ↗  趋势图  ")
        self._tabs.addTab(self.snapshot_tab, "  ◧  快照对比  ")
        self._tabs.addTab(self.entry_tab, "  ↥  数据录入  ")


# ══════════════════════════════════════════════════════════════════════════════
# ── 工具函数 ──────────────────────────────────────────────────────────────────


def _parse_dt(s: str) -> Optional[datetime]:
    """将时间字符串解析为 datetime 对象，支持多种格式"""
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[: len(fmt)].strip(), fmt)
        except Exception as e:
            logger.debug("解析时间字符串失败: %s", e)
    return None


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """将十六进制颜色转换为 RGB 三元组"""
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    """将 RGB 三元组转换为十六进制颜色字符串"""
    return f"#{min(255, max(0, r)):02x}{min(255, max(0, g)):02x}{min(255, max(0, b)):02x}"


def _blend(c1: str, c2: str, t: float) -> str:
    """颜色插值混合：t=0 → c1, t=1 → c2"""
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex(int(r1 + (r2 - r1) * t), int(g1 + (g2 - g1) * t), int(b1 + (b2 - b1) * t))


def _darken(c1: str, factor: float) -> str:
    """颜色变暗：factor < 1 时变暗"""
    r, g, b = _hex_to_rgb(c1)
    return _rgb_to_hex(int(r * factor), int(g * factor), int(b * factor))
