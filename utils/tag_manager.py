"""
视频标签管理模块
支持为 BV 号添加/删除/查询自定义标签，持久化到 JSON。
"""

import json
import os
import logging
from typing import Dict, List, Set

from utils import project_path

logger = logging.getLogger(__name__)

_TAG_FILE = project_path("data", "video_tags.json")
_tags: Dict[str, List[str]] = {}
_loaded = False


def _load():
    """从磁盘加载标签数据"""
    global _tags, _loaded
    if _loaded:
        return
    if os.path.exists(_TAG_FILE):
        try:
            with open(_TAG_FILE, "r", encoding="utf-8") as f:
                _tags = json.load(f)
        except Exception as e:
            logger.warning("加载标签文件失败: %s", e)
            _tags = {}
    _loaded = True


def _save():
    """将标签数据持久化到磁盘"""
    os.makedirs(os.path.dirname(_TAG_FILE), exist_ok=True)
    with open(_TAG_FILE, "w", encoding="utf-8") as f:
        json.dump(_tags, f, ensure_ascii=False, indent=2)


def get_tags(bvid: str) -> List[str]:
    """获取指定 BV 号的所有标签"""
    _load()
    return _tags.get(bvid, [])


def set_tags(bvid: str, tags: List[str]):
    """设置指定 BV 号的标签列表（全覆盖）"""
    _load()
    _tags[bvid] = tags
    _save()


def add_tag(bvid: str, tag: str):
    """为指定 BV 号添加单个标签"""
    _load()
    if bvid not in _tags:
        _tags[bvid] = []
    if tag not in _tags[bvid]:
        _tags[bvid].append(tag)
        _save()


def remove_tag(bvid: str, tag: str):
    """从指定 BV 号移除单个标签"""
    _load()
    if bvid in _tags and tag in _tags[bvid]:
        _tags[bvid].remove(tag)
        if not _tags[bvid]:
            del _tags[bvid]
        _save()


def remove_bvid(bvid: str):
    """移除指定 BV 号的所有标签"""
    _load()
    _tags.pop(bvid, None)
    _save()


def all_tags() -> Set[str]:
    """获取所有已使用的标签集合"""
    _load()
    result = set()
    for tags in _tags.values():
        result.update(tags)
    return result


def get_bvids_by_tag(tag: str) -> List[str]:
    """根据标签查找所有包含该标签的 BV 号列表"""
    _load()
    return [bvid for bvid, tags in _tags.items() if tag in tags]


def get_all_tagged() -> Dict[str, List[str]]:
    """获取所有已标记的视频及其标签字典"""
    _load()
    return dict(_tags)


def suggest_tags(video: dict) -> List[str]:
    """根据视频元数据自动建议标签。

    Args:
        video: 包含 title, author, view_count 等字段的视频信息字典

    Returns:
        建议标签列表（已去重，不包含已有标签）
    """
    suggestions = []
    title = video.get("title", "")
    author = video.get("author", "")
    views = video.get("view_count", 0)
    duration = video.get("duration", 0)

    # 按播放量区间
    if views >= 10_000_000:
        suggestions.append("千万播放")
    elif views >= 1_000_000:
        suggestions.append("百万播放")
    elif views >= 100_000:
        suggestions.append("十万播放")
    elif views < 10_000:
        suggestions.append("播放<1万")

    # 按时长
    if duration >= 3600:
        suggestions.append("长视频 (>1h)")
    elif duration >= 1800:
        suggestions.append("中视频 (30-60min)")
    elif 0 < duration <= 60:
        suggestions.append("短视频 (<1min)")

    # 按标题关键词
    keywords_map = {
        "教程": ["教程", "教学", "入门", "指南", "实战", "新手"],
        "游戏": ["游戏", "通关", "攻略", "实况", "Minecraft", "原神", "LOL"],
        "音乐": ["音乐", "MV", "翻唱", "钢琴", "吉他", "演奏"],
        "科技": ["评测", "开箱", "科技", "数码", "手机", "电脑", "芯片"],
        "动画": ["动画", "动漫", "番剧", "MAD", "AMV"],
        "生活": ["vlog", "VLOG", "日常", "美食", "做饭", "探店"],
        "知识": ["科普", "历史", "哲学", "数学", "物理", "经济"],
        "影视": ["电影", "解说", "剧集", "剪辑", "混剪"],
        "编程": ["Python", "Java", "C++", "编程", "代码", "开源"],
    }
    for tag, keywords in keywords_map.items():
        for kw in keywords:
            if kw.lower() in title.lower():
                suggestions.append(tag)
                break

    # 按 UP 主（如果已有此 UP 主的标签，建议复用）
    if author:
        existing = suggest_tags.by_author.get(author)
        if existing is None:
            existing = set()
            tag_counts: Dict[str, int] = {}
            for bvid, tags in get_all_tagged().items():
                for tag in tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
            # 出现 3 次以上的标签建议复用
            existing = {tag for tag, count in tag_counts.items() if count >= 3}
            suggest_tags.by_author[author] = existing
        for tag in existing:
            if tag not in suggestions:
                suggestions.append(tag)

    return suggestions


suggest_tags.by_author = {}  # type: ignore
