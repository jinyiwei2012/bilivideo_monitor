"""
健康探针详情窗口 — PyQt6 版
雷达图 + 详细指标 + 建议
"""

import math
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QColor, QFont, QBrush, QPen, QPolygonF
from PyQt6.QtCore import QPointF

from ui.theme import C
from ui.dialog_base import DialogBase
from utils.interaction_quality import (
    calculate_probe,
)


# ══════════════════════════════════════════════════════════════════════════════
# ── 雷达图绘制组件 ─────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


class RadarChartWidget(QWidget):
    """QPainter 绘制的五维雷达图"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result = None
        self.setMinimumSize(100, 80)
        self.setStyleSheet(f"background-color: {C['bg_elevated']};")

    def set_result(self, result):
        self._result = result
        self.update()

    def paintEvent(self, a0):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        W = self.width()
        H = self.height()
        if W < 50 or H < 50:
            painter.end()
            return

        result = self._result
        if result is None:
            painter.end()
            return

        cx, cy = W // 2, H // 2
        radius = min(W, H) * 0.35

        labels = ["点赞率", "硬币率", "收藏率", "分享率"]
        values = [
            min(result.like_rate, 15),
            min(result.coin_rate, 15),
            min(result.favorite_rate, 15),
            min(result.share_rate, 15),
        ]
        max_val = 15.0

        # 四个维度的角度（从正上方开始）
        angles = [i * math.pi * 2 / 4 - math.pi / 2 for i in range(4)]

        # 绘制同心网格（4 层）
        grid_pen = QPen(QColor(C["border_sub"]), 1)
        for ring in range(1, 5):
            r = radius * ring / 4
            points = QPolygonF()
            for ang in angles:
                points.append(QPointF(cx + r * math.cos(ang), cy + r * math.sin(ang)))
            painter.setPen(grid_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(points)

        # 绘制坐标轴和标签
        label_font = QFont("Microsoft YaHei UI", 9)
        for ang, lbl in zip(angles, labels):
            x_end = cx + radius * math.cos(ang)
            y_end = cy + radius * math.sin(ang)
            painter.setPen(grid_pen)
            painter.drawLine(int(cx), int(cy), int(x_end), int(y_end))

            # 标签位置略远一点
            x_lbl = cx + radius * 1.15 * math.cos(ang)
            y_lbl = cy + radius * 1.15 * math.sin(ang)
            painter.setPen(QColor(C["text_2"]))
            painter.setFont(label_font)
            painter.drawText(int(x_lbl), int(y_lbl), lbl)

        # 绘制实际数据的多边形（半透明粉色填充）
        data_points = QPolygonF()
        for val, ang in zip(values, angles):
            r = radius * val / max_val
            data_points.append(QPointF(cx + r * math.cos(ang), cy + r * math.sin(ang)))
        painter.setBrush(QBrush(QColor("#44fb7299")))
        data_pen = QPen(QColor("#fb7299"), 2)
        painter.setPen(data_pen)
        painter.drawPolygon(data_points)

        # 绘制数据点（粉色圆点）
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#fb7299")))
        for val, ang in zip(values, angles):
            r = radius * val / max_val
            x = cx + r * math.cos(ang)
            y = cy + r * math.sin(ang)
            painter.drawEllipse(int(x - 3), int(y - 3), 6, 6)

        painter.end()


# ══════════════════════════════════════════════════════════════════════════════
# ── 主窗口 ────────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


class HealthProbeWindow(DialogBase):
    """健康探针详情窗口，含五维雷达图、详细指标与建议"""

    def __init__(self, parent=None, video: Optional[dict] = None):
        if parent:
            screen = parent.screen()
            if screen:
                geo = screen.geometry()
                sw, sh = geo.width(), geo.height()
            else:
                sw, sh = 1920, 1080
        else:
            sw, sh = 1920, 1080

        super().__init__(
            parent, "一键三连健康探针",
            (int(sw * 0.38), int(sh * 0.65)),
            modal=False,
        )
        self.video = video or {}

        views = self.video.get("view_count", 0)
        likes = self.video.get("like_count", 0)
        coins = self.video.get("coin_count", 0)
        favors = self.video.get("favorite_count", 0)
        shares = self.video.get("share_count", 0)
        self._probe_result = calculate_probe(views, likes, coins, favors, shares)

        self._setup_ui()

    def _setup_ui(self):
        """构建健康探针窗口的完整 UI：雷达图、分数卡片、异常与建议"""
        title = self.video.get("title", "未知视频")[:30]
        self.header(f"一键三连健康探针 — {title}", "基于点赞率·硬币率·收藏率·分享率的综合评估")

        # 上部分：雷达图 + 分数卡片（水平布局）
        top = QWidget()
        top.setStyleSheet(f"background-color: {C['bg_surface']};")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(24, 12, 24, 0)

        # 雷达图
        radar_frame = QFrame()
        radar_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {C['bg_elevated']};
                border: 1px solid {C['border_sub']};
                border-radius: 6px;
            }}
        """)
        radar_layout = QVBoxLayout(radar_frame)
        radar_layout.setContentsMargins(8, 8, 8, 8)

        self._radar_chart = RadarChartWidget()
        self._radar_chart.set_result(self._probe_result)
        radar_layout.addWidget(self._radar_chart)
        top_layout.addWidget(radar_frame, 1)

        # 右侧摘要卡片
        summary = QFrame()
        summary.setStyleSheet(f"""
            QFrame {{
                background-color: {C['bg_elevated']};
                border: 1px solid {C['border_sub']};
                border-radius: 6px;
            }}
        """)
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(18, 14, 18, 14)
        summary_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        score = self._probe_result.health_score
        grade = self._probe_result.health_grade

        grade_colors = {"S": "#fb7299", "A": "#23ade5", "B": "#42b983", "C": "#f5a623", "D": "#e74c3c"}
        gc = grade_colors.get(grade, C["text_1"])

        # 大分数
        score_lbl = QLabel(f"{score:.0f}")
        score_font = QFont("Consolas", 48)
        score_font.setBold(True)
        score_lbl.setFont(score_font)
        score_lbl.setStyleSheet(f"color: {gc};")
        score_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        summary_layout.addWidget(score_lbl)

        grade_lbl = QLabel(f"评级 {grade}")
        grade_font = QFont("Microsoft YaHei UI", 16)
        grade_font.setBold(True)
        grade_lbl.setFont(grade_font)
        grade_lbl.setStyleSheet(f"color: {gc};")
        grade_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        summary_layout.addWidget(grade_lbl)

        anomalies_color = C["danger"] if self._probe_result.anomalies else C["success"]
        anom_lbl = QLabel(f"{len(self._probe_result.anomalies)} 项异常")
        anom_lbl.setFont(QFont("Microsoft YaHei UI", 10))
        anom_lbl.setStyleSheet(f"color: {anomalies_color};")
        anom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        summary_layout.addWidget(anom_lbl)

        # 比率小卡片
        summary_layout.addSpacing(12)
        items = [
            ("点赞率", self._probe_result.like_rate, "%"),
            ("硬币率", self._probe_result.coin_rate, "%"),
            ("收藏率", self._probe_result.favorite_rate, "%"),
            ("分享率", self._probe_result.share_rate, "%"),
        ]
        for label, val, unit in items:
            row_w = QWidget()
            row_w.setStyleSheet(f"background-color: {C['bg_elevated']};")
            row_layout = QHBoxLayout(row_w)
            row_layout.setContentsMargins(0, 1, 0, 1)
            lbl = QLabel(label)
            lbl.setFont(QFont("Microsoft YaHei UI", 9))
            lbl.setStyleSheet(f"color: {C['text_2']};")
            lbl.setFixedWidth(64)
            row_layout.addWidget(lbl)
            val_lbl = QLabel(f"{val:.2f}{unit}")
            val_lbl.setFont(QFont("Consolas", 10))
            val_lbl.setStyleSheet(f"color: {C['text_1']};")
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            row_layout.addWidget(val_lbl)
            summary_layout.addWidget(row_w)

        top_layout.addWidget(summary)

        # 将 top 放入 container 的 layout
        self._main_layout.addWidget(top)

        # 下部分：异常与建议
        bottom = QWidget()
        bottom.setStyleSheet(f"background-color: {C['bg_surface']};")
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(24, 12, 24, 0)

        if self._probe_result.anomalies:
            sec = self.section(parent=bottom, title="△ 异常项", padding=8)
            sec_layout = sec.layout()
            if sec_layout is not None:
                for a in self._probe_result.anomalies:
                    lbl = QLabel(f"  \u2022 {a}")
                    lbl.setFont(QFont("Microsoft YaHei UI", 9))
                    lbl.setStyleSheet(f"color: {C['danger']};")
                    sec_layout.addWidget(lbl)

        if self._probe_result.tips:
            sec2 = self.section(parent=bottom, title="\u2728 建议", padding=8)
            sec2_layout = sec2.layout()
            if sec2_layout is not None:
                for t in self._probe_result.tips:
                    lbl = QLabel(f"  \u2022 {t}")
                    lbl.setFont(QFont("Microsoft YaHei UI", 9))
                    lbl.setStyleSheet(f"color: {C['text_1']};")
                    sec2_layout.addWidget(lbl)

        self._main_layout.addWidget(bottom)

        self.button_row([("关闭", self.reject, "default")])

        # QTimer 触发雷达图首次绘制（确保 layout 已完成）
        QTimer.singleShot(200, self._radar_chart.update)
