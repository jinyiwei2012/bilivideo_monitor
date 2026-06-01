"""Web 服务启动入口 —— 启动 FastAPI REST API 服务器

用法:
    python web_entry.py                  # 默认 0.0.0.0:8800
    python web_entry.py --port 8800       # 指定端口
    python web_entry.py --host 127.0.0.1 --port 8800
"""

import argparse
import atexit
import logging
import threading
import sys
import os

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

logger = logging.getLogger("web")


def start_api_server(host: str = "0.0.0.0", port: int = 8800, reload: bool = False):
    import uvicorn
    from web.api_server import app

    logger.info("API 服务器启动: http://%s:%d", host, port)
    logger.info("Web Dashboard: http://%s:%d/", "127.0.0.1" if host == "0.0.0.0" else host, port)
    logger.info("API 文档: http://%s:%d/docs", "127.0.0.1" if host == "0.0.0.0" else host, port)

    atexit.register(_shutdown_engine)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        reload=reload,
    )


def _shutdown_engine():
    try:
        from backend import get_engine
        get_engine().stop_all()
    except Exception:
        pass


def start_in_background(host: str = "0.0.0.0", port: int = 8800):
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
    parser = argparse.ArgumentParser(description="B站视频监控 Web 服务器")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8800, help="监听端口 (默认 8800)")
    parser.add_argument("--reload", action="store_true", help="启用热重载（开发模式）")
    args = parser.parse_args()

    start_api_server(host=args.host, port=args.port, reload=args.reload)
