"""
周刊虚拟歌手中文曲排行榜分数计算

参考 B站 "周刊虚拟歌手中文曲排行榜" 的官方计分规则实现。
分数体系综合考虑视频的播放量、互动数据、收藏数、硬币数等多个维度，
通过一系列修正系数计算出最终的"得点"排名分数。

计分维度：
- 播放得点：   基础播放分 × 修正D
- 互动得点：   (弹幕 + 评论) × 修正A × 15
- 收藏得点：   收藏数 × 修正B
- 硬币得点：   硬币数 × 修正C
- 点赞得点：   min(点赞数, 硬币数 × 2)
- 总得点 = 以上 5 项之和

修正系数：
- 修正A: 互动质量修正 — 降低刷弹幕/评论对分数的影响
- 修正B: 收藏质量修正 — 根据收藏与硬币比例调整收藏权重（上限 50）
- 修正C: 硬币质量修正 — 根据硬币与收藏比例调整硬币权重（上限 50）
- 修正D: 播放质量修正 — 根据收藏率调整播放权重（上限 1）
"""

from typing import Dict
from dataclasses import dataclass


@dataclass
class VideoData:
    """周刊计分的输入视频数据。

    Attributes:
        view_count: 播放量（累计）
        like_count: 点赞数（累计）
        coin_count: 硬币数（累计）
        favorite_count: 收藏数（累计）
        danmaku_count: 弹幕数（累计）
        reply_count: 评论数（累计）
    """

    view_count: int  # 播放量
    like_count: int  # 点赞数
    coin_count: int  # 硬币数
    favorite_count: int  # 收藏数
    danmaku_count: int  # 弹幕数
    reply_count: int  # 评论数


@dataclass
class WeeklyScoreResult:
    """周刊分数计算的完整结果。

    Attributes:
        total_score: 最终得点（总分），这是周刊排名的依据
        view_score: 播放得点
        interaction_score: 互动得点（弹幕+评论相关）
        favorite_score: 收藏得点
        coin_score: 硬币得点
        like_score: 点赞得点
        correction_a: 修正A（互动质量修正系数）
        correction_b: 修正B（收藏质量修正系数，上限50）
        correction_c: 修正C（硬币质量修正系数，上限50）
        correction_d: 修正D（播放质量修正系数，上限1）
        base_view_score: 基础播放得点（修正D之前的原始值）
    """

    total_score: float  # 最终得点
    view_score: float  # 播放得点
    interaction_score: float  # 互动得点
    favorite_score: float  # 收藏得点
    coin_score: float  # 硬币得点
    like_score: float  # 点赞得点
    correction_a: float  # 修正A
    correction_b: float  # 修正B
    correction_c: float  # 修正C
    correction_d: float  # 修正D
    base_view_score: float  # 基础播放得点


def calculate_weekly_score(data: VideoData) -> WeeklyScoreResult:
    """计算周刊虚拟歌手中文曲排行榜分数。

    完整实现 B站 周刊评分算法，依次计算：
    1. 基础播放得点（播放量 > 1万时有加成）
    2. 四项修正系数（A/B/C/D）
    3. 五项得点（播放/互动/收藏/硬币/点赞）
    4. 最终总得点

    Args:
        data: 视频数据对象，包含播放量和各项互动数据

    Returns:
        WeeklyScoreResult: 完整的计算结果，包含各项得分和修正系数

    Example:
        >>> data = VideoData(34000, 2000, 800, 1200, 300, 291)
        >>> result = calculate_weekly_score(data)
        >>> print(result.total_score)
        67439.5
    """
    view = data.view_count
    like = data.like_count
    coin = data.coin_count
    favorite = data.favorite_count
    danmaku = data.danmaku_count
    reply = data.reply_count

    # ── 基础播放得点 ──
    # 播放量超过 1 万后，每增加 1 播放量额外获得 0.5 加成
    if view > 10000:
        base_view_score = view * 0.5 + 5000  # 超过部分 ×0.5 + 基础 5000
    else:
        base_view_score = float(view)  # 1 万以下按实际播放量计分

    # ── 修正A: 互动质量修正 ──
    # ((基础播放得点 + 收藏) ÷ (基础播放得点 + 收藏 + (弹幕 + 评论) × 20))²
    # 目的：降低刷弹幕和评论对分数的影响（互动过多反而惩罚）
    interaction_total = danmaku + reply
    denominator_a = base_view_score + favorite + interaction_total * 20
    if denominator_a > 0:
        correction_a = ((base_view_score + favorite) / denominator_a) ** 2
    else:
        correction_a = 1.0

    # ── 修正B: 收藏质量修正（最大 50） ──
    # 收藏 > 硬币 × 2 时用硬币视角；否则用收藏率视角
    if view > 0:
        if favorite > coin * 2:
            correction_b = (coin**2 / (view * favorite)) * 1000  # 硬币视角：硬币少但收藏多时降低权重
        else:
            correction_b = (favorite / view) * 250  # 收藏率视角：收藏率越高权重越大
        correction_b = min(correction_b, 50.0)  # 上限 50
    else:
        correction_b = 0.0

    # ── 修正C: 硬币质量修正（最大 50） ──
    # 硬币 > 收藏时用收藏视角；否则用硬币率视角
    if view > 0 and coin > 0:
        if coin > favorite:
            correction_c = (favorite**2 / (view * coin)) * 250  # 收藏视角：硬币多但收藏少时降低权重
        else:
            correction_c = (coin / view) * 250  # 硬币率视角：硬币率越高权重越大
        correction_c = min(correction_c, 50.0)  # 上限 50
    else:
        correction_c = 0.0

    # ── 修正D: 播放质量修正（最大 1） ──
    # 根据收藏率或硬币率调整播放得分权重
    if view > 0:
        if favorite > coin:
            correction_d = (coin / view) * 25  # 硬币率视角
        else:
            correction_d = (favorite / view) * 25  # 收藏率视角
        correction_d = min(correction_d, 1.0)  # 上限 1（最多不扣分，不会加成）
    else:
        correction_d = 0.0

    # ── 各项得点计算 ──
    view_score = base_view_score * correction_d  # 播放得点 = 基础播放 × 修正D
    interaction_score = interaction_total * correction_a * 15  # 互动得点 = (弹幕+评论) × 修正A × 15
    favorite_score = favorite * correction_b  # 收藏得点 = 收藏数 × 修正B
    coin_score = coin * correction_c  # 硬币得点 = 硬币数 × 修正C

    # 点赞得点：被硬币数约束（防止买赞作弊）
    if like > coin * 2:
        like_score = coin * 2  # 点赞数被硬币数的 2 倍封顶
    else:
        like_score = float(like)

    # ── 最终得点（总分） ──
    total_score = view_score + interaction_score + favorite_score + coin_score + like_score

    return WeeklyScoreResult(
        total_score=round(total_score, 2),
        view_score=round(view_score, 2),
        interaction_score=round(interaction_score, 2),
        favorite_score=round(favorite_score, 2),
        coin_score=round(coin_score, 2),
        like_score=round(like_score, 2),
        correction_a=round(correction_a, 4),
        correction_b=round(correction_b, 4),
        correction_c=round(correction_c, 4),
        correction_d=round(correction_d, 4),
        base_view_score=round(base_view_score, 2),
    )


def calculate_from_dict(data: Dict[str, int]) -> WeeklyScoreResult:
    """从字典数据计算周刊分数（便捷函数）。

    从 B站 API 返回的字典中提取字段并计算。

    Args:
        data: 视频数据字典，键名：view_count, like_count, coin_count,
              favorite_count, danmaku_count, reply_count

    Returns:
        WeeklyScoreResult: 周刊分数计算结果
    """
    video_data = VideoData(
        view_count=data.get("view_count", 0),
        like_count=data.get("like_count", 0),
        coin_count=data.get("coin_count", 0),
        favorite_count=data.get("favorite_count", 0),
        danmaku_count=data.get("danmaku_count", 0),
        reply_count=data.get("reply_count", 0),
    )
    return calculate_weekly_score(video_data)


def format_score_result(result: WeeklyScoreResult) -> str:
    """格式化周刊分数计算结果为可读的文本输出。

    以缩进层级展示各维度的得分和修正系数，便于调试和查看。

    Args:
        result: 周刊分数计算结果

    Returns:
        str: 格式化后的多行字符串
    """
    lines = [
        "=" * 40,
        "周刊虚拟歌手中文曲排行榜分数",
        "=" * 40,
        f"最终得点: {result.total_score:,.2f}",
        "-" * 40,
        f"播放得点: {result.view_score:,.2f}",
        f"  └ 基础播放得点: {result.base_view_score:,.2f}",
        f"  └ 修正D: {result.correction_d:.4f}",
        f"互动得点: {result.interaction_score:,.2f}",
        f"  └ 修正A: {result.correction_a:.4f}",
        f"收藏得点: {result.favorite_score:,.2f}",
        f"  └ 修正B: {result.correction_b:.4f}",
        f"硬币得点: {result.coin_score:,.2f}",
        f"  └ 修正C: {result.correction_c:.4f}",
        f"点赞得点: {result.like_score:,.2f}",
        "=" * 40,
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    # 测试示例：模拟一个播放量 3.4 万的视频
    test_data = VideoData(
        view_count=34000, like_count=2000, coin_count=800, favorite_count=1200, danmaku_count=300, reply_count=291
    )

    result = calculate_weekly_score(test_data)
    print(format_score_result(result))
