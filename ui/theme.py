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
    "bg_base": "#ffffff",
    "bg_surface": "#f6f8fa",
    "bg_elevated": "#ffffff",
    "bg_hover": "#eef1f5",
    "border": "#d0d7de",
    "border_sub": "#e8ecf0",
    "bilibili": "#fb7299",
    "bilibili_dim": "#e05580",
    "accent": "#0969da",
    "success": "#1a7f37",
    "warning": "#9a6700",
    "danger": "#d1242f",
    "text_1": "#1f2328",
    "text_2": "#656d76",
    "text_3": "#8b949e",
    "chart_line": "#fb7299",
    "chart_area": "#fb7299",
    "chart_dot": "#fb7299",
    "thresh_10w": "#1a7f37",
    "thresh_100w": "#9a6700",
    "thresh_1000w": "#8250df",
    "canvas_bg": "#ffffff",
    "canvas_text": "#1f2328",
    "log_debug": "#656d76",
    "log_info": "#0969da",
    "log_warn": "#9a6700",
    "log_error": "#d1242f",
    "log_time": "#8b949e",
    "grid_line": "#e8ecf0",
    # ── 设计系统令牌 ────────────────────────
    "radius_sm": 6,
    "radius_md": 8,
    "radius_lg": 12,
    "radius_xl": 16,
    "brand": "#fb7299",
    "brand_hover": "#e05580",
    "text_primary": "#1f2328",
    "text_secondary": "#656d76",
    "text_tertiary": "#8b949e",
    "bg_default": "#ffffff",
    "border_default": "#d0d7de",
    "border_subtle": "#e8ecf0",
    # 大屏专用（深色）
    "dash_bg": "#0d1117",
    "dash_card_bg": "#161b22",
    "dash_text_1": "#f0f6fc",
    "dash_text_2": "#8b949e",
}

# 暗色主题配色
THEME_DARK = {
    "bg_base": "#0d1117",
    "bg_surface": "#161b22",
    "bg_elevated": "#1c2128",
    "bg_hover": "#292e36",
    "border": "#30363d",
    "border_sub": "#21262d",
    "bilibili": "#fb7299",
    "bilibili_dim": "#e05580",
    "accent": "#58a6ff",
    "success": "#3fb950",
    "warning": "#d29922",
    "danger": "#f85149",
    "text_1": "#f0f6fc",
    "text_2": "#8b949e",
    "text_3": "#484f58",
    "chart_line": "#fb7299",
    "chart_area": "#fb7299",
    "chart_dot": "#fb7299",
    "thresh_10w": "#3fb950",
    "thresh_100w": "#d29922",
    "thresh_1000w": "#bc8cff",
    "canvas_bg": "#0d1117",
    "canvas_text": "#f0f6fc",
    "log_debug": "#8b949e",
    "log_info": "#58a6ff",
    "log_warn": "#d29922",
    "log_error": "#f85149",
    "log_time": "#484f58",
    "grid_line": "#21262d",
    # ── 设计系统令牌 ────────────────────────
    "radius_sm": 6,
    "radius_md": 8,
    "radius_lg": 12,
    "radius_xl": 16,
    "brand": "#fb7299",
    "brand_hover": "#e05580",
    "text_primary": "#f0f6fc",
    "text_secondary": "#8b949e",
    "text_tertiary": "#484f58",
    "bg_default": "#0d1117",
    "border_default": "#30363d",
    "border_subtle": "#21262d",
    # 大屏专用（深色，暗色模式下不变）
    "dash_bg": "#0d1117",
    "dash_card_bg": "#161b22",
    "dash_text_1": "#f0f6fc",
    "dash_text_2": "#8b949e",
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
