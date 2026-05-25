"""Tests for utils/time_utils.py"""
import time
from datetime import datetime
import pytest
from utils.time_utils import normalize_timestamp, safe_timestamp, safe_datetime


class TestNormalizeTimestamp:
    def test_from_datetime(self):
        dt = datetime(2025, 6, 1, 12, 0, 0)
        result_dt, result_ts, result_str = normalize_timestamp(dt)
        assert result_dt == dt
        assert isinstance(result_ts, float)
        assert result_str == "2025-06-01 12:00:00"

    def test_from_float(self):
        ts = 1700000000.0
        result_dt, result_ts, result_str = normalize_timestamp(ts)
        assert result_ts == ts
        assert isinstance(result_dt, datetime)
        assert isinstance(result_str, str)

    def test_from_int(self):
        ts = 1700000000
        result_dt, result_ts, result_str = normalize_timestamp(ts)
        assert result_ts == float(ts)

    def test_from_iso_string(self):
        iso = "2025-06-01T12:00:00"
        result_dt, result_ts, result_str = normalize_timestamp(iso)
        assert result_dt.year == 2025
        assert result_dt.month == 6
        assert result_dt.day == 1

    def test_from_datetime_string(self):
        s = "2025-06-01 12:00:00"
        result_dt, result_ts, result_str = normalize_timestamp(s)
        assert result_dt.year == 2025

    def test_invalid_type_raises(self):
        with pytest.raises(TypeError, match="不支持的时间戳类型"):
            normalize_timestamp([1, 2, 3])

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            normalize_timestamp("not-a-timestamp")


class TestSafeTimestamp:
    def test_from_float(self):
        ts = 1700000000.5
        assert safe_timestamp(ts) == ts

    def test_from_int(self):
        assert safe_timestamp(1700000000) == 1700000000.0

    def test_from_datetime(self):
        dt = datetime(2025, 1, 1)
        result = safe_timestamp(dt)
        assert isinstance(result, float)
        assert result > 0

    def test_from_string(self):
        result = safe_timestamp("2025-01-01T00:00:00")
        assert isinstance(result, float)
        assert result > 0


class TestSafeDatetime:
    def test_from_datetime(self):
        dt = datetime(2025, 6, 1)
        assert safe_datetime(dt) is dt

    def test_from_float(self):
        result = safe_datetime(1700000000.0)
        assert isinstance(result, datetime)

    def test_from_string(self):
        result = safe_datetime("2025-06-01T12:00:00")
        assert isinstance(result, datetime)


class TestEdgeCases:
    def test_near_zero_timestamp(self):
        dt, ts, s = normalize_timestamp(0.0)
        assert ts == 0.0
        assert dt.year == 1970

    def test_large_timestamp(self):
        future = 4102444800.0  # 2100-01-01
        dt, ts, s = normalize_timestamp(future)
        assert dt.year == 2100
