"""
数据大屏模式 — PyQt6 版
全屏无边框自动轮播数据展示
"""

import logging
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QStackedWidget, QFrame,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QColor, QFont, QBrush

from ui.helpers import THRESHOLDS, THRESHOLD_NAMES

logger = logging.getLogger(__name__)

# 大屏颜色主题（深色）
_DASH_COLORS = {
    "bg": "#0d1117",
    "card_bg": "#161b22",
    "text_1": "#f0f6fc",
    "text_2": "#8b949e",
    "accent": "#58a6ff",
    "success": "#3fb950",
    "warning": "#d29922",
    "danger": "#f85149",
    "bilibili": "#fb7299",
}


def _fmt(n):
    if n >= 1_0000_0000:
        return f"{n / 1_0000_0000:.2f}亿"
    if n >= 1_0000:
        return f"{n / 1_0000:.1f}万"
    return str(n)


# ══════════════════════════════════════════════════════════════════════════════
# ── 排行榜柱状图绘制组件 ───────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


class RankingBarChart(QWidget):
    """QPainter 水平柱状图：播放量 Top10"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._videos = []
        self.setMinimumSize(200, 100)

    def set_data(self, videos):
        self._videos = videos
        self.update()

    def paintEvent(self, a0):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        W = self.width()
        H = self.height()
        if W < 100 or H < 100:
            painter.end()
            return

        top = self._videos[:10]
        if not top:
            painter.end()
            return

        max_views = top[0].get("view_count", 1) or 1
        bar_h = 36
        canvas_w = W

        for i, v in enumerate(top):
            views = v.get("view_count", 0)
            bar_w = max(40, int(views / max_views * (canvas_w - 200)))
            y = 10 + i * bar_h

            # 柱状条（前 3 名实心，其余半透明）
            if i < 3:
                painter.setBrush(QBrush(QColor(_DASH_COLORS["accent"])))
            else:
                color = QColor(_DASH_COLORS["accent"])
                color.setAlpha(80)
                painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(10, y + 6, bar_w, bar_h - 12)

            # 排名文字
            painter.setPen(QColor("white"))
            rank_font = QFont("Consolas", 10)
            rank_font.setBold(True)
            painter.setFont(rank_font)
            painter.drawText(16, y + bar_h // 2 + 4, f"#{i + 1}")

            # 标题+播放量
            title_font = QFont("Microsoft YaHei UI", 10)
            painter.setFont(title_font)
            painter.setPen(QColor(_DASH_COLORS["text_1"]))
            label = f"{v.get('title', '')[:20]}  {_fmt(views)}"
            painter.drawText(24 + bar_w, y + bar_h // 2 + 4, label)

        painter.end()


# ══════════════════════════════════════════════════════════════════════════════
# ── 主窗口 ────────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


class DashboardWindow(QWidget):
    """全屏数据大屏 — 自动轮播 4 页（总览/排行/预测/健康）"""

    def __init__(self, gui, parent=None):
        super().__init__(parent)
        self.gui = gui
        self.setWindowTitle("数据大屏")
        self.setStyleSheet(f"background-color: {_DASH_COLORS['bg']};")

        self._page = 0
        self._total_pages = 4
        self._animating = True

        self._rotation_timer = QTimer(self)
        self._rotation_timer.timeout.connect(self._next_page)

        self._time_timer = QTimer(self)
        self._time_timer.timeout.connect(self._update_time)

        self._setup_ui()
        self._show_page(0)
        self._start_rotation()

        # 全屏显示
        self.showFullScreen()

    def keyPressEvent(self, a0):
        """Escape / F11 退出全屏"""
        if a0 is not None and a0.key() in (Qt.Key.Key_Escape, Qt.Key.Key_F11):
            self._animating = False
            self._rotation_timer.stop()
            self._time_timer.stop()
            self.close()
        if a0 is not None:
            super().keyPressEvent(a0)

    def _setup_ui(self):
        """构建大屏 UI：顶部标题 + 时间、页面指示器、内容区"""
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 20, 40, 20)

        # 顶部标题栏
        header = QWidget()
        header.setStyleSheet(f"background-color: {_DASH_COLORS['bg']};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)

        title_lbl = QLabel("数据大屏")
        title_font = QFont("Microsoft YaHei UI", 20)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setStyleSheet(f"color: {_DASH_COLORS['text_1']};")
        header_layout.addWidget(title_lbl)

        header_layout.addStretch()

        self._time_lbl = QLabel("")
        self._time_lbl.setFont(QFont("Microsoft YaHei UI", 12))
        self._time_lbl.setStyleSheet(f"color: {_DASH_COLORS['text_2']};")
        header_layout.addWidget(self._time_lbl)

        root.addWidget(header)

        # 页面指示器（圆点）
        dots = QWidget()
        dots.setStyleSheet(f"background-color: {_DASH_COLORS['bg']};")
        dots_layout = QHBoxLayout(dots)
        dots_layout.setContentsMargins(0, 8, 0, 0)

        self._dot_widgets = []
        for i in range(self._total_pages):
            d = QLabel("\u25cf")
            d.setFont(QFont("Microsoft YaHei UI", 8))
            d.setStyleSheet(f"color: {_DASH_COLORS['text_2']}; background: transparent;")
            dots_layout.addWidget(d)
            self._dot_widgets.append(d)

        root.addWidget(dots)

        # 内容区（QStackedWidget 预置 4 页，切换时重建）
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background-color: {_DASH_COLORS['bg']};")
        # 预填充空页面占位
        for _ in range(self._total_pages):
            page = QWidget()
            page.setStyleSheet(f"background-color: {_DASH_COLORS['bg']};")
            self._stack.addWidget(page)
        root.addWidget(self._stack, 1)

        # 启动时间刷新
        self._update_time()
        self._time_timer.start(1000)

    def _update_time(self):
        self._time_lbl.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def _start_rotation(self):
        self._rotation_timer.start(15000)

    def _next_page(self):
        if not self._animating:
            return
        self._page = (self._page + 1) % self._total_pages
        self._show_page(self._page)

    def _show_page(self, page: int):
        """渲染指定页码的内容到 QStackedWidget"""
        self._stack.setCurrentIndex(page)

        # 更新指示器
        for i, d in enumerate(self._dot_widgets):
            color = _DASH_COLORS["accent"] if i == page else _DASH_COLORS["text_2"]
            d.setStyleSheet(f"color: {color}; background: transparent;")

        # 重建当前页
        current_page = self._stack.currentWidget()
        # 清除旧内容
        self._clear_widget(current_page)

        pages = [
            self._build_overview,
            self._build_ranking,
            self._build_prediction,
            self._build_health,
        ]
        if 0 <= page < len(pages):
            pages[page](current_page)

    def _clear_widget(self, widget):
        """清除 QWidget 的所有子控件"""
        layout = widget.layout()
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
                del item
        else:
            # 首次使用，创建 layout
            widget.setLayout(QVBoxLayout())
            widget.layout().setContentsMargins(0, 0, 0, 0)

    # ── 第1页：总览 ────────────────────────────

    def _build_overview(self, page):
        """第 1 页：总览 — 监控总数、总播放量、总互动、已达标数、视频列表"""
        layout = page.layout()
        videos = self.gui.monitored_videos
        total = len(videos)
        total_views = sum(v.get("view_count", 0) for v in videos)
        total_likes = sum(v.get("like_count", 0) for v in videos)
        achieved = sum(1 for v in videos if v.get("view_count", 0) >= 10000)

        # 4 大指标卡片
        stat_row = QWidget()
        stat_row.setStyleSheet(f"background-color: {_DASH_COLORS['bg']};")
        stat_layout = QHBoxLayout(stat_row)
        stat_layout.setContentsMargins(0, 20, 0, 20)

        cards = [
            ("监控总数", f"{total}", _DASH_COLORS["accent"]),
            ("总播放量", _fmt(total_views), _DASH_COLORS["bilibili"]),
            ("总互动", _fmt(total_likes), _DASH_COLORS["success"]),
            ("已达标(万)", f"{achieved}", _DASH_COLORS["warning"]),
        ]
        for label, val, color in cards:
            card = QFrame()
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: {_DASH_COLORS['card_bg']};
                    border: 1px solid #30363d;
                    border-radius: 8px;
                }}
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.setContentsMargins(10, 30, 10, 30)

            lbl = QLabel(label)
            lbl.setFont(QFont("Microsoft YaHei UI", 12))
            lbl.setStyleSheet(f"color: {_DASH_COLORS['text_2']};")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(lbl)

            val_lbl = QLabel(val)
            val_font = QFont("Consolas", 28)
            val_font.setBold(True)
            val_lbl.setFont(val_font)
            val_lbl.setStyleSheet(f"color: {color};")
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(val_lbl)

            stat_layout.addWidget(card, 1)
            if label != cards[-1][0]:
                stat_layout.addSpacing(8)

        if layout is not None:
            layout.addWidget(stat_row)

        # 视频列表（前 8 个）
        table_frame = QFrame()
        table_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {_DASH_COLORS['card_bg']};
                border: 1px solid #30363d;
                border-radius: 8px;
            }}
        """)
        table_layout = QVBoxLayout(table_frame)
        table_layout.setContentsMargins(12, 8, 12, 8)

        title_lbl = QLabel("视频列表")
        title_font = QFont("Microsoft YaHei UI", 10)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setStyleSheet(f"color: {_DASH_COLORS['text_2']};")
        table_layout.addWidget(title_lbl)

        for v in videos[:8]:
            row = QWidget()
            row.setStyleSheet(f"background-color: {_DASH_COLORS['card_bg']};")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 1, 0, 1)

            bvid_lbl = QLabel(v.get("bvid", "")[:12])
            bvid_lbl.setFont(QFont("Consolas", 9))
            bvid_lbl.setStyleSheet(f"color: {_DASH_COLORS['accent']};")
            bvid_lbl.setFixedWidth(120)
            row_layout.addWidget(bvid_lbl)

            title_txt = v.get("title", "")[:35]
            title_item = QLabel(title_txt)
            title_item.setFont(QFont("Microsoft YaHei UI", 9))
            title_item.setStyleSheet(f"color: {_DASH_COLORS['text_1']};")
            row_layout.addWidget(title_item, 1)

            for key, width in [("view_count", 100), ("like_count", 80), ("danmaku_count", 80)]:
                val = _fmt(v.get(key, 0))
                lbl = QLabel(val)
                lbl.setFont(QFont("Consolas", 9))
                lbl.setStyleSheet(f"color: {_DASH_COLORS['text_2']};")
                lbl.setFixedWidth(width)
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
                row_layout.addWidget(lbl)

            table_layout.addWidget(row)

        if layout is not None:
            layout.addWidget(table_frame, 1)

    # ── 第2页：排行 ────────────────────────────

    def _build_ranking(self, page):
        """第 2 页：排行 — 播放量 Top10 水平柱状图"""
        layout = page.layout()
        videos = sorted(self.gui.monitored_videos, key=lambda v: v.get("view_count", 0), reverse=True)

        if not videos:
            lbl = QLabel("暂无数据")
            lbl.setFont(QFont("Microsoft YaHei UI", 16))
            lbl.setStyleSheet(f"color: {_DASH_COLORS['text_2']};")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if layout is not None:
                layout.addWidget(lbl)
            return

        title_lbl = QLabel("播放量排行 Top10")
        title_font = QFont("Microsoft YaHei UI", 14)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setStyleSheet(f"color: {_DASH_COLORS['text_1']};")
        if layout is not None:
            layout.addWidget(title_lbl)

        chart = RankingBarChart()
        chart.set_data(videos)
        if layout is not None:
            layout.addWidget(chart, 1)

    # ── 第3页：预测 ────────────────────────────

    def _build_prediction(self, page):
        """第 3 页：预测 — 各视频当前播放量及阈值完成进度"""
        layout = page.layout()

        title_lbl = QLabel("预测总览")
        title_font = QFont("Microsoft YaHei UI", 14)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setStyleSheet(f"color: {_DASH_COLORS['text_1']};")
        if layout is not None:
            layout.addWidget(title_lbl)

        row = QWidget()
        row.setStyleSheet(f"background-color: {_DASH_COLORS['bg']};")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 20, 0, 0)

        for v in self.gui.monitored_videos[:6]:
            views = v.get("view_count", 0)
            card = QFrame()
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: {_DASH_COLORS['card_bg']};
                    border: 1px solid #30363d;
                    border-radius: 8px;
                }}
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 14)

            title = QLabel(v.get("title", "")[:18])
            title_font = QFont("Microsoft YaHei UI", 10)
            title_font.setBold(True)
            title.setFont(title_font)
            title.setStyleSheet(f"color: {_DASH_COLORS['text_1']};")
            card_layout.addWidget(title)

            play_lbl = QLabel(f"播放: {_fmt(views)}")
            play_lbl.setFont(QFont("Consolas", 10))
            play_lbl.setStyleSheet(f"color: {_DASH_COLORS['text_2']};")
            card_layout.addWidget(play_lbl)

            # 每个阈值的完成进度
            for t, name in zip(THRESHOLDS, THRESHOLD_NAMES):
                pct = min(100, views / t * 100) if t > 0 else 0
                status = "\u2705" if views >= t else f"{pct:.0f}%"
                threshold_lbl = QLabel(f"  {name}: {status}")
                threshold_lbl.setFont(QFont("Microsoft YaHei UI", 9))
                color = _DASH_COLORS["success"] if views >= t else _DASH_COLORS["text_2"]
                threshold_lbl.setStyleSheet(f"color: {color};")
                card_layout.addWidget(threshold_lbl)

            row_layout.addWidget(card, 1)
            if v != self.gui.monitored_videos[:6][-1]:
                row_layout.addSpacing(6)

        if layout is not None:
            layout.addWidget(row)

    # ── 第4页：健康 ────────────────────────────

    def _build_health(self, page):
        """第 4 页：健康 — 实时预警列表 + 一键三连健康探针评分"""
        layout = page.layout()

        title_lbl = QLabel("健康概览")
        title_font = QFont("Microsoft YaHei UI", 14)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setStyleSheet(f"color: {_DASH_COLORS['text_1']};")
        if layout is not None:
            layout.addWidget(title_lbl)

        # ── 实时预警卡片 ──
        from core.smart_alert import AnomalyDetector

        alert_frame = QFrame()
        alert_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {_DASH_COLORS['card_bg']};
                border: 1px solid #30363d;
                border-radius: 8px;
            }}
        """)
        alert_layout = QVBoxLayout(alert_frame)
        alert_layout.setContentsMargins(12, 8, 12, 8)

        alert_title = QLabel("实时预警")
        alert_title_font = QFont("Microsoft YaHei UI", 10)
        alert_title_font.setBold(True)
        alert_title.setFont(alert_title_font)
        alert_title.setStyleSheet(f"color: {_DASH_COLORS['text_2']};")
        alert_layout.addWidget(alert_title)

        found_alert = False
        for v in self.gui.monitored_videos:
            bvid = v.get("bvid", "")
            if bvid in self.gui.video_dbs:
                try:
                    records = self.gui.video_dbs[bvid].get_all_records(limit=10)
                    alerts = AnomalyDetector.detect_all(records, bvid=bvid)
                    if alerts:
                        found_alert = True
                        for msg in alerts:
                            row = QWidget()
                            row.setStyleSheet(f"background-color: {_DASH_COLORS['card_bg']};")
                            row_layout = QHBoxLayout(row)
                            row_layout.setContentsMargins(0, 1, 0, 1)

                            name_lbl = QLabel(v.get("title", "")[:18])
                            name_lbl.setFont(QFont("Microsoft YaHei UI", 9))
                            name_lbl.setStyleSheet(f"color: {_DASH_COLORS['warning']};")
                            row_layout.addWidget(name_lbl)
                            row_layout.addSpacing(8)

                            msg_lbl = QLabel(msg[:60])
                            msg_lbl.setFont(QFont("Microsoft YaHei UI", 9))
                            msg_lbl.setStyleSheet(f"color: {_DASH_COLORS['text_1']};")
                            row_layout.addWidget(msg_lbl)

                            alert_layout.addWidget(row)
                except Exception as e:
                    logger.debug("渲染预警卡片失败: %s", e)

        if not found_alert:
            no_alert = QLabel("\u2705 暂无预警")
            no_alert.setFont(QFont("Microsoft YaHei UI", 12))
            no_alert.setStyleSheet(f"color: {_DASH_COLORS['success']};")
            no_alert.setAlignment(Qt.AlignmentFlag.AlignCenter)
            alert_layout.addWidget(no_alert)

        if layout is not None:
            layout.addWidget(alert_frame, 1)

        # ── 一键三连健康探针 ──
        try:
            from utils.interaction_quality import calculate_probe_from_dict

            probe_frame = QFrame()
            probe_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {_DASH_COLORS['card_bg']};
                    border: 1px solid #30363d;
                    border-radius: 8px;
                }}
            """)
            probe_layout = QVBoxLayout(probe_frame)
            probe_layout.setContentsMargins(12, 8, 12, 8)

            probe_title = QLabel("一键三连健康探针")
            probe_title_font = QFont("Microsoft YaHei UI", 10)
            probe_title_font.setBold(True)
            probe_title.setFont(probe_title_font)
            probe_title.setStyleSheet(f"color: {_DASH_COLORS['text_2']};")
            probe_layout.addWidget(probe_title)

            for v in self.gui.monitored_videos[:6]:
                try:
                    r = calculate_probe_from_dict(v)
                    grade_colors = {
                        "S": _DASH_COLORS["bilibili"],
                        "A": _DASH_COLORS["accent"],
                        "B": _DASH_COLORS["success"],
                        "C": _DASH_COLORS["warning"],
                        "D": _DASH_COLORS["danger"],
                    }
                    gc = grade_colors.get(r.health_grade, _DASH_COLORS["text_2"])

                    row = QWidget()
                    row.setStyleSheet(f"background-color: {_DASH_COLORS['card_bg']};")
                    row_layout = QHBoxLayout(row)
                    row_layout.setContentsMargins(0, 1, 0, 1)

                    name_lbl = QLabel(v.get("title", "")[:20])
                    name_lbl.setFont(QFont("Microsoft YaHei UI", 9))
                    name_lbl.setStyleSheet(f"color: {_DASH_COLORS['text_1']};")
                    row_layout.addWidget(name_lbl)

                    row_layout.addStretch()

                    score_lbl = QLabel(f"{r.health_score:.0f} {r.health_grade}")
                    score_font = QFont("Consolas", 11)
                    score_font.setBold(True)
                    score_lbl.setFont(score_font)
                    score_lbl.setStyleSheet(f"color: {gc};")
                    row_layout.addWidget(score_lbl)

                    probe_layout.addWidget(row)
                except Exception as e:
                    logger.debug("渲染单个视频健康探针失败: %s", e)

            if layout is not None:
                layout.addWidget(probe_frame)
        except Exception as e:
            logger.debug("渲染健康探针区域失败: %s", e)
