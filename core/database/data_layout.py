"""Named filesystem roles for the current multi-copy SQLite layout.

This module only resolves paths.  It deliberately does not open databases,
create directories, or select a read/write routing policy.
"""

import os

from config import DATA_DIR
from utils import project_path

CENTRAL_DB_FILENAME = "bilibili_monitor.db"

# The active roots contain the current authoritative per-video detail and the
# central projection.  The backup root contains mirrored video detail and the
# backup central snapshot used by legacy UI readers.
ACTIVE_ROOT = project_path("core", "data")
BACKUP_ROOT = DATA_DIR

DATA_ROLE_DESCRIPTIONS = {
    "active_root": "活跃存储根：权威视频明细与活跃中央投影",
    "backup_root": "备份存储根：镜像视频明细与备份中央快照",
    "active_central": "活跃中央投影库",
    "backup_central": "备份中央快照库",
    "active_video": "权威视频明细库",
    "mirror_video": "视频明细镜像库",
    "viewer_db": "视频在线人数附属快照库",
}


def active_root() -> str:
    """Return the root containing active authoritative video detail."""
    return ACTIVE_ROOT


def backup_root() -> str:
    """Return the root containing legacy backup and mirror copies."""
    return BACKUP_ROOT


def mirror_video_root(bvid: str) -> str:
    """Return one BVID's mirror directory below the backup root."""
    return os.path.join(BACKUP_ROOT, bvid)


def active_central() -> str:
    """Return the active central projection database path."""
    return os.path.join(ACTIVE_ROOT, CENTRAL_DB_FILENAME)


def backup_central() -> str:
    """Return the backup central snapshot database path."""
    return os.path.join(BACKUP_ROOT, CENTRAL_DB_FILENAME)


def active_video(bvid: str) -> str:
    """Return a BVID's authoritative active detail database path."""
    return os.path.join(ACTIVE_ROOT, bvid, f"{bvid}.db")


def mirror_video(bvid: str) -> str:
    """Return a BVID's mirrored detail database path."""
    return os.path.join(mirror_video_root(bvid), f"{bvid}.db")


def viewer_db(bvid: str, root: str) -> str:
    """Return a BVID's viewer-count snapshot path under an explicit root."""
    return os.path.join(root, bvid, "viewercount.db")
