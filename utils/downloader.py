"""
aria2 下载器
封装 aria2c 实现多线程下载，支持进度回调、断点续传。
首次使用时自动下载 aria2c.exe 到 data/aria2/ 目录。
"""

import logging
import os
import re
import subprocess
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

from config import DATA_DIR

logger = logging.getLogger(__name__)

ARIA2_DIR = Path(DATA_DIR) / "aria2"
ARIA2_EXE = ARIA2_DIR / "aria2c.exe"
ARIA2_VERSION = "1.37.0"
# aria2 Windows 64bit 下载地址
ARIA2_DOWNLOAD_URL = (
    f"https://github.com/aria2/aria2/releases/download/release-{ARIA2_VERSION}/"
    f"aria2-{ARIA2_VERSION}-win-64bit-build1.zip"
)


def ensure_aria2() -> bool:
    """确保 aria2c.exe 可用，不存在时自动下载"""
    if ARIA2_EXE.exists():
        return True
    ARIA2_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = ARIA2_DIR / "aria2.zip"
    logger.info("正在下载 aria2c (%s)…", ARIA2_VERSION)
    try:
        urllib.request.urlretrieve(ARIA2_DOWNLOAD_URL, zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(ARIA2_DIR)
        # 移动 aria2c.exe 到根目录
        extracted = ARIA2_DIR / f"aria2-{ARIA2_VERSION}-win-64bit-build1"
        if extracted.exists():
            src = extracted / "aria2c.exe"
            if src.exists():
                src.rename(ARIA2_EXE)
                # 清理临时文件
                import shutil
                shutil.rmtree(extracted, ignore_errors=True)
        zip_path.unlink(missing_ok=True)
        logger.info("aria2c 下载完成: %s", ARIA2_EXE)
        return ARIA2_EXE.exists()
    except Exception as e:
        logger.warning("aria2c 自动下载失败: %s", e)
        return False


class Aria2Downloader:
    """aria2 下载器，支持进度回调"""

    def __init__(
        self,
        url: str,
        dest: str,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        done_cb: Optional[Callable[[bool, str], None]] = None,
    ):
        self.url = url
        self.dest = dest
        self.progress_cb = progress_cb
        self.done_cb = done_cb
        self._process: Optional[subprocess.Popen] = None
        self._stop_event = threading.Event()

    def start(self):
        """启动下载（阻塞直到完成，进度在独立线程上报）"""
        if not ARIA2_EXE.exists() and not ensure_aria2():
            if self.done_cb:
                self.done_cb(False, "aria2c 不可用")
            return False

        os.makedirs(os.path.dirname(self.dest), exist_ok=True)
        # aria2c 参数：继续、进度 JSON-RPC、输出路径、连接数
        cmd = [
            str(ARIA2_EXE),
            "--continue=true",
            "--console-log-level=error",
            "--summary-interval=0",
            f"--dir={os.path.dirname(self.dest)}",
            f"--out={os.path.basename(self.dest)}",
            "--max-connection-per-server=4",
            "--split=4",
            "--allow-overwrite=true",
            "--auto-file-renaming=false",
            self.url,
        ]
        logger.debug("aria2c: %s", " ".join(cmd))
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            # 解析进度行: [DL:xxxB ETA:xx]
            total = 0
            for line in iter(self._process.stdout.readline, b""):
                if self._stop_event.is_set():
                    self._process.terminate()
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text.startswith("["):
                    # 解析下载进度
                    m = re.search(r"DL:([\d.]+)([KMGT])iB", text)
                    if m:
                        val = float(m.group(1))
                        unit = m.group(2)
                        multiplier = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
                        downloaded = int(val * multiplier.get(unit, 1))
                    else:
                        downloaded = 0
                    if self.progress_cb:
                        self.progress_cb(downloaded, total)
            self._process.wait()
            success = self._process.returncode == 0 and os.path.exists(self.dest)
            if self.done_cb:
                self.done_cb(success, "" if success else f"aria2c 退出码 {self._process.returncode}")
            return success
        except Exception as e:
            logger.warning("aria2 下载异常: %s", e)
            if self.done_cb:
                self.done_cb(False, str(e))
            return False

    def cancel(self):
        """取消下载"""
        self._stop_event.set()
        if self._process:
            self._process.terminate()


def download_file(
    url: str,
    dest: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    done_cb: Optional[Callable[[bool, str], None]] = None,
) -> bool:
    """便捷函数：使用 aria2 下载文件"""
    dl = Aria2Downloader(url, dest, progress_cb, done_cb)
    return dl.start()
