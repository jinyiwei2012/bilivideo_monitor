"""Projection reconstruction and replay regression tests."""

from pathlib import Path

from core.database.central_db import Database
from core.database.projector import CentralProjector
from core.database.video_db import VideoDatabase


def test_projector_rebuilds_authority_streams_idempotently(tmp_path) -> None:
    bvid = "BV1xx411c7mD"
    video = VideoDatabase(bvid, str(tmp_path / "video"))
    central = Database(str(tmp_path / "central.db"))
    try:
        assert video.save_prediction_cycle(
            "2026-10-05 12:00:00",
            [],
            {
                "prediction": 123,
                "confidence": 0.8,
                "valid_algos": 2,
                "total_algos": 3,
                "prediction_interval": {"lower": 100, "upper": 150},
                "interval_width_ratio": 0.4,
                "surge_correction_applied": True,
                "surge_magnitude": 1.5,
                "surge_type": "burst",
            },
            [("linear", 0.98765)],
        )
        assert video.upsert_milestone(
            "1周", {"view_count": 1000, "like_count": 20, "note": "recovered", "recorded_at": "2026-10-05 12:01:00"}
        )
        projector = CentralProjector(central)
        assert projector.project_video(video).delivered == 3
        ensemble = central._conn.execute(
            "SELECT prediction, surge_correction_applied FROM prediction_ensemble"
        ).fetchone()
        coherence = central._conn.execute("SELECT algorithm, coherence FROM algorithm_coherence").fetchone()
        milestone = central._conn.execute("SELECT period, view_count, note FROM video_milestones").fetchone()
        assert tuple(ensemble) == (123, 1)
        assert tuple(coherence) == ("linear", 0.9877)
        assert tuple(milestone) == ("1周", 1000, "recovered")
        counts_before = [
            central._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("prediction_ensemble", "algorithm_coherence", "video_milestones")
        ]
        assert projector.project_video(video).delivered == 0
        counts_after = [
            central._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("prediction_ensemble", "algorithm_coherence", "video_milestones")
        ]
        assert counts_after == counts_before
    finally:
        video.close()
        central.close()


def test_projection_design_declares_existing_prediction_idempotency_key() -> None:
    design = Path("docs/b5b_projection_design.md").read_text(encoding="utf-8")
    assert "`(bvid, algorithm, target_threshold)`" in design
    assert "idx_central_predict_unique" in Path("core/database/central_schema.py").read_text(encoding="utf-8")
