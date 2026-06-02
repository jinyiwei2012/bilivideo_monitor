"""
主题系统模块 — 设计令牌（固定亮色主题）
========================================

集中管理所有颜色、圆角、间距等设计系统令牌。
各 UI 模块通过 ``from ui.theme import C`` 获取颜色字典。

设计原则：
  - 主题色：B 站粉 (#fb7299) 为主品牌色
  - 背景层级：bg_base → bg_surface → bg_elevated → bg_hover（从深到浅的视觉层次）
  - 文字层级：text_1（主要）、text_2（次要）、text_3（辅助）
  - 语义色：success/警告（warning）/危险（danger）/强调（accent）
  - 图表专用色：chart_line/area/dot、阈值颜色、日志级别颜色

Token 命名：
  - `radius_*`：圆角值（sm:6, md:8, lg:12, xl:16）
  - `C` 是 THEME 的浅拷贝，允许运行时覆盖而不污染原始字典

辅助函数：
  - ``get_radius(size)``：获取指定级别的圆角值
  - ``get_space(index)``：获取间距值（8px 基准，index 0~8）
  - ``init_theme(root)``：一次性初始化 CTk 外观 + ttk 样式
  - ``rounded_rect(canvas, ...)``：画 Canvas 圆角矩形
  - ``apply_rounded_style(widget, ...)``：为控件应用圆角样式
"""

import logging
import customtkinter as ctk

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# 亮色主题配色字典
# ═══════════════════════════════════════════════════════════════════════════════
THEME = {
    "bg_base": "#ffffff",       # 最底层背景
    "bg_surface": "#f6f8fa",    # 表面层背景（卡片、面板）
    "bg_elevated": "#ffffff",   # 浮层背景（输入框、表格）
    "bg_hover": "#eef1f5",      # 悬停态背景
    "border": "#d0d7de",         # 主边框
    "border_sub": "#e8ecf0",     # 次级边框（更淡）
    "bilibili": "#fb7299",       # B 站品牌粉
    "bilibili_dim": "#e05580",   # B 站粉暗色变体
    "accent": "#0969da",         # 强调色（蓝色）
    "success": "#1a7f37",        # 成功/正常
    "warning": "#9a6700",        # 警告
    "danger": "#d1242f",         # 危险/错误
    "text_1": "#1f2328",         # 主要文字
    "text_2": "#656d76",         # 次要文字
    "text_3": "#8b949e",         # 辅助文字（占位符等）
    "chart_line": "#fb7299",     # 图表折线色
    "chart_area": "#fb7299",     # 图表面积色
    "chart_dot": "#fb7299",      # 图表数据点色
    "thresh_10w": "#1a7f37",     # 10万阈值线颜色
    "thresh_100w": "#9a6700",    # 100万阈值线颜色
    "thresh_1000w": "#8250df",   # 1000万阈值线颜色
    "canvas_bg": "#ffffff",      # Canvas 背景
    "canvas_text": "#1f2328",    # Canvas 文字
    "log_debug": "#656d76",      # 日志 DEBUG 颜色
    "log_info": "#0969da",       # 日志 INFO 颜色
    "log_warn": "#9a6700",       # 日志 WARN 颜色
    "log_error": "#d1242f",      # 日志 ERROR 颜色
    "log_time": "#8b949e",       # 日志时间戳颜色
    "grid_line": "#e8ecf0",      # 图表网格线颜色
    # ── 设计系统令牌（语义化别名）────
    "radius_sm": 6,              # 小圆角
    "radius_md": 8,              # 中圆角
    "radius_lg": 12,             # 大圆角
    "radius_xl": 16,             # 超大圆角
    "brand": "#fb7299",          # 品牌色（同 bilibili）
    "brand_hover": "#e05580",    # 品牌悬停色
    "text_primary": "#1f2328",   # 主要文字（同 text_1）
    "text_secondary": "#656d76", # 次要文字（同 text_2）
    "text_tertiary": "#8b949e",  # 辅助文字（同 text_3）
    "bg_default": "#ffffff",     # 默认背景（同 bg_base）
    "border_default": "#d0d7de", # 默认边框（同 border）
    "border_subtle": "#e8ecf0",  # 微妙边框（同 border_sub）
}

# 全局颜色字典 — 所有 UI 模块通过 from ui.theme import C 使用
# shallow copy 以允许运行时覆盖而不污染 THEME 原始字典
C = dict(THEME)


# ── 设计系统辅助函数 ────────────────────────


def get_radius(size="md"):
    """
    获取指定级别的圆角值。

    :param size: "sm"(6) | "md"(8) | "lg"(12) | "xl"(16)，默认 md
    :returns: 圆角像素值
    """
    return C.get(f"radius_{size}", 8)


def get_space(index):
    """
    获取 8px 基准的间距值。

    :param index: 0~8，对应 [0, 4, 8, 12, 16, 24, 32, 48, 64] px
    :returns: 间距像素值
    """
    SPACE = [0, 4, 8, 12, 16, 24, 32, 48, 64]
    return SPACE[min(index, len(SPACE) - 1)]


# ── ttk Style 配置 ─────────────────────────────
_CTK_INITIALIZED = False  # 全局标志：CTk 是否已初始化


def init_theme(root):
    """
    一次性初始化主题：CTk 外观设置 + ttk 样式配置。

    调用两次只会执行一次（_CTK_INITIALIZED 标志保护）。
    需要传入 Tk root 窗口引用以正确初始化 Style。

    :param root: Tk 根窗口
    """
    global _CTK_INITIALIZED
    if not _CTK_INITIALIZED:
        ctk.set_appearance_mode("light")     # 固定亮色模式
        ctk.set_default_color_theme("blue")   # CTk 默认蓝色主题
        _CTK_INITIALIZED = True
    _apply_ttk_styles(root)


def _apply_ttk_styles(root):
    """
    根据当前 C 字典配置所有 ttk 样式。

    涵盖的样式：
      - 全局默认 (".")：背景、文字、边框、选择色
      - TFrame / TLabel 变体（Surface, Elevated, Muted, Sub, Bilibili, Success 等）
      - TSeparator（分隔线）
      - TScrollbar（滚动条）
      - TButton / Primary.TButton / Danger.TButton（按钮）
      - TEntry（输入框）
      - TNotebook / TNotebook.Tab（标签页）
      - Treeview / Treeview.Heading（树形视图）
      - TSpinbox（数值调节框）

    :param root: Tk 根窗口
    """
    from tkinter import ttk
    from ui.helpers import FONT

    style = ttk.Style(root)
    style.theme_use("clam")  # 使用 clam 主题以获得最佳定制效果

    # ── 全局默认样式 ──
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
    # Frame 变体
    style.configure("TFrame", background=C["bg_base"])
    style.configure("Surface.TFrame", background=C["bg_surface"])
    style.configure("Elevated.TFrame", background=C["bg_elevated"])

    # Label 变体 — 在不同背景上的文字标签
    style.configure("TLabel", background=C["bg_base"], foreground=C["text_1"])
    style.configure("Surface.TLabel", background=C["bg_surface"], foreground=C["text_1"])
    style.configure("Muted.TLabel", background=C["bg_surface"], foreground=C["text_3"])
    style.configure("Sub.TLabel", background=C["bg_surface"], foreground=C["text_2"])
    style.configure("Bilibili.TLabel", background=C["bg_surface"], foreground=C["bilibili"])
    style.configure("Success.TLabel", background=C["bg_surface"], foreground=C["success"])
    style.configure("Danger.TLabel", background=C["bg_surface"], foreground=C["danger"])
    style.configure("Warning.TLabel", background=C["bg_surface"], foreground=C["warning"])
    style.configure("Accent.TLabel", background=C["bg_surface"], foreground=C["accent"])

    # Elevated 背景上的 Label 变体
    style.configure("EL.TLabel", background=C["bg_elevated"], foreground=C["text_1"])
    style.configure("ELSub.TLabel", background=C["bg_elevated"], foreground=C["text_2"])
    style.configure("ELMuted.TLabel", background=C["bg_elevated"], foreground=C["text_3"])

    # 分隔线
    style.configure("TSeparator", background=C["border"])

    # 滚动条
    style.configure(
        "TScrollbar",
        background=C["bg_elevated"],
        troughcolor=C["bg_surface"],
        bordercolor=C["bg_surface"],
        arrowcolor=C["text_3"],
        relief="flat",
    )

    # 普通按钮
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
    # 主按钮（B站粉）
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
    # 危险按钮
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
        background=[("active", "#f8514922")],  # 危险悬停色（半透明红）
    )

    # 输入框
    style.configure(
        "TEntry",
        fieldbackground=C["bg_elevated"],
        foreground=C["text_1"],
        bordercolor=C["border"],
        insertcolor=C["text_1"],
        relief="flat",
        padding=4,
    )
    style.map("TEntry", bordercolor=[("focus", C["bilibili"])])  # 聚焦时边框变粉

    # 标签页
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

    # 树形视图
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

    # 数值调节框
    style.configure(
        "TSpinbox",
        fieldbackground=C["bg_elevated"],
        foreground=C["text_1"],
        bordercolor=C["border"],
        arrowcolor=C["text_2"],
        relief="flat",
    )

    # Root 窗口背景
    root.configure(bg=C["bg_base"])


# ── 辅助函数 ─────────────────────────────────────


def rounded_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    """
    在 Canvas 上绘制圆角矩形。
    通过 create_polygon 构建平滑顶点路径实现。

    :param canvas: tk.Canvas 控件
    :param x1, y1: 左上角坐标
    :param x2, y2: 右下角坐标
    :param r: 圆角半径
    :param kwargs: 传递给 create_polygon 的额外参数（如 fill, outline）
    :returns: Canvas 图形 ID
    """
    pts = [
        x1 + r, y1,       # 上边起始
        x2 - r, y1,       # 右上角弧前
        x2, y1,           # 右上角顶
        x2, y1 + r,       # 右上角弧后
        x2, y2 - r,       # 右下角弧前
        x2, y2,           # 右下角底
        x2 - r, y2,       # 右下角弧后
        x1 + r, y2,       # 左下角弧前
        x1, y2,           # 左下角底
        x1, y2 - r,       # 左下角弧后
        x1, y1 + r,       # 左上角弧后
        x1, y1,           # 回到起点
    ]
    return canvas.create_polygon(pts, smooth=True, **kwargs)


def apply_rounded_style(widget, radius_key="radius_md"):
    """
    为控件应用圆角样式（通过 highlightthickness + highlightbackground 模拟）。

    :param widget: tk.Widget
    :param radius_key: 圆角级别 key（"radius_sm"/"radius_md"/"radius_lg"/"radius_xl"）
    """
    try:
        widget.configure(highlightthickness=1, highlightbackground=C.get("border_default", "#30363d"), relief="flat")
    except Exception as e:
        logger.debug("应用圆角样式失败: %s", e)
