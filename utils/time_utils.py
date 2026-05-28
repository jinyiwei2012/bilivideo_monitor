"""
时间戳工具函数 — 统一处理 datetime/字符串/数值 三种格式
"""

from datetime import datetime
from typing import Tuple


def normalize_timestamp(ts) -> Tuple[datetime, float, str]:
    """统一时间戳处理

    Args:
        ts: datetime / ISO 格式字符串 / int/float 时间戳

    Returns:
        (datetime_obj, timestamp_float, "YYYY-MM-DD HH:MM:SS")
    """
    if isinstance(ts, datetime):
        return ts, ts.timestamp(), ts.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts)
        return dt, float(ts), dt.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(ts, str):
        dt = datetime.fromisoformat(ts)
        return dt, dt.timestamp(), dt.strftime("%Y-%m-%d %H:%M:%S")
    raise TypeError(f"不支持的时间戳类型: {type(ts)}")


def safe_timestamp(ts) -> float:
    """安全获取 Unix 时间戳（秒），兼容 datetime / str / float / int"""
    if isinstance(ts, (int, float)):
        return float(ts)
    dt, _, _ = normalize_timestamp(ts)
    return dt.timestamp()


def safe_datetime(ts) -> datetime:
    """安全获取 datetime 对象"""
    if isinstance(ts, datetime):
        return ts
    dt, _, _ = normalize_timestamp(ts)
    return dt
