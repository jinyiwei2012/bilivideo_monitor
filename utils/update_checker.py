"""
自动更新检查
启动时异步检查 GitHub Release，有新版本时提示更新，含 changelog 展示
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
CACHE_TTL = timedelta(hours=24)


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


def check_for_update() -> Tuple[bool, str, str, str]:
    """检查更新。返回 (has_update, latest_version, download_url, changelog)"""
    cached = _load_cache()
    if cached:
        latest = cached.get("latest_version", "")
        local = _get_local_version()
        if latest:
            return latest != local, latest, cached.get("download_url", ""), cached.get("changelog", "")

    try:
        resp = requests.get(GITHUB_API, timeout=10)
        if resp.status_code != 200:
            logger.debug("GitHub API 返回 %s", resp.status_code)
            return False, "", "", ""

        data = resp.json()
        latest = data.get("tag_name", "").lstrip("v")
        download_url = data.get("html_url", "")
        changelog = data.get("body", "")

        _save_cache({
            "latest_version": latest,
            "download_url": download_url,
            "changelog": changelog,
        })

        local = _get_local_version()
        return latest != local, latest, download_url, changelog

    except requests.RequestException as e:
        logger.debug("GitHub API 请求失败: %s", e)
        return False, "", "", ""


def check_for_update_async(callback):
    """异步检查更新，完成后调用 callback(has_update, latest_version, download_url, changelog)"""
    threading.Thread(target=lambda: callback(*check_for_update()), daemon=True).start()


def format_changelog_for_display(changelog: str, max_lines: int = 30) -> str:
    """截取 changelog 前 max_lines 行用于 UI 展示"""
    if not changelog:
        return "暂无更新说明"
    lines = changelog.strip().split("\n")
    display = "\n".join(lines[:max_lines])
    if len(lines) > max_lines:
        display += f"\n\n... 还有 {len(lines) - max_lines} 行，请前往 GitHub 查看完整内容"
    return display
