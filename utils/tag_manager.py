"""
视频标签管理模块

为每个监控的 BV 号添加自定义标签（如「热门」「技术」「搞笑」等），
支持增删查改操作，数据持久化到 JSON 文件中（data/video_tags.json）。

使用方式：
    from utils.tag_manager import add_tag, get_tags, all_tags

    add_tag("BV1xx4y1w7zz", "技术")
    print(get_tags("BV1xx4y1w7zz"))  # ['技术']
    print(all_tags())                 # {'技术', '热门', ...}
"""

import json
import os
import logging
from typing import Dict, List, Set

from utils import project_path

logger = logging.getLogger(__name__)

# 标签持久化文件路径：data/video_tags.json
_TAG_FILE = project_path("data", "video_tags.json")
# 内存中的标签缓存字典，key 为 BV 号，value 为该 BV 的标签列表
_tags: Dict[str, List[str]] = {}
# 是否已从磁盘加载过标签数据（延迟加载，按需初始化）
_loaded = False


def _load():
    """从磁盘加载标签数据到内存。

    采用延迟加载策略：首次调用任意公共函数时自动加载，
    后续调用直接使用内存缓存，避免重复 I/O。
    """
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
    """将内存中的标签数据持久化到磁盘 JSON 文件。

    每次标签变更后立即调用，保证数据不丢失。
    自动创建父目录如果不存在。
    """
    os.makedirs(os.path.dirname(_TAG_FILE), exist_ok=True)
    with open(_TAG_FILE, "w", encoding="utf-8") as f:
        json.dump(_tags, f, ensure_ascii=False, indent=2)


def get_tags(bvid: str) -> List[str]:
    """获取指定 BV 号的所有标签列表。

    Args:
        bvid: 视频 BV 号，如 "BV1xx4y1w7zz"

    Returns:
        list[str]: 该视频的标签列表，若未标记则返回空列表 []
    """
    _load()
    return _tags.get(bvid, [])


def set_tags(bvid: str, tags: List[str]):
    """设置指定 BV 号的标签列表（全覆盖模式，会替换原有标签）。

    注意：此操作会完全覆盖该 BV 号已有的所有标签。

    Args:
        bvid: 视频 BV 号
        tags: 新的标签列表，如 ["技术", "教程", "Python"]
    """
    _load()
    _tags[bvid] = tags
    _save()


def add_tag(bvid: str, tag: str):
    """为指定 BV 号添加一个标签（去重，重复添加不生效）。

    Args:
        bvid: 视频 BV 号
        tag: 要添加的标签名

    Example:
        >>> add_tag("BV1xx", "技术")
        >>> add_tag("BV1xx", "教程")
        >>> add_tag("BV1xx", "技术")  # 重复添加不生效
        >>> get_tags("BV1xx")
        ['技术', '教程']
    """
    _load()
    if bvid not in _tags:
        _tags[bvid] = []
    if tag not in _tags[bvid]:  # 去重检查
        _tags[bvid].append(tag)
        _save()


def remove_tag(bvid: str, tag: str):
    """从指定 BV 号移除一个标签。如果移除后该 BV 无标签，则同时清理空条目。

    Args:
        bvid: 视频 BV 号
        tag: 要移除的标签名
    """
    _load()
    if bvid in _tags and tag in _tags[bvid]:
        _tags[bvid].remove(tag)
        if not _tags[bvid]:  # 该 BV 无标签了，清理空条目节省空间
            del _tags[bvid]
        _save()


def remove_bvid(bvid: str):
    """移除指定 BV 号的所有标签记录（彻底删除）。

    当视频从监控列表中移除时调用，清理关联的标签数据。

    Args:
        bvid: 视频 BV 号
    """
    _load()
    _tags.pop(bvid, None)
    _save()


def all_tags() -> Set[str]:
    """获取系统中所有已使用过的标签集合（去重后的所有唯一标签名）。

    Returns:
        set[str]: 所有标签名称的集合，如 {'技术', '热门', '搞笑', '教程'}
    """
    _load()
    result = set()
    for tags in _tags.values():
        result.update(tags)
    return result


def get_bvids_by_tag(tag: str) -> List[str]:
    """根据标签名反向查找所有包含该标签的 BV 号列表。

    用于按标签筛选视频，如找出所有标记为「热门」的视频。

    Args:
        tag: 标签名称

    Returns:
        list[str]: 包含该标签的 BV 号列表
    """
    _load()
    return [bvid for bvid, tags in _tags.items() if tag in tags]


def get_all_tagged() -> Dict[str, List[str]]:
    """获取所有已标记的视频及其标签的完整字典。

    Returns:
        dict: {bvid: [tag1, tag2, ...], ...} 格式的完整映射
    """
    _load()
    return dict(_tags)  # 返回浅拷贝，防止外部直接修改内部数据
