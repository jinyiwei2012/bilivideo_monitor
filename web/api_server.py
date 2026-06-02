"""
FastAPI 服务器 —— REST API + WebSocket + Web Dashboard (前后端分离)

提供完整的 RESTful API 接口供前端和第三方调用。

API 路由概览：
- POST   /api/v1/auth/register         注册用户
- POST   /api/v1/auth/login            用户登录
- GET    /api/v1/auth/me               获取当前用户信息
- POST   /api/v1/auth/apikey/regenerate 重新生成 API Key
- DELETE /api/v1/auth/account          注销账户
- GET    /api/v1/health                健康检查
- GET    /api/v1/stats                 系统统计
- GET    /api/v1/videos                视频列表
- GET    /api/v1/videos/{bvid}         视频详情
- POST   /api/v1/videos                添加视频
- DELETE /api/v1/videos/{bvid}         移除视频
- GET    /api/v1/videos/{bvid}/records 监控记录
- GET    /api/v1/videos/{bvid}/records/latest 最新记录
- GET    /api/v1/videos/{bvid}/predictions     预测历史
- GET    /api/v1/predictions                   全局预测历史
- POST   /api/v1/videos/{bvid}/predict         触发单视频预测
- POST   /api/v1/predict-all                   触发全量预测
- GET    /api/v1/videos/{bvid}/milestones      里程碑
- GET    /api/v1/milestones                    全局里程碑
- GET    /api/v1/search                        搜索视频
- GET    /api/v1/config                        获取配置
- POST   /api/v1/config                        更新配置
- GET    /api/v1/engine/status                 引擎状态
- GET    /api/v1/videos/{bvid}/stats/daily     日聚合统计
- WS     /ws                                   WebSocket 连接
- GET    /                                      Web Dashboard
"""

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Query, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.database.models import _validate_bvid
from config import load_config, save_config

from backend.service import (
    list_videos, get_video, add_video, remove_video,
    get_records, get_latest_record, get_predictions, get_milestones,
    search_videos, get_stats,
    predict_video, predict_all,
    auth_register, auth_login, auth_get_user,
    auth_regenerate_apikey, auth_delete_user,
    get_engine_status, get_daily_stats,
)

from .auth import authenticate, get_optional_user, require_admin
from .websocket_manager import ws_manager

logger = logging.getLogger(__name__)

# ── 模板和静态文件路径 ────────────────────────

# 项目 web 目录基准路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Jinja2 模板目录
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# API 路径前缀
API_PREFIX = "/api/v1"


def _is_local_request(request: Request) -> bool:
    """
    判断请求是否来自本地网络。
    
    用于限制管理员注册等高敏感操作仅允许本地执行。
    检查 X-Forwarded-For 头（代理穿透）和直接客户端 IP。
    
    Args:
        request: FastAPI Request 对象
        
    Returns:
        bool: 是否为本地请求
    """
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else ""
    return client_ip in ("127.0.0.1", "::1", "localhost", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 应用生命周期管理。
    
    在启动时记录日志，关闭时执行清理。
    """
    logger.info("API 服务器已启动")
    yield
    logger.info("API 服务器已关闭")


# ── FastAPI 应用实例 ──────────────────────────

app = FastAPI(
    title="B站视频监控 API",
    description="B站视频监控与播放量预测系统 REST API",
    version="3.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)


# ── 认证 ──────────────────────────────────────
# 用户注册、登录、信息查询、密钥轮换、账户注销


@app.post(f"{API_PREFIX}/auth/register")
async def api_register(data: dict, request: Request):
    """
    注册新用户。
    
    用户名和密码不能为空。管理员账号仅限本地网络创建。
    
    Request body:
        {"username": "...", "password": "...", "is_admin": false}
        
    Responses:
        200: {"status": "ok", "user": {"username": "...", "apikey": "...", "is_admin": false}}
        400: 用户名或密码为空
        403: 管理员账号非本地创建
        409: 用户名已存在
    """
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    is_local = _is_local_request(request)
    if data.get("is_admin") and not is_local:
        raise HTTPException(status_code=403, detail="管理员账号仅限本地网络创建")
    try:
        user = auth_register(username, password)
        return {"status": "ok", "user": user}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post(f"{API_PREFIX}/auth/login")
async def api_login(data: dict):
    """
    用户登录，支持用户名+密码或 API Key 两种方式。
    
    Request body:
        {"username": "...", "password": "..."}  或  {"apikey": "..."}
        
    Responses:
        200: {"status": "ok", "user": {"id": ..., "username": "...", "apikey": "...", "is_admin": bool}}
        401: 认证信息无效
    """
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    apikey = data.get("apikey", "").strip()
    user = auth_login(username=username, password=password, apikey=apikey)
    if not user:
        raise HTTPException(status_code=401, detail="用户名/密码或 API Key 无效")
    return {"status": "ok", "user": user}


@app.get(f"{API_PREFIX}/auth/me")
async def api_me(user: dict = Depends(authenticate)):
    """
    获取当前登录用户的完整信息（需认证）。
    
    Headers:
        Authorization: Bearer <apikey>
        
    Responses:
        200: {"user": {...}}
        401: 未认证
    """
    return {"user": user}


@app.post(f"{API_PREFIX}/auth/apikey/regenerate")
async def api_regenerate_apikey(user: dict = Depends(authenticate)):
    """
    重新生成当前用户的 API Key（旧 Key 立即失效）。
    
    Headers:
        Authorization: Bearer <旧apikey>
        
    Responses:
        200: {"status": "ok", "apikey": "<新key>"}
    """
    new_key = auth_regenerate_apikey(user["id"])
    return {"status": "ok", "apikey": new_key}


@app.delete(f"{API_PREFIX}/auth/account")
async def api_delete_account(user: dict = Depends(authenticate)):
    """
    注销当前用户账户（管理员不可通过此接口删除）。
    
    Headers:
        Authorization: Bearer <apikey>
        
    Responses:
        200: {"status": "ok", "message": "已注销 <username>"}
        400: 管理员账户不可删除
    """
    if user.get("is_admin"):
        raise HTTPException(status_code=400, detail="管理员账户不可删除")
    auth_delete_user(user["id"])
    return {"status": "ok", "message": f"已注销 {user.get('username', '')}"}


# ── 健康检查 ──────────────────────────────────
# 提供系统运行状态的快速健康检查端点


@app.get(f"{API_PREFIX}/health")
async def health_check():
    """
    健康检查端点（无需认证）。
    
    Returns:
        {"status": "ok", "version": "3.2.0", "ws_connections": N, "stats": {...}, "timestamp": ...}
    """
    stats = get_stats()
    return {
        "status": "ok", "version": "3.2.0",
        "ws_connections": ws_manager.connection_count,
        "stats": stats, "timestamp": time.time(),
    }


# ── 统计 ──────────────────────────────────────


@app.get(f"{API_PREFIX}/stats")
async def api_stats(user: Optional[dict] = Depends(get_optional_user)):
    """
    获取系统总体统计数据（可选认证，非管理员只能看自己的数据）。
    
    Returns:
        统计信息字典，包含 total_views 等字段
    """
    return get_stats(user=user)


# ── 视频列表 ──────────────────────────────────


@app.get(f"{API_PREFIX}/videos")
async def api_list_videos(
    sort_by: str = Query("updated_at"),
    order: str = Query("DESC"),
    limit: int = Query(100, ge=1, le=500),
    user: Optional[dict] = Depends(get_optional_user),
):
    """
    获取视频列表，支持排序和分页（可选认证）。
    
    Query params:
        sort_by: 排序字段（默认 "updated_at"）
        order: 排序方向 "ASC"|"DESC"（默认 "DESC"）
        limit: 最大返回条数（1-500，默认 100）
        
    Returns:
        {"total": int, "videos": [...]}
    """
    return list_videos(sort_by=sort_by, order=order, limit=limit, user=user)


@app.get(f"{API_PREFIX}/videos/{{bvid}}")
async def api_get_video(bvid: str):
    """
    获取单个视频详情（无需认证）。
    
    Path params:
        bvid: 视频 BV 号
        
    Responses:
        200: 视频信息字典
        404: 视频不存在
    """
    try:
        return get_video(bvid)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post(f"{API_PREFIX}/videos")
async def api_add_video(bvid: str = Query(...), user: dict = Depends(authenticate)):
    """
    添加视频到监控列表（需认证）。
    
    Query params:
        bvid: 视频 BV 号
        
    Responses:
        200: {"bvid": ..., "title": ..., "status": "added"|"existed"}
        400: 无法获取视频信息
    """
    try:
        return add_video(bvid, user=user)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete(f"{API_PREFIX}/videos/{{bvid}}")
async def api_remove_video(bvid: str, user: dict = Depends(authenticate)):
    """
    从监控列表移除视频（需认证）。
    
    Path params:
        bvid: 视频 BV 号
        
    Responses:
        200: {"bvid": ..., "status": "removed"}
    """
    _validate_bvid(bvid)
    return remove_video(bvid, user=user)


# ── 监控记录 ──────────────────────────────────


@app.get(f"{API_PREFIX}/videos/{{bvid}}/records")
async def api_get_records(
    bvid: str,
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    limit: int = Query(1000, ge=1, le=10000),
):
    """
    查询视频监控记录（无需认证），支持时间范围过滤。
    
    Query params:
        start_time: 起始时间（ISO 格式，可选）
        end_time: 结束时间（ISO 格式，可选）
        limit: 最大返回条数（1-10000，默认 1000）
    """
    return get_records(bvid, start_time=start_time, end_time=end_time, limit=limit)


@app.get(f"{API_PREFIX}/videos/{{bvid}}/records/latest")
async def api_get_latest(bvid: str):
    """
    获取视频最新监控记录（无需认证）。
    
    Responses:
        200: {"bvid": ..., "record": {...}}
        404: 无监控记录
    """
    try:
        return get_latest_record(bvid)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── 预测 ──────────────────────────────────────


@app.get(f"{API_PREFIX}/videos/{{bvid}}/predictions")
async def api_get_predictions(bvid: str, algorithm: Optional[str] = Query(None), limit: int = Query(100)):
    """
    获取视频预测历史（无需认证）。
    
    Query params:
        algorithm: 算法名称过滤（可选）
        limit: 最大返回条数
    """
    return get_predictions(bvid=bvid, algorithm=algorithm, limit=limit)


@app.get(f"{API_PREFIX}/predictions")
async def api_get_all_predictions(
    algorithm: Optional[str] = Query(None),
    limit: int = Query(100),
    user: Optional[dict] = Depends(get_optional_user),
):
    """
    获取全局预测历史（可选认证）。
    
    Query params:
        algorithm: 算法名称过滤（可选）
        limit: 最大返回条数
    """
    return get_predictions(algorithm=algorithm, limit=limit, user=user)


@app.post(f"{API_PREFIX}/videos/{{bvid}}/predict")
async def api_predict_video(bvid: str, user: dict = Depends(authenticate)):
    """
    对指定视频触发一次即时预测（需认证）。
    
    会使用最新的历史数据运行所有算法，结果自动持久化。
    
    Responses:
        200: {"status": "ok", "bvid": ..., "result": {...}}
        404: 视频不存在
        500: 预测异常
    """
    try:
        return {"status": "ok", "bvid": bvid, "result": predict_video(bvid)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{API_PREFIX}/predict-all")
async def api_predict_all(user: dict = Depends(authenticate)):
    """
    对所有视频触发批量预测（需认证）。
    
    多用户模式下仅预测当前用户拥有的视频。
    单个视频的预测失败不影响其他视频。
    
    Responses:
        200: {"status": "ok", "total": N, "results": {bvid: result, ...}}
    """
    return {"status": "ok", **predict_all(user=user)}


# ── 里程碑 ────────────────────────────────────


@app.get(f"{API_PREFIX}/videos/{{bvid}}/milestones")
async def api_get_milestones(bvid: str):
    """
    获取指定视频的里程碑记录（无需认证）。
    """
    return get_milestones(bvid=bvid)


@app.get(f"{API_PREFIX}/milestones")
async def api_get_all_milestones():
    """
    获取全局里程碑记录（按分组聚合，无需认证）。
    """
    return get_milestones()


# ── 搜索 ──────────────────────────────────────


@app.get(f"{API_PREFIX}/search")
async def api_search(
    keyword: str = Query(""),
    field: str = Query("title"),
    limit: int = Query(50),
    user: Optional[dict] = Depends(get_optional_user),
):
    """
    搜索视频（可选认证）。
    
    Query params:
        keyword: 搜索关键词
        field: 搜索字段（默认 "title"）
        limit: 最大返回条数
    """
    return search_videos(keyword=keyword, field=field, limit=limit, user=user)


# ── 配置 ──────────────────────────────────────
# 管理员专用的配置读写接口


@app.get(f"{API_PREFIX}/config")
async def api_get_config(user: dict = Depends(require_admin)):
    """
    获取系统完整配置（需管理员权限）。
    
    Returns:
        完整配置字典
    """
    return load_config()


@app.post(f"{API_PREFIX}/config")
async def api_update_config(config: dict, user: dict = Depends(require_admin)):
    """
    更新系统配置（需管理员权限）。
    
    Request body:
        完整的配置 JSON 对象
        
    Responses:
        200: {"status": "ok"}
        400: 配置格式不正确
        500: 保存失败
    """
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="配置必须是 JSON 对象")
    if "watch_list" in config and not isinstance(config["watch_list"], list):
        raise HTTPException(status_code=400, detail="watch_list 必须是数组")
    if not save_config(config):
        raise HTTPException(status_code=500, detail="保存配置失败")
    return {"status": "ok"}


# ── 引擎状态 ──────────────────────────────────


@app.get(f"{API_PREFIX}/engine/status")
async def api_engine_status(user: dict = Depends(require_admin)):
    """
    获取监控引擎运行状态（需管理员权限）。
    
    Returns:
        {"video_count": int, "worker_count": int, "video_ids": [...]}
    """
    return get_engine_status()


# ── 日聚合 ────────────────────────────────────


@app.get(f"{API_PREFIX}/videos/{{bvid}}/stats/daily")
async def api_daily_stats(bvid: str, days: int = Query(30, ge=1, le=90)):
    """
    获取视频每日播放量增量统计（无需认证）。
    
    Query params:
        days: 返回天数（1-90，默认 30）
        
    Returns:
        {"bvid": ..., "daily": [{"date": ..., "view_increment": ..., ...}, ...]}
    """
    return get_daily_stats(bvid, days=days)


# ── WebSocket ─────────────────────────────────
# 实时双向通信通道


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket 连接端点。
    
    连接后自动发送 connected 消息，客户端可发送 {"action": "ping"} 进行心跳检测。
    服务器通过 ws_manager 管理所有连接，支持广播推送。
    
    Path: /ws
    Protocol: 纯文本 (JSON 编码)
    """
    await ws_manager.connect(websocket)
    try:
        await ws_manager.send_to(websocket, {"type": "connected", "message": "已连接", "timestamp": time.time()})
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("action") == "ping":
                    await ws_manager.send_to(websocket, {"type": "pong", "timestamp": time.time()})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(websocket)


# ── Dashboard ─────────────────────────────────
# Web 管理面板主页


@app.get("/")
async def dashboard(request: Request):
    """
    Web Dashboard 主页（无需认证）。
    
    渲染 Jinja2 模板 index.html，提供可视化管理界面。
    """
    return templates.TemplateResponse(request, "index.html")


# 挂载静态文件（CSS、JS、图片等）到 /static 路径
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
