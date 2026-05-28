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
    os.makedirs(os.path.dirname(_TAG_FILE), exist_ok=True)
    with open(_TAG_FILE, "w", encoding="utf-8") as f:
        json.dump(_tags, f, ensure_ascii=False, indent=2)


def get_tags(bvid: str) -> List[str]:
    _load()
    return _tags.get(bvid, [])


def set_tags(bvid: str, tags: List[str]):
    _load()
    _tags[bvid] = tags
    _save()


def add_tag(bvid: str, tag: str):
    _load()
    if bvid not in _tags:
        _tags[bvid] = []
    if tag not in _tags[bvid]:
        _tags[bvid].append(tag)
        _save()


def remove_tag(bvid: str, tag: str):
    _load()
    if bvid in _tags and tag in _tags[bvid]:
        _tags[bvid].remove(tag)
        if not _tags[bvid]:
            del _tags[bvid]
        _save()


def remove_bvid(bvid: str):
    _load()
    _tags.pop(bvid, None)
    _save()


def all_tags() -> Set[str]:
    _load()
    result = set()
    for tags in _tags.values():
        result.update(tags)
    return result


def get_bvids_by_tag(tag: str) -> List[str]:
    _load()
    return [bvid for bvid, tags in _tags.items() if tag in tags]


def get_all_tagged() -> Dict[str, List[str]]:
    _load()
    return dict(_tags)
