"""Path role contracts for the data layout baseline."""

import os

from core.database import data_layout
from utils import project_path


def test_data_layout_roles_resolve_from_project_root():
    bvid = "BV1test"
    assert data_layout.active_root() == project_path("core", "data")
    assert data_layout.backup_root() == project_path("data")
    assert data_layout.active_central() == project_path("core", "data", "bilibili_monitor.db")
    assert data_layout.backup_central() == project_path("data", "bilibili_monitor.db")
    assert data_layout.active_video(bvid) == project_path("core", "data", bvid, f"{bvid}.db")
    assert data_layout.mirror_video(bvid) == project_path("data", bvid, f"{bvid}.db")
    assert data_layout.viewer_db(bvid, data_layout.ACTIVE_ROOT) == os.path.join(
        data_layout.ACTIVE_ROOT, bvid, "viewercount.db"
    )
