"""M3.9 测试补充：训练目标构建(A+B 双尺度)、稳健增量、异常检测器契约。

覆盖计划中标注为高风险的逻辑：
- `_robust_increments` 的 MAD 补量剪除
- `VideoTimeSeriesDataset` 的 A+B 双尺度目标（短期稳健增量 ⊕ 长期平均速率）与共享缩放器
- `AnomalyDetector` 的分级检测器契约（返回 None 或合法 AlertHit）
"""

import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pytest

BVID = "BV1GJ411x7h7"
FEATURES = ("view_count", "like_count", "coin_count", "favorite_count", "share_count")
TS_FMT = "%Y-%m-%d %H:%M:%S"


def _make_video_db(tmp_path, bvid, views, step_seconds=75):
    """在 tmp_path 下建立 <bvid>/<bvid>.db，写入 monitor_records。"""
    vdir = tmp_path / bvid
    vdir.mkdir(exist_ok=True)
    conn = sqlite3.connect(vdir / f"{bvid}.db")
    cols = ", ".join(f"{c} INTEGER" for c in FEATURES)
    conn.execute(f"CREATE TABLE monitor_records ({cols}, timestamp TEXT)")
    base = datetime(2026, 1, 1, 0, 0, 0)
    for i, v in enumerate(views):
        vals = [v if c == "view_count" else int(v // 10) for c in FEATURES]
        ts = (base + timedelta(seconds=step_seconds * i)).strftime(TS_FMT)
        conn.execute(
            f"INSERT INTO monitor_records VALUES ({','.join('?' * len(FEATURES))}, ?)",
            (*vals, ts),
        )
    conn.commit()
    conn.close()
    return tmp_path


class TestRobustIncrements:
    """`_robust_increments`: 累计值 → 稳健增量（MAD 剪除一次性补量）。"""

    def test_linear_series_preserved(self):
        from algorithms.training.dataset import _robust_increments

        target = np.array([100, 110, 120, 130, 140], dtype=np.float32)
        inc = _robust_increments(target)
        assert inc[0] == 0.0, "首位增量语义为 0"
        assert list(inc[1:]) == [10.0, 10.0, 10.0, 10.0]

    def test_short_series_unchanged(self):
        from algorithms.training.dataset import _robust_increments

        target = np.array([100, 150], dtype=np.float32)
        inc = _robust_increments(target)
        assert list(inc) == [0.0, 50.0]

    def test_catch_up_spike_clipped_to_neighbourhood_median(self):
        from algorithms.training.dataset import _robust_increments

        # 平稳步进 + 单次一次性补量(+1000)
        incs = [10, 12, 9, 11, 10, 1000, 10, 11, 9, 12, 10, 11]
        target = np.cumsum([100] + incs).astype(np.float32)
        vel = _robust_increments(target)

        assert vel[1] == 10.0 and vel[2] == 12.0, "非线性段不应被改动"
        assert vel[5] == 10.0, "补量点之前不受污染"
        assert vel[6] < 1000.0, "补量尖峰必须被剪除"
        assert 5.0 <= vel[6] <= 20.0, f"应替换为近端中位, 实际 {vel[6]}"

    def test_zero_mad_means_no_clipping(self):
        """所有增量相同时 MAD=0 → 不触发剪除（已知边界，记录当前契约）。"""
        from algorithms.training.dataset import _robust_increments

        incs = [10] * 5 + [1000] + [10] * 5
        target = np.cumsum([100] + incs).astype(np.float32)
        vel = _robust_increments(target)
        assert vel[6] == 1000.0, "MAD 为 0 时不做剪除（守行为，不修改实现）"


class TestDatasetABTargets:
    """`VideoTimeSeriesDataset`: A+B 双尺度目标契约。"""

    @pytest.fixture(autouse=True)
    def _need_torch(self):
        pytest.importorskip("torch")

    def _build(self, tmp_path, views, **kwargs):
        from algorithms.training.dataset import VideoTimeSeriesDataset

        _make_video_db(tmp_path, BVID, views)
        kwargs.setdefault("bvids", [BVID])
        kwargs.setdefault("data_root", str(tmp_path))
        kwargs.setdefault("window", 10)
        kwargs.setdefault("horizon", 3)
        return VideoTimeSeriesDataset(**kwargs)

    def test_target_shape_is_horizon_plus_one(self, tmp_path):
        views = [100 + 10 * i for i in range(40)]
        ds = self._build(tmp_path, views, normalize=False)
        assert ds.n_videos() == 1
        assert len(ds) == 40 - 10 - 3 + 1
        x, y = ds[0]
        assert tuple(x.shape) == (10, ds.n_features())
        assert ds.n_features() == len(FEATURES) + 5, "5 原始 + 5 衍生"
        assert tuple(y.shape) == (3 + 1,), "y = [horizon 步增量 ⊕ 1 长期速率]"

    def test_linear_series_short_and_long_segments_consistent(self, tmp_path):
        """线性序列下短期增量与长期平均速率同为 10/步（样本长期窗完全落在序列内部）。"""
        views = [100 + 10 * i for i in range(100)]
        ds = self._build(tmp_path, views, normalize=False)
        _, y = ds[0]
        assert list(y[:3]) == pytest.approx([10.0, 10.0, 10.0])
        assert float(y[3]) == pytest.approx(10.0), "长期段 = 未来 long_window 平均速率"

    def test_tail_zero_pad_dilutes_long_target(self, tmp_path):
        """记录当前契约：靠近序列尾部时 long_rate 补 0 会被均值纳入，拉低长期目标。

        线性序列 N=40, window=10, horizon=3, long_window=48 → 样本 0 的长期窗为
        long_rate[11:40]，其中最后一位 (index 39) 为补 0，故均值 = 280/29 ≈ 9.655，
        而非理想的 10/步。此处锁定现状（不修改实现），提醒后续如需修正应单独评估。
        """
        views = [100 + 10 * i for i in range(40)]
        ds = self._build(tmp_path, views, normalize=False)
        _, y = ds[0]
        assert float(y[3]) == pytest.approx(280.0 / 29.0, rel=1e-5)

    def test_shared_scaler_between_short_and_long_segments(self, tmp_path):
        """长期段与短期段必须共用同一缩放器（否则推理端无法反归一化）。"""
        from algorithms.training.dataset import _robust_increments

        views = [100 + 10 * i for i in range(40)]
        ds = self._build(tmp_path, views, normalize=True, long_window=12)
        _, y = ds[0]

        target = np.array(views, dtype=np.float32)
        vel = _robust_increments(target)
        v_mean, v_std = float(np.mean(vel)), float(np.std(vel))
        if v_std < 1e-8:
            v_std = 1.0
        expected = (10.0 - v_mean) / v_std
        assert float(y[3]) == pytest.approx(expected, rel=1e-5)
        assert float(y[0]) == pytest.approx(expected, rel=1e-5), "两段同尺度"

    def test_insufficient_records_video_skipped(self, tmp_path):
        ds = self._build(tmp_path, [100 + 10 * i for i in range(5)], normalize=False)
        assert ds.n_videos() == 0 and len(ds) == 0

    def test_target_feature_must_be_in_features(self, tmp_path):
        from algorithms.training.dataset import VideoTimeSeriesDataset

        _make_video_db(tmp_path, BVID, [100 + 10 * i for i in range(40)])
        with pytest.raises(ValueError):
            VideoTimeSeriesDataset(bvids=[BVID], data_root=str(tmp_path), target_feature="not_a_column")


class TestAnomalyDetectorScored:
    """`AnomalyDetector`: 分级检测器契约。"""

    @staticmethod
    def _records(n=12, growth=0.0, step_minutes=5):
        base = datetime(2026, 1, 1, 0, 0, 0)
        out = []
        v = 10000.0
        for i in range(n):
            out.append(
                {
                    "timestamp": (base + timedelta(minutes=step_minutes * i)).strftime(TS_FMT),
                    "view_count": int(v),
                }
            )
            v += growth
        return out

    @pytest.mark.parametrize(
        "confidence,expected", [(0.9, "high"), (0.75, "high"), (0.6, "medium"), (0.5, "medium"), (0.2, "low")]
    )
    def test_alert_hit_level_derived_from_confidence(self, confidence, expected):
        from core.smart_alert import AlertHit

        hit = AlertHit(key="k", message="m", confidence=confidence)
        assert hit.level == expected

    def test_scored_detectors_return_none_or_valid_hit(self):
        from core.smart_alert import AlertHit, AnomalyDetector

        flat = self._records(n=12, growth=0.0)
        spiky = self._records(n=5, growth=0.0) + self._records(n=7, growth=50000.0)
        for records in (flat, spiky):
            for name in (
                "detect_growth_spike_scored",
                "detect_trend_reversal_scored",
                "detect_stall_scored",
                "detect_viewer_surge_scored",
                "detect_night_surge_scored",
                "detect_viewer_crash_scored",
            ):
                hit = getattr(AnomalyDetector, name)(records)
                assert hit is None or isinstance(hit, AlertHit), f"{name} 返回类型非法: {hit!r}"
                if isinstance(hit, AlertHit):
                    assert 0.0 <= hit.confidence <= 1.0
                    assert hit.level in ("high", "medium", "low")

    def test_too_few_records_no_hit(self):
        from core.smart_alert import AnomalyDetector

        assert AnomalyDetector.detect_growth_spike_scored(self._records(n=4, growth=10.0)) is None

    def test_flat_series_triggers_no_growth_spike(self):
        from core.smart_alert import AnomalyDetector

        assert AnomalyDetector.detect_growth_spike_scored(self._records(n=12, growth=0.0)) is None

    def test_detect_all_scored_returns_list_of_hits(self):
        from core.smart_alert import AlertHit, AnomalyDetector

        hits = AnomalyDetector.detect_all_scored(self._records(n=12, growth=0.0), BVID, None, None)
        assert isinstance(hits, list)
        assert all(isinstance(h, AlertHit) for h in hits)
        assert all(h.key for h in hits), "每个告警必须有 key 用于去重"
