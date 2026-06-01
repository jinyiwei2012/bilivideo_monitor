"""统一服务层 —— 前后端分离的标准接口"""

import logging
from typing import Optional, Dict

from core import db as central_db
from core.bilibili_api import get_bilibili_api
from core.database.models import _validate_bvid, VideoInfo
from config import load_config, save_config

from .engine import get_engine
from .user_manager import (
    register_user, login_user, get_user_by_apikey,
    regenerate_apikey, delete_user,
    add_video_ownership, remove_video_ownership, get_user_video_ids,
)

logger = logging.getLogger("backend.service")


# ── 视频管理 ──────────────────────────────────


def list_videos(sort_by="updated_at", order="DESC", limit=100, user=None) -> dict:
    videos = central_db.get_video_list(sort_by=sort_by, order=order, limit=limit)
    if user and not user.get("is_admin"):
        bvids = get_user_video_ids(user["id"])
        videos = [v for v in videos if v.get("bvid") in bvids]
    return {"total": len(videos), "videos": videos}


def get_video(bvid: str) -> dict:
    _validate_bvid(bvid)
    video = central_db.get_video(bvid)
    if not video:
        raise ValueError(f"视频 {bvid} 不存在")
    d = {}
    for f in video.__dataclass_fields__:
        d[f] = getattr(video, f)
    return d


def add_video(bvid: str, user=None) -> dict:
    _validate_bvid(bvid)
    existing = central_db.get_video(bvid)
    if existing:
        if user:
            add_video_ownership(bvid, user["id"])
        engine = get_engine()
        engine.add_video(bvid)
        return {"bvid": bvid, "title": existing.title, "status": "existed"}

    api = get_bilibili_api()
    data = api.get_video_info(bvid)
    if not data or data.get("code") != 0:
        raise RuntimeError("无法获取视频信息")

    vdata = data.get("data", {})
    video = VideoInfo.from_api_data(bvid, vdata)
    central_db.add_video(video)

    if user:
        add_video_ownership(bvid, user["id"])

    engine = get_engine()
    engine.add_video(bvid)

    config = load_config()
    watch_list = config.get("watch_list", [])
    if bvid not in watch_list:
        watch_list.append(bvid)
        config["watch_list"] = watch_list
        save_config(config)

    return {"bvid": bvid, "title": video.title, "status": "added"}


def remove_video(bvid: str, user=None) -> dict:
    _validate_bvid(bvid)
    if user:
        remove_video_ownership(bvid, user["id"])
    else:
        central_db.delete_video(bvid)
    engine = get_engine()
    engine.remove_video(bvid)
    return {"bvid": bvid, "status": "removed"}


# ── 数据查询 ──────────────────────────────────


def get_records(bvid: str, start_time=None, end_time=None, limit=1000) -> dict:
    _validate_bvid(bvid)
    records = central_db.query_monitor_records(bvid, start_time=start_time, end_time=end_time, limit=limit)
    return {"bvid": bvid, "total": len(records), "records": records}


def get_latest_record(bvid: str) -> dict:
    _validate_bvid(bvid)
    records = central_db.get_monitor_history(bvid, limit=1)
    if not records:
        raise ValueError(f"视频 {bvid} 无监控记录")
    return {"bvid": bvid, "record": records[0]}


def get_predictions(bvid=None, algorithm=None, limit=100, user=None) -> dict:
    if user and not user.get("is_admin") and bvid is None:
        bvids = get_user_video_ids(user["id"])
        all_preds = []
        for bid in bvids:
            all_preds += central_db.get_predictions(bvid=bid, algorithm=algorithm, limit=limit)
            if len(all_preds) >= limit:
                break
        predictions = all_preds[:limit]
    else:
        predictions = central_db.get_predictions(bvid=bvid, algorithm=algorithm, limit=limit)
    return {"bvid": bvid, "total": len(predictions), "predictions": predictions}


def get_milestones(bvid=None) -> dict:
    if bvid:
        _validate_bvid(bvid)
        milestones = central_db.get_milestones(bvid=bvid)
        return {"bvid": bvid, "milestones": milestones}
    return {"milestones": central_db.get_all_milestones_grouped()}


def search_videos(keyword="", field="title", limit=50, user=None) -> dict:
    results = central_db.search_videos(keyword=keyword, field=field, limit=limit)
    if user and not user.get("is_admin"):
        bvids = get_user_video_ids(user["id"])
        results = [r for r in results if r.get("bvid") in bvids]
    return {"keyword": keyword, "total": len(results), "results": results}


def get_stats(user=None) -> dict:
    stats = central_db.get_summary_stats()
    if user and not user.get("is_admin"):
        bvids = get_user_video_ids(user["id"])
        total_views = 0
        for bvid in bvids:
            v = central_db.get_video(bvid)
            if v:
                total_views += v.view_count
    else:
        videos = central_db.get_video_list(limit=100)
        total_views = sum(v.get("view_count", 0) for v in videos)
    return {**stats, "total_views": total_views}


# ── 预测 ──────────────────────────────────────


def predict_video(bvid: str) -> dict:
    _validate_bvid(bvid)
    video = central_db.get_video(bvid)
    if not video:
        raise ValueError(f"视频 {bvid} 不存在")

    engine = get_engine()
    current_view = video.view_count
    history = central_db.get_monitor_history(bvid, limit=500)
    history_data = [(r.get("timestamp", ""), r.get("view_count", 0)) for r in history if r]

    results = engine._do_run_prediction(bvid, current_view, history_data)
    engine._save_predictions(bvid, current_view, results)
    return engine._build_prediction_result(bvid, current_view, results)


def predict_all(user=None) -> dict:
    if user and not user.get("is_admin"):
        bvids = get_user_video_ids(user["id"])
    else:
        bvids = [v.get("bvid") for v in central_db.get_video_list(limit=100)]

    results = {}
    for bvid in bvids:
        try:
            results[bvid] = predict_video(bvid)
        except Exception as e:
            results[bvid] = {"error": str(e)}
    return {"total": len(results), "results": results}


# ── 用户管理 ──────────────────────────────────


def auth_register(username: str, password: str) -> dict:
    return register_user(username, password)


def auth_login(username: str = None, password: str = None, apikey: str = None) -> Optional[Dict]:
    return login_user(username=username, password=password, apikey=apikey)


def auth_get_user(apikey: str) -> Optional[Dict]:
    return get_user_by_apikey(apikey)


def auth_regenerate_apikey(user_id: int) -> str:
    return regenerate_apikey(user_id)


def auth_delete_user(user_id: int):
    delete_user(user_id)
