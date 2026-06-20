"""
Matplotlib 统一导入与 QtAgg 后端配置

PyQt6 版本：使用 QtAgg 后端替代 TkAgg。
"""

try:
    import matplotlib

    # 设置 Matplotlib 后端为 QtAgg（必须在导入 pyplot 之前）
    matplotlib.use("QtAgg", force=True)

    # 配置中文字体
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

    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure

    mpl_available = True
except Exception:
    FigureCanvasQTAgg = None
    Figure = None
    mpl_available = False
