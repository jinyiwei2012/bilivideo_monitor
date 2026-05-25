"""
自动更新检查
启动时异步检查 GitHub Release，有新版本时提示更新
"""

import logging
import json
import threading
from typing import Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path

import requests

from config import DATA_DIR

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com/repos/jinyiwei2012/bilivideo_monitor/releases/latest"
CACHE_FILE = Path(DATA_DIR) / ".update_cache.json"
CACHE_TTL = timedelta(hours=24)  # 每天最多检查一次


def _get_local_version() -> str:
    try:
        from __init__ import __version__
        return __version__
    except Exception:
        return "0.0.0"


def _load_cache() -> Optional[dict]:
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            cached_time = datetime.fromisoformat(data.get("cached_at", "2000-01-01"))
            if datetime.now() - cached_time < CACHE_TTL:
                return data
    except Exception:
        pass
    return None


def _save_cache(data: dict):
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data["cached_at"] = datetime.now().isoformat()
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug("保存更新缓存失败: %s", e)


def check_for_update() -> Tuple[bool, str, str]:
    """检查更新。返回 (has_update, latest_version, download_url)"""
    cached = _load_cache()
    if cached:
        latest = cached.get("latest_version", "")
        local = _get_local_version()
        if latest:
            return latest != local, latest, cached.get("download_url", "")

    try:
        resp = requests.get(GITHUB_API, timeout=10)
        if resp.status_code != 200:
            logger.debug("GitHub API 返回 %s", resp.status_code)
            return False, "", ""

        data = resp.json()
        latest = data.get("tag_name", "").lstrip("v")
        download_url = data.get("html_url", "")
        _save_cache({"latest_version": latest, "download_url": download_url})

        local = _get_local_version()
        return latest != local, latest, download_url

    except requests.RequestException as e:
        logger.debug("GitHub API 请求失败: %s", e)
        return False, "", ""


def check_for_update_async(callback):
    """异步检查更新，完成后调用 callback(has_update, latest_version, download_url)"""
    threading.Thread(target=lambda: callback(*check_for_update()), daemon=True).start()
