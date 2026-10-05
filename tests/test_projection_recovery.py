"""B5-b reconstruction facts and idempotency-key contract tests."""

from pathlib import Path

import pytest

from core.database.central_db import Database


@pytest.mark.xfail(strict=True, reason="B5-b 前中央独有表无权威来源")
def test_central_only_streams_cannot_currently_rebuild_from_video_data(tmp_path) -> None:
    central_path = tmp_path / "central.db"
    database = Database(str(central_path))
    try:
        assert database.sync_prediction_ensemble("BV1", "2026-10-05 12:00:00", {"prediction": 1})
        assert database.sync_algorithm_coherence("BV1", "2026-10-05 12:00:00", [("algo", 0.5)])
        assert database.upsert_milestone("BV1", "1周", {"view_count": 1})
    finally:
        database.close()

    central_path.unlink()
    rebuilt = Database(str(central_path))
    try:
        counts = [
            rebuilt._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("prediction_ensemble", "algorithm_coherence", "video_milestones")
        ]
        assert counts == [1, 1, 1]
    finally:
        rebuilt.close()


def test_projection_design_declares_existing_prediction_idempotency_key() -> None:
    design = Path("docs/b5b_projection_design.md").read_text(encoding="utf-8")
    assert "`(bvid, algorithm, target_threshold)`" in design
    assert "idx_central_predict_unique" in Path("core/database/central_schema.py").read_text(encoding="utf-8")
