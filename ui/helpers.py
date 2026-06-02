"""
通用工具函数和常量模块

提供字体定义、阈值管理、数字格式化、圆角矩形绘制、置信度计算等
全 UI 模块共享的工具函数。

本模块在导入时自动从配置文件加载阈值列表，并提供运行时刷新能力。
所有函数均为无副作用的纯函数（除 reload_thresholds 外），可在任何上下文中安全调用。
"""

import math
from ui.theme import C

from utils import PROJECT_ROOT, project_path  # noqa: F401 — 重新导出以方便其他模块引用

# ── 字体定义 ─────────────────────────────────
# 统一的字体规范，全 UI 模块通过引用这些常量保持视觉一致性
FONT = ("Microsoft YaHei UI", 9)            # 标准字体（正文、标签）
FONT_BOLD = ("Microsoft YaHei UI", 9, "bold")  # 粗体
FONT_SM = ("Microsoft YaHei UI", 8)        # 小号字体（辅助文字、提示）
FONT_LG = ("Microsoft YaHei UI", 11, "bold")  # 大号粗体（标题）
FONT_MONO = ("Consolas", 9)                # 等宽字体（数字、日志）
FONT_MONO_LG = ("Consolas", 14, "bold")    # 大号等宽粗体（预测值等）

# ── 阈值与间隔 ───────────────────────────────
# 默认值（首次导入时从 config 加载；运行时可通过 reload_thresholds() 动态刷新）
THRESHOLDS: list = []        # 阈值数值列表，如 [100000, 1000000, 10000000]
THRESHOLD_NAMES: list = []   # 阈值名称列表，如 ["10万", "100万", "1000万"]
THRESH_COLORS: list = []     # 阈值对应的颜色列表

# 阈值颜色调色板（支持 N 个阈值循环使用，避免颜色不够）
_THRESH_PALETTE = [
    "#1a7f37",  # 绿
    "#9a6700",  # 琥珀
    "#8250df",  # 紫
    "#0969da",  # 蓝
    "#d1242f",  # 红
    "#bf3989",  # 粉紫
    "#0550ae",  # 深蓝
    "#953800",  # 棕
    "#0e765c",  # 青绿
    "#6e40c9",  # 紫罗兰
]


def _get_threshold_colors(n):
    """为 N 个阈值生成颜色列表（使用调色板循环）

    Args:
        n: 阈值数量

    Returns:
        list[str]: 长度为 n 的颜色十六进制字符串列表
    """
    return [_THRESH_PALETTE[i % len(_THRESH_PALETTE)] for i in range(n)]


def reload_thresholds():
    """从配置文件加载阈值列表，就地刷新 THRESHOLDS/THRESHOLD_NAMES/THRESH_COLORS 全局变量。

    兼容两种存储格式：
    - 新格式: thresholds = [[100000, "10万"], [1000000, "100万"], ...]
    - 旧格式: thresholds = [100000, 1000000, ...] + 自动生成名称

    加载时会按阈值升序排列，确保进度条等 UI 组件显示顺序一致。
    """
    global THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS  # noqa: F824
    try:
        from config import load_config

        cfg = load_config()
        raw = cfg.get("prediction", {}).get("thresholds", [])
        if not raw:
            # 无配置时使用默认三档阈值
            raw = [100_000, 1_000_000, 10_000_000]
    except Exception:
        raw = [100_000, 1_000_000, 10_000_000]

    values = []
    names = []

    # 判断格式：新格式为 [[int, str], ...]，旧格式为 [int, ...]
    if raw and isinstance(raw[0], (list, tuple)):
        for item in raw:
            v = int(item[0])
            n = str(item[1]) if len(item) > 1 else auto_threshold_name(v)
            values.append(v)
            names.append(n)
    else:
        values = [int(v) for v in raw]
        names = [auto_threshold_name(v) for v in raw]

    # 排序：按阈值升序，确保 UI 中从小到大排列
    pairs = sorted(zip(values, names), key=lambda x: x[0])
    values = [p[0] for p in pairs]
    names = [p[1] for p in pairs]

    # 就地修改，保持引用不变（其他模块引用的列表对象无需重新赋值）
    THRESHOLDS[:] = values
    THRESHOLD_NAMES[:] = names
    THRESH_COLORS[:] = _get_threshold_colors(len(values))


def auto_threshold_name(v):
    """自动生成阈值名称（如 100000 → "10万"，100000000 → "1亿"）

    Args:
        v: 数值（整数）

    Returns:
        str: 格式化的中文数字名称
    """
    if v >= 100_000_000:
        return f"{v / 100_000_000:.0f}亿"
    if v >= 10_000:
        w = v / 10_000
        if w == int(w):
            return f"{int(w)}万"
        return f"{w}万"
    return str(v)


# 模块加载时自动初始化阈值（从配置文件读取）
reload_thresholds()

# 刷新间隔常量
DEFAULT_INTERVAL = 75   # 默认刷新间隔（秒）
FAST_INTERVAL = 10      # 接近阈值时的快速刷新间隔（秒）
FAST_GAP = 500          # 距离阈值多远时启用快速模式（播放量差值）


def fmt_num(n):
    """格式化数字为带千分位分隔符的字符串

    Args:
        n: 数字（整数或可转为整数的值）

    Returns:
        str: 格式化后的字符串，如 "1,234,567"
    """
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def _parse_viewer_count(s):
    """解析B站在线人数字符串为整数。

    支持格式:
      - 纯数字 "1234" → 1234
      - 含"万"  "1.5万" → 15000
      - 含"+"   "1000+人在看" → 1000

    Args:
        s: 原始字符串

    Returns:
        int: 解析后的整数值，解析失败返回 0
    """
    if not s or not isinstance(s, str):
        return 0
    s = s.strip()
    # 去除"人在看"和"+"后缀
    s = s.replace("人在看", "").replace("+", "").strip()
    try:
        if "万" in s:
            return int(float(s.replace("万", "")) * 10000)
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def fmt_eta(minutes):
    """格式化预计时间（分钟 → 人类可读字符串）

    Args:
        minutes: 分钟数（float）

    Returns:
        str: 如 "约2h30min"、"约45min"、或 "—"（非正数时）
    """
    if minutes <= 0:
        return "—"
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    days = hours // 24
    hrs = hours % 24
    if days > 0:
        return f"约{days}天{hrs}h"
    if hours > 0:
        return f"约{hours}h{mins}min"
    return f"约{mins}min"


def nearest_threshold_gap(views):
    """查找最近一个尚未达到的阈值

    Args:
        views: 当前播放量

    Returns:
        tuple: (差值, 阈值索引)，如果已超过所有阈值则返回 (0, -1)
    """
    for i, t in enumerate(THRESHOLDS):
        if t > views:
            return t - views, i
    return 0, -1


def card_status_tag(gap: int):
    """根据与阈值的距离返回视频卡片的状态标签

    Args:
        gap: 与最近阈值的差值

    Returns:
        tuple: (标签文字, 颜色)
          - gap < 500   → 即将突破（红色）
          - gap < 10000 → 进行中（绿色）
          - 其他        → 正常（灰色）
    """
    if 0 < gap < 500:
        return "🔥 接近", C["danger"]
    if 0 < gap < 10000:
        return "📈 进行中", C["success"]
    return "📊 正常", C["text_3"]


def abbrev(n):
    """数字缩写：99500 → "9.9w"，10000000 → "1.0kw"

    Args:
        n: 整数

    Returns:
        str: 缩写后的字符串
    """
    n = int(n)
    if n >= 10_000_000:
        return f"{n / 10_000_000:.0f}kw"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}w"
    if n >= 10_000:
        return f"{n / 10_000:.1f}w"
    return str(n)


def rounded_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    """在 Canvas 上画圆角矩形

    通过 create_polygon + smooth 参数模拟圆角效果。

    Args:
        canvas: Tkinter Canvas 对象
        x1, y1: 左上角坐标
        x2, y2: 右下角坐标
        r: 圆角半径
        **kwargs: 传递给 create_polygon 的额外参数（如 fill, outline）

    Returns:
        int: Canvas 多边形对象 ID
    """
    pts = [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kwargs)


# ── 置信度辅助 ─────────────────────────────────


def loss_to_confidence(val_loss: float) -> float:
    """将 val_loss 映射到 [0, 1] 置信度。

    使用 exp(-loss) 归一化，loss 越小置信度越高。

    Args:
        val_loss: 验证损失值（越小越好）

    Returns:
        float: 0.0 ~ 1.0 之间的置信度
    """
    if val_loss is None or val_loss < 0:
        return 0.0
    return max(0.0, min(1.0, math.exp(-val_loss)))


def format_confidence(conf: float):
    """将置信度数值格式化为显示文本和颜色

    Args:
        conf: [0, 1] 范围内的置信度

    Returns:
        tuple: (显示文本, 颜色)
          - conf >= 0.8 → 高置信（绿色）
          - conf >= 0.5 → 中等（黄色）
          - 其他        → 低置信（红色）
    """
    if conf <= 0:
        return "—", C["text_3"]
    pct = conf * 100
    if conf >= 0.8:
        return f"↑ {pct:.0f}%", C["success"]
    elif conf >= 0.5:
        return f"→ {pct:.0f}%", C["warning"]
    else:
        return f"↓ {pct:.0f}%", C["danger"]


def clear_loss_chart(ax, fig, canvas):
    """清空并样式化损失曲线图表（training/finetune 面板共用）。

    设置 Matplotlib Axes 的深色主题外观：背景色、刻度颜色、
    网格线、坐标轴线颜色等。

    Args:
        ax: Matplotlib Axes 对象
        fig: Matplotlib Figure 对象
        canvas: FigureCanvasTkAgg 对象
    """
    from ui.mpl_imports import mpl_available

    if not mpl_available or ax is None:
        return
    ax.clear()
    ax.set_facecolor(C["bg_elevated"])
    ax.tick_params(colors=C["text_3"], labelsize=7)
    ax.set_xlabel("Epoch", color=C["text_3"], fontsize=7)
    ax.set_ylabel("Loss", color=C["text_3"], fontsize=7)
    ax.grid(True, alpha=0.3, color=C["border"])
    for spine in ax.spines.values():
        spine.set_color(C["border"])
    fig.tight_layout(pad=1.5)
    canvas.draw_idle()


def load_algo_confidence(algo_id: str) -> float:
    """读取算法 active checkpoint 的 val_loss 并计算置信度。

    通过 CheckpointManager 查找指定算法的激活版本，获取其 val_loss，
    然后用 loss_to_confidence 转换为 [0, 1] 置信度。

    Args:
        algo_id: 算法标识符（如 "arima_timeseries"）

    Returns:
        float: 置信度 [0, 1]，读取失败返回 0.0
    """
    try:
        from algorithms.training.checkpoint_manager import CheckpointManager

        ckpt = CheckpointManager(algo_id)
        versions = ckpt.list_versions()
        active_v = ckpt.active_version()
        if not versions or not active_v:
            return 0.0
        for v in versions:
            if v["version"] == active_v:
                return loss_to_confidence(v.get("val_loss", -1.0))
        return loss_to_confidence(versions[0].get("val_loss", -1.0))
    except Exception:
        return 0.0


def is_valid_bvid(s: str) -> bool:
    """校验 BV 号格式，防止路径穿越等安全问题。

    BV 号格式: "BV" + 10~12 位字母数字字符

    Args:
        s: 待校验字符串

    Returns:
        bool: 是否为合法 BV 号
    """
    import re

    return bool(re.match(r"^BV[A-Za-z0-9]{10,12}$", s.strip()))
