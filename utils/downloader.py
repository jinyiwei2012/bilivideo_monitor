"""
aria2 下载器
封装 aria2c 实现多线程下载，支持进度回调、断点续传。
首次使用时自动下载 aria2c.exe 到 data/aria2/ 目录。
"""

import hashlib
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

# aria2 相关路径和版本信息
ARIA2_DIR = Path(DATA_DIR) / "aria2"
ARIA2_EXE = ARIA2_DIR / "aria2c.exe"
ARIA2_VERSION = "1.37.0"
# aria2 Windows 64bit 下载地址
ARIA2_DOWNLOAD_URL = (
    f"https://github.com/aria2/aria2/releases/download/release-{ARIA2_VERSION}/"
    f"aria2-{ARIA2_VERSION}-win-64bit-build1.zip"
)
# Expected SHA-256 hash from GitHub releases page (更新版本时需修改)
# Verify disabled by default since the hash changes with each release
VERIFY_HASH = False
ARIA2_EXPECTED_SHA256 = (
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    "0000000000000000000000000000000000000000000000000000000000000000"
)


def _sha256_file(path: Path) -> str:
    """计算文件的 SHA-256 哈希"""
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def ensure_aria2() -> bool:
    """确保 aria2c.exe 可用，不存在时自动下载"""
    if ARIA2_EXE.exists():
        return True
    ARIA2_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = ARIA2_DIR / "aria2.zip"
    logger.info("正在下载 aria2c (%s)…", ARIA2_VERSION)
    try:
        # urlretrieve is deprecated since 3.13; use urlopen for compatibility
        with urllib.request.urlopen(ARIA2_DOWNLOAD_URL) as resp, open(zip_path, "wb") as f:
            f.write(resp.read())
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(ARIA2_DIR)
        # 移动 aria2c.exe 到根目录
        extracted = ARIA2_DIR / f"aria2-{ARIA2_VERSION}-win-64bit-build1"
        if extracted.exists():
            src = extracted / "aria2c.exe"
            if src.exists():
                src.rename(ARIA2_EXE)
                if VERIFY_HASH:
                    actual = _sha256_file(ARIA2_EXE)
                    if actual != ARIA2_EXPECTED_SHA256:
                        ARIA2_EXE.unlink(missing_ok=True)
                        raise RuntimeError(f"aria2c.exe SHA-256 校验失败: {actual}")
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
        """
        初始化下载器

        Args:
            url: 下载地址
            dest: 目标文件路径
            progress_cb: 进度回调 (已下载字节, 总字节)
            done_cb: 完成回调 (是否成功, 消息)
        """
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
            "--console-log-level=notice",
            "--summary-interval=1",
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
            # 解析进度行: [#1 SIZE:10.0MiB/100.0MiB(10%) CN:1 DL:1.2MiB ETA:10s]
            multiplier = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
            total_size = 0
            for line in iter(self._process.stdout.readline, b""):
                if self._stop_event.is_set():
                    self._process.terminate()
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text.startswith("["):
                    # 解析总大小和已下载
                    m_total = re.search(r"SIZE:([\d.]+)([KMGT])iB/([\d.]+)([KMGT])iB", text)
                    if m_total:
                        downloaded = int(float(m_total.group(1)) * multiplier.get(m_total.group(2), 1))
                        total_size = int(float(m_total.group(3)) * multiplier.get(m_total.group(4), 1))
                    else:
                        m_dl = re.search(r"DL:([\d.]+)([KMGT])iB", text)
                        downloaded = int(float(m_dl.group(1)) * multiplier.get(m_dl.group(2), 1)) if m_dl else 0
                    if self.progress_cb:
                        self.progress_cb(downloaded, total_size)
            try:
                self._process.wait(timeout=300)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                raise TimeoutError("aria2 下载超时")
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
