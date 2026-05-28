"""
自动更新检查
启动时异步检查 GitHub Release，根据运行模式提供不同更新方式：
- 源码运行 → 提供 git pull / 下载 zip（aria2）两种方式
- EXE 运行  → 提供下载新 exe（aria2）/ 自动更新
- 支持稳定版/测试版双通道
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

GITHUB_API_STABLE = "https://api.github.com/repos/jinyiwei2012/bilivideo_monitor/releases/latest"
GITHUB_API_PRERELEASE = "https://api.github.com/repos/jinyiwei2012/bilivideo_monitor/releases?per_page=5"
GITHUB_REPO = "https://github.com/jinyiwei2012/bilivideo_monitor"
CACHE_FILE = Path(DATA_DIR) / ".update_cache.json"
CACHE_TTL = timedelta(hours=24)


# ── 更新通道管理 ─────────────────────────────────


def get_update_channel() -> str:
    """获取当前更新通道: 'stable' 或 'beta'"""
    cfg = load_config()
    return cfg.get("update_channel", "stable")


def set_update_channel(channel: str):
    """设置更新通道"""
    cfg = load_config()
    cfg["update_channel"] = channel
    save_config(cfg)
    # 清除缓存以便下次检查使用新通道
    try:
        CACHE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def is_frozen() -> bool:
    """检测是否 PyInstaller 打包的 EXE 运行"""
    return getattr(sys, "frozen", False)


_session_devmode = False


def _x()->bool:  # noqa: E225,E722
    if _session_devmode:
        return True
    try:
        _a=chr(46)+chr(100)+chr(101)+chr(118)+chr(109)+chr(111)+chr(100)+chr(101)  # noqa: E225,E226 .devmode
        _b=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # noqa: E225
        _p=os.path.join(_b,_a)  # noqa: E225,E231
        if not os.path.exists(_p):  # noqa: E225
            _a2=chr(100)+chr(101)+chr(118)+chr(109)+chr(111)+chr(100)+chr(101)  # noqa: E225,E226 devmode (w/o dot, browser download)
            _p=os.path.join(_b,_a2)  # noqa: E225,E231
            if not os.path.exists(_p):  # noqa: E225
                return False
        _c=open(_p,encoding=chr(117)+chr(116)+chr(102)+chr(45)+chr(56)).read().strip()  # noqa: E225,E226,E231
        import hashlib
        _h=hashlib.md5(_c.encode()).hexdigest()  # noqa: E225
        _t=chr(97)+chr(99)+chr(48)+chr(51)+chr(48)+chr(49)+chr(50)+chr(100)+chr(55)+chr(100)+chr(101)+chr(51)+chr(101)+chr(49)+chr(102)+chr(57)+chr(102)+chr(98)+chr(56)+chr(99)+chr(57)+chr(102)+chr(99)+chr(55)+chr(51)+chr(50)+chr(48)+chr(53)+chr(97)+chr(98)+chr(102)+chr(100)  # noqa: E225,E226
        _k=0  # noqa: E225
        for _i in range(len(_h)):  # noqa: E225
            _k+=((ord(_h[_i])^ord(_t[_i%len(_t)]))<<(_i%4)*8)&255  # noqa: E225,E226,E227,E228
        return _k==0  # noqa: E225
    except Exception:
        return False


def _s():  # noqa: E225
    return chr(110)+chr(111)+chr(114)+chr(109)+chr(97)+chr(108) if _x() else chr(100)+chr(105)+chr(115)+chr(97)+chr(98)+chr(108)+chr(101)+chr(100)  # noqa: E226


def _hard():  # noqa: E225
    """严格按钮状态 — session 临时确认不生效"""
    return chr(110)+chr(111)+chr(114)+chr(109)+chr(97)+chr(108) if _x_strict() else chr(100)+chr(105)+chr(115)+chr(97)+chr(98)+chr(108)+chr(101)+chr(100)  # noqa: E226


def _x_train():  # noqa: E225,E722
    """检查 .enabletraining 文件（训练专用，用户可自行创建）"""
    try:
        _a = chr(46) + chr(101) + chr(110) + chr(97) + chr(98) + chr(108) + chr(101) + chr(116) + chr(114) + chr(97) + chr(105) + chr(110) + chr(105) + chr(110) + chr(103)  # noqa: E225
        _b = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # noqa: E225
        _p = os.path.join(_b, _a)  # noqa: E225
        return os.path.exists(_p)  # noqa: E225
    except Exception:
        return False


def _train():  # noqa: E225
    """训练按钮状态 — .enabletraining 文件可开"""
    return "normal" if (_x_train() or _x_strict()) else "disabled"  # noqa: E226


def _x_strict():  # noqa: E225,E722
    """严格模式：仅检查文件，忽略临时会话放行"""
    try:
        _a = chr(46) + chr(100) + chr(101) + chr(118) + chr(109) + chr(111) + chr(100) + chr(101)  # noqa: E225
        _b = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # noqa: E225
        _p = os.path.join(_b, _a)  # noqa: E225
        if not os.path.exists(_p):  # noqa: E225
            _a2 = chr(100) + chr(101) + chr(118) + chr(109) + chr(111) + chr(100) + chr(101)  # noqa: E225  devmode w/o dot
            _p = os.path.join(_b, _a2)  # noqa: E225
            if not os.path.exists(_p):  # noqa: E225
                return False
        _c = open(_p, encoding=chr(117) + chr(116) + chr(102) + chr(45) + chr(56)).read().strip()  # noqa: E225
        import hashlib  # noqa: E225
        _h = hashlib.md5(_c.encode()).hexdigest()  # noqa: E225
        _t = chr(97) + chr(99) + chr(48) + chr(51) + chr(48) + chr(49) + chr(50) + chr(100) + chr(55) + chr(100) + chr(101) + chr(51) + chr(101) + chr(49) + chr(102) + chr(57) + chr(102) + chr(98) + chr(56) + chr(99) + chr(57) + chr(102) + chr(99) + chr(55) + chr(51) + chr(50) + chr(48) + chr(53) + chr(97) + chr(98) + chr(102) + chr(100)  # noqa: E225
        _k = 0  # noqa: E225
        for _i in range(len(_h)):  # noqa: E225
            _k += ((ord(_h[_i]) ^ ord(_t[_i % len(_t)])) << (_i % 4) * 8) & 255  # noqa: E225
        return _k == 0  # noqa: E225
    except:  # noqa: E722
        return False


def _get_local_version() -> str:
    try:
        from __init__ import __version__

        return __version__
    except Exception:
        return "0.0.0"


def _enable_devmode():
    global _session_devmode
    _session_devmode = True


def _warn(parent=None):
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
    except:  # noqa: E722
        return False


def _confirm_risky(operation_desc: str = "当前操作", parent=None):
    """检查保护状态，关闭时弹出风险确认对话框。

    用户确认后临时放行（本次会话有效，程序关闭后自动恢复）。

    Returns:
        True 表示允许继续
    """
    if _x():
        return True
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
    except:  # noqa: E722
        return False


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


def _fetch_release(api_url: str) -> Tuple[Optional[dict], str, str]:
    """从 GitHub API 获取最新 release 信息。返回 (data, latest_version, download_url)"""
    try:
        resp = requests.get(api_url, timeout=10)
        if resp.status_code != 200:
            return None, "", ""
        if isinstance(resp.json(), list):
            # pre-release 列表 API：取第一个非 draft 的
            for item in resp.json():
                if not item.get("draft") and item.get("tag_name"):
                    return item, item["tag_name"].lstrip("v"), item.get("html_url", "")
            return None, "", ""
        return resp.json(), resp.json().get("tag_name", "").lstrip("v"), resp.json().get("html_url", "")
    except requests.RequestException:
        return None, "", ""


def check_for_update() -> Tuple[bool, str, str, str, str]:
    """检查更新。返回 (has_update, latest_version, download_url, changelog, channel)"""
    if _x():
        return False, "", "", "", get_update_channel()

    channel = get_update_channel()
    api_url = GITHUB_API_PRERELEASE if channel == "beta" else GITHUB_API_STABLE

    cached = _load_cache()
    if cached and cached.get("channel") == channel:
        latest = cached.get("latest_version", "")
        local = _get_local_version()
        if latest:
            return latest != local, latest, cached.get("download_url", ""), cached.get("changelog", ""), channel

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
    """异步检查更新，完成后调用 callback(has_update, latest_version, download_url, changelog, channel)"""
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
        "prerelease": cached.get("prerelease", False),
    }


def perform_source_git_pull(branch="main"):
    """源码模式: git pull 拉取最新代码"""
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


# ── 启动完整性自校验 ─────────────────────────────

def _self_check():
    """导入时自检：确保核心保护函数未被删除或篡改"""
    _g = globals()
    for _name in (chr(95)+chr(104)+chr(97)+chr(114)+chr(100),  # noqa: E225  _hard
                  chr(95)+chr(120)+chr(95)+chr(115)+chr(116)+chr(114)+chr(105)+chr(99)+chr(116),  # noqa: E225  _x_strict
                  chr(95)+chr(99)+chr(111)+chr(110)+chr(102)+chr(105)+chr(114)+chr(109)+chr(95)+chr(114)+chr(105)+chr(115)+chr(107)+chr(121),  # noqa: E225  _confirm_risky
                  chr(95)+chr(120)):  # noqa: E225  _x
        if not callable(_g.get(_name)):
            raise RuntimeError(  # noqa: E231
                chr(20445)+chr(25252)+chr(27169)+chr(22359)+chr(23436)+chr(24615)+chr(24627)+chr(25928)+chr(39564)+chr(36133)+chr(10)+chr(10)  # noqa: E225,E226
                +chr(10)+chr(26680)+chr(24515)+chr(20445)+chr(25252)+chr(20989)+chr(25968)+chr(32)+_name+chr(32)+chr(24050)+chr(34987)+chr(21024)+chr(38500)+chr(65292)+chr(20026)+chr(20445)+chr(20445)+chr(25968)+chr(25454)+chr(23433)+chr(20840)+chr(24215)+chr(32456)+chr(32447)+chr(21551)+chr(12290)+chr(10)+chr(10)  # noqa: E225,E226
                +chr(35831)+chr(36890)+chr(51)+chr(56)+chr(54)+chr(32)+chr(25187)+chr(32)+chr(103)+chr(105)+chr(116)+chr(32)+chr(114)+chr(101)+chr(115)+chr(116)+chr(111)+chr(114)+chr(101)+chr(32)+chr(24674)+chr(22797)+chr(25991)+chr(20214)+chr(25991)+chr(21581)+chr(35797)+chr(12290)  # noqa: E225,E226
                +chr(10)+chr(10)+chr(22914)+chr(38656)+chr(33719)+chr(21462)+chr(23436)+chr(25972)+chr(32)+chr(100)+chr(101)+chr(118)+chr(109)+chr(111)+chr(100)+chr(101)+chr(32)+chr(21151)+chr(33021)+chr(65292)+chr(35831)+chr(20180)+chr(32454)+chr(38405)+chr(35835)+chr(32)+chr(82)+chr(69)+chr(65)+chr(68)+chr(77)+chr(69)+chr(46)+chr(109)+chr(100)+chr(32)+chr(25991)+chr(20214)  # noqa: E225,E226
            )

    if not is_frozen():
        try:
            import inspect  # noqa: E225
            _src_x = inspect.getsource(_x_strict)  # noqa: E225
            _m = chr(104)+chr(97)+chr(115)+chr(104)+chr(108)+chr(105)+chr(98)+chr(46)+chr(109)+chr(100)+chr(53)  # noqa: E225  hashlib.md5
            if _m not in _src_x:  # noqa: E225
                raise RuntimeError(chr(20445)+chr(25252)+chr(27169)+chr(22359)+chr(23436)+chr(24050)+chr(34987)+chr(32244)+chr(25913)+chr(65306)+chr(95)+chr(120)+chr(95)+chr(115)+chr(116)+chr(114)+chr(105)+chr(99)+chr(116)+chr(32)+chr(20869)+chr(23481)+chr(19981)+chr(23436)+chr(32570)+chr(22833)+chr(10)+chr(10)+chr(22914)+chr(38656)+chr(33719)+chr(21462)+chr(23436)+chr(25972)+chr(32)+chr(100)+chr(101)+chr(118)+chr(109)+chr(111)+chr(100)+chr(101)+chr(32)+chr(21151)+chr(33021)+chr(65292)+chr(35831)+chr(20180)+chr(32454)+chr(38405)+chr(35835)+chr(32)+chr(82)+chr(69)+chr(65)+chr(68)+chr(77)+chr(69)+chr(46)+chr(109)+chr(100)+chr(32)+chr(25991)+chr(20214))  # noqa: E225,E226
            _src_h = inspect.getsource(_hard)  # noqa: E225
            _xs = chr(95)+chr(120)+chr(95)+chr(115)+chr(116)+chr(114)+chr(105)+chr(99)+chr(116)  # noqa: E225  _x_strict
            if _xs not in _src_h:  # noqa: E225
                raise RuntimeError(chr(20445)+chr(25252)+chr(27169)+chr(22359)+chr(23436)+chr(24050)+chr(34987)+chr(32244)+chr(25913)+chr(65306)+chr(95)+chr(104)+chr(97)+chr(114)+chr(100)+chr(32)+chr(32467)+chr(26500)+chr(24322)+chr(24120)+chr(10)+chr(10)+chr(22914)+chr(38656)+chr(33719)+chr(21462)+chr(23436)+chr(25972)+chr(32)+chr(100)+chr(101)+chr(118)+chr(109)+chr(111)+chr(100)+chr(101)+chr(32)+chr(21151)+chr(33021)+chr(65292)+chr(35831)+chr(20180)+chr(32454)+chr(38405)+chr(35835)+chr(32)+chr(82)+chr(69)+chr(65)+chr(68)+chr(77)+chr(69)+chr(46)+chr(109)+chr(100)+chr(32)+chr(25991)+chr(20214))  # noqa: E225,E226
        except RuntimeError:
            raise
        except Exception:
            raise RuntimeError(  # noqa: E231
                chr(20445)+chr(25252)+chr(27169)+chr(22359)+chr(23436)+chr(24615)+chr(24627)+chr(25928)+chr(39564)+chr(36133)+chr(10)+chr(10)  # noqa: E225,E226
                +chr(26080)+chr(27861)+chr(35835)+chr(21462)+chr(28304)+chr(30721)+chr(36827)+chr(25928)+chr(39564)+chr(36133)+chr(65292)+chr(31243)+chr(32456)+chr(32447)+chr(25454)+chr(32473)+chr(21551)+chr(12290)+chr(10)+chr(10)  # noqa: E225,E226
                +chr(35831)+chr(26816)+chr(26597)+chr(26535)+chr(20445)+chr(26435)+chr(38480)+chr(25135)+chr(25110)+chr(36890)+chr(51)+chr(56)+chr(54)+chr(32)+chr(103)+chr(105)+chr(116)+chr(32)+chr(114)+chr(101)+chr(115)+chr(116)+chr(111)+chr(114)+chr(101)+chr(32)+chr(24674)+chr(22797)+chr(25991)+chr(20214)+chr(25991)+chr(21581)+chr(35797)+chr(12290)  # noqa: E225,E226
                +chr(10)+chr(10)+chr(22914)+chr(38656)+chr(33719)+chr(21462)+chr(23436)+chr(25972)+chr(32)+chr(100)+chr(101)+chr(118)+chr(109)+chr(111)+chr(100)+chr(101)+chr(32)+chr(21151)+chr(33021)+chr(65292)+chr(35831)+chr(20180)+chr(32454)+chr(38405)+chr(35835)+chr(32)+chr(82)+chr(69)+chr(65)+chr(68)+chr(77)+chr(69)+chr(46)+chr(109)+chr(100)+chr(32)+chr(25991)+chr(20214)  # noqa: E225,E226
            )


_self_check()
