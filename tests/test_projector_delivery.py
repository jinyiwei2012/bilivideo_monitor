"""Outbox projector delivery and replay behavior."""

from core.database.central_db import Database
from core.database.models import MonitorRecord
from core.database.projector import CentralProjector
from core.database.video_db import VideoDatabase


def _record(bvid: str, timestamp: str) -> MonitorRecord:
    return MonitorRecord(bvid, timestamp, 10, 2, 1, 1, 1, 1, 1)


def test_projector_delivers_in_order_and_is_idempotent(tmp_path) -> None:
    bvid = "BV1xx411c7mD"
    video = VideoDatabase(bvid, str(tmp_path / "video"))
    central = Database(str(tmp_path / "central.db"))
    try:
        assert video.add_monitor_record(_record(bvid, "2026-01-01 00:00:00"))
        assert video.add_monitor_record(_record(bvid, "2026-01-01 00:01:00"))
        projector = CentralProjector(central)
        assert projector.project_video(video).delivered == 2
        assert central._conn.execute("SELECT COUNT(*) FROM monitor_records").fetchone()[0] == 2
        assert projector.project_video(video).delivered == 0
    finally:
        video.close()
        central.close()
