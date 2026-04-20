"""
通用工具函数和常量
"""
from ui.theme import C

THRESHOLDS      = [100_000, 1_000_000, 10_000_000]
THRESHOLD_NAMES = ["10万", "100万", "1000万"]
THRESH_COLORS   = [C["thresh_10w"], C["thresh_100w"], C["thresh_1000w"]]

DEFAULT_INTERVAL = 75
FAST_INTERVAL    = 10
FAST_GAP         = 500


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
    mins  = int(minutes % 60)
    days  = hours // 24
    hrs   = hours % 24
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
        return f"{n/10_000_000:.0f}kw"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}w"
    if n >= 10_000:
        return f"{n/10_000:.1f}w"
    return str(n)
