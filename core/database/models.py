"""数据模型定义 —— 视频信息、监控记录、预测记录的数据类及 BV 号校验"""

import re
from dataclasses import dataclass


@dataclass
class VideoInfo:
    """视频信息数据类
    存储从 Bilibili API 获取的视频元数据及计算指标
    """

    bvid: str  # BV号
    title: str  # 视频标题
    view_count: int = 0  # 播放量
    like_count: int = 0  # 点赞数
    coin_count: int = 0  # 投币数
    share_count: int = 0  # 分享数
    favorite_count: int = 0  # 收藏数
    danmaku_count: int = 0  # 弹幕数
    reply_count: int = 0  # 评论数
    viewers_app: int = 0  # APP端观看人数
    viewers_web: int = 0  # 网页端观看人数
    viewers_total: int = 0  # 总观看人数
    cover_path: str = ""  # 封面本地存储路径
    like_view_ratio: float = 0.0  # 播赞比（点赞/播放）
    owner_name: str = ""  # UP主名称
    owner_id: int = 0  # UP主 UID
    pubdate: str = ""  # 发布时间
    duration: int = 0  # 视频时长（秒）
    pic: str = ""  # 封面封面 URL


@dataclass
class MonitorRecord:
    """监控记录数据类
    单次数据采集的快照，记录当时各指标数值
    """

    bvid: str  # BV号
    timestamp: str  # 采集时间戳
    view_count: int  # 播放量
    like_count: int  # 点赞数
    coin_count: int  # 投币数
    share_count: int  # 分享数
    favorite_count: int  # 收藏数
    danmaku_count: int  # 弹幕数
    reply_count: int  # 评论数
    viewers_app: int = 0  # APP端观看人数
    viewers_web: int = 0  # 网页端观看人数
    viewers_total: int = 0  # 总观看人数
    like_view_ratio: float = 0.0  # 播赞比


@dataclass
class PredictionRecord:
    """预测记录数据类
    由算法预测的播放量达峰时间及置信度等信息
    """

    bvid: str  # BV号
    algorithm: str  # 算法名称
    algorithm_id: str  # 算法唯一标识
    target_threshold: int  # 目标阈值（播放量）
    predicted_seconds: int  # 预测到达目标所需的秒数
    predicted_time: str  # 预测到达时间
    confidence: float  # 预测置信度（0~1）
    current_views: int  # 预测时的当前播放量
    metadata: str = ""  # JSON 字符串，存储额外的元数据
    predicted_hours: float = 0.0  # 预测所需小时数
    current_velocity: float = 0.0  # 当前播放速度（每小时播放增量）
    is_reached: bool = False  # 是否已达到目标阈值
    actual_time: str = ""  # 实际到达目标的时间
    error_rate: float = 0.0  # 预测误差率


_BVID_PATTERN = re.compile(r"^BV[A-Za-z0-9]{10,12}$")


def _validate_bvid(bvid: str) -> str:
    """校验 BV 号格式，防止路径穿越攻击

    Args:
        bvid: 待校验的 BV 号

    Returns:
        校验通过的 BV 号

    Raises:
        ValueError: 格式不合法时抛出
    """
    if not _BVID_PATTERN.match(bvid):
        raise ValueError(f"无效的 BV 号: {bvid!r}")
    return bvid
