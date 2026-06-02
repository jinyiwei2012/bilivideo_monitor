"""
工具模块 (utils)

本模块是 B站视频监控与播放量预测系统 的基础工具集合，提供：
├── file_logger     — 按天自动分割的线程安全文件日志
├── time_utils      — 时间戳统一处理（datetime/字符串/数值三种格式互转）
├── ai_qa           — AI 智能问答（支持 OpenAI 兼容 API / 纯规则回答）
├── browser_cookies — 从 Chrome/Edge 等浏览器提取 B站 Cookie
├── checkpoint_io   — 算法模型检查点（checkpoint）的批量导出/导入
├── cover_manager   — 视频封面本地缓存管理（含 MD5 校验）
├── crypto          — Cookie 和敏感配置的 AES 加密存储
├── downloader      — aria2 多线程下载器封装
├── geetest_solver  — 极验（Geetest）滑块验证码自动求解
├── interaction_quality — 一键三连健康探针（赞播比/币播比等）
├── report_exporter — HTML/Excel/CSV/JSON 格式的报告导出
├── sentiment_analyzer — 弹幕/评论情绪分析（基于规则的情感词典）
├── tag_manager     — 视频自定义标签管理（JSON 持久化）
├── update_checker  — 自动更新检查（GitHub Release）
├── weekly_score    — 周刊虚拟歌手中文曲排行榜分数计算
├── yearly_score    — 年刊虚拟歌手中文曲排行榜分数计算
└── PROJECT_ROOT    — 项目根目录绝对路径常量
"""

import os

from .file_logger import FileLogger
from .time_utils import normalize_timestamp, safe_timestamp, safe_datetime

# ── 项目根路径：用于在其他模块中定位项目资源文件 ──────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def project_path(*parts: str) -> str:
    """返回项目根目录下的绝对路径，便于跨平台组合文件路径。

    Args:
        *parts: 相对于项目根目录的子路径片段，例如 'data', 'file.json'

    Returns:
        str: 拼接后的绝对路径，如 'C:\\b站监控\\data\\file.json'

    Example:
        >>> project_path('data', 'video_tags.json')
        'C:\\b站监控\\data\\video_tags.json'
    """
    return os.path.join(PROJECT_ROOT, *parts)


__all__ = [
    "FileLogger",
    "normalize_timestamp",
    "safe_timestamp",
    "safe_datetime",
    "PROJECT_ROOT",
    "project_path",
]
