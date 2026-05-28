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

# ── 启动安全校验 — 校验 2/3：模块完整性 ──────
try:
    from utils.update_checker import _x as _uc_x
    _ = callable(_uc_x)
    _ = isinstance(_uc_x(), bool)
    del _
except Exception:
    raise RuntimeError(
        chr(20445)+chr(25252)+chr(27169)+chr(22359)+chr(23436)+chr(31995)+chr(22359)+chr(24050)+chr(34987)+chr(34987)+chr(34945)+chr(24050)+chr(34987)+chr(26524)+chr(65292)+chr(31243)+chr(32456)+chr(32447)+chr(25298)+chr(32477)+chr(21551)+chr(12290)+chr(10)
        +chr(35831)+chr(36890)+chr(32)+chr(103)+chr(105)+chr(116)+chr(32)+chr(114)+chr(101)+chr(115)+chr(116)+chr(111)+chr(114)+chr(101)+chr(32)+chr(24674)+chr(22797)+chr(25991)+chr(20214)+chr(25991)+chr(21581)+chr(35797)+chr(12290)
        +chr(10)+chr(10)+chr(22914)+chr(38656)+chr(33719)+chr(21462)+chr(23436)+chr(25972)+chr(32)+chr(100)+chr(101)+chr(118)+chr(109)+chr(111)+chr(100)+chr(101)+chr(32)+chr(21151)+chr(33021)+chr(65292)+chr(35831)+chr(20180)+chr(32454)+chr(38405)+chr(35835)+chr(32)+chr(82)+chr(69)+chr(65)+chr(68)+chr(77)+chr(69)+chr(46)+chr(109)+chr(100)+chr(32)+chr(25991)+chr(20214)
    )
finally:
    try:
        del _uc_x
    except Exception:
        pass
