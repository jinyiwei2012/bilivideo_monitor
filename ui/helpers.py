"""
通用工具函数和常量 - PyQt6 版

提供字体定义、阈值管理、数字格式化、置信度计算等
全 UI 模块共享的工具函数。

与 Tkinter 版差异：移除了 rounded_rect (Canvas 专用)，
新增了 Qt 友好的颜色/字体工具。
"""

import math
from ui.theme import C

from utils import PROJECT_ROOT, project_path  # noqa: F401 — 重新导出以方便使用

from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import QApplication

# ── 字体定义 ─────────────────────────────────
def _font(name="Microsoft YaHei UI", size=9, bold=False):
    f = QFont(name, size)
    f.setBold(bold)
    return f

FONT = _font()                          # 标准字体
FONT_BOLD = _font(bold=True)           # 粗体
FONT_SM = _font(size=8)                 # 小号字体
FONT_LG = _font(size=11, bold=True)    # 大号粗体
FONT_MONO = _font("Consolas", 9)        # 等宽字体
FONT_MONO_LG = _font("Consolas", 14, bold=True)  # 大号等宽粗体

# ── 阈值与间隔 ───────────────────────────────
THRESHOLDS: list = []
THRESHOLD_NAMES: list = []
THRESH_COLORS: list = []

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
    return [_THRESH_PALETTE[i % len(_THRESH_PALETTE)] for i in range(n)]


def reload_thresholds():
    """从配置文件加载阈值列表"""
    global THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS
    try:
        from config import load_config, DEFAULT_CONFIG

        cfg = load_config()
        raw = cfg.get("prediction", {}).get("thresholds", [])
        if not raw:
            # 默认阈值单点定义见 config.DEFAULT_CONFIG
            raw = DEFAULT_CONFIG["prediction"]["thresholds"]
    except Exception:
        from config import DEFAULT_CONFIG

        raw = DEFAULT_CONFIG["prediction"]["thresholds"]

    values = []
    names = []
    if raw and isinstance(raw[0], (list, tuple)):
        for item in raw:
            v = int(item[0])
            n = str(item[1]) if len(item) > 1 else auto_threshold_name(v)
            values.append(v)
            names.append(n)
    else:
        values = [int(v) for v in raw]
        names = [auto_threshold_name(v) for v in raw]

    pairs = sorted(zip(values, names), key=lambda x: x[0])
    values = [p[0] for p in pairs]
    names = [p[1] for p in pairs]

    THRESHOLDS[:] = values
    THRESHOLD_NAMES[:] = names
    THRESH_COLORS[:] = _get_threshold_colors(len(values))


def auto_threshold_name(v):
    if v >= 100_000_000:
        return f"{v / 100_000_000:.0f}亿"
    if v >= 10_000:
        w = v / 10_000
        if w == int(w):
            return f"{int(w)}万"
        return f"{w}万"
    return str(v)


reload_thresholds()

DEFAULT_INTERVAL = 75
FAST_INTERVAL = 10
FAST_GAP = 500
PREDICT_INTERVAL = 75


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


# ── 置信度辅助 ─────────────────────────────────

def loss_to_confidence(val_loss: float) -> float:
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


def clear_loss_chart(fig, canvas):
    """清空并样式化损失曲线图表（training/finetune 面板共用）。"""
    from ui.mpl_imports import mpl_available

    if not mpl_available:
        return
    ax = fig.axes[0] if fig.axes else None
    if ax is None:
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
    from core.constants import BV_PATTERN

    return bool(BV_PATTERN.match(s.strip()))
