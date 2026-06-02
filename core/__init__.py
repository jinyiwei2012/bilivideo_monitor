"""
核心模块 (Core Module)
=====================

本模块是 B站视频监控与播放量预测系统 的核心层，包含以下子模块：

  - database          : 数据库管理层（每视频独立 SQLite + 中央汇总库）
  - bilibili_api      : B站 API 封装（请求、重试、412 绕过、WBI 签名）
  - bilibili_auth     : B站认证管理（密码登录、QR 扫码、Cookie 持久化、多账号）
  - bilibili_request  : HTTP 请求核心（curl_cffi TLS 伪装、代理绑定、指数退避）
  - bilibili_video    : 视频相关操作（信息、统计、观看人数、弹幕、评论）
  - bilibili_up       : UP主相关操作（搜索、信息、统计、视频列表）
  - browser_fallback  : 无头浏览器兜底（Playwright，最终回退方案）
  - notification      : 通知管理（Windows 原生通知 + QQ/OneBot 推送）
  - proxy_manager     : 代理管理器（轮询、UA绑定、失败清理、自动发现）
  - smart_alert       : 智能预警（异常增长检测、趋势反转、在线人数异常）
  - up_database       : UP主数据库管理（信息表 + 趋势历史表）
  - up_fetcher        : UP主数据多源获取器（多库并行，防 412 限流）

对外导出的公共接口：
  Database, VideoInfo, MonitorRecord, PredictionRecord, get_db, db
  BilibiliAPI, get_bilibili_api
  NotificationManager, notification_manager

便捷别名：
  from core import db          → 全局数据库实例（延迟初始化）
  from core import bilibili_api → 全局 API 实例（通过 __getattr__ 代理访问）
"""

from .database import Database, VideoInfo, MonitorRecord, PredictionRecord, get_db
from .bilibili_api import BilibiliAPI, get_bilibili_api
from .notification import NotificationManager, notification_manager

# 便捷别名：db = get_db()（延迟初始化，首次访问时才创建连接）
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
