"""
工具函数模块
包含各种辅助函数
"""

import re
from typing import Union


def format_number(n: Union[int, float, str]) -> str:
    """
    格式化数字，转换为万/亿单位
    
    Args:
        n: 数字
        
    Returns:
        格式化后的字符串
    """
    try:
        n = float(n)
        if n >= 100000000:
            return f"{n/100000000:.1f}亿"
        elif n >= 10000:
            return f"{n/10000:.1f}万"
        else:
            return str(int(n))
    except (ValueError, TypeError):
        return str(n)


def format_duration(seconds: int) -> str:
    """
    格式化时长
    
    Args:
        seconds: 秒数
        
    Returns:
        格式化后的时长字符串 (如: 12:34)
    """
    try:
        seconds = int(seconds)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"
    except (ValueError, TypeError):
        return "0:00"


def parse_duration(duration_str: str) -> int:
    """
    解析时长字符串为秒数
    
    Args:
        duration_str: 时长字符串 (如: "12:34" 或 "1:23:45")
        
    Returns:
        秒数
    """
    try:
        parts = duration_str.split(':')
        if len(parts) == 2:
            # MM:SS
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            # HH:MM:SS
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except (ValueError, IndexError):
        pass
    return 0


def parse_threshold(s: str) -> int:
    """
    解析阈值字符串为数字
    
    Args:
        s: 阈值字符串 (如: "10万", "1000万", "1亿")
        
    Returns:
        数字
    """
    s = str(s).strip().replace(',', '')
    try:
        if '亿' in s:
            return int(float(s.replace('亿', '')) * 100000000)
        elif '万' in s:
            return int(float(s.replace('万', '')) * 10000)
        else:
            return int(float(s))
    except (ValueError, TypeError):
        return 0


def format_threshold(n: int) -> str:
    """
    格式化阈值数字为字符串
    
    Args:
        n: 数字
        
    Returns:
        格式化后的字符串 (如: "10万", "1000万")
    """
    if n >= 100000000:
        return f"{n//100000000}亿"
    elif n >= 10000:
        return f"{n//10000}万"
    else:
        return str(n)


def clean_html(text: str) -> str:
    """
    清除HTML标签

    Args:
        text: 包含HTML的文本

    Returns:
        清除HTML后的文本
    """
    return re.sub(re.compile('<.*?>'), '', text)


def truncate_text(text: str, max_length: int = 50, suffix: str = "...") -> str:
    """
    截断文本
    
    Args:
        text: 原文本
        max_length: 最大长度
        suffix: 后缀
        
    Returns:
        截断后的文本
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def calculate_growth_rate(current: int, previous: int, hours: float) -> float:
    """
    计算增长率
    
    Args:
        current: 当前值
        previous: 之前的值
        hours: 时间间隔（小时）
        
    Returns:
        每小时增长率
    """
    if hours <= 0 or previous <= 0:
        return 0.0
    return (current - previous) / hours


def calculate_like_view_ratio(like_count: int, view_count: int) -> float:
    """
    计算播赞比
    
    Args:
        like_count: 点赞数
        view_count: 播放量
        
    Returns:
        播赞比
    """
    if view_count <= 0:
        return 0.0
    return like_count / view_count


def safe_divide(numerator: Union[int, float], denominator: Union[int, float], default: float = 0.0) -> float:
    """
    安全除法
    
    Args:
        numerator: 分子
        denominator: 分母
        default: 默认值
        
    Returns:
        除法结果或默认值
    """
    try:
        if denominator == 0:
            return default
        return numerator / denominator
    except (TypeError, ValueError):
        return default


__all__ = [
    'format_number',
    'format_duration',
    'parse_duration',
    'parse_threshold',
    'format_threshold',
    'clean_html',
    'truncate_text',
    'calculate_growth_rate',
    'calculate_like_view_ratio',
    'safe_divide'
]
