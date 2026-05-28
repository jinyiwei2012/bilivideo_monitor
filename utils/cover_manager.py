"""
封面管理器 - 本地缓存、MD5 校验、按需重新下载
"""

import hashlib
import logging
import os
import re

from config import COVER_DIR

logger = logging.getLogger(__name__)

_MAX_TITLE_LEN = 60


def _sanitize(title: str) -> str:
    """清理标题中的非法文件名字符，并截断到合理长度"""
    safe = re.sub(r'[<>:"/\\|?*]', "", title).strip()
    safe = re.sub(r"\s+", "_", safe)
    if not safe:
        safe = "untitled"
    return safe[:_MAX_TITLE_LEN]


import re as _re
_BVID_RE = _re.compile(r"^BV[A-Za-z0-9]{10,12}$")


def _cover_path(bvid: str, title: str = "") -> str:
    if not _BVID_RE.match(bvid):
        raise ValueError(f"无效的 BV 号: {bvid!r}")
    if title:
        return os.path.join(COVER_DIR, f"{bvid}_{_sanitize(title)}.jpg")
    return os.path.join(COVER_DIR, f"{bvid}.jpg")


def _md5_path(bvid: str, title: str = "") -> str:
    if not _BVID_RE.match(bvid):
        raise ValueError(f"无效的 BV 号: {bvid!r}")
    if title:
        return os.path.join(COVER_DIR, f"{bvid}_{_sanitize(title)}.jpg.md5")
    return os.path.join(COVER_DIR, f"{bvid}.jpg.md5")


def _compute_md5(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def _read_md5(bvid: str, title: str = "") -> str | None:
    """读取本地保存的 MD5 值（优先按标题查找，回退无标题版本）"""
    candidates = [_md5_path(bvid, title), _md5_path(bvid)]
    if title:
        # 只有给定标题时才插入带标题路径到首位
        pass  # candidates 顺序已正确
    for path in candidates:
        try:
            with open(path, "r") as f:
                return f.read().strip()
        except (FileNotFoundError, OSError):
            continue
    return None


def _write_md5(bvid: str, md5: str, title: str = "") -> None:
    """持久化 MD5 值"""
    try:
        with open(_md5_path(bvid, title), "w") as f:
            f.write(md5)
    except OSError as e:
        logger.warning("写入封面 MD5 失败 %s: %s", bvid, e)


def save_cover(bvid: str, image_data: bytes, title: str = "") -> str | None:
    """保存封面图片并记录 MD5，返回保存路径"""
    try:
        md5 = _compute_md5(image_data)
        path = _cover_path(bvid, title)
        with open(path, "wb") as f:
            f.write(image_data)
        _write_md5(bvid, md5, title)
        # 如果有旧格式文件，删除它
        if title:
            old = _cover_path(bvid)
            if os.path.isfile(old):
                os.remove(old)
                old_md5 = _md5_path(bvid)
                if os.path.isfile(old_md5):
                    os.remove(old_md5)
        logger.debug("封面已保存 %s (%s)", path, md5[:8])
        return path
    except OSError as e:
        logger.warning("保存封面失败 %s: %s", bvid, e)
        return None


def get_valid_cover(bvid: str, title: str = "") -> str | None:
    """获取本地有效封面路径，若丢失或 MD5 不匹配则返回 None"""
    path = _cover_path(bvid, title)
    if not os.path.isfile(path):
        # 尝试旧格式（无标题）
        if title:
            alt = _cover_path(bvid)
            if os.path.isfile(alt):
                path = alt
            else:
                return None
        else:
            return None
    try:
        with open(path, "rb") as f:
            data = f.read()
        expected = _read_md5(bvid, title)
        if expected is None:
            return path
        if _compute_md5(data) == expected:
            return path
        logger.info("封面损坏（MD5 不匹配），将重新下载 %s", bvid)
        os.remove(path)
    except OSError as e:
        logger.warning("读取封面失败 %s: %s", bvid, e)
    return None
