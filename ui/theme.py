"""
主题系统 - 设计令牌 & 亮/暗主题切换
"""
import tkinter as tk

# 暗色主题配色（GitHub Dark 风格）
THEME_DARK = {
    "bg_base":      "#0d1117",
    "bg_surface":   "#161b22",
    "bg_elevated":  "#21262d",
    "bg_hover":     "#30363d",
    "border":       "#30363d",
    "border_sub":   "#21262d",

    "bilibili":     "#fb7299",
    "bilibili_dim": "#c45a79",

    "accent":       "#58a6ff",
    "success":      "#3fb950",
    "warning":      "#d29922",
    "danger":       "#f85149",

    "text_1":       "#e6edf3",
    "text_2":       "#8b949e",
    "text_3":       "#484f58",

    "chart_line":   "#fb7299",
    "chart_area":   "#fb7299",
    "chart_dot":    "#fb7299",
    "thresh_10w":   "#3fb950",
    "thresh_100w":  "#d29922",
    "thresh_1000w": "#a78bfa",

    "canvas_bg":    "#0d1117",
    "canvas_text":  "#c9d1d9",
    "log_debug":    "#8b949e",
    "log_info":     "#58a6ff",
    "log_warn":     "#d29922",
    "log_error":    "#f85149",
    "log_time":     "#6e7681",
    "grid_line":    "#21262d",

    # ── 设计系统令牌 ────────────────────────
    # 圆角系统
    "radius_sm": 6,
    "radius_md": 8,
    "radius_lg": 12,
    "radius_xl": 16,

    # 语义化色彩别名 (便于代码理解)
    "brand":          "#fb7299",
    "brand_hover":    "#c45a79",
    "text_primary":   "#e6edf3",
    "text_secondary": "#8b949e",
    "text_tertiary":  "#484f58",
    "bg_default":     "#0d1117",
    "border_default": "#30363d",
    "border_subtle":  "#21262d",
}

# 亮色主题配色
THEME_LIGHT = {
    "bg_base":      "#ffffff",
    "bg_surface":   "#f6f8fa",
    "bg_elevated":  "#ffffff",
    "bg_hover":     "#eef1f5",
    "border":       "#d0d7de",
    "border_sub":   "#e8ecf0",

    "bilibili":     "#fb7299",
    "bilibili_dim": "#e05580",

    "accent":       "#0969da",
    "success":      "#1a7f37",
    "warning":      "#9a6700",
    "danger":       "#d1242f",

    "text_1":       "#1f2328",
    "text_2":       "#656d76",
    "text_3":       "#8b949e",

    "chart_line":   "#fb7299",
    "chart_area":   "#fb7299",
    "chart_dot":    "#fb7299",
    "thresh_10w":   "#1a7f37",
    "thresh_100w":  "#9a6700",
    "thresh_1000w": "#8250df",

    "canvas_bg":    "#ffffff",
    "canvas_text":  "#1f2328",
    "log_debug":    "#656d76",
    "log_info":     "#0969da",
    "log_warn":     "#9a6700",
    "log_error":    "#d1242f",
    "log_time":     "#8b949e",
    "grid_line":    "#e8ecf0",

    # ── 设计系统令牌 ────────────────────────
    # 圆角系统
    "radius_sm": 6,
    "radius_md": 8,
    "radius_lg": 12,
    "radius_xl": 16,

    # 语义化色彩别名 (便于代码理解)
    "brand":          "#fb7299",
    "brand_hover":    "#e05580",
    "text_primary":   "#1f2328",
    "text_secondary": "#656d76",
    "text_tertiary":  "#8b949e",
    "bg_default":     "#ffffff",
    "border_default": "#d0d7de",
    "border_subtle":  "#e8ecf0",
}

THEMES = {"dark": THEME_DARK, "light": THEME_LIGHT}

# 当前活跃配色字典（apply_theme 会就地更新）
C = dict(THEME_DARK)


def current_theme_name():
    """返回当前主题名 dark/light"""
    if C["bg_base"] == THEME_LIGHT["bg_base"]:
        return "light"
    return "dark"


# ── 设计系统辅助函数 ────────────────────────

def get_radius(size="md"):
    """获取圆角值 (sm:6, md:8, lg:12, xl:16)"""
    return C.get(f"radius_{size}", 8)


def get_space(index):
    """获取间距值 (8px基准, index: 0-8)"""
    SPACE = [0, 4, 8, 12, 16, 24, 32, 48, 64]
    return SPACE[min(index, len(SPACE) - 1)]


# ── 控件颜色刷新 ─────────────────────────
_WIDGET_BG_ATTRS = ["bg", "background"]
_WIDGET_FG_ATTRS = ["fg", "foreground"]
_WIDGET_OTHER = {
    "tk.Canvas":  [("highlightbackground", "border")],
    "tk.Text":    [("insertbackground", "text_1"), ("highlightbackground", "bg_base")],
    "tk.Entry":   [("insertbackground", "text_1"), ("highlightbackground", "border")],
    "tk.Menu":    [("activebackground", "bg_hover"), ("activeforeground", "text_1")],
}

# (控件类型, 属性) → C 的 key
_SEMANTIC_BG_MAP = {
    ("tk.Frame", "bg"): [
        ("bg_base", "bg_base"), ("bg_surface", "bg_surface"),
        ("bg_elevated", "bg_elevated"), ("bg_hover", "bg_hover"),
        ("border", "border"), ("border_sub", "border_sub"),
    ],
    ("tk.Label", "bg"): [
        ("bg_base", "bg_base"), ("bg_surface", "bg_surface"),
        ("bg_elevated", "bg_elevated"), ("bg_hover", "bg_hover"),
    ],
    ("tk.Label", "fg"): [
        ("text_1", "text_1"), ("text_2", "text_2"), ("text_3", "text_3"),
        ("bilibili", "bilibili"), ("accent", "accent"),
        ("success", "success"), ("warning", "warning"), ("danger", "danger"),
        ("bilibili_dim", "bilibili_dim"),
    ],
    ("tk.Canvas", "bg"): [
        ("bg_base", "canvas_bg"), ("bg_surface", "bg_surface"),
        ("bg_elevated", "bg_elevated"),
    ],
    ("tk.Text", "bg"): [
        ("bg_base", "canvas_bg"), ("bg_elevated", "bg_elevated"),
    ],
    ("tk.Text", "fg"): [
        ("text_1", "canvas_text"), ("text_2", "canvas_text"),
    ],
    ("tk.Entry", "bg"): [
        ("bg_elevated", "bg_elevated"),
    ],
    ("tk.Entry", "fg"): [
        ("text_1", "text_1"), ("text_3", "text_3"),
    ],
    ("tk.Menu", "bg"): [
        ("bg_elevated", "bg_elevated"),
    ],
    ("tk.Menu", "fg"): [
        ("text_1", "text_1"), ("text_2", "text_2"),
    ],
    ("tk.Listbox", "bg"): [
        ("bg_base", "bg_base"), ("bg_elevated", "bg_elevated"), ("bg_surface", "bg_surface"),
    ],
    ("tk.Listbox", "fg"): [
        ("text_1", "text_1"), ("text_2", "text_2"),
    ],
    ("tk.LabelFrame", "bg"): [
        ("bg_base", "bg_base"), ("bg_surface", "bg_surface"),
        ("bg_elevated", "bg_elevated"),
    ],
    ("tk.LabelFrame", "fg"): [
        ("text_1", "text_1"), ("text_2", "text_2"),
    ],
}

# 旧暗色/亮色值 → 语义 key 的反向索引
_OLD_VALUE_TO_KEY = {}
for _widget_type, _attr in _SEMANTIC_BG_MAP:
    for _old_val, _key in _SEMANTIC_BG_MAP[(_widget_type, _attr)]:
        _OLD_VALUE_TO_KEY.setdefault((_widget_type, _attr, THEME_DARK[_key]), _key)
        _OLD_VALUE_TO_KEY.setdefault((_widget_type, _attr, THEME_LIGHT[_key]), _key)


def _recolor_widget_tree(widget):
    """递归刷新所有原生 tk 控件的颜色"""
    cls = widget.winfo_class()

    for attr in _WIDGET_BG_ATTRS:
        _try_recolor(widget, cls, attr)
    for attr in _WIDGET_FG_ATTRS:
        _try_recolor(widget, cls, attr)

    if cls in _WIDGET_OTHER:
        for attr, c_key in _WIDGET_OTHER[cls]:
            try:
                widget[attr] = C[c_key]
            except Exception:
                pass

    if cls == "tk.Canvas":
        try:
            widget.configure(bg=C.get("canvas_bg", C["bg_base"]))
        except Exception:
            pass

    if cls == "tk.Text":
        _recolor_text_tags(widget)

    if cls == "tk.Menu":
        try:
            widget.configure(bg=C["bg_elevated"], fg=C["text_1"],
                             activebackground=C["bg_hover"],
                             activeforeground=C["text_1"])
        except Exception:
            pass

    for child in widget.winfo_children():
        _recolor_widget_tree(child)


def _try_recolor(widget, cls, attr):
    """根据控件当前值推断语义 key 并刷新"""
    try:
        cur = widget.cget(attr)
        lookup = (cls, attr, cur)
        if lookup in _OLD_VALUE_TO_KEY:
            key = _OLD_VALUE_TO_KEY[lookup]
            new_val = C[key]
        else:
            return
        widget.configure(**{attr: new_val})
    except Exception:
        pass


def _recolor_text_tags(text_widget):
    """刷新 tk.Text 的 tag 颜色"""
    tag_map = {
        "DEBUG":  ("log_debug",  "foreground"),
        "INFO":   ("log_info",   "foreground"),
        "WARNING":("log_warn",   "foreground"),
        "ERROR":  ("log_error",  "foreground"),
        "TIME":   ("log_time",   "foreground"),
        "head":   ("bilibili",   "foreground"),
        "mono":   ("text_1",     "foreground"),
        "mono_b": ("bilibili",   "foreground"),
        "mono_ok":("success",    "foreground"),
        "mono_accent":("accent", "foreground"),
        "title":  ("text_3",     "foreground"),
        "total":  ("accent",     "foreground"),
        "separator":("text_3",   "foreground"),
        "label":  ("text_3",     "foreground"),
        "value":  ("text_1",     "foreground"),
        "detail": ("accent",     "foreground"),
    }
    for tag, (c_key, kw) in tag_map.items():
        try:
            text_widget.tag_configure(tag, **{kw: C[c_key]})
        except Exception:
            pass


# ── ttk Style 配置 ─────────────────────────────
def _apply_ttk_styles(root, FONT):
    """根据当前 C 字典配置所有 ttk 样式（不重设 C 本身）"""
    from tkinter import ttk
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".",
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
    style.configure("Muted.TLabel",   background=C["bg_surface"], foreground=C["text_3"])
    style.configure("Sub.TLabel",     background=C["bg_surface"], foreground=C["text_2"])
    style.configure("Bilibili.TLabel",background=C["bg_surface"], foreground=C["bilibili"])
    style.configure("Success.TLabel", background=C["bg_surface"], foreground=C["success"])
    style.configure("Danger.TLabel",  background=C["bg_surface"], foreground=C["danger"])
    style.configure("Warning.TLabel", background=C["bg_surface"], foreground=C["warning"])
    style.configure("Accent.TLabel",  background=C["bg_surface"], foreground=C["accent"])

    style.configure("EL.TLabel",     background=C["bg_elevated"], foreground=C["text_1"])
    style.configure("ELSub.TLabel",  background=C["bg_elevated"], foreground=C["text_2"])
    style.configure("ELMuted.TLabel",background=C["bg_elevated"], foreground=C["text_3"])

    style.configure("TSeparator", background=C["border"])

    style.configure("TScrollbar",
        background=C["bg_elevated"],
        troughcolor=C["bg_surface"],
        bordercolor=C["bg_surface"],
        arrowcolor=C["text_3"],
        relief="flat",
    )

    style.configure("TButton",
        background=C["bg_elevated"],
        foreground=C["text_2"],
        bordercolor=C["border"],
        relief="flat",
        padding=(8, 4),
        font=FONT,
    )
    style.map("TButton",
        background=[("active", C["bg_hover"]), ("pressed", C["bg_hover"])],
        foreground=[("active", C["text_1"])],
    )
    style.configure("Primary.TButton",
        background=C["bilibili"],
        foreground="#ffffff",
        font=FONT,
        padding=(10, 5),
    )
    style.map("Primary.TButton",
        background=[("active", C["bilibili_dim"]), ("pressed", C["bilibili_dim"])],
    )
    style.configure("Danger.TButton",
        background=C["bg_surface"],
        foreground=C["danger"],
        bordercolor=C["danger"],
        font=FONT,
        padding=(8, 4),
    )
    style.map("Danger.TButton",
        background=[("active", "#f8514922")],
    )

    style.configure("TEntry",
        fieldbackground=C["bg_elevated"],
        foreground=C["text_1"],
        bordercolor=C["border"],
        insertcolor=C["text_1"],
        relief="flat",
        padding=4,
    )
    style.map("TEntry", bordercolor=[("focus", C["bilibili"])])

    style.configure("TNotebook",
        background=C["bg_surface"],
        bordercolor=C["border"],
        tabmargins=[0, 0, 0, 0],
    )
    style.configure("TNotebook.Tab",
        background=C["bg_surface"],
        foreground=C["text_2"],
        padding=[14, 6],
        font=FONT,
        bordercolor=C["border"],
    )
    style.map("TNotebook.Tab",
        background=[("selected", C["bg_surface"])],
        foreground=[("selected", C["bilibili"])],
        focuscolor=[("selected", C["bilibili"])],
    )

    style.configure("Treeview",
        background=C["bg_elevated"],
        fieldbackground=C["bg_elevated"],
        foreground=C["text_1"],
        rowheight=24,
        bordercolor=C["border"],
    )
    style.configure("Treeview.Heading",
        background=C["bg_surface"],
        foreground=C["text_2"],
        bordercolor=C["border"],
        relief="flat",
        font=FONT,
    )
    style.map("Treeview",
        background=[("selected", C["bilibili_dim"])],
        foreground=[("selected", "#ffffff")],
    )

    style.configure("TSpinbox",
        fieldbackground=C["bg_elevated"],
        foreground=C["text_1"],
        bordercolor=C["border"],
        arrowcolor=C["text_2"],
        relief="flat",
    )

    root.configure(bg=C["bg_base"])


def apply_theme(root, theme_name="dark"):
    """切换主题：更新 C 字典 → ttk 样式 → 遍历刷新所有控件（含 Toplevel 子窗口）"""
    from ui.main_gui import FONT
    theme = THEMES.get(theme_name, THEME_DARK)
    C.clear()
    C.update(theme)
    _apply_ttk_styles(root, FONT)
    _recolor_widget_tree(root)
    # Toplevel 窗口不是 root 的子控件，需要单独遍历
    for w in root.winfo_children():
        if w.winfo_class() == "Toplevel":
            _recolor_widget_tree(w)


# 兼容旧调用
def apply_dark_style(root):
    apply_theme(root, "dark")


# ── 辅助函数 ─────────────────────────────────────
def rounded_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    """在 Canvas 上画圆角矩形"""
    pts = [
        x1+r, y1,   x2-r, y1,
        x2,   y1,   x2,   y1+r,
        x2,   y2-r, x2,   y2,
        x2-r, y2,   x1+r, y2,
        x1,   y2,   x1,   y2-r,
        x1,   y1+r, x1,   y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kwargs)


def apply_rounded_style(widget, radius_key="radius_md"):
    """为控件应用圆角样式 (通过 highlightthickness 模拟)"""
    radius = C.get(radius_key, 8)
    try:
        widget.configure(
            highlightthickness=1,
            highlightbackground=C.get("border_default", "#30363d"),
            relief="flat"
        )
    except Exception:
        pass
