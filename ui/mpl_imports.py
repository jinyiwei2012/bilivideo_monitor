"""
Matplotlib 统一导入与 TkAgg 后端配置
"""

try:
    import matplotlib

    # 设置 Matplotlib 后端为 TkAgg（必须在导入 pyplot 之前）
    matplotlib.use("TkAgg", force=True)

    # 配置中文字体，防止 DejaVu Sans 缺少 CJK 字形警告
    import platform

    if platform.system() == "Windows":
        matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    else:
        matplotlib.rcParams["font.sans-serif"] = ["WenQuanYi Micro Hei", "Noto Sans CJK SC", "DejaVu Sans"]
    # 修复负号显示问题
    matplotlib.rcParams["axes.unicode_minus"] = False

    # 抑制 CJK 字体回退时缺失字形的 UserWarning
    import warnings
    warnings.filterwarnings("ignore", message="Glyph.*missing from font.*")

    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    mpl_available = True
except Exception:
    FigureCanvasTkAgg = None
    Figure = None
    mpl_available = False
