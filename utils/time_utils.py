"""
时间戳工具函数 — 统一处理 datetime/字符串/数值 三种格式

全库统一的时间戳字符串格式（写入 SQLite 一律用它）::

    TS_FMT = "%Y-%m-%d %H:%M:%S"   # 本地时间 / 秒精度 / 可直接字典序比较

注意：``datetime.isoformat()`` 产出 "YYYY-MM-DDTHH:MM:SS.ffffff"（含 T 与微秒），
与上面的格式**不可混用** —— 'T'(0x54) 与 ' '(0x20) 字典序不同，混用会使
范围比较（``created_at >= ?``）结果错误。写库请统一用 now_ts() / format_ts()。
"""

from datetime import datetime
from typing import Tuple

TS_FMT = "%Y-%m-%d %H:%M:%S"


def format_ts(dt: datetime | None = None) -> str:
    """按全库统一格式格式化时间戳（默认取当前时间）。"""
    return (dt or datetime.now()).strftime(TS_FMT)


def now_ts() -> str:
    """当前时间的统一格式字符串（写数据库用）。"""
    return datetime.now().strftime(TS_FMT)


def normalize_timestamp(ts) -> Tuple[datetime, float, str]:
    """统一时间戳处理

    Args:
        ts: datetime / ISO 格式字符串 / int/float 时间戳

    Returns:
        (datetime_obj, timestamp_float, "YYYY-MM-DD HH:MM:SS")
    """
    if isinstance(ts, datetime):
        return ts, ts.timestamp(), ts.strftime(TS_FMT)
    if isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts)
        return dt, float(ts), dt.strftime(TS_FMT)
    if isinstance(ts, str):
        dt = datetime.fromisoformat(ts)
        return dt, dt.timestamp(), dt.strftime(TS_FMT)
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
