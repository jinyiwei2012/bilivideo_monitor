"""
主题系统 - PyQt6 QSS + QPalette 设计令牌

集中管理所有颜色、圆角、间距等设计系统令牌，
各 UI 模块通过 ``from ui.theme import C, apply_theme, qapp`` 使用。

Theme 使用 QPalette + 全局 QSS 实现深色/亮色统一切换。
"""

import logging
from PyQt6.QtGui import QPalette, QColor, QFont
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

logger = logging.getLogger(__name__)

# ── 设计令牌 ────────────────────────────────
# 亮色主题配色
THEME_LIGHT = {
    "bg_base": "#f6faff",
    "bg_surface": "#eef5fc",
    "bg_elevated": "#ffffff",
    "bg_hover": "#e0edfa",
    "border": "#d3e3f5",
    "border_sub": "#e8f0fa",
    "bilibili": "#4d9fff",
    "bilibili_dim": "#2e7fe0",
    "accent": "#4d9fff",
    "accent_hover": "#2e7fe0",
    "success": "#3fa97a",
    "warning": "#c58a1f",
    "danger": "#d6455d",
    "text_1": "#1c2a3a",
    "text_2": "#5a6f85",
    "text_3": "#8aa0b8",
    "chart_line": "#4d9fff",
    "chart_area": "#66ccff",
    "chart_dot": "#66ccff",
    "thresh_10w": "#3fa97a",
    "thresh_100w": "#c58a1f",
    "thresh_1000w": "#7b5fd0",
    "canvas_bg": "#ffffff",
    "canvas_text": "#1c2a3a",
    "log_debug": "#5a6f85",
    "log_info": "#4d9fff",
    "log_warn": "#c58a1f",
    "log_error": "#d6455d",
    "log_time": "#8aa0b8",
    "grid_line": "#e8f0fa",
    # ── 设计系统令牌 ────────────────────────
    "radius_sm": 6,
    "radius_md": 8,
    "radius_lg": 12,
    "radius_xl": 16,
    "brand": "#4d9fff",
    "brand_hover": "#2e7fe0",
    "text_primary": "#1c2a3a",
    "text_secondary": "#5a6f85",
    "text_tertiary": "#8aa0b8",
    "bg_default": "#f6faff",
    "border_default": "#d3e3f5",
    "border_subtle": "#e8f0fa",
    # ── 洛天依主题令牌 ──────────────────────
    "lty_blue": "#66ccff",       # 官方应援色「天依蓝」
    "lty_blue_deep": "#4d9fff",  # 深一阶天依蓝 (可读性)
    "lty_blue_light": "#b8e4ff", # 浅天依蓝 (水波高光)
    "lty_jade": "#63d3a5",       # 翡翠绿 (绿瞳/玉佩)
    "lty_wave_a": "#66ccff",     # 水波渐变起点
    "lty_wave_b": "#b8e4ff",     # 水波渐变终点
    # 大屏专用（深色）
    "dash_bg": "#0b1220",
    "dash_card_bg": "#101a2c",
    "dash_text_1": "#eaf4ff",
    "dash_text_2": "#8aa0b8",
}

# 暗色主题配色
THEME_DARK = {
    "bg_base": "#0b1220",
    "bg_surface": "#101a2c",
    "bg_elevated": "#16233a",
    "bg_hover": "#1d2c47",
    "border": "#263650",
    "border_sub": "#1b2a42",
    "bilibili": "#66ccff",
    "bilibili_dim": "#85d8ff",
    "accent": "#66ccff",
    "accent_hover": "#85d8ff",
    "success": "#63d3a5",
    "warning": "#d9a03a",
    "danger": "#e5537a",
    "text_1": "#eaf4ff",
    "text_2": "#8aa0b8",
    "text_3": "#4d6480",
    "chart_line": "#66ccff",
    "chart_area": "#66ccff",
    "chart_dot": "#66ccff",
    "thresh_10w": "#63d3a5",
    "thresh_100w": "#d9a03a",
    "thresh_1000w": "#b48cff",
    "canvas_bg": "#0b1220",
    "canvas_text": "#eaf4ff",
    "log_debug": "#8aa0b8",
    "log_info": "#66ccff",
    "log_warn": "#d9a03a",
    "log_error": "#e5537a",
    "log_time": "#4d6480",
    "grid_line": "#1b2a42",
    # ── 设计系统令牌 ────────────────────────
    "radius_sm": 6,
    "radius_md": 8,
    "radius_lg": 12,
    "radius_xl": 16,
    "brand": "#66ccff",
    "brand_hover": "#85d8ff",
    "text_primary": "#eaf4ff",
    "text_secondary": "#8aa0b8",
    "text_tertiary": "#4d6480",
    "bg_default": "#0b1220",
    "border_default": "#263650",
    "border_subtle": "#1b2a42",
    # ── 洛天依主题令牌 (暗色下不变) ────────
    "lty_blue": "#66ccff",
    "lty_blue_deep": "#4d9fff",
    "lty_blue_light": "#b8e4ff",
    "lty_jade": "#63d3a5",
    "lty_wave_a": "#66ccff",
    "lty_wave_b": "#2e6fb8",
    # 大屏专用（深色，暗色模式下不变）
    "dash_bg": "#0b1220",
    "dash_card_bg": "#101a2c",
    "dash_text_1": "#eaf4ff",
    "dash_text_2": "#8aa0b8",
}

# 当前激活的主题
C = dict(THEME_LIGHT)

# ── 全局 QSS 样式表 ─────────────────────────

def _build_qss(theme: dict) -> str:
    """根据主题令牌生成全局 QSS 样式表"""
    t = theme
    return f"""
    /* 全局 */
    QMainWindow, QDialog, QWidget {{
        background-color: {t['bg_base']};
        color: {t['text_1']};
        font-family: "Microsoft YaHei UI";
        font-size: 9pt;
    }}
    QFrame {{
        border: none;
    }}
    /* 标签 */
    QLabel {{
        background-color: transparent;
        color: {t['text_1']};
    }}
    QLabel[textSecondary="true"] {{
        color: {t['text_2']};
    }}
    QLabel[textTertiary="true"] {{
        color: {t['text_3']};
    }}
    /* 按钮 */
    QPushButton {{
        background-color: {t['bg_elevated']};
        color: {t['text_1']};
        border: 1px solid {t['border']};
        border-radius: {t['radius_sm']}px;
        padding: 4px 14px;
        min-height: 28px;
    }}
    QPushButton:hover {{
        background-color: {t['bg_hover']};
    }}
    QPushButton:pressed {{
        background-color: {t['border']};
    }}
    QPushButton[primary="true"] {{
        background-color: {t['bilibili']};
        color: #ffffff;
        border: none;
    }}
    QPushButton[primary="true"]:hover {{
        background-color: {t['bilibili_dim']};
    }}
    QPushButton[danger="true"] {{
        background-color: transparent;
        color: {t['danger']};
        border: 1px solid {t['danger']};
    }}
    QPushButton[danger="true"]:hover {{
        background-color: {t['danger']};
        color: #ffffff;
    }}
    QPushButton[accent="true"] {{
        background-color: {t['accent']};
        color: #ffffff;
        border: none;
    }}
    QPushButton[accent="true"]:hover {{
        background-color: #0859c6;
    }}
    /* 输入框 */
    QLineEdit, QSpinBox, QDoubleSpinBox {{
        background-color: {t['bg_base']};
        color: {t['text_1']};
        border: 1px solid {t['border']};
        border-radius: {t['radius_sm']}px;
        padding: 4px 8px;
        min-height: 24px;
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border-color: {t['accent']};
    }}
    /* 下拉框 */
    QComboBox {{
        background-color: {t['bg_base']};
        color: {t['text_1']};
        border: 1px solid {t['border']};
        border-radius: {t['radius_sm']}px;
        padding: 4px 8px;
        min-height: 24px;
    }}
    QComboBox:hover {{
        border-color: {t['accent']};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {t['bg_elevated']};
        color: {t['text_1']};
        selection-background-color: {t['bg_hover']};
        border: 1px solid {t['border']};
    }}
    /* 复选框 */
    QCheckBox {{
        spacing: 6px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {t['border']};
        border-radius: 3px;
        background-color: {t['bg_base']};
    }}
    QCheckBox::indicator:checked {{
        background-color: {t['accent']};
        border-color: {t['accent']};
    }}
    /* 单选按钮 */
    QRadioButton {{
        spacing: 6px;
    }}
    QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {t['border']};
        border-radius: 8px;
        background-color: {t['bg_base']};
    }}
    QRadioButton::indicator:checked {{
        background-color: {t['accent']};
        border-color: {t['accent']};
    }}
    /* 进度条 */
    QProgressBar {{
        background-color: {t['bg_hover']};
        border: none;
        border-radius: {t['radius_sm']}px;
        text-align: center;
        min-height: 8px;
        max-height: 8px;
    }}
    QProgressBar::chunk {{
        background-color: {t['accent']};
        border-radius: {t['radius_sm']}px;
    }}
    /* 滚动条 */
    QScrollBar:vertical {{
        background-color: {t['bg_surface']};
        width: 8px;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background-color: {t['border']};
        border-radius: 4px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {t['text_3']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background-color: {t['bg_surface']};
        height: 8px;
        border: none;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {t['border']};
        border-radius: 4px;
        min-width: 30px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: {t['text_3']};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    /* 树状视图 / 表格 */
    QTreeWidget, QTableWidget, QListView, QListWidget {{
        background-color: {t['bg_base']};
        color: {t['text_1']};
        border: 1px solid {t['border']};
        outline: none;
    }}
    QTreeWidget::item, QTableWidget::item, QListView::item, QListWidget::item {{
        padding: 4px 8px;
    }}
    QTreeWidget::item:selected, QTableWidget::item:selected,
    QListView::item:selected, QListWidget::item:selected {{
        background-color: {t['bg_hover']};
        color: {t['text_1']};
    }}
    QTreeWidget::item:hover, QTableWidget::item:hover,
    QListView::item:hover, QListWidget::item:hover {{
        background-color: {t['bg_hover']};
    }}
    /* 选项卡 */
    QTabWidget::pane {{
        border: 1px solid {t['border']};
        border-top: none;
        background-color: {t['bg_base']};
    }}
    QTabBar::tab {{
        background-color: {t['bg_surface']};
        color: {t['text_2']};
        border: 1px solid {t['border']};
        border-bottom: none;
        padding: 6px 16px;
        margin-right: 2px;
        border-top-left-radius: {t['radius_sm']}px;
        border-top-right-radius: {t['radius_sm']}px;
    }}
    QTabBar::tab:selected {{
        background-color: {t['bg_base']};
        color: {t['text_1']};
        border-bottom-color: {t['bg_base']};
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {t['bg_hover']};
    }}
    /* 菜单 */
    QMenuBar {{
        background-color: {t['bg_surface']};
        border-bottom: 1px solid {t['border']};
    }}
    QMenuBar::item {{
        padding: 4px 12px;
    }}
    QMenuBar::item:selected {{
        background-color: {t['bg_hover']};
    }}
    QMenu {{
        background-color: {t['bg_elevated']};
        border: 1px solid {t['border']};
        border-radius: {t['radius_sm']}px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 32px 6px 16px;
        border-radius: {t['radius_sm']}px;
    }}
    QMenu::item:selected {{
        background-color: {t['bg_hover']};
    }}
    QMenu::separator {{
        height: 1px;
        background-color: {t['border']};
        margin: 4px 8px;
    }}
    /* 状态栏 */
    QStatusBar {{
        background-color: {t['bg_surface']};
        border-top: 1px solid {t['border']};
        color: {t['text_3']};
        font-size: 8pt;
    }}
    /* 工具提示 */
    QToolTip {{
        background-color: {t['bg_elevated']};
        color: {t['text_1']};
        border: 1px solid {t['border']};
        border-radius: {t['radius_sm']}px;
        padding: 4px 8px;
    }}
    /* 文本编辑 */
    QTextEdit, QPlainTextEdit {{
        background-color: {t['bg_base']};
        color: {t['text_1']};
        border: 1px solid {t['border']};
        border-radius: {t['radius_sm']}px;
    }}
    /* 分组框 */
    QGroupBox {{
        border: 1px solid {t['border']};
        border-radius: {t['radius_md']}px;
        margin-top: 12px;
        padding-top: 12px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 8px;
        color: {t['text_2']};
    }}
    /* 滑块 */
    QSlider::groove:horizontal {{
        height: 4px;
        background-color: {t['bg_hover']};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background-color: {t['accent']};
        width: 16px;
        height: 16px;
        margin: -6px 0;
        border-radius: 8px;
    }}
    QSlider::sub-page:horizontal {{
        background-color: {t['accent']};
        border-radius: 2px;
    }}
    /* 分割器 */
    QSplitter::handle {{
        background-color: {t['border']};
        width: 1px;
    }}
    QSplitter::handle:hover {{
        background-color: {t['accent']};
    }}
    """


def _build_palette(theme: dict) -> QPalette:
    """根据主题令牌生成 QPalette"""
    t = theme
    p = QPalette()

    def _c(hex_color):
        return QColor(hex_color)

    p.setColor(QPalette.ColorRole.Window, _c(t["bg_base"]))
    p.setColor(QPalette.ColorRole.WindowText, _c(t["text_1"]))
    p.setColor(QPalette.ColorRole.Base, _c(t["bg_default"]))
    p.setColor(QPalette.ColorRole.AlternateBase, _c(t["bg_hover"]))
    p.setColor(QPalette.ColorRole.ToolTipBase, _c(t["bg_elevated"]))
    p.setColor(QPalette.ColorRole.ToolTipText, _c(t["text_1"]))
    p.setColor(QPalette.ColorRole.Text, _c(t["text_1"]))
    p.setColor(QPalette.ColorRole.Button, _c(t["bg_elevated"]))
    p.setColor(QPalette.ColorRole.ButtonText, _c(t["text_1"]))
    p.setColor(QPalette.ColorRole.BrightText, _c(t["danger"]))
    p.setColor(QPalette.ColorRole.Highlight, _c(t["accent"]))
    p.setColor(QPalette.ColorRole.HighlightedText, _c("#ffffff"))
    p.setColor(QPalette.ColorRole.Link, _c(t["accent"]))
    p.setColor(QPalette.ColorRole.LinkVisited, _c(t["bilibili"]))

    # Disabled states
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, _c(t["text_3"]))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, _c(t["text_3"]))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, _c(t["text_3"]))

    return p


# ── 全局 QApplication 引用 ─────────────────
qapp: QApplication = None  # 由 init_theme() 设置


def init_theme(app: QApplication, dark: bool = False):
    """初始化全局主题

    必须在 QApplication 创建后调用。
    """
    global qapp, C
    qapp = app

    theme_dict = THEME_DARK if dark else THEME_LIGHT
    C.clear()
    C.update(theme_dict)

    # 应用 QPalette
    app.setPalette(_build_palette(theme_dict))

    # 应用 QSS
    app.setStyleSheet(_build_qss(theme_dict))

    # 全局字体
    font = QFont("Microsoft YaHei UI", 9)
    app.setFont(font)

    logger.info("主题已初始化: %s", "暗色" if dark else "亮色")


def toggle_theme():
    """切换深色/亮色主题"""
    is_dark = C.get("bg_base", "#ffffff") == "#0d1117"
    init_theme(qapp, dark=not is_dark)
