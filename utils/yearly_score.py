"""
年刊虚拟歌手中文曲排行榜分数计算
参考：年刊虚拟歌手中文曲排行榜计分规则
"""

from typing import Dict, Optional
from dataclasses import dataclass


@dataclass
class YearlyVideoData:
    """视频数据"""
    view_count: int      # 播放量
    like_count: int      # 点赞数
    coin_count: int      # 硬币数
    favorite_count: int  # 收藏数
    danmaku_count: int   # 弹幕数
    reply_count: int     # 评论数


@dataclass
class YearlyScoreResult:
    """年刊分数计算结果"""
    total_score: float           # 最终得点
    view_score: float            # 播放得点
    interaction_score: float     # 互动得点
    favorite_score: float        # 收藏得点
    coin_score: float            # 硬币得点
    like_score: float            # 点赞得点
    correction_a: float          # 修正A
    correction_b: float          # 修正B
    correction_c: float          # 修正C


def calculate_yearly_score(data: YearlyVideoData) -> YearlyScoreResult:
    """
    计算年刊虚拟歌手中文曲排行榜分数
    
    Args:
        data: 视频数据对象
        
    Returns:
        YearlyScoreResult: 计算结果
    """
    view = data.view_count
    like = data.like_count
    coin = data.coin_count
    favorite = data.favorite_count
    danmaku = data.danmaku_count
    reply = data.reply_count
    
    # 播放得点
    if view > 300000:
        view_score = view * 0.5 + 150000
    else:
        view_score = float(view)
    
    # 点赞得点
    if like > coin * 2:
        like_score = coin * 2
    else:
        like_score = float(like)
    
    # 修正A: 互动修正
    # ((播放得点 + 收藏) ÷ (播放得点 + 收藏 + (弹幕 + 评论) × 50))² × 30
    interaction_total = danmaku + reply
    denominator_a = view_score + favorite + interaction_total * 50
    if denominator_a > 0:
        correction_a = ((view_score + favorite) / denominator_a) ** 2 * 30
    else:
        correction_a = 30.0
    
    # 修正B: 收藏修正
    if favorite > coin * 2:
        if favorite > 0:
            correction_b = (coin / favorite) * 40
        else:
            correction_b = 20.0
    else:
        correction_b = 20.0
    
    # 修正C: 硬币修正
    if coin > 0:
        if favorite < coin:
            correction_c = (favorite / coin) * 20
        else:
            correction_c = 20.0
    else:
        correction_c = 20.0
    
    # 各项得点计算
    interaction_score = interaction_total * correction_a
    favorite_score = favorite * correction_b
    coin_score = coin * correction_c
    
    # 最终得点
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
        correction_c=round(correction_c, 4)
    )


def calculate_yearly_from_dict(data: Dict[str, int]) -> YearlyScoreResult:
    """
    从字典计算年刊分数
    
    Args:
        data: 包含视频数据的字典，键名：view_count, like_count, coin_count, 
              favorite_count, danmaku_count, reply_count
              
    Returns:
        YearlyScoreResult: 计算结果
    """
    video_data = YearlyVideoData(
        view_count=data.get('view_count', 0),
        like_count=data.get('like_count', 0),
        coin_count=data.get('coin_count', 0),
        favorite_count=data.get('favorite_count', 0),
        danmaku_count=data.get('danmaku_count', 0),
        reply_count=data.get('reply_count', 0)
    )
    return calculate_yearly_score(video_data)


def format_yearly_score_result(result: YearlyScoreResult) -> str:
    """
    格式化输出计算结果
    
    Args:
        result: 计算结果对象
        
    Returns:
        str: 格式化后的字符串
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
        "=" * 40
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    # 测试示例
    test_data = YearlyVideoData(
        view_count=500000,
        like_count=5000,
        coin_count=2000,
        favorite_count=3000,
        danmaku_count=500,
        reply_count=400
    )
    
    result = calculate_yearly_score(test_data)
    print(format_yearly_score_result(result))
