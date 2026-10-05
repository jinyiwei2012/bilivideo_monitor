"""Source-application packaging contract smoke tests.

These checks exercise runtime contracts needed by the frozen application, but
do not build or validate a PyInstaller executable image.
"""

import os

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"


def test_source_application_packaging_contract(tmp_path):
    """Exercise registry, SQLite, a deterministic predictor, and Qt startup."""
    from PyQt6.QtWidgets import QApplication, QWidget

    from algorithms.models.simple.linear_velocity import LinearVelocityAlgorithm
    from algorithms.registry import AlgorithmRegistry
    from core.database.models import MonitorRecord
    from core.database.video_db import VideoDatabase

    AlgorithmRegistry.initialize()
    assert len(AlgorithmRegistry.get_all_algorithms()) == 137

    database = VideoDatabase("BV1xx411c7mD", base_dir=str(tmp_path))
    try:
        record = MonitorRecord(
            bvid="BV1xx411c7mD",
            timestamp="2026-10-05 12:00:00",
            view_count=140,
            like_count=14,
            coin_count=2,
            share_count=1,
            favorite_count=3,
            danmaku_count=4,
            reply_count=5,
        )
        assert database.add_monitor_record(record)
        records = database.get_all_records()
        assert len(records) == 1
        assert records[0]["view_count"] == 140
    finally:
        database.close()

    history = [{"timestamp": 1_700_000_000 + index * 1_800, "view_count": 100 + index * 10} for index in range(5)]
    prediction = LinearVelocityAlgorithm().predict({"view_count": 140, "history_data": history}, threshold=180)
    assert prediction.predicted_hours == pytest.approx(2.0)

    app = QApplication.instance() or QApplication([])
    widget = QWidget()
    widget.show()
    app.processEvents()
    widget.close()
