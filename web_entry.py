"""
Web 服务启动入口 —— 启动 FastAPI REST API 服务器

提供 Web 服务的独立启动方式，与 GUI 完全解耦。

用法:
    python web_entry.py                  # 默认 0.0.0.0:8800
    python web_entry.py --port 8800       # 指定端口
    python web_entry.py --host 127.0.0.1 --port 8800  # 指定地址和端口
    python web_entry.py --reload          # 热重载模式（开发用）

API 文档自动生成在 /docs 路径（Swagger UI）。

主要功能：
    - start_api_server(): 启动 uvicorn 服务器
    - start_in_background(): 在后台线程中启动（供 GUI 集成使用）
    - _shutdown_engine(): 进程退出时自动停止监控引擎
"""

import argparse
import atexit
import logging
import threading
import sys
import os

# 确保项目根目录在 sys.path 中（支持从任意目录启动）
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

logger = logging.getLogger("web")


def start_api_server(host: str = "0.0.0.0", port: int = 8800, reload: bool = False):
    """
    启动 FastAPI REST API 服务器（uvicorn 单进程）。

    会自动注册 atexit 钩子，在进程退出时停止监控引擎、
    释放数据库连接等资源。

    Args:
        host: 监听地址（默认 "0.0.0.0" 监听所有网卡）
        port: 监听端口（默认 8800）
        reload: 是否启用热重载（开发模式，监控文件变更自动重启）
    """
    import uvicorn
    from web.api_server import app

    logger.info("API 服务器启动: http://%s:%d", host, port)
    logger.info("Web Dashboard: http://%s:%d/", "127.0.0.1" if host == "0.0.0.0" else host, port)
    logger.info("API 文档: http://%s:%d/docs", "127.0.0.1" if host == "0.0.0.0" else host, port)

    # 注册退出回调：进程退出时停止监控引擎
    atexit.register(_shutdown_engine)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        reload=reload,
    )


def _shutdown_engine():
    """
    关闭后端的监控引擎。

    尝试停止所有 Worker 线程，释放资源。
    异常静默处理（atexit 回调中不应抛出异常）。
    """
    try:
        from backend import get_engine
        get_engine().stop_all()
    except Exception:
        pass


def start_in_background(host: str = "0.0.0.0", port: int = 8800):
    """
    在后台守护线程中启动 API 服务器（供 GUI 集成使用）。

    用于在 Tkinter GUI 运行时同时提供 Web API 服务，
    不阻塞主线程。

    Args:
        host: 监听地址
        port: 监听端口

    Returns:
        threading.Thread: 后台服务器线程
    """
    thread = threading.Thread(
        target=start_api_server,
        args=(host, port),
        kwargs={"reload": False},
        daemon=True,
        name="api-server",
    )
    thread.start()
    return thread


if __name__ == "__main__":
    # ── 命令行参数解析 ──────
    parser = argparse.ArgumentParser(description="B站视频监控 Web 服务器")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8800, help="监听端口 (默认 8800)")
    parser.add_argument("--reload", action="store_true", help="启用热重载（开发模式）")
    args = parser.parse_args()

    start_api_server(host=args.host, port=args.port, reload=args.reload)
