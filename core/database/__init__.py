"""
数据库模块 - 增强版
支持观看人数、封面保存、播赞比、预测记录
每个视频独立数据库 + 总数据库同步
"""

from .models import VideoInfo, MonitorRecord, PredictionRecord, _validate_bvid
from .connection import _ConnectionCtx, _http_session
from .video_db import VideoDatabase
from .central_db import Database, db

__all__ = [
    'VideoInfo',
    'MonitorRecord',
    'PredictionRecord',
    '_validate_bvid',
    '_ConnectionCtx',
    '_http_session',
    'VideoDatabase',
    'Database',
    'db',
]
