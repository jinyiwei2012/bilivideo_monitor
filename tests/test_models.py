"""Tests for core/database/models.py"""
import pytest
from core.database.models import (
    VideoInfo,
    MonitorRecord,
    PredictionRecord,
    _validate_bvid,
)


class TestValidateBvid:
    def test_valid_bvid(self):
        assert _validate_bvid("BV1GJ411x7hQ") == "BV1GJ411x7hQ"
        assert _validate_bvid("BV1xx411c7mD") == "BV1xx411c7mD"

    def test_invalid_bvid_too_short(self):
        with pytest.raises(ValueError, match="无效的 BV 号"):
            _validate_bvid("BV1")

    def test_invalid_bvid_no_prefix(self):
        with pytest.raises(ValueError):
            _validate_bvid("AB1234567890")

    def test_invalid_bvid_special_chars(self):
        with pytest.raises(ValueError):
            _validate_bvid("BV1!@#$%^&*()")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            _validate_bvid("")

    def test_path_traversal_attempt(self):
        with pytest.raises(ValueError):
            _validate_bvid("../etc/passwd")


class TestVideoInfo:
    def test_default_values(self):
        v = VideoInfo(bvid="BV1xx411c7mD", title="")
        assert v.view_count == 0
        assert v.like_count == 0
        assert v.coin_count == 0
        assert v.share_count == 0
        assert v.favorite_count == 0
        assert v.danmaku_count == 0
        assert v.reply_count == 0
        assert v.cover_path == ""
        assert v.like_view_ratio == 0.0

    def test_with_full_data(self):
        v = VideoInfo(
            bvid="BV1GJ411x7hQ",
            title="Test Video",
            view_count=10000,
            like_count=500,
            coin_count=100,
            share_count=50,
            favorite_count=200,
            owner_name="TestCreator",
            owner_id=12345,
        )
        assert v.title == "Test Video"
        assert v.view_count == 10000
        assert v.owner_name == "TestCreator"


class TestMonitorRecord:
    def test_required_fields(self):
        r = MonitorRecord(
            bvid="BV1xx411c7mD",
            timestamp="2025-06-01 12:00:00",
            view_count=5000,
            like_count=100,
            coin_count=10,
            share_count=5,
            favorite_count=20,
            danmaku_count=50,
            reply_count=10,
        )
        assert r.bvid == "BV1xx411c7mD"
        assert r.view_count == 5000
        assert r.like_view_ratio == 0.0

    def test_optional_fields(self):
        r = MonitorRecord(
            bvid="BV1xx411c7mD",
            timestamp="2025-06-01 12:00:00",
            view_count=5000,
            like_count=100,
            coin_count=10,
            share_count=5,
            favorite_count=20,
            danmaku_count=50,
            reply_count=10,
            viewers_total=500,
            like_view_ratio=0.02,
        )
        assert r.viewers_total == 500
        assert r.like_view_ratio == 0.02


class TestPredictionRecord:
    def test_required_fields(self):
        p = PredictionRecord(
            bvid="BV1xx411c7mD",
            algorithm="线性速度",
            algorithm_id="linear_velocity",
            target_threshold=100000,
            predicted_seconds=86400,
            predicted_time="2025-06-02 12:00:00",
            confidence=0.85,
            current_views=5000,
        )
        assert p.bvid == "BV1xx411c7mD"
        assert p.predicted_seconds == 86400
        assert p.confidence == 0.85

    def test_defaults(self):
        p = PredictionRecord(
            bvid="BV1xx411c7mD",
            algorithm="test",
            algorithm_id="test",
            target_threshold=100000,
            predicted_seconds=0,
            predicted_time="",
            confidence=0.0,
            current_views=0,
        )
        assert p.metadata == ""
        assert p.predicted_hours == 0.0
        assert p.current_velocity == 0.0
        assert p.is_reached is False
        assert p.error_rate == 0.0
