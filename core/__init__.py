"""
核心模块
包含数据库、API、通知等核心功能
"""

from .database import Database, VideoInfo, MonitorRecord, PredictionRecord, db
from .bilibili_api import BilibiliAPI, bilibili_api
from .notification import NotificationManager, notification_manager

__all__ = [
    'Database',
    'VideoInfo',
    'MonitorRecord',
    'PredictionRecord',
    'db',
    'BilibiliAPI',
    'bilibili_api',
    'NotificationManager',
    'notification_manager'
]
