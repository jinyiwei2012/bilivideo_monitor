"""
aria2 多线程下载器

封装 aria2c.exe 实现高性能多线程下载，支持：
- 断点续传：已下载部分不会丢失，重启后自动继续
- 进度回调：实时获取 (已下载字节, 总字节) 供 UI 展示进度条
- 自动部署：首次使用时自动从 GitHub Release 下载 aria2c.exe 到 data/aria2/ 目录
- 多连接下载：默认 4 线程并发，充分利用带宽

注意：aria2c.exe 仅在 Windows 平台提供，本模块专为 Windows 设计。
如果下载失败或 aria2c 不可用，会自动降级，调用方应做好错误处理。
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

# ── aria2 路径和版本配置 ──────────────────────────────
# aria2c.exe 存放目录
ARIA2_DIR = Path(DATA_DIR) / "aria2"
# aria2c.exe 完整路径
ARIA2_EXE = ARIA2_DIR / "aria2c.exe"
# 内置的 aria2 版本号（用于下载和更新）
ARIA2_VERSION = "1.37.0"
# aria2 Windows 64bit 下载地址（GitHub Release）
ARIA2_DOWNLOAD_URL = (
    f"https://github.com/aria2/aria2/releases/download/release-{ARIA2_VERSION}/"
    f"aria2-{ARIA2_VERSION}-win-64bit-build1.zip"
)
# 是否启用 SHA-256 校验（默认关闭以减少启动时间）
# Expected SHA-256 hash from GitHub releases page (更新版本时需修改)
# 从 GitHub Releases 页面复制对应版本的 aria2c.exe 的 SHA-256
# 设置 VERIFY_HASH = True 启用下载验证
VERIFY_HASH = False
# 预期的 SHA-256 值（预留，默认不校验）
ARIA2_EXPECTED_SHA256 = ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")


def _sha256_file(path: Path) -> str:
    """计算文件的 SHA-256 哈希值（分块读取，避免大文件 OOM）。

    Args:
        path: 文件路径

    Returns:
        str: 16 进制 SHA-256 哈希字符串
    """
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):  # 每次读 64KB 分块
            sha.update(chunk)
    return sha.hexdigest()


def ensure_aria2() -> bool:
    """确保 aria2c.exe 可用，不存在时自动从 GitHub Release 下载。

    下载流程：
    1. 创建 data/aria2/ 目录
    2. 下载 zip 到临时位置
    3. 解压并提取 aria2c.exe
    4. 可选验证 SHA-256
    5. 清理临时文件

    Returns:
        bool: aria2c.exe 是否可用（已存在或下载成功返回 True）
    """
    if ARIA2_EXE.exists():
        return True  # 已存在，无需下载
    ARIA2_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = ARIA2_DIR / "aria2.zip"
    logger.info("正在下载 aria2c (%s)…", ARIA2_VERSION)
    try:
        # urlretrieve is deprecated since 3.13; use urlopen for compatibility
        with urllib.request.urlopen(ARIA2_DOWNLOAD_URL) as resp, open(zip_path, "wb") as f:
            f.write(resp.read())
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(ARIA2_DIR)
        # 移动 aria2c.exe 到根目录（去掉解压后的子文件夹层级）
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
                # 清理解压后的临时子文件夹
                import shutil

                shutil.rmtree(extracted, ignore_errors=True)
        zip_path.unlink(missing_ok=True)  # 删除下载的 zip 文件
        logger.info("aria2c 下载完成: %s", ARIA2_EXE)
        return ARIA2_EXE.exists()
    except Exception as e:
        logger.warning("aria2c 自动下载失败: %s", e)
        return False


class Aria2Downloader:
    """aria2 下载器，封装 aria2c 进程管理，支持进度回调和完成通知。

    下载在独立线程中运行（通过 subprocess），不会阻塞调用线程。
    进度通过解析 aria2c 的 stdout 输出实时获取。
    """

    def __init__(
        self,
        url: str,
        dest: str,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        done_cb: Optional[Callable[[bool, str], None]] = None,
    ):
        """
        初始化下载器。

        Args:
            url: 下载地址（HTTP/HTTPS/FTP）
            dest: 目标文件完整路径（包含文件名）
            progress_cb: 进度回调函数，签名: (downloaded_bytes: int, total_bytes: int) -> None
                         total_bytes 可能为 0（尚未获取到文件大小时）
            done_cb: 完成回调函数，签名: (success: bool, message: str) -> None
                     success=True 表示下载成功，message 为空或成功信息
                     success=False 表示下载失败，message 包含错误原因
        """
        self.url = url
        self.dest = dest
        self.progress_cb = progress_cb
        self.done_cb = done_cb
        self._process: Optional[subprocess.Popen] = None  # aria2c 子进程句柄
        self._stop_event = threading.Event()  # 取消下载的信号量

    def start(self):
        """启动下载（阻塞直到下载完成或出错）。

        此方法会启动 aria2c 子进程并阻塞等待其完成。
        进度通过解析 stdout 输出实时上报给 progress_cb。
        建议在独立线程中调用此方法以免阻塞 UI。

        Returns:
            bool: 下载是否成功
        """
        # 确保 aria2c.exe 可用
        if not ARIA2_EXE.exists() and not ensure_aria2():
            if self.done_cb:
                self.done_cb(False, "aria2c 不可用")
            return False

        os.makedirs(os.path.dirname(self.dest), exist_ok=True)
        # aria2c 命令行参数：
        # --continue=true       断点续传
        # --console-log-level   console 输出级别
        # --summary-interval=1  每秒输出一次进度摘要
        # --dir                 下载目录
        # --out                 输出文件名
        # --max-connection-per-server=4  每个服务器最大连接数
        # --split=4             分成 4 段并行下载
        # --allow-overwrite     允许覆盖
        # --auto-file-renaming  禁止自动重命名
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
            # 启动 aria2c 子进程，捕获 stdout（隐藏控制台窗口）
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            # 解析进度输出行格式: [#1 SIZE:10.0MiB/100.0MiB(10%) CN:1 DL:1.2MiB ETA:10s]
            multiplier = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}
            total_size = 0
            for line in iter(self._process.stdout.readline, b""):
                if self._stop_event.is_set():
                    self._process.terminate()  # 用户取消，终止子进程
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text.startswith("["):  # 进度信息行
                    # 解析总大小和已下载量："SIZE:10.0MiB/100.0MiB"
                    m_total = re.search(r"SIZE:([\d.]+)([KMGT])iB/([\d.]+)([KMGT])iB", text)
                    if m_total:
                        downloaded = int(float(m_total.group(1)) * multiplier.get(m_total.group(2), 1))
                        total_size = int(float(m_total.group(3)) * multiplier.get(m_total.group(4), 1))
                    else:
                        # 降级方案：仅解析已下载量 "DL:1.2MiB"
                        m_dl = re.search(r"DL:([\d.]+)([KMGT])iB", text)
                        downloaded = int(float(m_dl.group(1)) * multiplier.get(m_dl.group(2), 1)) if m_dl else 0
                    if self.progress_cb:
                        self.progress_cb(downloaded, total_size)
            try:
                self._process.wait(timeout=300)  # 最多等待 5 分钟
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
        """取消正在进行的下载。

        设置停止信号量 → 终止 aria2c 子进程。
        子进程终止后 start() 方法会返回 False。
        """
        self._stop_event.set()
        if self._process:
            self._process.terminate()


def download_file(
    url: str,
    dest: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    done_cb: Optional[Callable[[bool, str], None]] = None,
) -> bool:
    """便捷函数：使用 aria2 下载单个文件。

    这是 Aria2Downloader 的简化封装，创建下载器实例后立即启动下载。

    Args:
        url: 下载地址
        dest: 目标文件路径
        progress_cb: 进度回调 (downloaded_bytes, total_bytes)
        done_cb: 完成回调 (success, message)

    Returns:
        bool: 下载是否成功

    Example:
        >>> download_file(
        ...     "https://example.com/video.mp4",
        ...     "downloads/video.mp4",
        ...     progress_cb=lambda d, t: print(f"{d}/{t}"),
        ...     done_cb=lambda ok, msg: print(f"Done: {ok}, {msg}")
        ... )
    """
    dl = Aria2Downloader(url, dest, progress_cb, done_cb)
    return dl.start()
