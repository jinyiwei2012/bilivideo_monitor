"""
时间戳工具函数 — 统一处理 datetime / 字符串 / 数值三种格式

本模块提供三个核心函数，用于在项目中统一处理各种时间表示形式：
- normalize_timestamp: 将任意格式时间戳标准化为 (datetime, float, str) 三元组
- safe_timestamp:     安全获取 Unix 浮点时间戳（秒），兼容所有常见类型
- safe_datetime:      安全获取 Python datetime 对象，兼容所有常见类型

这些函数在数据库读写、图表绘制、日志记录等多个场景中被广泛使用，
避免了各处重复编写类型判断和转换逻辑。
"""

from datetime import datetime
from typing import Tuple


def normalize_timestamp(ts) -> Tuple[datetime, float, str]:
    """统一时间戳处理，将任意格式的标准时间表示转换为标准化的三元组。

    支持三种输入格式：
    1. datetime 对象  — 直接解析
    2. int/float 数值  — 作为 Unix 时间戳（秒）处理
    3. ISO 格式字符串  — 如 "2025-01-01T12:00:00"

    Args:
        ts: 时间戳，可以是 datetime / ISO 格式字符串 / int/float 数值

    Returns:
        三元组 (datetime_obj, timestamp_float, "YYYY-MM-DD HH:MM:SS"):
        - datetime_obj: Python datetime 对象
        - timestamp_float: Unix 时间戳浮点数（秒）
        - 格式化字符串: 便于显示和日志

    Raises:
        TypeError: 当传入不支持的时间戳类型时抛出
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
    """安全获取 Unix 时间戳（秒），兼容 datetime / str / float / int 等多种类型。

    此函数内部调用 normalize_timestamp 进行类型转换，适用于不确定输入类型
    但需要统一 float 时间戳的场景（如数据库写入、API 参数等）。

    Args:
        ts: 时间戳，支持 datetime / ISO 字符串 / 数值

    Returns:
        float: Unix 时间戳（秒），如 1717300000.0
    """
    if isinstance(ts, (int, float)):
        return float(ts)
    dt, _, _ = normalize_timestamp(ts)
    return dt.timestamp()


def safe_datetime(ts) -> datetime:
    """安全获取 datetime 对象，兼容 datetime / str / float / int 等类型。

    用于需要 datetime 对象进行日期运算、格式化输出等场景。

    Args:
        ts: 时间戳，支持 datetime / ISO 字符串 / 数值

    Returns:
        datetime: Python datetime 对象
    """
    if isinstance(ts, datetime):
        return ts
    dt, _, _ = normalize_timestamp(ts)
    return dt
