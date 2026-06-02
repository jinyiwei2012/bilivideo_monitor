"""
年刊虚拟歌手中文曲排行榜分数计算

参考 B站 "年刊虚拟歌手中文曲排行榜" 的官方计分规则实现。
与周刊版本的区别在于计分阈值和修正系数的调整（年刊门槛更高）。

计分维度：
- 播放得点：   播放量 × 分段加成（> 30万时：×0.5 + 150000）
- 点赞得点：   min(点赞数, 硬币数 × 2)
- 互动得点：   (弹幕 + 评论) × 修正A
- 收藏得点：   收藏数 × 修正B
- 硬币得点：   硬币数 × 修正C
- 总得点 = 以上 5 项之和

修正系数：
- 修正A: 互动质量修正 — ((播放得点 + 收藏) / (播放得点 + 收藏 + 互动×50))² × 30
- 修正B: 收藏质量修正 — 收藏 > 硬币×2 时：(硬币/收藏)×40，否则 20
- 修正C: 硬币质量修正 — 收藏 < 硬币时：(收藏/硬币)×20，否则 20

与周刊的主要差异：
- 播放加成阈值更高（30万 vs 1万）
- 修正A 的互动惩罚系数更大（50 vs 20，年刊对刷弹幕更严格）
- 修正A 多了一个 ×30 的乘数
- 修正B/C 的计算逻辑不同（年刊采用固定值 20 作为基准）
"""

from typing import Dict
from dataclasses import dataclass


@dataclass
class YearlyVideoData:
    """年刊计分的输入视频数据。

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
class YearlyScoreResult:
    """年刊分数计算的完整结果。

    Attributes:
        total_score: 最终得点（总分），这是年刊排名的依据
        view_score: 播放得点
        interaction_score: 互动得点（弹幕+评论相关）
        favorite_score: 收藏得点
        coin_score: 硬币得点
        like_score: 点赞得点
        correction_a: 修正A（互动质量修正系数，含 ×30 乘数）
        correction_b: 修正B（收藏质量修正系数）
        correction_c: 修正C（硬币质量修正系数）
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


def calculate_yearly_score(data: YearlyVideoData) -> YearlyScoreResult:
    """计算年刊虚拟歌手中文曲排行榜分数。

    完整实现 B站 年刊评分算法。与周刊的主要区别在于更高的播放加成
    阈值（30 万 vs 1 万）和更严格的反作弊修正系数。

    算法步骤：
    1. 计算播放得点（分段加成）
    2. 计算点赞得点（被硬币封顶）
    3. 计算三项修正系数（A/B/C）
    4. 计算互动/收藏/硬币得点
    5. 汇总最终得点

    Args:
        data: 视频数据对象

    Returns:
        YearlyScoreResult: 完整的年刊计算结果

    Example:
        >>> data = YearlyVideoData(500000, 5000, 2000, 3000, 500, 400)
        >>> result = calculate_yearly_score(data)
        >>> print(result.total_score)
    """
    view = data.view_count
    like = data.like_count
    coin = data.coin_count
    favorite = data.favorite_count
    danmaku = data.danmaku_count
    reply = data.reply_count

    # ── 播放得点（年刊阈值：30万） ──
    # 超过 30 万播放后，额外部分×0.5 并 +150000 基础分
    if view > 300000:
        view_score = view * 0.5 + 150000
    else:
        view_score = float(view)  # 30 万以下按实际播放量计分

    # ── 点赞得点 ──
    # 被硬币数封顶：点赞得分 = min(点赞数, 硬币数 × 2)
    if like > coin * 2:
        like_score = coin * 2
    else:
        like_score = float(like)

    # ── 修正A: 互动质量修正 ──
    # ((播放得点 + 收藏) / (播放得点 + 收藏 + (弹幕+评论) × 50))² × 30
    # 年刊的互动惩罚系数为 50（周刊为 20），对刷弹幕/评论更严格
    # 最后 ×30 是年刊特有的放大系数（周刊的修正A不含这个乘数）
    interaction_total = danmaku + reply
    denominator_a = view_score + favorite + interaction_total * 50
    if denominator_a > 0:
        correction_a = ((view_score + favorite) / denominator_a) ** 2 * 30
    else:
        correction_a = 30.0  # 分母为 0 时取最大值

    # ── 修正B: 收藏质量修正 ──
    # 收藏 > 硬币 × 2：取 (硬币/收藏) × 40，否则取固定值 20
    # 目的：收藏远高于硬币时降低收藏权重（可能存在刷收藏嫌疑）
    if favorite > coin * 2:
        if favorite > 0:
            correction_b = (coin / favorite) * 40
        else:
            correction_b = 20.0
    else:
        correction_b = 20.0  # 正常情况取固定基准值

    # ── 修正C: 硬币质量修正 ──
    # 收藏 < 硬币：取 (收藏/硬币) × 20，否则取固定值 20
    # 目的：硬币远高于收藏时降低硬币权重（可能存在刷硬币嫌疑）
    if coin > 0:
        if favorite < coin:
            correction_c = (favorite / coin) * 20
        else:
            correction_c = 20.0  # 正常情况取固定基准值
    else:
        correction_c = 20.0

    # ── 各项得点计算 ──
    interaction_score = interaction_total * correction_a  # 互动得点 = (弹幕+评论) × 修正A
    favorite_score = favorite * correction_b  # 收藏得点 = 收藏数 × 修正B
    coin_score = coin * correction_c  # 硬币得点 = 硬币数 × 修正C

    # ── 最终得点（总分） ──
    total_score = view_score + interaction_score + favorite_score + coin_score + like_score

    return YearlyScoreResult(
        total_score=round(total_score, 2),
        view_score=round(view_score, 2),
        interaction_score=round(interaction_score, 2),
        favorite_score=round(favorite_score, 2),
        coin_score=round(coin_score, 2),
        like_score=round(like_score, 2),
        correction_a=round(correction_a, 4),
        correction_b=round(correction_b, 4),
        correction_c=round(correction_c, 4),
    )


def calculate_yearly_from_dict(data: Dict[str, int]) -> YearlyScoreResult:
    """从字典数据计算年刊分数（便捷函数）。

    Args:
        data: 视频数据字典，键名：view_count, like_count, coin_count,
              favorite_count, danmaku_count, reply_count

    Returns:
        YearlyScoreResult: 年刊分数计算结果
    """
    video_data = YearlyVideoData(
        view_count=data.get("view_count", 0),
        like_count=data.get("like_count", 0),
        coin_count=data.get("coin_count", 0),
        favorite_count=data.get("favorite_count", 0),
        danmaku_count=data.get("danmaku_count", 0),
        reply_count=data.get("reply_count", 0),
    )
    return calculate_yearly_score(video_data)


def format_yearly_score_result(result: YearlyScoreResult) -> str:
    """格式化年刊分数计算结果为可读的文本输出。

    以缩进层级展示各维度的得分和修正系数，便于调试和查看。

    Args:
        result: 年刊分数计算结果

    Returns:
        str: 格式化后的多行字符串
    """
    lines = [
        "=" * 40,
        "年刊虚拟歌手中文曲排行榜分数",
        "=" * 40,
        f"最终得点: {result.total_score:,.2f}",
        "-" * 40,
        f"播放得点: {result.view_score:,.2f}",
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
    # 测试示例：模拟一个播放量 50 万的年刊投稿
    test_data = YearlyVideoData(
        view_count=500000, like_count=5000, coin_count=2000, favorite_count=3000, danmaku_count=500, reply_count=400
    )

    result = calculate_yearly_score(test_data)
    print(format_yearly_score_result(result))
