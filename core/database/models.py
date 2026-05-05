"""数据模型定义"""

import re
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass


@dataclass
class VideoInfo:
    """视频信息"""
    bvid: str
    title: str
    view_count: int = 0
    like_count: int = 0
    coin_count: int = 0
    share_count: int = 0
    favorite_count: int = 0
    danmaku_count: int = 0
    reply_count: int = 0
    viewers_app: int = 0
    viewers_web: int = 0
    viewers_total: int = 0
    cover_path: str = ""
    like_view_ratio: float = 0.0
    owner_name: str = ""
    owner_id: int = 0
    pubdate: str = ""
    duration: int = 0
    pic: str = ""


@dataclass
class MonitorRecord:
    """监控记录"""
    bvid: str
    timestamp: str
    view_count: int
    like_count: int
    coin_count: int
    share_count: int
    favorite_count: int
    danmaku_count: int
    reply_count: int
    viewers_app: int = 0
    viewers_web: int = 0
    viewers_total: int = 0
    like_view_ratio: float = 0.0


@dataclass
class PredictionRecord:
    """预测记录"""
    bvid: str
    algorithm: str
    algorithm_id: str
    target_threshold: int
    predicted_seconds: int
    predicted_time: str
    confidence: float
    current_views: int
    metadata: str = ""  # JSON字符串，存储额外的元数据
    predicted_hours: float = 0.0  # 预测所需小时数
    current_velocity: float = 0.0  # 当前播放速度
    is_reached: bool = False
    actual_time: str = ""
    error_rate: float = 0.0


_BVID_PATTERN = re.compile(r'^BV[A-Za-z0-9]{10,12}$')


def _validate_bvid(bvid: str) -> str:
    """校验 BV 号格式，防止路径穿越。"""
    if not _BVID_PATTERN.match(bvid):
        raise ValueError(f"无效的 BV 号: {bvid!r}")
    return bvid
