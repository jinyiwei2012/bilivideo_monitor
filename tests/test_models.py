"""
测试 core/database/models.py — 数据库模型

测试范围：
- _validate_bvid: BV 号格式校验（合法、非法、路径穿越攻击）
- VideoInfo: 数据类默认值和完整字段
- MonitorRecord: 监控记录的必填和可选字段
- PredictionRecord: 预测记录的字段和默认值
"""

import pytest
from core.database.models import (
    VideoInfo,
    MonitorRecord,
    PredictionRecord,
    _validate_bvid,
)


class TestValidateBvid:
    """测试 BV 号校验函数"""

    def test_valid_bvid(self):
        """合法 BV 号应通过校验"""
        assert _validate_bvid("BV1GJ411x7hQ") == "BV1GJ411x7hQ"
        assert _validate_bvid("BV1xx411c7mD") == "BV1xx411c7mD"

    def test_invalid_bvid_too_short(self):
        """过短的 BV 号应触发异常"""
        with pytest.raises(ValueError, match="无效的 BV 号"):
            _validate_bvid("BV1")

    def test_invalid_bvid_no_prefix(self):
        """缺少 BV 前缀应触发异常"""
        with pytest.raises(ValueError):
            _validate_bvid("AB1234567890")

    def test_invalid_bvid_special_chars(self):
        """包含特殊字符应触发异常"""
        with pytest.raises(ValueError):
            _validate_bvid("BV1!@#$%^&*()")

    def test_empty_string(self):
        """空字符串应触发异常"""
        with pytest.raises(ValueError):
            _validate_bvid("")

    def test_path_traversal_attempt(self):
        """路径穿越攻击尝试应触发异常（防御 ../ 路径注入）"""
        with pytest.raises(ValueError):
            _validate_bvid("../etc/passwd")


class TestVideoInfo:
    """测试 VideoInfo 模型"""

    def test_default_values(self):
        """默认值检查：播放量等字段应初始化为 0"""
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
        """完整数据字段检查：所有字段值应正确保留"""
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
    """测试 MonitorRecord 模型"""

    def test_required_fields(self):
        """必填字段检查：基本字段应正确赋值"""
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
        """可选字段检查：在线人数和点赞率应正确赋值"""
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
    """测试 PredictionRecord 模型"""

    def test_required_fields(self):
        """必填字段检查：核心预测字段应正确赋值"""
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
        """默认值检查：metadata、predicted_hours 等应初始化为合理默认值"""
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
