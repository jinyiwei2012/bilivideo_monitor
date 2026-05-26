"""
自动更新检查
启动时异步检查 GitHub Release，根据运行模式提供不同更新方式：
- 源码运行 → 提供 git pull / 下载 zip（aria2）两种方式
- EXE 运行  → 提供下载新 exe（aria2）/ 自动更新
"""

import logging
import json
import os
import sys
import threading
import subprocess
from typing import Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path

import requests

from config import DATA_DIR

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com/repos/jinyiwei2012/bilivideo_monitor/releases/latest"
GITHUB_REPO = "https://github.com/jinyiwei2012/bilivideo_monitor"
CACHE_FILE = Path(DATA_DIR) / ".update_cache.json"
CACHE_TTL = timedelta(hours=24)


def is_frozen() -> bool:
    """检测是否 PyInstaller 打包的 EXE 运行"""
    return getattr(sys, "frozen", False)


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

        _save_cache(
            {
                "latest_version": latest,
                "download_url": download_url,
                "changelog": changelog,
                "assets": [
                    {"name": a.get("name"), "url": a.get("browser_download_url")}
                    for a in data.get("assets", [])
                ],
                "zipball_url": data.get("zipball_url", ""),
            }
        )

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


def get_download_urls() -> dict:
    """从缓存中获取各平台下载地址"""
    cached = _load_cache()
    if not cached:
        return {}
    return {
        "exe": next(
            (a["url"] for a in cached.get("assets", []) if a["name"].endswith(".exe")),
            cached.get("download_url", ""),
        ),
        "zip": cached.get("zipball_url", ""),
        "release_page": cached.get("download_url", ""),
    }


def perform_source_git_pull(parent_widget=None):
    """源码模式: git pull 拉取最新代码"""
    try:
        result = subprocess.run(
            ["git", "pull"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        if result.returncode == 0:
            return True, f"git pull 成功:\n{result.stdout[:500]}"
        else:
            return False, f"git pull 失败:\n{result.stderr[:500]}"
    except Exception as e:
        return False, f"git pull 异常: {e}"


def perform_source_download_zip(progress_cb=None, done_cb=None):
    """源码模式: aria2 下载 ZIP"""
    urls = get_download_urls()
    url = urls.get("zip") or urls.get("release_page")
    if not url:
        if done_cb:
            done_cb(False, "无法获取下载地址")
        return False
    dest = os.path.join(DATA_DIR, "downloads", "source.zip")
    from utils.downloader import download_file

    return download_file(url, dest, progress_cb, done_cb)


def perform_exe_download(progress_cb=None, done_cb=None):
    """EXE 模式: aria2 下载新 EXE"""
    urls = get_download_urls()
    url = urls.get("exe") or urls.get("release_page")
    if not url:
        if done_cb:
            done_cb(False, "无法获取 EXE 下载地址")
        return False
    dest = os.path.join(DATA_DIR, "downloads", "BiliMonitor_new.exe")
    from utils.downloader import download_file

    return download_file(url, dest, progress_cb, done_cb)


def perform_exe_self_update(progress_cb=None, done_cb=None):
    """EXE 模式: 下载新 EXE 并创建重启脚本"""
    def _on_done(success, msg):
        if success:
            _create_restart_script()
        if done_cb:
            done_cb(success, msg)

    return perform_exe_download(progress_cb, _on_done)


def _create_restart_script():
    """创建重启脚本：等待主进程退出 → 替换 EXE → 重启"""
    if not is_frozen():
        return
    exe_path = sys.executable
    exe_dir = os.path.dirname(exe_path)
    new_exe = os.path.join(DATA_DIR, "downloads", "BiliMonitor_new.exe")
    script_path = os.path.join(exe_dir, "update_restart.bat")
    bat_content = f"""@echo off
chcp 65001 >nul
echo 正在更新 BiliMonitor…
:sleep
timeout /t 2 /nobreak >nul
copy /Y "{new_exe}" "{exe_path}" >nul 2>nul
if %errorlevel% neq 0 goto sleep
del "{new_exe}" >nul 2>nul
start "" "{exe_path}"
del "%~f0" >nul 2>nul
"""
    try:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(bat_content)
        subprocess.Popen(
            [script_path],
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        logger.info("重启脚本已创建: %s", script_path)
    except Exception as e:
        logger.warning("创建重启脚本失败: %s", e)
