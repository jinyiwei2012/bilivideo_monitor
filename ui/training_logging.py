"""Training UI and file log persistence."""

import logging
import os
import time
from datetime import datetime
from typing import Optional, TextIO

from ui.training_base import _TrainingPanelContract

logger = logging.getLogger(__name__)


class TrainingLoggingMixin(_TrainingPanelContract):
    _log_dir: str
    _log_file: Optional[TextIO]
    _log_file_path: str

    def _open_log_file(self, algo_count: int, epochs: int, batch: int, mode: str, lr: float = 0.001):
        """创建训练日志文件。"""
        os.makedirs(self._log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_file_path = os.path.join(self._log_dir, f"train_{ts}.log")
        self._log_file = open(self._log_file_path, "w", encoding="utf-8")
        # 写文件头
        self._log_file.write(f"{'=' * 60}\n")
        self._log_file.write(f"  训练启动: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        self._log_file.write(
            f"  模式: {mode}  |  算法: {algo_count}  |  epoch: {epochs}  |  batch: {batch}  |  lr: {lr:.6f}\n"
        )
        self._log_file.write(f"{'=' * 60}\n")
        self._log_file.flush()

    def _close_log_file(self):
        """关闭训练日志文件。"""
        if self._log_file is None:
            return
        try:
            self._log_file.write(f"{'=' * 60}\n")
            self._log_file.write(f"  训练结束: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            self._log_file.write(f"{'=' * 60}\n")
            self._log_file.flush()
            self._log_file.close()
        except Exception as e:
            logger.debug("关闭训练日志文件失败: %s", e)
        self._log_file = None
        logger.info("训练日志已保存: %s", self._log_file_path)

    def __del__(self):
        """析构时兜底关闭日志文件，防止异常路径下文件句柄泄漏。"""
        log_file = getattr(self, "_log_file", None)
        if log_file is not None:
            try:
                log_file.flush()
                log_file.close()
            except Exception:
                pass
            self._log_file = None

    def _append_log(self, text: str):
        """追加日志到 UI 和文件"""
        super()._append_log(text)
        if self._log_file is not None:
            try:
                line = f"[{time.strftime('%H:%M:%S')}] {text}\n"
                self._log_file.write(line)
                self._log_file.flush()
            except Exception as e:
                logger.debug("写入训练日志文件失败: %s", e)
