"""FastAPI 服务器 —— REST API + WebSocket + Web Dashboard (前后端分离)"""

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
)

from .auth import authenticate, get_optional_user, require_admin
from .websocket_manager import ws_manager

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

API_PREFIX = "/api/v1"


def _is_local_request(request: Request) -> bool:
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else ""
    return client_ip in ("127.0.0.1", "::1", "localhost", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("API 服务器已启动")
    yield
    logger.info("API 服务器已关闭")


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


@app.post(f"{API_PREFIX}/auth/register")
async def api_register(data: dict, request: Request):
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
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    apikey = data.get("apikey", "").strip()
    user = auth_login(username=username, password=password, apikey=apikey)
    if not user:
        raise HTTPException(status_code=401, detail="用户名/密码或 API Key 无效")
    return {"status": "ok", "user": user}


@app.get(f"{API_PREFIX}/auth/me")
async def api_me(user: dict = Depends(authenticate)):
    return {"user": user}


@app.post(f"{API_PREFIX}/auth/apikey/regenerate")
async def api_regenerate_apikey(user: dict = Depends(authenticate)):
    new_key = auth_regenerate_apikey(user["id"])
    return {"status": "ok", "apikey": new_key}


@app.delete(f"{API_PREFIX}/auth/account")
async def api_delete_account(user: dict = Depends(authenticate)):
    if user.get("is_admin"):
        raise HTTPException(status_code=400, detail="管理员账户不可删除")
    auth_delete_user(user["id"])
    return {"status": "ok", "message": f"已注销 {user.get('username', '')}"}


# ── 健康检查 ──────────────────────────────────


@app.get(f"{API_PREFIX}/health")
async def health_check():
    stats = get_stats()
    return {
        "status": "ok", "version": "3.2.0",
        "ws_connections": ws_manager.connection_count,
        "stats": stats, "timestamp": time.time(),
    }


# ── 统计 ──────────────────────────────────────


@app.get(f"{API_PREFIX}/stats")
async def api_stats(user: Optional[dict] = Depends(get_optional_user)):
    return get_stats(user=user)


# ── 视频列表 ──────────────────────────────────


@app.get(f"{API_PREFIX}/videos")
async def api_list_videos(
    sort_by: str = Query("updated_at"),
    order: str = Query("DESC"),
    limit: int = Query(100, ge=1, le=500),
    user: Optional[dict] = Depends(get_optional_user),
):
    return list_videos(sort_by=sort_by, order=order, limit=limit, user=user)


@app.get(f"{API_PREFIX}/videos/{{bvid}}")
async def api_get_video(bvid: str):
    try:
        return get_video(bvid)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post(f"{API_PREFIX}/videos")
async def api_add_video(bvid: str = Query(...), user: dict = Depends(authenticate)):
    try:
        return add_video(bvid, user=user)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete(f"{API_PREFIX}/videos/{{bvid}}")
async def api_remove_video(bvid: str, user: dict = Depends(authenticate)):
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
    return get_records(bvid, start_time=start_time, end_time=end_time, limit=limit)


@app.get(f"{API_PREFIX}/videos/{{bvid}}/records/latest")
async def api_get_latest(bvid: str):
    try:
        return get_latest_record(bvid)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── 预测 ──────────────────────────────────────


@app.get(f"{API_PREFIX}/videos/{{bvid}}/predictions")
async def api_get_predictions(bvid: str, algorithm: Optional[str] = Query(None), limit: int = Query(100)):
    return get_predictions(bvid=bvid, algorithm=algorithm, limit=limit)


@app.get(f"{API_PREFIX}/predictions")
async def api_get_all_predictions(
    algorithm: Optional[str] = Query(None),
    limit: int = Query(100),
    user: Optional[dict] = Depends(get_optional_user),
):
    return get_predictions(algorithm=algorithm, limit=limit, user=user)


@app.post(f"{API_PREFIX}/videos/{{bvid}}/predict")
async def api_predict_video(bvid: str, user: dict = Depends(authenticate)):
    try:
        return {"status": "ok", "bvid": bvid, "result": predict_video(bvid)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{API_PREFIX}/predict-all")
async def api_predict_all(user: dict = Depends(authenticate)):
    return {"status": "ok", **predict_all(user=user)}


# ── 里程碑 ────────────────────────────────────


@app.get(f"{API_PREFIX}/videos/{{bvid}}/milestones")
async def api_get_milestones(bvid: str):
    return get_milestones(bvid=bvid)


@app.get(f"{API_PREFIX}/milestones")
async def api_get_all_milestones():
    return get_milestones()


# ── 搜索 ──────────────────────────────────────


@app.get(f"{API_PREFIX}/search")
async def api_search(
    keyword: str = Query(""),
    field: str = Query("title"),
    limit: int = Query(50),
    user: Optional[dict] = Depends(get_optional_user),
):
    return search_videos(keyword=keyword, field=field, limit=limit, user=user)


# ── 配置 ──────────────────────────────────────


@app.get(f"{API_PREFIX}/config")
async def api_get_config(user: dict = Depends(require_admin)):
    return load_config()


@app.post(f"{API_PREFIX}/config")
async def api_update_config(config: dict, user: dict = Depends(require_admin)):
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="配置必须是 JSON 对象")
    if "watch_list" in config and not isinstance(config["watch_list"], list):
        raise HTTPException(status_code=400, detail="watch_list 必须是数组")
    if not save_config(config):
        raise HTTPException(status_code=500, detail="保存配置失败")
    return {"status": "ok"}


# ── WebSocket ─────────────────────────────────


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
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


@app.get("/")
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "index.html")


app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
