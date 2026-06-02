"""
数据库模块入口
================
本模块是数据库子系统的公共接口，负责导出核心数据模型、连接管理、
视频独立库和中央总数据库的接口，供项目中其他模块引用。

导出的符号分为三类：
1. 数据模型：VideoInfo（视频信息）、MonitorRecord（监控记录）、PredictionRecord（预测记录）
2. 基础设施：_ConnectionCtx（线程安全连接上下文）、_http_session（全局 HTTP 会话）
3. 数据库接口：VideoDatabase（单视频独立库）、Database（中央总库）、get_db（单例工厂）
"""
#  ── 数据模型导入 ────────────────────────────────────────────────
from .models import VideoInfo, MonitorRecord, PredictionRecord, _validate_bvid

#  ── 基础设施导入 ────────────────────────────────────────────────
from .connection import _ConnectionCtx, _http_session

#  ── 数据库接口导入 ──────────────────────────────────────────────
from .video_db import VideoDatabase
from .central_db import Database, get_db

#  ── 控制 from database import * 的行为 ───────────────────────────
__all__ = [
    "VideoInfo",          # 视频信息数据类
    "MonitorRecord",      # 监控记录数据类
    "PredictionRecord",   # 预测记录数据类
    "_validate_bvid",     # BV号校验函数
    "_ConnectionCtx",     # 线程安全的数据库连接上下文管理器
    "_http_session",      # 全局 HTTP 会话（用于封面下载）
    "VideoDatabase",      # 单个视频的独立数据库
    "Database",           # 中央总数据库管理类
    "get_db",             # 获取全局 Database 单例
]
