"""
一键三连健康探针 — 基于互动率计算视频的综合健康分数

功能说明：
根据视频的播放量与各项互动数据（点赞、硬币、收藏、分享），
计算出各项互动率并与 B站正常区间比较，得出 0-100 分的综合健康评分。

B站正常区间参考（经验值）：
- 赞播比: 3% - 8%
- 币播比: 1% - 4%
- 收藏播比: 2% - 6%
- 分享播比: 0.5% - 3%

各维度权重：
- 点赞率: 30%
- 硬币率: 30%
- 收藏率: 25%
- 分享率: 15%

健康评级标准：
- S: >= 90 分（优秀）
- A: >= 75 分（良好）
- B: >= 60 分（一般）
- C: >= 40 分（较差）
- D: < 40 分（差）
"""

from typing import List
from dataclasses import dataclass, field


@dataclass
class ProbeResult:
    """健康探针计算结果的数据容器。

    Attributes:
        health_score: 综合健康分 (0-100)，越高越好
        health_grade: 健康评级 (S/A/B/C/D)
        like_rate: 点赞率 (%)，点赞数 / 播放量 * 100
        coin_rate: 硬币率 (%)，硬币数 / 播放量 * 100
        favorite_rate: 收藏率 (%)，收藏数 / 播放量 * 100
        share_rate: 分享率 (%)，分享数 / 播放量 * 100
        anomalies: 异常项列表，如 ["点赞率异常偏低 (0.50%)"]
        tips: 优化建议列表，如 ["点赞率严重偏低，建议检查内容质量或推广力度"]
    """

    health_score: float  # 综合健康分 0-100
    health_grade: str  # 评级 S/A/B/C/D
    like_rate: float  # 点赞率 (%)
    coin_rate: float  # 硬币率 (%)
    favorite_rate: float  # 收藏率 (%)
    share_rate: float  # 分享率 (%)
    anomalies: List[str] = field(default_factory=list)  # 异常项
    tips: List[str] = field(default_factory=list)  # 优化建议


# B站正常互动率区间参考（下限, 上限），单位 %
_NORMAL_RANGES = {
    "like_rate": (3.0, 8.0),
    "coin_rate": (1.0, 4.0),
    "favorite_rate": (2.0, 6.0),
    "share_rate": (0.5, 3.0),
}

# 各维度对综合评分的权重
_WEIGHTS = {
    "like_rate": 0.30,  # 点赞率权重 30%
    "coin_rate": 0.30,  # 硬币率权重 30%
    "favorite_rate": 0.25,  # 收藏率权重 25%
    "share_rate": 0.15,  # 分享率权重 15%
}


def _safe_pct(num: float, den: float) -> float:
    """安全计算百分比，避免除以零。

    Args:
        num: 分子（如点赞数）
        den: 分母（如播放量）

    Returns:
        float: 百分比值 (%)，分母为 0 时返回 0.0
    """
    return (num / den * 100) if den > 0 else 0.0


def _rate_score(value: float, lo: float, hi: float) -> float:
    """将单项互动率映射为 0-100 的分数。

    评分规则：
    - 落在正常区间 [lo, hi] 内：得满分 100 分
    - 低于下限：线性递减，低于下限 50% 时得 0 分
    - 高于上限：线性递减，高于上限 2.5 倍时得 0 分

    Args:
        value: 实际互动率 (%)
        lo: 正常区间下限
        hi: 正常区间上限

    Returns:
        float: 该项的得分 (0-100)，上限 100
    """
    if lo <= value <= hi:
        return 100.0  # 在正常区间内，满分
    if value < lo:
        if lo <= 0:
            return 0.0
        # 低于下限：线性降分，低于下限 50% 时得 0
        threshold = lo * 0.5
        return max(0, 100 * (value - threshold) / (lo - threshold))
    else:
        # 高于上限：线性降分，高于上限 2.5 倍时得 0
        threshold = hi * 2.5
        return max(0, 100 * (threshold - value) / (threshold - hi))


def _grade(score: float) -> str:
    """根据健康分返回对应的评级。

    Args:
        score: 综合健康分 (0-100)

    Returns:
        str: 评级 (S/A/B/C/D)
    """
    if score >= 90:
        return "S"  # 优秀
    if score >= 75:
        return "A"  # 良好
    if score >= 60:
        return "B"  # 一般
    if score >= 40:
        return "C"  # 较差
    return "D"  # 差


def calculate_probe(
    view_count: int = 0, like_count: int = 0, coin_count: int = 0, favorite_count: int = 0, share_count: int = 0
) -> ProbeResult:
    """计算视频的一键三连健康探针分数。

    综合评估视频的点赞率、硬币率、收藏率、分享率，输出加权综合健康分、
    评级、异常项和优化建议。

    各维度计算方式：
    1. 计算每项互动率（互动数 / 播放量 * 100%）
    2. 将每项映射为 0-100 分数
    3. 按权重加权求和得到综合分
    4. 检测异常（严重偏离正常区间）

    Args:
        view_count: 播放量（累计）
        like_count: 点赞数（累计）
        coin_count: 硬币数（累计）
        favorite_count: 收藏数（累计）
        share_count: 分享数（累计）

    Returns:
        ProbeResult: 完整的健康探针计算结果

    Example:
        >>> result = calculate_probe(34000, 2000, 800, 1200, 300)
        >>> print(f"健康分: {result.health_score}, 评级: {result.health_grade}")
        健康分: 85.5, 评级: A
    """
    # 计算各项互动率（百分比）
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

    # 加权综合评分：每项得分 × 权重，求和
    weighted = 0.0
    for key, weight in _WEIGHTS.items():
        lo, hi = _NORMAL_RANGES[key]
        weighted += _rate_score(rates[key], lo, hi) * weight

    # 异常检测：对比正常区间，标记严重偏离的指标
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
        # 低于正常下限的 50%：严重偏低 → 异常项
        if val < lo * 0.5:
            anomalies.append(f"{nm}异常偏低 ({val:.2f}%)")
            tips.append(f"{nm}严重偏低，建议检查内容质量或推广力度")
        # 低于正常下限但未到 50%：轻微偏低 → 建议项
        elif val < lo:
            tips.append(f"{nm}偏低 ({val:.2f}%)，仍有提升空间")
        # 高于正常上限的 2 倍：严重偏高 → 异常项（可能为异常流量）
        elif val > hi * 2:
            anomalies.append(f"{nm}异常偏高 ({val:.2f}%)")
            tips.append(f"{nm}异常高，可能为异常流量")
        # 高于正常上限但未到 2 倍：偏高 → 提示项
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
    """从字典数据计算健康探针（便捷函数）。

    从 B站 API 返回的视频数据字典中提取所需字段并计算探针分数。

    Args:
        data: B站视频数据字典，应包含 view_count, like_count, coin_count,
              favorite_count, share_count 等字段

    Returns:
        ProbeResult: 健康探针计算结果
    """
    return calculate_probe(
        view_count=data.get("view_count", 0),
        like_count=data.get("like_count", 0),
        coin_count=data.get("coin_count", 0),
        favorite_count=data.get("favorite_count", 0),
        share_count=data.get("share_count", 0),
    )


def format_probe_result(result: ProbeResult) -> str:
    """格式化健康探针结果为可读的纯文本字符串。

    用于在控制台或日志中打印输出。

    Args:
        result: 健康探针计算结果

    Returns:
        str: 格式化后的多行字符串，包含各项得分和异常/建议信息
    """
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
    # 测试示例：模拟一个播放量 3.4 万的视频数据
    test = calculate_probe(view_count=34000, like_count=2000, coin_count=800, favorite_count=1200, share_count=300)
    print(format_probe_result(test))
