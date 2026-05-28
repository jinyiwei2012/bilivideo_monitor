"""
核心模块
包含数据库、API、通知等核心功能
"""

from .database import Database, VideoInfo, MonitorRecord, PredictionRecord, get_db
from .bilibili_api import BilibiliAPI, get_bilibili_api
from .notification import NotificationManager, notification_manager

# Convenience alias: db = get_db() (lazy, resolves on first access)
db = get_db()

__all__ = [
    "Database",
    "VideoInfo",
    "MonitorRecord",
    "PredictionRecord",
    "get_db",
    "db",
    "BilibiliAPI",
    "get_bilibili_api",
    "NotificationManager",
    "notification_manager",
]
