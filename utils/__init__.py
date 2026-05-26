"""
工具模块
包含各种工具函数和辅助类
"""

import os

from .file_logger import FileLogger
from .time_utils import normalize_timestamp, safe_timestamp, safe_datetime

# ── 项目根路径 ────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def project_path(*parts: str) -> str:
    """返回项目根目录下的路径：project_path('data', 'file.json')"""
    return os.path.join(PROJECT_ROOT, *parts)


__all__ = [
    "FileLogger",
    "normalize_timestamp",
    "safe_timestamp",
    "safe_datetime",
    "PROJECT_ROOT",
    "project_path",
]
