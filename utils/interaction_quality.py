"""
一键三连健康探针 — 计算点赞率/硬币率/收藏率/分享率加权综合健康分
参考B站正常区间：赞播比3-8%，币播比1-4%，收藏播比2-6%，分享播比0.5-3%
"""

from typing import List
from dataclasses import dataclass, field


@dataclass
class ProbeResult:
    """健康探针计算结果"""

    health_score: float  # 综合健康分 0-100
    health_grade: str  # S/A/B/C/D
    like_rate: float  # 点赞率 (%)
    coin_rate: float  # 硬币率 (%)
    favorite_rate: float  # 收藏率 (%)
    share_rate: float  # 分享率 (%)
    anomalies: List[str] = field(default_factory=list)
    tips: List[str] = field(default_factory=list)


# 正常区间参考
_NORMAL_RANGES = {
    "like_rate": (3.0, 8.0),
    "coin_rate": (1.0, 4.0),
    "favorite_rate": (2.0, 6.0),
    "share_rate": (0.5, 3.0),
}

# 各维度权重
_WEIGHTS = {
    "like_rate": 0.30,
    "coin_rate": 0.30,
    "favorite_rate": 0.25,
    "share_rate": 0.15,
}


def _safe_pct(num: float, den: float) -> float:
    """安全计算百分比，避免除零"""
    return (num / den * 100) if den > 0 else 0.0


def _rate_score(value: float, lo: float, hi: float) -> float:
    """单项率映射到 0-100 分，落在正常区间内得满分，偏离越远分越低"""
    if lo <= value <= hi:
        return 100.0
    if value < lo:
        if lo <= 0:
            return 0.0
        # 低于下限：线性跌到 0（低于下限 2 倍得 0）
        threshold = lo * 0.5
        return max(0, 100 * (value - threshold) / (lo - threshold))
    else:
        # 高于上限
        threshold = hi * 2.5
        return max(0, 100 * (threshold - value) / (threshold - hi))


def _grade(score: float) -> str:
    """根据健康分返回评级 S/A/B/C/D"""
    if score >= 90:
        return "S"
    if score >= 75:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    return "D"


def calculate_probe(
    view_count: int = 0, like_count: int = 0, coin_count: int = 0, favorite_count: int = 0, share_count: int = 0
) -> ProbeResult:
    """
    计算一键三连健康探针分数

    Args:
        view_count: 播放量
        like_count: 点赞数
        coin_count: 硬币数
        favorite_count: 收藏数
        share_count: 分享数

    Returns:
        ProbeResult: 探针结果
    """
    like_r = _safe_pct(like_count, view_count)
    coin_r = _safe_pct(coin_count, view_count)
    favorite_r = _safe_pct(favorite_count, view_count)
    share_r = _safe_pct(share_count, view_count)

    rates = {
        "like_rate": like_r,
        "coin_rate": coin_r,
        "favorite_rate": favorite_r,
        "share_rate": share_r,
    }

    # 综合加权分
    weighted = 0.0
    for key, weight in _WEIGHTS.items():
        lo, hi = _NORMAL_RANGES[key]
        weighted += _rate_score(rates[key], lo, hi) * weight

    # 异常检测
    anomalies = []
    tips = []
    for key, val in rates.items():
        lo, hi = _NORMAL_RANGES[key]
        name_map = {
            "like_rate": "点赞率",
            "coin_rate": "硬币率",
            "favorite_rate": "收藏率",
            "share_rate": "分享率",
        }
        nm = name_map[key]
        if val < lo * 0.5:
            anomalies.append(f"{nm}异常偏低 ({val:.2f}%)")
            tips.append(f"{nm}严重偏低，建议检查内容质量或推广力度")
        elif val < lo:
            tips.append(f"{nm}偏低 ({val:.2f}%)，仍有提升空间")
        elif val > hi * 2:
            anomalies.append(f"{nm}异常偏高 ({val:.2f}%)")
            tips.append(f"{nm}异常高，可能为异常流量")
        elif val > hi:
            tips.append(f"{nm}偏高 ({val:.2f}%)，表现优异")

    return ProbeResult(
        health_score=round(weighted, 1),
        health_grade=_grade(weighted),
        like_rate=round(like_r, 2),
        coin_rate=round(coin_r, 2),
        favorite_rate=round(favorite_r, 2),
        share_rate=round(share_r, 2),
        anomalies=anomalies,
        tips=tips,
    )


def calculate_probe_from_dict(data: dict) -> ProbeResult:
    """从字典计算健康探针"""
    return calculate_probe(
        view_count=data.get("view_count", 0),
        like_count=data.get("like_count", 0),
        coin_count=data.get("coin_count", 0),
        favorite_count=data.get("favorite_count", 0),
        share_count=data.get("share_count", 0),
    )


def format_probe_result(result: ProbeResult) -> str:
    """格式化健康探针输出"""
    lines = [
        "=" * 40,
        "一键三连健康探针",
        "=" * 40,
        f"健康分: {result.health_score:.1f}  (评级: {result.health_grade})",
        "-" * 40,
        f"点赞率:   {result.like_rate:.2f}%    (正常 3-8%)",
        f"硬币率:   {result.coin_rate:.2f}%    (正常 1-4%)",
        f"收藏率:   {result.favorite_rate:.2f}%  (正常 2-6%)",
        f"分享率:   {result.share_rate:.2f}%   (正常 0.5-3%)",
    ]
    if result.anomalies:
        lines.extend(["", "⚠ 异常项:"])
        lines.extend([f"  - {a}" for a in result.anomalies])
    if result.tips:
        lines.extend(["", "💡 建议:"])
        lines.extend([f"  - {t}" for t in result.tips])
    lines.append("=" * 40)
    return "\n".join(lines)


if __name__ == "__main__":
    # 测试
    test = calculate_probe(view_count=34000, like_count=2000, coin_count=800, favorite_count=1200, share_count=300)
    print(format_probe_result(test))
