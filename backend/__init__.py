"""
后端模块 —— 独立监控引擎 + 统一服务层

本模块提供与 GUI 完全解耦的后端核心功能：
- MonitorEngine: 视频数据拉取、预测计算、数据库写入的独立引擎
- 统一服务层: 视频管理、数据查询、预测、用户认证的标准化接口

所有功能均通过 get_engine() 获取全局单例，支持多视频并发监控。
"""
from .engine import MonitorEngine, get_engine
from .service import (
    list_videos, get_video, add_video, remove_video,
    get_records, get_latest_record, get_predictions, get_milestones,
    search_videos, get_stats,
    predict_video, predict_all,
    auth_register, auth_login, auth_get_user, auth_regenerate_apikey, auth_delete_user,
)
