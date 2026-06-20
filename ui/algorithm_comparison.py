"""算法可视化比较：准确率 / 权重 / 详细数据对比 — PyQt6 版"""

import logging
from typing import List, Dict

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QHeaderView,
)
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QPainter, QColor, QFont

from ui.theme import C
from ui.helpers import FONT, FONT_SM

logger = logging.getLogger(__name__)

# 图表边距
_ML, _MR, _MT, _MB = 60, 20, 32, 80
_BAR_H = 18  # 柱状图每行高度
_BAR_GAP = 6  # 柱状图行间距

# 按类别分配颜色
_CATEGORY_COLORS = {
    "速度类": "#0969da",
    "时间衰减": "#8250df",
    "扩散模型": "#1a7f37",
    "时间序列": "#bf3989",
    "统计模型": "#d1242f",
    "集成学习": "#9a6700",
    "深度学习": "#0550ae",
    "高级分析": "#0e765c",
    "基础": "#6e40c9",
    "其他": "#8b949e",
}


def _cat_color(cat: str) -> str:
    """获取类别对应的颜色"""
    return _CATEGORY_COLORS.get(cat, "#8b949e")


def _fmt_pct(v: float) -> str:
    """将小数格式化为百分比字符串"""
    return f"{v * 100:.1f}%"


# ══════════════════════════════════════════════════════════════════════════════
# ── 横向柱状图绘制组件（通用：准确率 / 权重） ──────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


class HorizontalBarChart(QWidget):
    """QPainter 绘制的横向柱状图，支持准确率与权重两种模式"""

    MODE_ACCURACY = "accuracy"
    MODE_WEIGHT = "weight"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filtered: List[Dict] = []
        self._mode = self.MODE_ACCURACY
        self.setMinimumSize(200, 120)

    def set_data(self, data: List[Dict], mode: str = MODE_ACCURACY):
        self._filtered = data
        self._mode = mode
        self.update()

    def paintEvent(self, a0):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        W = self.width()
        H = self.height()
        if W < 100 or H < 100:
            painter.end()
            return

        filtered = self._filtered
        if not filtered:
            painter.setPen(QColor(C["text_3"]))
            painter.setFont(FONT)
            painter.drawText(QRect(0, 0, W, H), Qt.AlignmentFlag.AlignCenter, "无数据")
            painter.end()
            return

        cw = W - _ML - _MR
        ch = max(50, H - _MT - _MB)
        bar_unit = _BAR_H + _BAR_GAP
        visible = filtered[: max(1, int(ch / bar_unit))]

        title_font = QFont("Microsoft YaHei UI", 9)
        title_font.setBold(True)
        painter.setPen(QColor(C["text_1"]))
        painter.setFont(title_font)
        title = "算法准确率对比" if self._mode == self.MODE_ACCURACY else "算法权重对比"
        painter.drawText(QRect(0, 0, W, _MT), Qt.AlignmentFlag.AlignCenter, title)

        data_font = QFont("Microsoft YaHei UI", 8)
        label_font = QFont("Consolas", 7)
        max_w = 1.0
        if self._mode == self.MODE_WEIGHT:
            max_w = max(info.get("final_weight", 1) for info in visible) or 1

        for i, info in enumerate(visible):
            y0 = _MT + i * bar_unit
            name = info.get("name", "?")[:28]
            color = _cat_color(info.get("category", "其他"))

            acc = 0.5
            if self._mode == self.MODE_ACCURACY:
                acc = max(0, min(1, info.get("accuracy", 0.5)))
                bar_w = acc * cw
            else:
                w_val = max(0, info.get("final_weight", 1.0))
                bar_w = w_val / max_w * cw

            # 类别色条（左侧小色块）
            painter.setBrush(QColor(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(_ML - 10, y0, 6, _BAR_H)

            # 柱体
            if bar_w > 0:
                painter.drawRect(_ML, y0, int(bar_w), _BAR_H)

            # 名称（右对齐到柱体起始）
            painter.setPen(QColor(C["text_2"]))
            painter.setFont(data_font)
            fm = painter.fontMetrics()
            name_width = fm.horizontalAdvance(name)
            painter.drawText(int(_ML - 14 - name_width), y0 + _BAR_H // 2 + fm.ascent() // 2 - 1, name)

            # 数值标签
            if self._mode == self.MODE_ACCURACY:
                lbl = _fmt_pct(acc)
            else:
                is_custom = info.get("is_customized", False)
                suffix = " ✎" if is_custom else ""
                lbl = f"{info.get('final_weight', 1.0):.2f}{suffix}"

            painter.setPen(QColor(C["text_1"]))
            painter.drawText(int(_ML + bar_w + 6), y0 + _BAR_H // 2 + fm.ascent() // 2 - 1, lbl)

            # 样本数（准确率模式）
            if self._mode == self.MODE_ACCURACY:
                samples = info.get("samples", 0)
                if samples:
                    painter.setPen(QColor(C["text_3"]))
                    painter.setFont(label_font)
                    lbl2 = f"n={samples}"
                    fm2 = painter.fontMetrics()
                    lbl2_width = fm2.horizontalAdvance(lbl2)
                    painter.drawText(int(_ML + cw - lbl2_width), y0 + _BAR_H // 2 + fm2.ascent() // 2 - 1, lbl2)
                    painter.setFont(data_font)

        # 图例（准确率模式）
        if self._mode == self.MODE_ACCURACY:
            used_cats = {info.get("category", "其他") for info in visible}
            lx = _ML
            ly = _MT + len(visible) * bar_unit + 10
            leg_font = QFont("Microsoft YaHei UI", 8)
            painter.setFont(leg_font)
            for cat in sorted(used_cats):
                painter.setBrush(QColor(_cat_color(cat)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(lx, ly, 12, 12)
                painter.setPen(QColor(C["text_2"]))
                painter.drawText(lx + 16, ly + 10, cat)
                lx += 70

        painter.end()


# ══════════════════════════════════════════════════════════════════════════════
# ── 主窗口 ────────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


class AlgorithmComparisonWindow(QDialog):
    """算法可视化比较窗口：准确率柱状图、权重柱状图、详细数据表格"""

    def __init__(self, parent=None):
        super().__init__(parent)
        if parent:
            screen = parent.screen()
            if screen:
                geo = screen.geometry()
                sw, sh = geo.width(), geo.height()
            else:
                sw, sh = 1920, 1080
        else:
            sw, sh = 1920, 1080
        self.resize(int(sw * 0.52), int(sh * 0.72))
        self.setMinimumSize(700, 500)

        self.setWindowTitle("算法可视化比较")
        self.setStyleSheet(f"background-color: {C['bg_surface']};")

        self._algo_info: List[Dict] = []  # 算法信息列表
        self._load_data()
        self._setup_ui()

    # ── 数据加载 ────────────────────────────────────────

    def _load_data(self):
        """从注册器和权重管理器加载所有算法的准确率、权重、样本数等数据"""
        try:
            from algorithms.registry import AlgorithmRegistry

            self._algo_info = AlgorithmRegistry.get_weights_info()
            # 补充算法类别信息
            for info in self._algo_info:
                name = info.get("name", "")
                # 去除 [Model] 等前缀后再次尝试匹配
                clean_name = name.split("] ", 1)[-1] if "] " in name else name
                algo = AlgorithmRegistry.get_algorithm(clean_name) or AlgorithmRegistry.get_algorithm(name)
                if algo is not None:
                    info["category"] = getattr(algo, "category", "其他")
                else:
                    info["category"] = "其他"
                # 设置默认值
                info.setdefault("samples", 0)
                info.setdefault("accuracy", 0.5)
                info.setdefault("final_weight", 1.0)
        except Exception as e:
            logger.warning("加载算法信息失败: %s", e)

    # ── UI ──────────────────────────────────────────────

    def _setup_ui(self):
        """构建比较窗口 UI：标题、过滤控制栏、三标签页"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 标题
        title = QLabel(f"算法可视化比较（共 {len(self._algo_info)} 个算法）")
        title_font = QFont("Microsoft YaHei UI", 13)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {C['text_1']}; padding: 14px 14px 4px 14px;")
        layout.addWidget(title)

        # 控制栏：类别过滤 + 排序
        ctrl = QWidget()
        ctrl.setStyleSheet(f"background-color: {C['bg_surface']};")
        ctrl_layout = QHBoxLayout(ctrl)
        ctrl_layout.setContentsMargins(14, 0, 14, 6)

        # 类别过滤
        cat_lbl = QLabel("类别过滤:")
        cat_lbl.setStyleSheet(f"color: {C['text_2']};")
        cat_lbl.setFont(FONT)
        ctrl_layout.addWidget(cat_lbl)

        self._cat_combo = QComboBox()
        self._cat_combo.setStyleSheet("font-size: 9pt; padding: 2px 4px;")
        cats = self._collect_categories()
        self._cat_combo.addItems(cats)
        self._cat_combo.currentIndexChanged.connect(lambda _: self._refresh())
        ctrl_layout.addWidget(self._cat_combo)

        ctrl_layout.addSpacing(12)

        # 排序方式
        sort_lbl = QLabel("排序:")
        sort_lbl.setStyleSheet(f"color: {C['text_2']};")
        sort_lbl.setFont(FONT)
        ctrl_layout.addWidget(sort_lbl)

        self._sort_combo = QComboBox()
        self._sort_combo.setStyleSheet("font-size: 9pt; padding: 2px 4px;")
        sorts = ["准确率 ↓", "准确率 ↑", "权重 ↓", "权重 ↑", "样本数 ↓", "名称"]
        self._sort_combo.addItems(sorts)
        self._sort_combo.currentIndexChanged.connect(lambda _: self._refresh())
        ctrl_layout.addWidget(self._sort_combo)

        ctrl_layout.addSpacing(6)

        # 统计摘要
        self._summary_lbl = QLabel("")
        self._summary_lbl.setStyleSheet(f"color: {C['text_3']};")
        self._summary_lbl.setFont(FONT_SM)
        ctrl_layout.addWidget(self._summary_lbl)

        ctrl_layout.addStretch()

        # 刷新按钮
        refresh_btn = QPushButton("↻ 刷新")
        refresh_btn.clicked.connect(self._refresh)
        ctrl_layout.addWidget(refresh_btn)

        layout.addWidget(ctrl)

        # 三标签页 QTabWidget
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
        layout.addWidget(self._tabs, 1)

        # Tab 1: 准确率对比
        tab_acc = QWidget()
        tab_acc.setStyleSheet(f"background-color: {C['bg_base']};")
        self._tabs.addTab(tab_acc, "  准确率对比  ")
        acc_layout = QVBoxLayout(tab_acc)
        acc_layout.setContentsMargins(0, 0, 0, 0)
        self._acc_chart = HorizontalBarChart()
        self._acc_chart.setStyleSheet(f"background-color: {C['bg_base']};")
        acc_layout.addWidget(self._acc_chart)

        # Tab 2: 权重对比
        tab_weight = QWidget()
        tab_weight.setStyleSheet(f"background-color: {C['bg_base']};")
        self._tabs.addTab(tab_weight, "  权重对比  ")
        weight_layout = QVBoxLayout(tab_weight)
        weight_layout.setContentsMargins(0, 0, 0, 0)
        self._weight_chart = HorizontalBarChart()
        self._weight_chart.setStyleSheet(f"background-color: {C['bg_base']};")
        weight_layout.addWidget(self._weight_chart)

        # Tab 3: 详细数据
        tab_detail = QWidget()
        tab_detail.setStyleSheet(f"background-color: {C['bg_base']};")
        self._tabs.addTab(tab_detail, "  详细数据  ")
        self._setup_detail_tab(tab_detail)

        self._refresh()

    def _collect_categories(self) -> list:
        """收集所有算法类别，返回排序后的列表（含"全部"）"""
        cats = set()
        for info in self._algo_info:
            cats.add(info.get("category", "其他"))
        return ["全部"] + sorted(cats)

    # ── 数据过滤与排序 ──────────────────────────────────

    def _get_filtered(self) -> list:
        """根据用户选择的类别和排序方式过滤并排序算法数据"""
        cat = self._cat_combo.currentText()
        filtered = [info for info in self._algo_info if cat == "全部" or info.get("category") == cat]

        s = self._sort_combo.currentText()
        if s == "准确率 ↓":
            filtered.sort(key=lambda x: x.get("accuracy", 0), reverse=True)
        elif s == "准确率 ↑":
            filtered.sort(key=lambda x: x.get("accuracy", 0))
        elif s == "权重 ↓":
            filtered.sort(key=lambda x: x.get("final_weight", 1), reverse=True)
        elif s == "权重 ↑":
            filtered.sort(key=lambda x: x.get("final_weight", 1))
        elif s == "样本数 ↓":
            filtered.sort(key=lambda x: x.get("samples", 0), reverse=True)
        else:
            filtered.sort(key=lambda x: x.get("name", ""))
        return filtered

    # ── 详细数据表格 ────────────────────────────────────

    def _setup_detail_tab(self, parent):
        """构建详细数据表格页"""
        cols = ("name", "category", "accuracy", "final_weight", "samples", "is_customized")

        layout = QVBoxLayout(parent)
        layout.setContentsMargins(10, 10, 10, 10)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(cols)
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setStyleSheet(f"""
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

        col_widths = {"name": 220, "category": 80, "accuracy": 80,
                      "final_weight": 80, "samples": 80, "is_customized": 80}
        for cid in cols:
            self._tree.setColumnWidth(len([x for x in cols[:cols.index(cid)]]), col_widths[cid])

        header = self._tree.header()
        if header is not None:
            header.setStretchLastSection(False)
            for i in range(len(cols)):
                if cols[i] == "name":
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
                else:
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            # 点击表头排序
            header.setSortIndicatorShown(True)
            self._tree.setSortingEnabled(True)

        layout.addWidget(self._tree)

    def _populate_tree(self):
        """用过滤后的数据填充详细数据表格"""
        self._tree.setSortingEnabled(False)
        self._tree.clear()
        filtered = self._get_filtered()
        for info in filtered:
            item = QTreeWidgetItem()
            item.setText(0, info.get("name", ""))
            item.setText(1, info.get("category", ""))
            item.setText(2, _fmt_pct(info.get("accuracy", 0.5)))
            item.setText(3, f"{info.get('final_weight', 1.0):.2f}")
            item.setText(4, str(info.get("samples", 0)))
            item.setText(5, "是" if info.get("is_customized") else "否")
            for col in range(6):
                item.setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)
            item.setTextAlignment(0, Qt.AlignmentFlag.AlignLeft)
            self._tree.addTopLevelItem(item)
        self._tree.setSortingEnabled(True)

    # ── 通用 ────────────────────────────────────────────

    def _update_summary(self, filtered):
        """更新统计摘要"""
        n_total = len(self._algo_info)
        n_filtered = len(filtered)
        avg_acc = sum(info.get("accuracy", 0) for info in filtered) / max(1, n_filtered)
        avg_weight = sum(info.get("final_weight", 1) for info in filtered) / max(1, n_filtered)
        self._summary_lbl.setText(
            f"展示 {n_filtered}/{n_total} | 平均准确率 {_fmt_pct(avg_acc)} | 平均权重 {avg_weight:.2f}"
        )

    def _refresh(self):
        """刷新所有标签页的数据和图表"""
        filtered = self._get_filtered()
        self._acc_chart.set_data(filtered, HorizontalBarChart.MODE_ACCURACY)
        self._weight_chart.set_data(filtered, HorizontalBarChart.MODE_WEIGHT)
        self._populate_tree()
        self._update_summary(filtered)
