"""
Matplotlib 统一导入与 TkAgg 后端配置
"""

try:
    import matplotlib

    matplotlib.use("TkAgg", force=True)
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    mpl_available = True
except Exception:
    FigureCanvasTkAgg = None
    Figure = None
    mpl_available = False
