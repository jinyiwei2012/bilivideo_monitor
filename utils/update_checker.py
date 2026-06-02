"""
自动更新检查模块

启动时异步检查 GitHub Release 是否有新版本可用。

运行模式判断：
- 源码运行（非 frozen）→ 提供 git pull / 下载 ZIP（aria2）两种更新方式
- EXE 运行（frozen）    → 提供下载新 EXE / 自动更新（下载+替换+重启）

更新通道：
- stable: 稳定版（GitHub Latest Release）
- beta:   预发布版（GitHub Pre-release）

额外包含：
- 开发者模式控制（.devmode 文件 + 会话临时放行）
- 训练功能开关（.enabletraining 文件）

依赖：requests 库，aria2 下载器（utils.downloader）
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

from config import DATA_DIR, load_config, save_config

logger = logging.getLogger(__name__)

# ── GitHub Release API 地址 ──────────────────────────────
# 稳定版 API（取最新 Release）
GITHUB_API_STABLE = "https://api.github.com/repos/jinyiwei2012/bilivideo_monitor/releases/latest"
# 预发布版 API（取最近 5 个 Release，用于 beta 通道）
GITHUB_API_PRERELEASE = "https://api.github.com/repos/jinyiwei2012/bilivideo_monitor/releases?per_page=5"
GITHUB_REPO = "https://github.com/jinyiwei2012/bilivideo_monitor"
# 更新缓存文件（避免频繁请求 GitHub API）
CACHE_FILE = Path(DATA_DIR) / ".update_cache.json"
# 缓存有效期：24 小时
CACHE_TTL = timedelta(hours=24)


# ── 更新通道管理 ────────────────────────────────────────


def get_update_channel() -> str:
    """获取当前更新通道。

    Returns:
        str: 'stable'（稳定版）或 'beta'（预发布版）
    """
    cfg = load_config()
    return cfg.get("update_channel", "stable")


def set_update_channel(channel: str):
    """设置更新通道并清除旧缓存。

    Args:
        channel: 'stable' 或 'beta'
    """
    cfg = load_config()
    cfg["update_channel"] = channel
    save_config(cfg)
    # 清除缓存以便下次检查使用新通道
    try:
        CACHE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def is_frozen() -> bool:
    """检测当前运行环境是否为 PyInstaller 打包的 EXE。

    Returns:
        bool: True 表示 EXE 运行，False 表示源码运行
    """
    return getattr(sys, "frozen", False)


# ── 开发者模式控制 ─────────────────────────────────────
# _session_devmode: 会话级临时放行标志（程序关闭后自动恢复 False）
_session_devmode = False
# .devmode 文件内容的期望 SHA-256（去除首尾空白后），用于验证文件内容的合法性
_DEVMODE_HASH = "40175C25B9517A906FCF778E50387017BB8FA6121D28EBD0720474E85EE7ECA8"


def _verify_devmode_content(path: str) -> bool:
    """校验 .devmode 文件内容的 SHA-256 是否匹配。

    这是一种简单的文件内容验证机制，防止用户随意创建 .devmode 文件。

    Args:
        path: .devmode 文件路径

    Returns:
        bool: 文件存在且内容哈希匹配
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        import hashlib

        h = hashlib.sha256(content.encode()).hexdigest().upper()
        return h == _DEVMODE_HASH
    except Exception:
        return False


def _find_devmode() -> str:
    """查找 .devmode 或 devmode 文件并校验内容。

    在项目根目录搜索两种命名方式：.devmode（隐藏文件）和 devmode（普通文件）。
    只有通过 SHA-256 校验的文件才被识别为有效的开发者模式文件。

    Returns:
        str: 找到的有效文件路径，未找到时返回空字符串
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in (".devmode", "devmode"):
        path = os.path.join(root, name)
        if os.path.isfile(path) and _verify_devmode_content(path):
            return path
    return ""


def _x() -> bool:
    """检查开发者模式是否开启。

    判断逻辑：
    1. 先检查会话级临时放行（_session_devmode）
    2. 再检查 .devmode 文件是否存在且内容校验通过

    Returns:
        bool: True 表示开发者模式已启用
    """
    if _session_devmode:
        return True
    return bool(_find_devmode())


def _s() -> str:
    """检查开发者模式是否开启，返回 UI 按钮状态。

    Returns:
        str: 'normal'（可用）或 'disabled'（禁用）
    """
    return "normal" if _x() else "disabled"


def _hard() -> str:
    """检查严格模式（仅校验 .devmode 文件，忽略会话临时放行）。

    用于高权限操作的强制验证场景。

    Returns:
        str: 'normal'（可用）或 'disabled'（禁用）
    """
    return "normal" if _x_strict() else "disabled"


def _x_train() -> bool:
    """检查训练功能是否可用。

    判断依据：项目根目录是否存在 .enabletraining 文件。
    用户手动创建此空文件即可启用训练相关功能。

    Returns:
        bool: True 表示训练功能已启用
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.exists(os.path.join(root, ".enabletraining"))


def _train() -> str:
    """检查训练功能是否可用，返回 UI 按钮状态。

    训练功能在以下任一条件满足时可用：
    1. 项目根目录存在 .enabletraining 文件
    2. 处于严格开发者模式（.devmode 文件校验通过）

    Returns:
        str: 'normal'（可用）或 'disabled'（禁用）
    """
    return "normal" if (_x_train() or _x_strict()) else "disabled"


def _x_strict() -> bool:
    """严格开发者模式检查：仅依赖 .devmode 文件，忽略会话临时放行。

    用于强制验证的高权限场景，即使之前通过弹窗确认放行过也不认。

    Returns:
        bool: .devmode 文件存在且校验通过
    """
    return bool(_find_devmode())


def _get_local_version() -> str:
    """获取本地版本号。

    尝试从 __init__.py 读取 __version__ 常量，
    失败时返回默认版本 "0.0.0"。

    Returns:
        str: 版本号字符串，如 "1.6.0"
    """
    try:
        from __init__ import __version__

        return __version__
    except Exception:
        return "0.0.0"


def _enable_devmode():
    """启用会话级开发者模式（临时放行，程序关闭后自动恢复）。"""
    global _session_devmode
    _session_devmode = True


def _warn(parent=None):
    """弹出高风险操作确认对话框，用户确认后启用会话级开发者模式。

    Args:
        parent: tkinter 父窗口（可选，用于模态对话框）

    Returns:
        bool: 用户是否确认
    """
    try:
        from tkinter import messagebox

        r = messagebox.askyesno(
            "高风险操作",
            "当前操作可能导致不可逆的数据损坏或模型损坏。\n\n是否确认开启开发者模式？程序关闭后自动恢复。",
            icon="warning",
            parent=parent,
        )
        if r:
            _enable_devmode()
        return r
    except Exception:
        return False


def _confirm_risky(operation_desc: str = "当前操作", parent=None):
    """检查保护状态，未开启时弹出高风险确认对话框。

    用户确认后临时放行（本次会话有效）。
    如果已处于开发者模式，直接返回 True 无需弹窗。

    Args:
        operation_desc: 操作描述文本，用于对话框文案
        parent: tkinter 父窗口

    Returns:
        bool: True 表示允许继续操作
    """
    if _x():
        return True  # 已在开发者模式，直接放行
    try:
        from tkinter import messagebox

        r = messagebox.askyesno(
            "高风险操作",
            f"{operation_desc}可能导致不可逆的数据损坏或模型损坏。\n\n是否确认开启开发者模式？程序关闭后自动恢复。",
            icon="warning",
            parent=parent,
        )
        if r:
            _enable_devmode()
        return r
    except Exception:
        return False


# ── 更新缓存管理 ───────────────────────────────────────


def _load_cache() -> Optional[dict]:
    """加载本地更新缓存。

    仅在缓存未过期（24 小时内）时返回有效数据，否则返回 None。
    避免频繁请求 GitHub API 触发 rate limit。

    Returns:
        dict | None: 缓存数据字典，包含 latest_version/下载地址等字段；缓存过期或无效返回 None
    """
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
    """保存更新检查结果到本地缓存文件。

    写入的字段包括：latest_version, download_url, changelog, channel, assets 等，
    以及 cached_at 时间戳。

    Args:
        data: 要缓存的更新数据字典
    """
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data["cached_at"] = datetime.now().isoformat()
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug("保存更新缓存失败: %s", e)


# ── GitHub API 交互 ───────────────────────────────────


def _fetch_release(api_url: str) -> Tuple[Optional[dict], str, str]:
    """从 GitHub API 获取最新 Release 信息。

    兼容两种 API 格式：
    - /releases/latest: 直接返回单个 Release 对象
    - /releases?per_page=5: 返回 Release 列表，取第一个非 draft 的

    Args:
        api_url: GitHub API 地址

    Returns:
        (data, latest_version, download_url):
        - data: Release JSON 或 None
        - latest_version: 版本号字符串（不含 "v" 前缀）
        - download_url: GitHub Release 页面 URL
    """
    try:
        resp = requests.get(api_url, timeout=10)
        if resp.status_code != 200:
            return None, "", ""
        if isinstance(resp.json(), list):
            # pre-release 列表 API：取第一个非 draft 的 Release
            for item in resp.json():
                if not item.get("draft") and item.get("tag_name"):
                    return item, item["tag_name"].lstrip("v"), item.get("html_url", "")
            return None, "", ""
        return resp.json(), resp.json().get("tag_name", "").lstrip("v"), resp.json().get("html_url", "")
    except requests.RequestException:
        return None, "", ""


# ── 公开 API ───────────────────────────────────────────


def check_for_update() -> Tuple[bool, str, str, str, str]:
    """检查是否有新版本可用。

    检查流程：
    1. 如果在开发者模式，跳过更新检查
    2. 检查本地缓存是否有效
    3. 缓存无效时向 GitHub API 请求最新 Release
    4. 比较本地版本 vs 远程版本

    Returns:
        (has_update, latest_version, download_url, changelog, channel):
        - has_update: bool    是否有更新
        - latest_version: str 最新版本号
        - download_url: str   Release 页面 URL
        - changelog: str      更新日志（Markdown 格式）
        - channel: str        当前使用的更新通道
    """
    if _x():
        return False, "", "", "", get_update_channel()  # 开发者模式跳过更新

    channel = get_update_channel()
    # 根据通道选择对应的 GitHub API 地址
    api_url = GITHUB_API_PRERELEASE if channel == "beta" else GITHUB_API_STABLE

    # 优先使用本地缓存
    cached = _load_cache()
    if cached and cached.get("channel") == channel:
        latest = cached.get("latest_version", "")
        local = _get_local_version()
        if latest:
            # 版本号比较：将 "1.6.0" 切分为 (1, 6, 0) 元组进行比较
            _pv = lambda v: tuple(int(x) for x in v.split("-")[0].split(".") if x.isdigit())
            return (
                _pv(latest) > _pv(local),
                latest,
                cached.get("download_url", ""),
                cached.get("changelog", ""),
                channel,
            )

    # 缓存已过期或无缓存，发起 API 请求
    data, latest, download_url = _fetch_release(api_url)
    if not data:
        return False, "", "", "", channel

    changelog = data.get("body", "")
    _save_cache({
        "latest_version": latest,
        "download_url": download_url,
        "changelog": changelog,
        "channel": channel,
        "assets": [
            {"name": a.get("name"), "url": a.get("browser_download_url")}
            for a in data.get("assets", [])
        ],
        "zipball_url": data.get("zipball_url", ""),
        "prerelease": data.get("prerelease", False),
    })

    local = _get_local_version()
    return latest != local, latest, download_url, changelog, channel


def check_for_update_async(callback):
    """异步检查更新（在后台线程中执行）。

    完成后通过回调函数通知结果，不会阻塞 UI 线程。

    Args:
        callback: 回调函数，签名为 callback(has_update, latest_version, download_url, changelog, channel)
    """
    threading.Thread(target=lambda: callback(*check_for_update()), daemon=True).start()


def format_changelog_for_display(changelog: str, max_lines: int = 30) -> str:
    """截取 changelog 前 max_lines 行用于 UI 展示。

    GitHub Release 的 changelog 可能非常长，需要截断避免 UI 溢出。

    Args:
        changelog: 完整的 changelog 文本
        max_lines: 最大显示行数，默认 30

    Returns:
        str: 截取后的 changelog 文本
    """
    if not changelog:
        return "暂无更新说明"
    lines = changelog.strip().split("\n")
    display = "\n".join(lines[:max_lines])
    if len(lines) > max_lines:
        display += f"\n\n... 还有 {len(lines) - max_lines} 行，请前往 GitHub 查看完整内容"
    return display


def get_download_urls() -> dict:
    """从缓存中获取各平台下载地址。

    Returns:
        dict: {
            "exe": EXE 下载地址,
            "zip": 源码 ZIP 下载地址,
            "release_page": GitHub Release 页面 URL,
            "prerelease": 是否为预发布版,
        }
    """
    cached = _load_cache()
    if not cached:
        return {}
    return {
        "exe": next(
            (a["url"] for a in cached.get("assets", []) if a.get("name") and a["name"].endswith(".exe")),
            cached.get("download_url", ""),
        ),
        "zip": cached.get("zipball_url", ""),
        "release_page": cached.get("download_url", ""),
        "prerelease": cached.get("prerelease", False),
    }


# ── 更新执行操作 ────────────────────────────────────────


def perform_source_git_pull(branch="main"):
    """源码模式：通过 git pull 从指定分支拉取最新代码。

    安全限制：只允许预定义的分支名，防止命令注入。

    Args:
        branch: 目标分支名（必须在允许列表中）

    Returns:
        (success: bool, message: str): 执行结果

    Raises:
        ValueError: 分支名不在允许列表中
    """
    allowed = {"main", "releases", "pre-release", "dev", "fixbug", "algorithms-dev", "algorithms-optimize", "ui界面",
               "feat/training-auto-callback"}
    if branch not in allowed:
        raise ValueError(f"不允许的分支名: {branch}")
    try:
        result = subprocess.run(
            ["git", "pull", "origin", branch],
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
    """源码模式：使用 aria2 下载最新版本的源码 ZIP 包。

    Args:
        progress_cb: 进度回调 (downloaded_bytes, total_bytes)
        done_cb: 完成回调 (success, message)

    Returns:
        bool: 下载是否成功
    """
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
    """EXE 模式：使用 aria2 下载最新版本的 EXE 文件。

    下载到 data/downloads/BiliMonitor_new.exe。

    Args:
        progress_cb: 进度回调 (downloaded_bytes, total_bytes)
        done_cb: 完成回调 (success, message)

    Returns:
        bool: 下载是否成功
    """
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
    """EXE 模式全自动更新：下载新 EXE → 创建重启脚本 → 提示重启。

    流程：
    1. 下载新 EXE 到 data/downloads/BiliMonitor_new.exe
    2. 创建 update_restart.bat 批处理脚本
    3. 启动脚本（等待当前进程退出 → 替换 EXE → 重新启动）

    Args:
        progress_cb: 进度回调
        done_cb: 完成回调
    """

    def _on_done(success, msg):
        if success:
            _create_restart_script()  # 下载成功后创建自动重启脚本
        if done_cb:
            done_cb(success, msg)

    return perform_exe_download(progress_cb, _on_done)


def _create_restart_script():
    """创建 Windows 批处理重启脚本 update_restart.bat。

    脚本行为：
    1. 等待当前 BiliMonitor.exe 进程退出（通过持续尝试覆盖文件检测）
    2. 将新 EXE 复制覆盖到原位置
    3. 启动新的 BiliMonitor.exe
    4. 自删除

    仅在 EXE（frozen）模式下有效。
    """
    if not is_frozen():
        return
    exe_path = sys.executable
    exe_dir = os.path.dirname(exe_path)
    new_exe = os.path.join(DATA_DIR, "downloads", "BiliMonitor_new.exe")
    script_path = os.path.join(exe_dir, "update_restart.bat")
    # 批处理脚本：循环等待原进程退出，复制新 exe 覆盖后启动，最后自删除
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
