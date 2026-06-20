"""
算法可视化对比窗口 — PyQt6 版

对比多个预测算法的历史准确率（MAE/MAPE），
含排名表、误差分布图、预测 vs 实际对比图。

数据来源：per-video 数据库中的 predictions 表（含 error_rate）。
"""

import logging
from typing import List, Dict

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QHeaderView,
)
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QPainter, QColor, QFont, QBrush

from ui.theme import C
from ui.dialog_base import DialogBase
from ui.helpers import FONT, FONT_SM, fmt_num

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# ── 误差分布图绘制组件 ─────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


class ErrorChartWidget(QWidget):
    """QPainter 绘制的误差分布柱状图（MAE 柱 + MAPE 散点）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._algo_data: List[Dict] = []
        self.setMinimumSize(200, 120)

    def set_data(self, data: List[Dict]):
        """设置数据并触发重绘"""
        self._algo_data = data
        self.update()

    def paintEvent(self, a0):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        W = self.width()
        H = self.height()
        if W < 50 or H < 50:
            painter.end()
            return

        data = self._algo_data
        if not data:
            painter.setPen(QColor(C["text_3"]))
            painter.drawText(QRect(0, 0, W, H), Qt.AlignmentFlag.AlignCenter, "暂无数据")
            painter.end()
            return

        ML, MR, MT, MB = 60, 20, 30, 50
        cw = W - ML - MR
        ch = H - MT - MB
        if cw < 20 or ch < 20:
            painter.end()
            return

        # 只显示前 20 个算法
        top = data[:20]
        n = len(top)
        bar_w = max(8, min(30, cw // n - 4))
        max_err = max(s["mae"] for s in top) or 1
        max_mape = max(s["mape"] for s in top) or 1

        # 双 Y 轴：左=MAE 柱, 右=MAPE 散点
        for i, s in enumerate(top):
            x = ML + (i + 0.5) * cw / n

            # MAE 柱
            mae_h = (s["mae"] / max_err) * ch * 0.9 if max_err > 0 else 0
            painter.setBrush(QBrush(QColor(C["accent"])))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(
                int(x - bar_w / 2), int(MT + ch - mae_h),
                int(bar_w), int(mae_h),
            )

            # MAPE 散点
            mape_y = MT + ch - (s["mape"] / max_mape) * ch * 0.9 if max_mape > 0 else MT + ch
            painter.setBrush(QBrush(QColor(C["danger"])))
            painter.drawEllipse(int(x - 3), int(mape_y - 3), 6, 6)

            # 名称标签（每 5 个）
            if i % 5 == 0 or i == n - 1:
                name = s["name"].replace("[Model] ", "")[:12]
                painter.setPen(QColor(C["text_3"]))
                label_font = QFont("Microsoft YaHei UI", 7)
                painter.setFont(label_font)
                painter.drawText(int(x), int(MT + ch + 12), name)

        # 图例
        painter.setBrush(QBrush(QColor(C["accent"])))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(ML + 4, MT + 4, 12, 12)

        painter.setPen(QColor(C["text_2"]))
        leg_font = QFont("Microsoft YaHei UI", 8)
        painter.setFont(leg_font)
        painter.drawText(ML + 22, MT + 14, "MAE(绝对误差)")

        painter.setBrush(QBrush(QColor(C["danger"])))
        painter.drawEllipse(ML + 120, MT + 5, 12, 12)

        painter.setPen(QColor(C["text_2"]))
        painter.drawText(ML + 138, MT + 14, "MAPE(百分比误差)")

        painter.end()


# ══════════════════════════════════════════════════════════════════════════════
# ── 主窗口 ────────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


class AlgorithmCompareWindow(DialogBase):
    """算法预测对比分析窗口"""

    def __init__(self, parent=None, gui=None):
        # 计算窗口尺寸
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
            parent, "算法预测对比",
            (int(sw * 0.62), int(sh * 0.72)),
            modal=False,
        )
        self.gui = gui
        self._algo_data: List[Dict] = []
        self._current_bvid = ""
        self._setup_ui()

    def _setup_ui(self):
        self.header("算法预测对比", "对比各算法的历史预测准确率与误差分布")

        # ── 视频选择 ──
        sec = self.section(title="选择视频", padding=8)
        row0 = QWidget()
        row0.setStyleSheet(f"background-color: {C['bg_elevated']};")
        row0_layout = QHBoxLayout(row0)
        row0_layout.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("视频:")
        lbl.setStyleSheet(f"color: {C['text_2']};")
        lbl.setFont(FONT)
        row0_layout.addWidget(lbl)

        self._bv_combo = QComboBox()
        self._bv_combo.setMinimumWidth(400)
        self._bv_combo.setStyleSheet("""
            QComboBox {{
                font-family: Consolas; font-size: 9pt;
                padding: 2px 4px;
            }}
        """)
        if self.gui and self.gui.monitored_videos:
            for v in self.gui.monitored_videos:
                text = f"{v.get('bvid','')}  {v.get('title','')[:25]}"
                self._bv_combo.addItem(text)
        self._bv_combo.currentIndexChanged.connect(self._load_data)
        row0_layout.addWidget(self._bv_combo, 1)

        analyze_btn = QPushButton("分析")
        analyze_btn.setProperty("primary", True)
        style = analyze_btn.style()
        if style is not None:
            style.unpolish(analyze_btn)
            style.polish(analyze_btn)
        analyze_btn.clicked.connect(self._load_data)
        row0_layout.addWidget(analyze_btn)

        # 将 row0 + status 放入 section 的 layout
        sec_layout = sec.layout()
        if sec_layout is not None:
            sec_layout.addWidget(row0)
            self._status_lbl = QLabel("")
            self._status_lbl.setStyleSheet(f"color: {C['text_3']};")
            self._status_lbl.setFont(FONT_SM)
            sec_layout.addWidget(self._status_lbl)

        # ── 主内容：QTabWidget ──
        tabs_container = self.content_area()
        tabs_layout = QVBoxLayout(tabs_container)
        tabs_layout.setContentsMargins(24, 8, 24, 12)

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
        tabs_layout.addWidget(self._tabs)

        # Tab 1: 排名表
        rank_page = QWidget()
        rank_page.setStyleSheet(f"background-color: {C['bg_base']};")
        self._tabs.addTab(rank_page, "  准确率排名  ")
        self._build_rank_tab(rank_page)

        # Tab 2: 误差分布
        err_page = QWidget()
        err_page.setStyleSheet(f"background-color: {C['bg_base']};")
        self._tabs.addTab(err_page, "  误差分布  ")
        self._build_error_tab(err_page)

        # Tab 3: 预测 vs 实际
        pred_page = QWidget()
        pred_page.setStyleSheet(f"background-color: {C['bg_base']};")
        self._tabs.addTab(pred_page, "  预测 vs 实际  ")
        self._build_predict_tab(pred_page)

    def _build_rank_tab(self, parent):
        """排名表：算法名 / MAE / MAPE / 置信度 / 样本数"""
        cols = ("排名", "算法名称", "MAE", "MAPE", "平均置信度", "样本数")
        widths = [40, 200, 80, 80, 80, 60]

        container = QWidget(parent)
        container.setStyleSheet(f"background-color: {C['bg_elevated']};")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)

        self._rank_tree = QTreeWidget()
        self._rank_tree.setHeaderLabels(cols)
        self._rank_tree.setRootIsDecorated(False)
        self._rank_tree.setAlternatingRowColors(True)
        self._rank_tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {C['bg_elevated']};
                alternate-background-color: {C['bg_surface']};
                border: 1px solid {C['border_sub']};
                font-size: 9pt;
            }}
            QTreeWidget::item {{
                padding: 2px 4px;
            }}
            QHeaderView::section {{
                background-color: {C['bg_surface']};
                color: {C['text_2']};
                border: 1px solid {C['border_sub']};
                padding: 4px 8px;
                font-weight: bold;
            }}
        """)

        header = self._rank_tree.header()
        if header is not None:
            for i, w in enumerate(widths):
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
                self._rank_tree.setColumnWidth(i, w)
            # 算法名称列可拉伸
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self._rank_tree)

        # 放入 parent 布局
        pl = QVBoxLayout(parent)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(container)

    def _build_error_tab(self, parent):
        """误差分布 Chart 组件"""
        self._err_chart = ErrorChartWidget()
        self._err_chart.setStyleSheet(f"background-color: {C['bg_base']};")

        layout = QVBoxLayout(parent)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(self._err_chart)

    def _build_predict_tab(self, parent):
        """预测值 vs 实际值对比表"""
        cols = ("时间", "实际播放量", "加权预测", "最佳预测", "最差预测")
        widths = [140, 100, 100, 180, 180]

        container = QWidget(parent)
        container.setStyleSheet(f"background-color: {C['bg_elevated']};")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)

        self._pred_tree = QTreeWidget()
        self._pred_tree.setHeaderLabels(cols)
        self._pred_tree.setRootIsDecorated(False)
        self._pred_tree.setAlternatingRowColors(True)
        self._pred_tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {C['bg_elevated']};
                alternate-background-color: {C['bg_surface']};
                border: 1px solid {C['border_sub']};
                font-size: 9pt;
            }}
            QHeaderView::section {{
                background-color: {C['bg_surface']};
                color: {C['text_2']};
                border: 1px solid {C['border_sub']};
                padding: 4px 8px;
                font-weight: bold;
            }}
        """)

        header = self._pred_tree.header()
        if header is not None:
            for i, w in enumerate(widths):
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
                self._pred_tree.setColumnWidth(i, w)

        layout.addWidget(self._pred_tree)

        pl = QVBoxLayout(parent)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(container)

    # ══════════════════════════════════════════════════════════════════════════
    # ── 数据加载 ──────────────────────────────────────────────────────────────
    # ══════════════════════════════════════════════════════════════════════════

    def _load_data(self):
        """从数据库加载预测对比数据"""
        bv_text = self._bv_combo.currentText()
        if not bv_text:
            self._status_lbl.setText("请先选择视频")
            return
        bvid = bv_text.split()[0]
        self._current_bvid = bvid

        video_db = self.gui.video_dbs.get(bvid) if self.gui else None
        if not video_db:
            self._status_lbl.setText("无法访问数据库")
            return

        try:
            records = self._get_prediction_history(video_db)
        except Exception as e:
            self._status_lbl.setText(f"加载失败: {e}")
            return

        if not records:
            self._status_lbl.setText("暂无预测数据")
            return

        self._algo_data = self._compute_algo_stats(records)
        self._populate_rank_table()
        self._err_chart.set_data(self._algo_data)
        self._populate_predict_table(records)
        self._status_lbl.setText(
            f"已加载 {len(self._algo_data)} 个算法 · {len(records)} 条预测记录"
        )

    def _get_prediction_history(self, video_db) -> List[Dict]:
        """从数据库获取预测历史记录"""
        try:
            with video_db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT p.*, m.view_count as actual_view, m.timestamp as monitor_time
                    FROM predictions p
                    LEFT JOIN monitor_records m ON m.timestamp = p.created_at
                    WHERE m.view_count IS NOT NULL
                    ORDER BY p.created_at DESC
                    LIMIT 500
                """)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.debug("算法对比JOIN查询失败: %s", e)
            try:
                with video_db._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT * FROM predictions ORDER BY created_at DESC LIMIT 500"
                    )
                    return [dict(row) for row in cursor.fetchall()]
            except Exception as e2:
                logger.debug("算法对比简化查询失败: %s", e2)
                return []

    def _compute_algo_stats(self, records: List[Dict]) -> List[Dict]:
        """按算法聚合统计：MAE、MAPE、置信度、样本数"""
        algo_map: Dict[str, List[Dict]] = {}
        for r in records:
            algo = r.get("algorithm", "unknown")
            if algo not in algo_map:
                algo_map[algo] = []
            algo_map[algo].append(r)

        stats = []
        for name, rows in algo_map.items():
            errors = []
            confidences = []
            for r in rows:
                err = r.get("error_rate", 0) or 0
                conf = r.get("confidence", 0) or 0
                errors.append(err)
                confidences.append(conf)

            n = len(rows)
            mae_val = sum(abs(e) for e in errors) / n if n else 0
            mape_val = (sum(e for e in errors if e > 0) / n * 100) if n else 0
            avg_conf = sum(confidences) / n if n else 0

            stats.append({
                "name": name,
                "n": n,
                "mae": mae_val,
                "mape": mape_val,
                "avg_confidence": avg_conf,
            })

        # 按 MAE 升序
        stats.sort(key=lambda x: x["mae"])
        return stats

    def _populate_rank_table(self):
        """填充排名表"""
        self._rank_tree.clear()
        for i, s in enumerate(self._algo_data):
            item = QTreeWidgetItem()
            item.setText(0, str(i + 1))
            item.setText(1, s["name"])
            item.setText(2, f"{s['mae']:,.0f}")
            item.setText(3, f"{s['mape']:.1f}%")
            item.setText(4, f"{s['avg_confidence']:.1%}")
            item.setText(5, str(s["n"]))
            for col in range(6):
                item.setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignLeft)

            # 前三名粗体
            if i < 3:
                font = item.font(0)
                font.setBold(True)
                for col in range(6):
                    item.setFont(col, font)
                    item.setForeground(col, QColor(C["bilibili"]))

            self._rank_tree.addTopLevelItem(item)

    def _populate_predict_table(self, records: List[Dict]):
        """填充预测 vs 实际对比表"""
        self._pred_tree.clear()
        sorted_recs = sorted(records, key=lambda r: str(r.get("created_at", "")), reverse=True)[:50]
        for r in sorted_recs:
            ts = str(r.get("created_at", ""))[:16]
            actual = r.get("current_views", 0) or 0
            predicted = int(r.get("predicted_seconds", 0) / 60) if r.get("predicted_seconds") else 0
            algo = r.get("algorithm", "")
            conf = r.get("confidence", 0) or 0

            item = QTreeWidgetItem()
            item.setText(0, ts)
            item.setText(1, fmt_num(actual))
            item.setText(2, fmt_num(predicted))
            item.setText(3, f"{algo} ({conf:.0%})")
            item.setText(4, "")
            for col in range(5):
                item.setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)
            self._pred_tree.addTopLevelItem(item)
