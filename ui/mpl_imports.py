"""
Matplotlib 统一导入与 TkAgg 后端配置模块

在导入 Matplotlib 时统一设置:
  - TkAgg 后端（与 Tkinter 兼容）
  - 中文字体配置（Windows: Microsoft YaHei/SimHei, Linux: WenQuanYi/Noto Sans CJK）
  - 负号显示修复
  - CJK 字体警告抑制

导出:
  - mpl_available        : bool, Matplotlib 是否可用
  - FigureCanvasTkAgg    : Tkinter 兼容的 Matplotlib Canvas
  - Figure               : Matplotlib Figure 类

使用方式:
    from ui.mpl_imports import mpl_available, FigureCanvasTkAgg, Figure
    if mpl_available:
        fig = Figure()
        canvas = FigureCanvasTkAgg(fig, master=frame)
"""

try:
    import matplotlib

    # 设置 Matplotlib 后端为 TkAgg（必须在导入 pyplot 之前设置）
    matplotlib.use("TkAgg", force=True)

    # 配置中文字体，防止 DejaVu Sans 缺少 CJK 字形产生大量警告
    import platform

    if platform.system() == "Windows":
        matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    else:
        matplotlib.rcParams["font.sans-serif"] = ["WenQuanYi Micro Hei", "Noto Sans CJK SC", "DejaVu Sans"]
    # 修复负号显示问题（使用 Unicode 减号而非 ASCII 连字符）
    matplotlib.rcParams["axes.unicode_minus"] = False

    # 抑制 CJK 字体回退时缺失字形的 UserWarning（大量警告会刷屏日志）
    import warnings
    warnings.filterwarnings("ignore", message="Glyph.*missing from font.*")

    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    mpl_available = True
except Exception:
    # Matplotlib 未安装或导入失败时，设为不可用状态
    FigureCanvasTkAgg = None
    Figure = None
    mpl_available = False
