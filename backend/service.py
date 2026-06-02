"""
统一服务层 —— 前后端分离的标准接口

本模块是后端对外的标准化 API 服务层，屏蔽底层实现细节。
所有函数返回纯字典（dict），不依赖任何 GUI 组件。
Web API 和 GUI 均通过本层间接访问引擎和数据库。

功能模块：
- 视频管理: list_videos, get_video, add_video, remove_video
- 数据查询: get_records, get_latest_record, get_predictions, get_milestones
- 通用查询: search_videos, get_stats
- 预测服务: predict_video, predict_all
- 用户认证: auth_register, auth_login, auth_get_user 等
- 引擎状态: get_engine_status
- 日聚合统计: get_daily_stats
"""

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
# 提供视频的 CRUD 操作，集成 Bilibili API 和配置持久化


def list_videos(sort_by="updated_at", order="DESC", limit=100, user=None) -> dict:
    """
    获取视频列表，支持排序、分页和多用户隔离。
    
    Args:
        sort_by: 排序字段（默认 "updated_at"）
        order: 排序方向 "ASC" 或 "DESC"
        limit: 最大返回条数
        user: 当前登录用户信息字典，非管理员用户仅能看到自己的视频
        
    Returns:
        dict: {"total": int, "videos": [dict, ...]}
    """
    videos = central_db.get_video_list(sort_by=sort_by, order=order, limit=limit)
    if user and not user.get("is_admin"):
        bvids = get_user_video_ids(user["id"])
        videos = [v for v in videos if v.get("bvid") in bvids]
    return {"total": len(videos), "videos": videos}


def get_video(bvid: str) -> dict:
    """
    获取单个视频的详细信息。
    
    Args:
        bvid: 视频 BV 号
        
    Returns:
        dict: 视频信息字典
        
    Raises:
        ValueError: BV 号无效或视频不存在
    """
    _validate_bvid(bvid)
    video = central_db.get_video(bvid)
    if not video:
        raise ValueError(f"视频 {bvid} 不存在")
    d = {}
    for f in video.__dataclass_fields__:
        d[f] = getattr(video, f)
    return d


def add_video(bvid: str, user=None) -> dict:
    """
    添加视频到监控列表。
    
    如果视频已存在，仅建立所有权关系并启动监控；
    如果是新视频，先通过 Bilibili API 获取信息入库，再启动监控。
    同时将 BV 号添加到配置的 watch_list 中实现持久化。
    
    Args:
        bvid: 视频 BV 号
        user: 当前登录用户信息字典
        
    Returns:
        dict: {"bvid": str, "title": str, "status": "existed"|"added"}
        
    Raises:
        RuntimeError: API 获取视频信息失败
    """
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
    """
    从监控列表中移除视频。
    
    按用户隔离：只撤销当前用户的所有权；
    如果没有指定用户，则直接从数据库删除视频记录。
    
    Args:
        bvid: 视频 BV 号
        user: 当前登录用户信息字典
        
    Returns:
        dict: {"bvid": str, "status": "removed"}
    """
    _validate_bvid(bvid)
    if user:
        remove_video_ownership(bvid, user["id"])
    else:
        central_db.delete_video(bvid)
    engine = get_engine()
    engine.remove_video(bvid)
    return {"bvid": bvid, "status": "removed"}


# ── 数据查询 ──────────────────────────────────
# 提供监控记录、预测结果、里程碑的查询接口


def get_records(bvid: str, start_time=None, end_time=None, limit=1000) -> dict:
    """
    查询指定视频的监控记录，支持时间范围过滤。
    
    Args:
        bvid: 视频 BV 号
        start_time: 起始时间（可选）
        end_time: 结束时间（可选）
        limit: 最大返回条数
        
    Returns:
        dict: {"bvid": str, "total": int, "records": [dict, ...]}
    """
    _validate_bvid(bvid)
    records = central_db.query_monitor_records(bvid, start_time=start_time, end_time=end_time, limit=limit)
    return {"bvid": bvid, "total": len(records), "records": records}


def get_latest_record(bvid: str) -> dict:
    """
    获取指定视频的最新一条监控记录。
    
    Args:
        bvid: 视频 BV 号
        
    Returns:
        dict: {"bvid": str, "record": dict}
        
    Raises:
        ValueError: 视频无监控记录
    """
    _validate_bvid(bvid)
    records = central_db.get_monitor_history(bvid, limit=1)
    if not records:
        raise ValueError(f"视频 {bvid} 无监控记录")
    return {"bvid": bvid, "record": records[0]}


def get_predictions(bvid=None, algorithm=None, limit=100, user=None) -> dict:
    """
    获取预测记录，支持按视频、算法过滤。
    
    多用户模式下，非管理员仅能看到自己的视频的预测。
    
    Args:
        bvid: 视频 BV 号（可选）
        algorithm: 算法名称过滤（可选）
        limit: 最大返回条数
        user: 当前登录用户信息字典
        
    Returns:
        dict: {"bvid": str|None, "total": int, "predictions": [dict, ...]}
    """
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
    """
    获取里程碑记录。
    
    如果指定 bvid，返回该视频的里程碑列表；
    否则返回所有里程碑按分组聚合的结果。
    
    Args:
        bvid: 视频 BV 号（可选）
        
    Returns:
        dict: 包含 milestones 信息的字典
    """
    if bvid:
        _validate_bvid(bvid)
        milestones = central_db.get_milestones(bvid=bvid)
        return {"bvid": bvid, "milestones": milestones}
    return {"milestones": central_db.get_all_milestones_grouped()}


def search_videos(keyword="", field="title", limit=50, user=None) -> dict:
    """
    搜索视频，支持按标题等字段模糊匹配。
    
    Args:
        keyword: 搜索关键词
        field: 搜索字段（默认 "title"）
        limit: 最大返回条数
        user: 当前登录用户信息字典
        
    Returns:
        dict: {"keyword": str, "total": int, "results": [dict, ...]}
    """
    results = central_db.search_videos(keyword=keyword, field=field, limit=limit)
    if user and not user.get("is_admin"):
        bvids = get_user_video_ids(user["id"])
        results = [r for r in results if r.get("bvid") in bvids]
    return {"keyword": keyword, "total": len(results), "results": results}


def get_stats(user=None) -> dict:
    """
    获取系统总体统计数据，包括视频数、总播放量等。
    
    多用户模式下，非管理员仅统计自己的视频。
    
    Args:
        user: 当前登录用户信息字典
        
    Returns:
        dict: 统计信息字典，包含 total_views 等字段
    """
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
# 提供按需和批量预测的调用接口


def predict_video(bvid: str) -> dict:
    """
    对指定视频执行一次完整预测（收集历史 → 运行算法 → 保存结果）。
    
    Args:
        bvid: 视频 BV 号
        
    Returns:
        dict: 聚合后的预测结果，包含 prediction, growth, success_list 等
        
    Raises:
        ValueError: 视频不存在
    """
    _validate_bvid(bvid)
    video = central_db.get_video(bvid)
    if not video:
        raise ValueError(f"视频 {bvid} 不存在")

    engine = get_engine()
    current_view = video.view_count
    history = central_db.get_monitor_history(bvid, limit=500)
    history_data = [(r.get("timestamp", ""), r.get("view_count", 0)) for r in history if r]

    db_history = engine._fetch_db_history(bvid)

    results = engine._do_run_prediction(bvid, current_view, history_data, db_history)
    engine._save_predictions(bvid, current_view, results)
    return engine._build_prediction_result(bvid, current_view, results)


def predict_all(user=None) -> dict:
    """
    对所有视频执行批量预测。
    
    多用户模式下仅预测当前用户的视频。
    单个视频的预测异常不会中断整体流程。
    
    Args:
        user: 当前登录用户信息字典
        
    Returns:
        dict: {"total": int, "results": {bvid: result, ...}}
    """
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
# 对 user_manager 的薄封装，提供统一的认证接口


def auth_register(username: str, password: str) -> dict:
    """
    注册新用户。
    
    Args:
        username: 用户名（至少 2 个字符）
        password: 密码（至少 4 个字符）
        
    Returns:
        dict: {"username": str, "apikey": str, "is_admin": bool}
        
    Raises:
        ValueError: 用户名已存在或格式不符合要求
    """
    return register_user(username, password)


def auth_login(username: str = None, password: str = None, apikey: str = None) -> Optional[Dict]:
    """
    用户登录，支持用户名+密码 或 API Key 两种方式。
    
    Args:
        username: 用户名（可选）
        password: 密码（可选）
        apikey: API Key（可选，优先级高于用户名密码）
        
    Returns:
        dict: 用户信息字典，失败返回 None
    """
    return login_user(username=username, password=password, apikey=apikey)


def auth_get_user(apikey: str) -> Optional[Dict]:
    """
    通过 API Key 获取用户信息。
    
    Args:
        apikey: 用户的 API Key
        
    Returns:
        dict: 用户信息字典，不存在返回 None
    """
    return get_user_by_apikey(apikey)


def auth_regenerate_apikey(user_id: int) -> str:
    """
    重新生成指定用户的 API Key（旧 Key 立即失效）。
    
    Args:
        user_id: 用户 ID
        
    Returns:
        str: 新的 API Key
    """
    return regenerate_apikey(user_id)


def auth_delete_user(user_id: int):
    """
    删除用户账户及其所有关联数据。
    
    Args:
        user_id: 要删除的用户 ID
    """
    delete_user(user_id)


# ── 引擎状态 ──────────────────────────────────
# 提供后端引擎的运行状态查询


def get_engine_status() -> dict:
    """
    获取监控引擎的当前运行状态。
    
    Returns:
        dict: {"video_count": int, "worker_count": int, "video_ids": [str, ...]}
    """
    engine = get_engine()
    return {
        "video_count": engine.video_count,
        "worker_count": len(engine._workers),
        "video_ids": engine.video_ids,
    }


# ── 日聚合统计 ────────────────────────────────
# 将原始监控记录按天聚合为日增量统计


def get_daily_stats(bvid: str, days: int = 30) -> dict:
    """
    获取指定视频的每日播放量增量统计。
    
    将原始监控记录按日期分组，计算每日的：
    - view_increment: 播放量增量（当日最大值 - 前一日最大值）
    - max_views: 当日最大播放量
    - likes: 当日点赞数
    
    Args:
        bvid: 视频 BV 号
        days: 返回最近多少天的数据（默认 30）
        
    Returns:
        dict: {"bvid": str, "daily": [{"date": str, "view_increment": int, ...}, ...]}
    """
    _validate_bvid(bvid)
    records = central_db.query_monitor_records(bvid, limit=days * 144)
    if not records:
        return {"bvid": bvid, "daily": []}

    from collections import defaultdict
    daily = defaultdict(lambda: {"views": 0, "likes": 0, "max_views": 0})
    for r in records:
        day = str(r.get("timestamp", ""))[:10]  # 取日期部分 YYYY-MM-DD
        v = r.get("view_count", 0)
        l = r.get("like_count", 0)
        daily[day]["max_views"] = max(daily[day]["max_views"], v)
        daily[day]["likes"] = max(daily[day]["likes"], l)

    sorted_days = sorted(daily.keys())
    result = []
    prev_max = 0
    for day in sorted_days:
        d = daily[day]
        increment = max(0, d["max_views"] - prev_max)
        prev_max = d["max_views"]
        result.append({
            "date": day,
            "view_increment": increment,
            "max_views": d["max_views"],
            "likes": d["likes"],
        })

    return {"bvid": bvid, "daily": result[-days:]}
