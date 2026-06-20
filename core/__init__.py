"""
核心模块
包含数据库、API、通知等核心功能
"""

from .database import Database, VideoInfo, MonitorRecord, PredictionRecord, get_db
from .bilibili_api import BilibiliAPI, get_bilibili_api
from .notification import NotificationManager, notification_manager

# Convenience aliases
db = get_db()
bilibili_api = get_bilibili_api()

__all__ = [
    "Database",
    "VideoInfo",
    "MonitorRecord",
    "PredictionRecord",
    "get_db",
    "db",
    "BilibiliAPI",
    "get_bilibili_api",
    "bilibili_api",
    "NotificationManager",
    "notification_manager",
]
