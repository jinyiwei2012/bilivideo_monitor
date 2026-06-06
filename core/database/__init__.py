"""
数据库模块入口
导出核心数据模型、连接管理、视频独立库和中央总数据库的接口
"""

from .models import VideoInfo, MonitorRecord, PredictionRecord, _validate_bvid
from .connection import _ConnectionCtx, _http_session
from .video_db import VideoDatabase
from .central_db import Database, get_db

__all__ = [
    "VideoInfo",  # 视频信息数据类
    "MonitorRecord",  # 监控记录数据类
    "PredictionRecord",  # 预测记录数据类
    "_validate_bvid",  # BV号校验函数
    "_ConnectionCtx",  # 线程安全的数据库连接上下文管理器
    "_http_session",  # 全局 HTTP 会话（用于封面下载）
    "VideoDatabase",  # 单个视频的独立数据库
    "Database",  # 中央总数据库管理类
    "get_db",  # 获取全局 Database 单例
]
