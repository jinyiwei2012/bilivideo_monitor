"""Projection failure-window delivery tests."""

from core.database.central_db import Database
from core.database.models import MonitorRecord
from core.database.projector import CentralProjector
from core.database.video_db import VideoDatabase


def test_projector_failure_leaves_outbox_pending_for_recovery(tmp_path, monkeypatch) -> None:
    bvid = "BV1xx411c7mD"
    video = VideoDatabase(bvid, str(tmp_path / "video"))
    central = Database(str(tmp_path / "central.db"))
    try:
        assert video.add_monitor_record(MonitorRecord(bvid, "2026-10-05 12:00:00", 10, 1, 1, 1, 1, 1, 1))
        projector = CentralProjector(central)
        monkeypatch.setattr(
            central, "apply_projection_batch", lambda _bvid, _events: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        assert projector.project_video(video).failed == 1
        pending = video._conn.execute("SELECT delivered_at, attempt_count FROM projection_outbox").fetchone()
        assert tuple(pending) == (None, 1)
        monkeypatch.undo()
        assert projector.project_video(video).delivered == 1
        assert video._conn.execute("SELECT delivered_at FROM projection_outbox").fetchone()[0] is not None
    finally:
        video.close()
        central.close()
