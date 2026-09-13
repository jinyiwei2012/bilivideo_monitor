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


_VIEW_SUGGESTIONS = (
    (10_000_000, "千万播放"),
    (1_000_000, "百万播放"),
    (100_000, "十万播放"),
)
"""播放量区间 → 标签（降序，首个命中生效）"""

_DURATION_SUGGESTIONS = (
    (3600, "长视频 (>1h)"),
    (1800, "中视频 (30-60min)"),
)
"""时长区间 → 标签（降序，首个命中生效）"""

_TITLE_KEYWORDS: Dict[str, List[str]] = {
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
"""标题关键词 → 标签"""


def _suggest_by_views(views: int) -> str:
    """按播放量区间给出标签（不落在任何区间时返回空串）。"""
    for threshold, label in _VIEW_SUGGESTIONS:
        if views >= threshold:
            return label
    return "播放<1万" if views < 10_000 else ""


def _suggest_by_duration(duration: int) -> str:
    """按时长给出标签（不落在任何区间时返回空串）。"""
    for threshold, label in _DURATION_SUGGESTIONS:
        if duration >= threshold:
            return label
    return "短视频 (<1min)" if 0 < duration <= 60 else ""


def _suggest_by_title(title: str) -> List[str]:
    """按标题关键词给出标签（每个类目至多一个）。"""
    lowered = title.lower()
    return [tag for tag, keywords in _TITLE_KEYWORDS.items() if any(kw.lower() in lowered for kw in keywords)]


def _suggest_by_author(author: str) -> set:
    """复用该 UP 主出现 ≥3 次的历史标签（结果按作者缓存）。"""
    cached = suggest_tags.by_author.get(author)
    if cached is not None:
        return cached
    tag_counts: Dict[str, int] = {}
    for tags in get_all_tagged().values():
        for tag in tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    cached = {tag for tag, count in tag_counts.items() if count >= 3}
    suggest_tags.by_author[author] = cached
    return cached


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

    # 按播放量区间 / 时长
    for label in (_suggest_by_views(views), _suggest_by_duration(duration)):
        if label:
            suggestions.append(label)

    # 按标题关键词
    suggestions.extend(_suggest_by_title(title))

    # 按 UP 主（如果已有此 UP 主的标签，建议复用）
    if author:
        for tag in _suggest_by_author(author):
            if tag not in suggestions:
                suggestions.append(tag)

    return suggestions


suggest_tags.by_author = {}  # type: ignore
