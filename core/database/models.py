"""
数据模型定义 —— 视频信息、监控记录、预测记录的数据类及 BV 号校验
==============================================================

本模块定义了数据库子系统的三个核心数据模型和 BV 号校验函数：
1. VideoInfo：从 Bilibili API 获取的视频元数据
2. MonitorRecord：单次数据采集的快照记录
3. PredictionRecord：算法预测的播放量达峰时间及置信度
4. _validate_bvid：BV 号格式校验（含路径穿越防护）

所有数据类使用 Python dataclass 实现，支持字段默认值和从 API 数据构造。
"""

import re
from dataclasses import dataclass


@dataclass(slots=True)
class VideoInfo:
    """视频信息数据类

    存储从 Bilibili API 获取的视频元数据及计算指标。
    提供 from_api_data 静态工厂方法，将 API 返回的 JSON 数据
    直接转换为 VideoInfo 对象。
    """

    bvid: str                                # BV号
    title: str                               # 视频标题
    view_count: int = 0                      # 播放量
    like_count: int = 0                      # 点赞数
    coin_count: int = 0                      # 投币数
    share_count: int = 0                     # 分享数
    favorite_count: int = 0                  # 收藏数
    danmaku_count: int = 0                   # 弹幕数
    reply_count: int = 0                     # 评论数
    viewers_app: int = 0                     # APP端观看人数（v2.0 新增指标）
    viewers_web: int = 0                     # 网页端观看人数（v2.0 新增指标）
    viewers_total: int = 0                   # 总观看人数（v2.0 新增指标）
    cover_path: str = ""                     # 封面本地存储路径
    like_view_ratio: float = 0.0             # 播赞比（点赞数/播放量）
    owner_name: str = ""                     # UP主名称
    owner_id: int = 0                        # UP主 UID（mid）
    pubdate: str = ""                        # 发布时间戳
    duration: int = 0                        # 视频时长（秒）
    pic: str = ""                            # 封面图片 URL
    view_token: int = 0                      # B站新播放量令牌 (stat.vt)，用于展示前端真实播放数据
    honor_reply: str = ""                    # 荣誉回复标签 (JSON 字符串)，如 "{'weekly': {...}}"
    ugc_season_id: int = 0                   # 合集 ID（若属于某个合集）
    no_cache: bool = False                   # 是否禁止缓存（true 表示实时数据）
    is_cooperation: bool = False             # 是否联合投稿
    tid: int = 0                             # 分区 ID（如 17=单机游戏）
    tname: str = ""                          # 分区名称

    @staticmethod
    def from_api_data(bvid: str, vdata: dict) -> "VideoInfo":
        """从 Bilibili API 返回的 JSON 数据构造 VideoInfo 对象

        安全地从嵌套的 API 数据结构中提取各字段，对缺失的嵌套对象
        使用 .get() 提供默认值，避免 KeyError。

        Args:
            bvid: BV 号
            vdata: Bilibili API (/x/web-interface/view) 返回的 data 字段

        Returns:
            VideoInfo 对象
        """
        # 提取子对象（stat 为播放数据统计，owner 为 UP 主信息）
        stat = vdata.get("stat", {})
        owner = vdata.get("owner", {})
        # 安全访问 ugc_season（合集信息可能不存在或非 dict）
        ugc_season = vdata.get("ugc_season")
        ugc_season_id = ugc_season.get("id", 0) if isinstance(ugc_season, dict) else 0
        # 安全访问 rights（版权/权限信息）
        rights = vdata.get("rights")
        is_coop = rights.get("is_cooperation", 0) == 1 if isinstance(rights, dict) else False
        return VideoInfo(
            bvid=bvid,
            title=vdata.get("title", ""),
            view_count=stat.get("view", 0),
            like_count=stat.get("like", 0),
            coin_count=stat.get("coin", 0),
            share_count=stat.get("share", 0),
            favorite_count=stat.get("favorite", 0),
            danmaku_count=stat.get("danmaku", 0),
            reply_count=stat.get("reply", 0),
            owner_name=owner.get("name", ""),
            owner_id=owner.get("mid", 0),
            pubdate=str(vdata.get("pubdate", "")),
            duration=vdata.get("duration", 0),
            pic=vdata.get("pic", ""),
            view_token=stat.get("vt", 0),
            honor_reply=str(vdata.get("honor_reply", "")),
            ugc_season_id=ugc_season_id,
            no_cache=vdata.get("no_cache", False),
            is_cooperation=is_coop,
            tid=vdata.get("tid", 0),
            tname=vdata.get("tname", ""),
        )


@dataclass(slots=True)
class MonitorRecord:
    """监控记录数据类

    单次数据采集的快照，记录当时各指标数值。
    与 VideoInfo 的区别：MonitorRecord 包含时间戳，
    用于追踪同一视频在不同时间点的数据变化，构成时序数据。
    """

    bvid: str                                # BV号
    timestamp: str                           # 采集时间戳（ISO 8601 格式）
    view_count: int                          # 播放量
    like_count: int                          # 点赞数
    coin_count: int                          # 投币数
    share_count: int                         # 分享数
    favorite_count: int                      # 收藏数
    danmaku_count: int                       # 弹幕数
    reply_count: int                         # 评论数
    viewers_app: int = 0                     # APP端观看人数（v2.0 新增）
    viewers_web: int = 0                     # 网页端观看人数（v2.0 新增）
    viewers_total: int = 0                   # 总观看人数（v2.0 新增）
    like_view_ratio: float = 0.0             # 播赞比（点赞数/播放量）


@dataclass(slots=True)
class PredictionRecord:
    """预测记录数据类

    由算法预测的播放量达峰时间及置信度等信息。
    每次运行预测算法时生成一条记录，存储预测目标、预计时间、
    置信度、当前状态和实际结果（用于评估算法精度）。
    """

    bvid: str                                # BV号
    algorithm: str                           # 算法名称（如 "linear_velocity"）
    algorithm_id: str                        # 算法唯一标识（如 "linear_velocity_v1"）
    target_threshold: int                    # 目标阈值（播放量），如 10000 表示预测达到一万粉的时间
    predicted_seconds: int                   # 预测到达目标所需的秒数（自发布起算）
    predicted_time: str                      # 预测到达时间（日期时间字符串）
    confidence: float                        # 预测置信度（0~1），越高越可靠
    current_views: int                       # 预测时的当前播放量（基准值）
    metadata: str = ""                       # JSON 字符串，存储算法特定的额外元数据
    predicted_hours: float = 0.0             # 预测所需小时数（= predicted_seconds / 3600）
    current_velocity: float = 0.0            # 当前播放速度（每小时播放增量）
    is_reached: bool = False                 # 是否已达到目标阈值
    actual_time: str = ""                    # 实际到达目标的时间（目标达成后回填）
    error_rate: float = 0.0                  # 预测误差率（计算方式因算法而异）


# ════════════════════════════════════════════════════════════════════
# BV 号校验
# ════════════════════════════════════════════════════════════════════

# Bilibili BV 号格式：以 "BV" 开头，后跟 10~12 位字母数字混合字符
_BVID_PATTERN = re.compile(r"^BV[A-Za-z0-9]{10,12}$")


def _validate_bvid(bvid: str) -> str:
    """校验 BV 号格式，防止路径穿越攻击

    本函数有双重用途：
    1. 格式校验：确保输入符合 BV 号正则模式
    2. 安全防护：BV 号会被用作目录名（data/<BV>/），不合法字符
       可能导致路径穿越，因此必须严格校验

    Args:
        bvid: 待校验的 BV 号字符串

    Returns:
        校验通过的 BV 号（原样返回）

    Raises:
        ValueError: 当 BV 号格式不合法时抛出，附带输入内容便于调试
    """
    if not _BVID_PATTERN.match(bvid):
        raise ValueError(f"无效的 BV 号: {bvid!r}")
    return bvid
