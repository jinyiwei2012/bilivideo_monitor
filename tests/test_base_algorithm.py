"""Tests for algorithms/base.py"""

import time
from datetime import datetime
import pytest
from algorithms.base import PredictionResult, BaseAlgorithm


class _ConcreteAlgorithm(BaseAlgorithm):
    """Concrete subclass for testing BaseAlgorithm's helper methods."""

    name = "TestAlgo"
    description = "Test algorithm"
    category = "测试"

    def predict(self, video_data, threshold=100000):
        return make_prediction_result()


def make_prediction_result(**overrides):
    defaults = dict(
        algorithm_name="test_algo",
        algorithm_id="test_algo_id",
        target_threshold=100000,
        predicted_hours=48.0,
        confidence=0.85,
        current_views=5000,
        current_velocity=100.0,
        metadata={},
        timestamp=datetime(2025, 6, 1, 12, 0, 0),
    )
    defaults.update(overrides)
    return PredictionResult(**defaults)


class TestPredictionResult:
    def test_to_dict(self):
        ts = datetime(2025, 6, 1, 12, 0, 0)
        r = make_prediction_result(timestamp=ts)
        d = r.to_dict()
        assert d["algorithm_name"] == "test_algo"
        assert d["target_threshold"] == 100000
        assert d["predicted_hours"] == 48.0
        assert d["confidence"] == 0.85
        assert d["current_views"] == 5000
        assert d["timestamp"] == "2025-06-01T12:00:00"

    def test_to_dict_roundtrip(self):
        r1 = make_prediction_result()
        d = r1.to_dict()
        assert d["algorithm_id"] == "test_algo_id"
        assert isinstance(d["metadata"], dict)

    def test_metadata_preserved(self):
        meta = {"key": "value", "nested": {"a": 1}}
        r = make_prediction_result(metadata=meta)
        assert r.to_dict()["metadata"] == meta


class TestBaseAlgorithmVelocity:
    def setup_method(self):
        self.algo = _ConcreteAlgorithm()

    def test_empty_history(self):
        data = {"history_data": []}
        assert self.algo.calculate_velocity(data) == 0.0

    def test_single_point(self):
        data = {"history_data": [{"view_count": 100, "timestamp": time.time() - 3600}]}
        assert self.algo.calculate_velocity(data) == 0.0

    def test_two_points_positive(self):
        t0 = time.time() - 7200
        t1 = time.time()
        data = {
            "history_data": [
                {"view_count": 100, "timestamp": t0},
                {"view_count": 200, "timestamp": t1},
            ]
        }
        vel = self.algo.calculate_velocity(data)
        assert vel == pytest.approx(50.0, rel=0.1)

    def test_two_points_no_change(self):
        t0 = time.time() - 3600
        t1 = time.time()
        data = {
            "history_data": [
                {"view_count": 100, "timestamp": t0},
                {"view_count": 100, "timestamp": t1},
            ]
        }
        assert self.algo.calculate_velocity(data) == 0.0

    def test_datetime_timestamps(self):
        t0 = datetime.now().timestamp() - 7200
        t1 = datetime.now().timestamp()
        data = {
            "history_data": [
                {"view_count": 0, "timestamp": t0},
                {"view_count": 100, "timestamp": t1},
            ]
        }
        vel = self.algo.calculate_velocity(data)
        assert vel > 0

    def test_decreasing_views_returns_zero(self):
        t0 = time.time() - 3600
        t1 = time.time()
        data = {
            "history_data": [
                {"view_count": 200, "timestamp": t0},
                {"view_count": 100, "timestamp": t1},
            ]
        }
        assert self.algo.calculate_velocity(data) == 0.0


class TestBaseAlgorithmEngagementRate:
    def setup_method(self):
        self.algo = _ConcreteAlgorithm()

    def test_zero_views(self):
        data = {"view_count": 0}
        rate = self.algo.get_engagement_rate(data)
        assert 0 <= rate <= 1

    def test_full_engagement(self):
        data = {"view_count": 100, "like_count": 100}
        rate = self.algo.get_engagement_rate(data)
        assert rate == 1.0

    def test_partial_engagement(self):
        data = {"view_count": 1000, "like_count": 50, "coin_count": 20}
        rate = self.algo.get_engagement_rate(data)
        assert 0 < rate < 1

    def test_no_interaction(self):
        data = {"view_count": 1000}
        assert self.algo.get_engagement_rate(data) == 0.0

    def test_all_interaction_types(self):
        data = {
            "view_count": 1000,
            "like_count": 50,
            "coin_count": 10,
            "favorite_count": 20,
            "share_count": 5,
        }
        rate = self.algo.get_engagement_rate(data)
        assert rate == pytest.approx(0.085, rel=0.01)


class TestBaseAlgorithmQualityScore:
    def setup_method(self):
        self.algo = _ConcreteAlgorithm()

    def test_score_range(self):
        data = {"view_count": 10000, "like_count": 500, "coin_count": 50, "danmaku_count": 100}
        score = self.algo.get_quality_score(data)
        assert 0 <= score <= 1

    def test_zero_views(self):
        data = {"view_count": 0}
        score = self.algo.get_quality_score(data)
        assert 0 <= score <= 1

    def test_high_quality(self):
        data = {
            "view_count": 1000,
            "like_count": 500,
            "coin_count": 200,
            "favorite_count": 100,
            "share_count": 50,
            "danmaku_count": 500,
        }
        score = self.algo.get_quality_score(data)
        assert score > 0.5

    def test_low_quality(self):
        data = {"view_count": 100000, "like_count": 1, "coin_count": 0, "danmaku_count": 0}
        score = self.algo.get_quality_score(data)
        assert score < 0.3


class TestBaseAlgorithmVideoAge:
    def setup_method(self):
        self.algo = _ConcreteAlgorithm()

    def test_no_history_no_timestamp(self):
        data = {}
        assert self.algo.get_video_age_hours(data) == 0.0

    def test_with_history(self):
        t = time.time() - 86400
        data = {
            "history_data": [
                {"view_count": 0, "timestamp": t},
                {"view_count": 100, "timestamp": time.time()},
            ]
        }
        age = self.algo.get_video_age_hours(data)
        assert age == pytest.approx(24.0, rel=0.1)

    def test_with_timestamp_field(self):
        pub_ts = time.time() - 7200
        data = {"timestamp": pub_ts}
        age = self.algo.get_video_age_hours(data)
        assert age == pytest.approx(2.0, rel=0.1)

    def test_with_datetime_timestamp(self):
        pub_dt = datetime.now().timestamp() - 3600
        data = {"timestamp": pub_dt}
        age = self.algo.get_video_age_hours(data)
        assert age == pytest.approx(1.0, rel=0.1)
