"""
通用工具函数和常量
"""
import os

from ui.theme import C

from utils import PROJECT_ROOT, project_path  # noqa: F401 — re-export for convenience

# ── 字体定义 ─────────────────────────────────
FONT = ("Microsoft YaHei UI", 9)
FONT_BOLD = ("Microsoft YaHei UI", 9, "bold")
FONT_SM = ("Microsoft YaHei UI", 8)
FONT_LG = ("Microsoft YaHei UI", 11, "bold")
FONT_MONO = ("Consolas", 9)
FONT_MONO_LG = ("Consolas", 14, "bold")

# ── 阈值与间隔 ───────────────────────────────
# 默认值（首次导入时从 config 加载；通过 reload_thresholds() 动态刷新）
THRESHOLDS: list = []
THRESHOLD_NAMES: list = []
THRESH_COLORS: list = []

# 阈值颜色调色板（支持 N 个阈值循环使用）
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
    """为 N 个阈值生成颜色列表（使用调色板循环）"""
    return [_THRESH_PALETTE[i % len(_THRESH_PALETTE)] for i in range(n)]


def reload_thresholds():
    """从配置文件加载阈值列表，就地刷新 THRESHOLDS/THRESHOLD_NAMES/THRESH_COLORS。

    兼容两种存储格式：
    - 新格式: thresholds = [[100000, "10万"], [1000000, "100万"], ...]
    - 旧格式: thresholds = [100000, 1000000, ...] + 自动生成名称
    """
    global THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS
    try:
        from config import load_config

        cfg = load_config()
        raw = cfg.get("prediction", {}).get("thresholds", [])
        if not raw:
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

    # 排序：按阈值升序
    pairs = sorted(zip(values, names), key=lambda x: x[0])
    values = [p[0] for p in pairs]
    names = [p[1] for p in pairs]

    THRESHOLDS[:] = values
    THRESHOLD_NAMES[:] = names
    THRESH_COLORS[:] = _get_threshold_colors(len(values))


def auto_threshold_name(v):
    """自动生成阈值名称（如 100000 → "10万"）"""
    if v >= 100_000_000:
        return f"{v / 100_000_000:.0f}亿"
    if v >= 10_000:
        w = v / 10_000
        if w == int(w):
            return f"{int(w)}万"
        return f"{w}万"
    return str(v)


# 首次初始化
reload_thresholds()

DEFAULT_INTERVAL = 75
FAST_INTERVAL = 10
FAST_GAP = 500


def fmt_num(n):
    """格式化数字"""
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def _parse_viewer_count(s):
    """解析B站在线人数字符串为整数。"""
    if not s or not isinstance(s, str):
        return 0
    s = s.strip()
    s = s.replace("人在看", "").replace("+", "").strip()
    try:
        if "万" in s:
            return int(float(s.replace("万", "")) * 10000)
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def fmt_eta(minutes):
    """格式化预计时间"""
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
    """返回 (gap, threshold_index)，找最近未达到的阈值"""
    for i, t in enumerate(THRESHOLDS):
        if t > views:
            return t - views, i
    return 0, -1


def card_status_tag(gap: int):
    """根据与阈值的距离返回 (标签文字, 颜色)"""
    if 0 < gap < 500:
        return "🔥 接近", C["danger"]
    if 0 < gap < 10000:
        return "📈 进行中", C["success"]
    return "📊 正常", C["text_3"]


def abbrev(n):
    """数字缩写：99500 -> 9.9w"""
    n = int(n)
    if n >= 10_000_000:
        return f"{n / 10_000_000:.0f}kw"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}w"
    if n >= 10_000:
        return f"{n / 10_000:.1f}w"
    return str(n)


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


# ── 置信度辅助 ─────────────────────────────────
import math


def loss_to_confidence(val_loss: float) -> float:
    """将 val_loss 映射到 [0, 1] 置信度。exp(-loss) 归一化。"""
    if val_loss is None or val_loss < 0:
        return 0.0
    return max(0.0, min(1.0, math.exp(-val_loss)))


def format_confidence(conf: float):
    """返回 (显示文本, 颜色) 对。"""
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
    """清空并样式化损失曲线图表（training/finetune 面板共用）。"""
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
    """读取算法 active checkpoint 的 val_loss 并计算置信度。"""
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
    """校验 BV 号格式，防止路径穿越。"""
    import re

    return bool(re.match(r"^BV[A-Za-z0-9]{10,12}$", s.strip()))
