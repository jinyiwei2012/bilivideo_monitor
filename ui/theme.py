"""
主题系统 - 设计令牌（固定亮色主题）
"""

import logging
import customtkinter as ctk

logger = logging.getLogger(__name__)

# 亮色主题配色
THEME = {
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
}

# 全局颜色字典（所有 UI 模块 from ui.theme import C 后使用）
C = dict(THEME)


# ── 设计系统辅助函数 ────────────────────────


def get_radius(size="md"):
    """获取圆角值 (sm:6, md:8, lg:12, xl:16)"""
    return C.get(f"radius_{size}", 8)


def get_space(index):
    """获取间距值 (8px基准, index: 0-8)"""
    SPACE = [0, 4, 8, 12, 16, 24, 32, 48, 64]
    return SPACE[min(index, len(SPACE) - 1)]


# ── ttk Style 配置 ─────────────────────────────
_CTK_INITIALIZED = False


def init_theme(root):
    """一次性初始化主题：CTk 外观 + ttk 样式"""
    global _CTK_INITIALIZED
    if not _CTK_INITIALIZED:
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        _CTK_INITIALIZED = True
    _apply_ttk_styles(root)


def _apply_ttk_styles(root):
    """根据当前 C 字典配置所有 ttk 样式"""
    from tkinter import ttk
    from ui.helpers import FONT

    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(
        ".",
        background=C["bg_base"],
        foreground=C["text_1"],
        bordercolor=C["border"],
        troughcolor=C["bg_elevated"],
        selectbackground=C["bilibili"],
        selectforeground="#ffffff",
        font=FONT,
    )
    style.configure("TFrame", background=C["bg_base"])
    style.configure("Surface.TFrame", background=C["bg_surface"])
    style.configure("Elevated.TFrame", background=C["bg_elevated"])

    style.configure("TLabel", background=C["bg_base"], foreground=C["text_1"])
    style.configure("Surface.TLabel", background=C["bg_surface"], foreground=C["text_1"])
    style.configure("Muted.TLabel", background=C["bg_surface"], foreground=C["text_3"])
    style.configure("Sub.TLabel", background=C["bg_surface"], foreground=C["text_2"])
    style.configure("Bilibili.TLabel", background=C["bg_surface"], foreground=C["bilibili"])
    style.configure("Success.TLabel", background=C["bg_surface"], foreground=C["success"])
    style.configure("Danger.TLabel", background=C["bg_surface"], foreground=C["danger"])
    style.configure("Warning.TLabel", background=C["bg_surface"], foreground=C["warning"])
    style.configure("Accent.TLabel", background=C["bg_surface"], foreground=C["accent"])

    style.configure("EL.TLabel", background=C["bg_elevated"], foreground=C["text_1"])
    style.configure("ELSub.TLabel", background=C["bg_elevated"], foreground=C["text_2"])
    style.configure("ELMuted.TLabel", background=C["bg_elevated"], foreground=C["text_3"])

    style.configure("TSeparator", background=C["border"])

    style.configure(
        "TScrollbar",
        background=C["bg_elevated"],
        troughcolor=C["bg_surface"],
        bordercolor=C["bg_surface"],
        arrowcolor=C["text_3"],
        relief="flat",
    )

    style.configure(
        "TButton",
        background=C["bg_elevated"],
        foreground=C["text_2"],
        bordercolor=C["border"],
        relief="flat",
        padding=(8, 4),
        font=FONT,
    )
    style.map(
        "TButton",
        background=[("active", C["bg_hover"]), ("pressed", C["bg_hover"])],
        foreground=[("active", C["text_1"])],
    )
    style.configure(
        "Primary.TButton",
        background=C["bilibili"],
        foreground="#ffffff",
        font=FONT,
        padding=(10, 5),
    )
    style.map(
        "Primary.TButton",
        background=[("active", C["bilibili_dim"]), ("pressed", C["bilibili_dim"])],
    )
    style.configure(
        "Danger.TButton",
        background=C["bg_surface"],
        foreground=C["danger"],
        bordercolor=C["danger"],
        font=FONT,
        padding=(8, 4),
    )
    style.map(
        "Danger.TButton",
        background=[("active", "#f8514922")],
    )

    style.configure(
        "TEntry",
        fieldbackground=C["bg_elevated"],
        foreground=C["text_1"],
        bordercolor=C["border"],
        insertcolor=C["text_1"],
        relief="flat",
        padding=4,
    )
    style.map("TEntry", bordercolor=[("focus", C["bilibili"])])

    style.configure(
        "TNotebook",
        background=C["bg_surface"],
        bordercolor=C["border"],
        tabmargins=[0, 0, 0, 0],
    )
    style.configure(
        "TNotebook.Tab",
        background=C["bg_surface"],
        foreground=C["text_2"],
        padding=[14, 6],
        font=FONT,
        bordercolor=C["border"],
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", C["bg_surface"])],
        foreground=[("selected", C["bilibili"])],
        focuscolor=[("selected", C["bilibili"])],
    )

    style.configure(
        "Treeview",
        background=C["bg_elevated"],
        fieldbackground=C["bg_elevated"],
        foreground=C["text_1"],
        rowheight=24,
        bordercolor=C["border"],
    )
    style.configure(
        "Treeview.Heading",
        background=C["bg_surface"],
        foreground=C["text_2"],
        bordercolor=C["border"],
        relief="flat",
        font=FONT,
    )
    style.map(
        "Treeview",
        background=[("selected", C["bilibili_dim"])],
        foreground=[("selected", "#ffffff")],
    )

    style.configure(
        "TSpinbox",
        fieldbackground=C["bg_elevated"],
        foreground=C["text_1"],
        bordercolor=C["border"],
        arrowcolor=C["text_2"],
        relief="flat",
    )

    root.configure(bg=C["bg_base"])


# ── 辅助函数 ─────────────────────────────────────


def rounded_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    """在 Canvas 上画圆角矩形"""
    pts = [
        x1 + r,
        y1,
        x2 - r,
        y1,
        x2,
        y1,
        x2,
        y1 + r,
        x2,
        y2 - r,
        x2,
        y2,
        x2 - r,
        y2,
        x1 + r,
        y2,
        x1,
        y2,
        x1,
        y2 - r,
        x1,
        y1 + r,
        x1,
        y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kwargs)


def apply_rounded_style(widget, radius_key="radius_md"):
    """为控件应用圆角样式 (通过 highlightthickness 模拟)"""
    C.get(radius_key, 8)
    try:
        widget.configure(highlightthickness=1, highlightbackground=C.get("border_default", "#30363d"), relief="flat")
    except Exception as e:
        logger.debug("应用圆角样式失败: %s", e)
