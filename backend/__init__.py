"""后端模块 —— 独立监控引擎 + 统一服务层"""
from .engine import MonitorEngine, get_engine
from .service import (
    list_videos, get_video, add_video, remove_video,
    get_records, get_latest_record, get_predictions, get_milestones,
    search_videos, get_stats,
    predict_video, predict_all,
    auth_register, auth_login, auth_get_user, auth_regenerate_apikey, auth_delete_user,
)
