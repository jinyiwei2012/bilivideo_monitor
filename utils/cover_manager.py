"""
封面管理器 — 视频封面的本地缓存、MD5 完整性校验、按需重新下载

功能说明：
1. 封面下载后保存到本地 config.COVER_DIR 目录
2. 同时保存对应的 MD5 校验文件 (.md5)
3. 读取封面时自动校验 MD5，发现损坏后删除缓存并返回 None，触发重新下载
4. 文件名格式：{bvid}_{sanitized_title}.jpg（优先）或 {bvid}.jpg（回退）

设计思路：
- 避免每次启动都重新下载封面，减轻 B站 API 压力
- MD5 校验机制确保本地缓存未被损坏或篡改
- 清理标题中的非法文件名字符，防止 Windows 文件系统报错
"""

import hashlib
import logging
import os
import re

from config import COVER_DIR

logger = logging.getLogger(__name__)

# 标题截断的最大长度，过长的标题文件名可能导致 Windows 路径超过 260 字符限制
_MAX_TITLE_LEN = 60


def _sanitize(title: str) -> str:
    """清理标题中的非法文件名字符，并截断到合理长度。

    Windows 文件名不能包含: < > : " / \\ | ? *
    同时将连续空白字符替换为单个下划线。

    Args:
        title: 原始视频标题

    Returns:
        str: 清理后的安全文件名（不含扩展名），如 "Python教程_从入门到精通"
    """
    safe = re.sub(r'[<>:"/\\|?*]', "", title).strip()
    safe = re.sub(r"\s+", "_", safe)
    if not safe:
        safe = "untitled"  # 标题全部被清理后使用默认名
    return safe[:_MAX_TITLE_LEN]


import re as _re

# BV 号正则：必须以 "BV" 开头，后跟 10-12 位字母或数字
_BVID_RE = _re.compile(r"^BV[A-Za-z0-9]{10,12}$")


def _cover_path(bvid: str, title: str = "") -> str:
    """构造封面图片的本地路径。

    优先使用包含标题的文件名（便于人工区分），无标题时使用纯 BV 号命名。

    Args:
        bvid: 视频 BV 号
        title: 视频标题（可选）

    Returns:
        str: 封面图片的完整本地路径，如 "data/covers/BV1xx_tutorial.jpg"

    Raises:
        ValueError: BV 号格式无效时抛出
    """
    if not _BVID_RE.match(bvid):
        raise ValueError(f"无效的 BV 号: {bvid!r}")
    if title:
        return os.path.join(COVER_DIR, f"{bvid}_{_sanitize(title)}.jpg")
    return os.path.join(COVER_DIR, f"{bvid}.jpg")


def _md5_path(bvid: str, title: str = "") -> str:
    """构造封面 MD5 校验文件的本地路径。

    每张封面对应一个 .md5 文件，存储原始数据的 MD5 哈希值，
    用于后续读取时做完整性校验。

    Args:
        bvid: 视频 BV 号
        title: 视频标题（可选）

    Returns:
        str: MD5 文件的完整本地路径，如 "data/covers/BV1xx_tutorial.jpg.md5"

    Raises:
        ValueError: BV 号格式无效时抛出
    """
    if not _BVID_RE.match(bvid):
        raise ValueError(f"无效的 BV 号: {bvid!r}")
    if title:
        return os.path.join(COVER_DIR, f"{bvid}_{_sanitize(title)}.jpg.md5")
    return os.path.join(COVER_DIR, f"{bvid}.jpg.md5")


def _compute_md5(data: bytes) -> str:
    """计算数据的 MD5 哈希值（用于完整性校验，非加密场景）。

    Args:
        data: 原始字节数据（封面图片）

    Returns:
        str: 16 进制 MD5 哈希字符串，如 "a1b2c3d4..."
    """
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def _read_md5(bvid: str, title: str = "") -> str | None:
    """读取本地保存的 MD5 值。

    查找策略：优先按标题查找 → 回退到无标题版本。

    Args:
        bvid: 视频 BV 号
        title: 视频标题（可选）

    Returns:
        str | None: 保存的 MD5 值，文件不存在时返回 None
    """
    candidates = [_md5_path(bvid, title), _md5_path(bvid)]
    for path in candidates:
        try:
            with open(path, "r") as f:
                return f.read().strip()
        except (FileNotFoundError, OSError):
            continue
    return None


def _write_md5(bvid: str, md5: str, title: str = "") -> None:
    """持久化 MD5 值到磁盘。

    Args:
        bvid: 视频 BV 号
        md5: MD5 哈希字符串
        title: 视频标题（可选）
    """
    try:
        with open(_md5_path(bvid, title), "w") as f:
            f.write(md5)
    except OSError as e:
        logger.warning("写入封面 MD5 失败 %s: %s", bvid, e)


def save_cover(bvid: str, image_data: bytes, title: str = "") -> str | None:
    """保存封面图片到本地并记录 MD5 校验值。

    保存成功后会同时创建 .jpg 和 .jpg.md5 两个文件。
    如果存在旧格式文件（纯 BV 号命名），会自动清理。

    Args:
        bvid: 视频 BV 号
        image_data: 封面图片的原始字节数据
        title: 视频标题（可选，用于生成易读文件名）

    Returns:
        str | None: 保存成功的文件路径，失败返回 None
    """
    try:
        md5 = _compute_md5(image_data)
        path = _cover_path(bvid, title)
        with open(path, "wb") as f:
            f.write(image_data)
        _write_md5(bvid, md5, title)
        # 如果提供了标题，清理旧的无标题格式文件以避免冗余
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
    """获取本地有效封面路径。

    有效性判断标准：
    1. 封面图片文件存在
    2. 对应的 MD5 校验文件存在
    3. 图片文件的实际 MD5 与校验值一致

    如果 MD5 不匹配（文件已损坏），自动删除缓存并返回 None，
    外部调用者收到 None 后应重新下载封面。

    Args:
        bvid: 视频 BV 号
        title: 视频标题（可选）

    Returns:
        str | None: 有效封面图片的路径，无效或不存在时返回 None
    """
    path = _cover_path(bvid, title)
    if not os.path.isfile(path):
        # 当前路径不存在，尝试无标题的旧格式回退
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
        # 如果 MD5 文件不存在，无法校验，直接返回路径（尽量保留缓存）
        if expected is None:
            return path
        if _compute_md5(data) == expected:
            return path
        # MD5 不匹配说明文件已损坏，删除后返回 None
        logger.info("封面损坏（MD5 不匹配），将重新下载 %s", bvid)
        os.remove(path)
    except OSError as e:
        logger.warning("读取封面失败 %s: %s", bvid, e)
    return None
