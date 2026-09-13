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


class TestOnlineLearnerHedge:
    """`OnlineLearner`: Hedge 权重更新契约（集成权重的核心）。"""

    @staticmethod
    def _learner(names, warmup=5):
        from algorithms.online_learner import OnlineLearner

        return OnlineLearner(list(names), warmup=warmup)

    def test_cold_start_weights_uniform_and_normalized(self):
        learner = self._learner(["a", "b", "c"])
        weights = learner.get_weights()
        assert set(weights) == {"a", "b", "c"}
        assert sum(weights.values()) == pytest.approx(1.0)
        assert len(set(round(w, 6) for w in weights.values())) == 1, "冷启动权重应均匀"

    def test_unregistered_or_nonpositive_actual_is_skipped(self):
        learner = self._learner(["a"])
        learner.update("not_registered", predicted=1.0, actual=2.0)  # 不应抛异常
        learner.update("a", predicted=100.0, actual=0.0)  # actual<=0 跳过
        learner.update("a", predicted=100.0, actual=-5.0)
        stats = learner.get_algorithm_stats()
        assert stats["a"]["error_count"] == 0, "非法更新不应计入样本"

    def test_better_algorithm_gains_weight_after_warmup(self):
        learner = self._learner(["good", "bad"], warmup=3)
        for _ in range(8):
            learner.update("good", predicted=1000.0, actual=1001.0)  # 极小相对误差
            learner.update("bad", predicted=1000.0, actual=5000.0)  # 极大相对误差
        weights = learner.get_weights()
        assert weights["good"] > weights["bad"], f"Hedge 应奖励表现好的算法: {weights}"
        assert weights["bad"] >= learner.min_weight * 0.5, "min_weight 保护不应被完全淘汰"
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_register_unregister_and_remove_by_prefix(self):
        learner = self._learner(["BV1x/_weighted"])
        learner.register("algo_a")
        learner.register("algo_a")  # 幂等
        assert "algo_a" in learner.get_weights()
        learner.unregister("algo_a")
        assert "algo_a" not in learner.get_weights()

        learner.register("BV2y/linear")
        learner.register("BV2y/exponential")
        learner.remove_by_prefix("BV2y/")
        assert not any(k.startswith("BV2y/") for k in learner.get_weights())

    def test_save_load_roundtrip(self, tmp_path):
        learner = self._learner(["a", "b"], warmup=1)
        for _ in range(4):
            learner.update("a", predicted=100.0, actual=101.0)
            learner.update("b", predicted=100.0, actual=900.0)
        path = tmp_path / "learner.json"
        learner.save(str(path))
        assert path.is_file()

        restored = self._learner(["a", "b"], warmup=1)
        restored.load(str(path))
        assert restored.get_weights() == pytest.approx(learner.get_weights())

    def test_global_algorithm_scores_after_samples(self):
        learner = self._learner(["a", "b"], warmup=1)
        for _ in range(5):
            learner.update("a", predicted=100.0, actual=100.0)
            learner.update("b", predicted=100.0, actual=400.0)
        scores = learner.get_global_algorithm_scores(min_samples=2)
        assert isinstance(scores, dict)
        assert "a" in scores and "b" in scores
        assert scores["a"] > scores["b"], "准确率更高的算法应有更高全局分"


class TestPrepareVideoData:
    """`AlgorithmRegistry._prepare_video_data`: 历史统一转换 + 派生特征缓存键。

    注意：`_derived_cache` / `_cache_lock` 定义在组合类 AlgorithmRegistry 上
    （mixin 单独使用不完整），故这里按真实消费者路径调用。
    """

    @staticmethod
    def _history(n=20, start=100.0, step=10.0, ts0=1_700_000_000.0, dt=75.0):
        return [(ts0 + dt * i, start + step * i) for i in range(n)]

    def test_returns_expected_contract(self):
        from algorithms.registry import AlgorithmRegistry

        history = self._history()
        data = AlgorithmRegistry._prepare_video_data(history, 290.0, BVID)
        assert isinstance(data, dict)
        assert data["view_count"] == 290.0
        assert data["bvid"] == BVID
        assert data["_sorted"] is True, "history_list 应已按时间升序"
        assert data["velocity"] == data["_velocity"]
        assert data["velocity"] > 0, "递增历史的预计算速度应为正"
        assert isinstance(data["history_data"], list) and len(data["history_data"]) == 20
        assert "timestamp" in data["history_data"][0]
        datetime.strptime(data["timestamp_str"], TS_FMT)  # 规范时间戳格式

    def test_empty_and_single_point_history_do_not_crash(self):
        from algorithms.registry import AlgorithmRegistry

        for history in ([], [(1_700_000_000.0, 100.0)]):
            data = AlgorithmRegistry._prepare_video_data(history, 100.0, BVID)
            assert data["view_count"] == 100.0

    def test_cache_key_includes_content_digest(self):
        """缓存键含内容摘要：长度/当前值相同但内容变化时必须重新计算。"""
        from algorithms.registry import AlgorithmRegistry

        AlgorithmRegistry._derived_cache.clear()
        h1 = self._history()
        AlgorithmRegistry._prepare_video_data(h1, 290.0, BVID)
        size1 = len(AlgorithmRegistry._derived_cache)

        # 同样长度、同样 current_value，但历史内容不同 → 必须产生新缓存条目
        h2 = [(ts, v * 1.5) for ts, v in h1]
        AlgorithmRegistry._prepare_video_data(h2, 290.0, BVID)
        size2 = len(AlgorithmRegistry._derived_cache)
        assert size2 > size1, "内容变化必须产生新的缓存键（避免命中陈旧派生特征）"

        # 完全相同的内容 → 命中缓存，不新增条目
        AlgorithmRegistry._prepare_video_data(h1, 290.0, BVID)
        assert len(AlgorithmRegistry._derived_cache) == size2, "相同内容应命中缓存"


class TestFetchLockScope:
    """DoD#3: 抓取批次的网络 I/O 不得在 `_data_lock` / `_viewers_lock` 持有期间进行。"""

    def test_network_call_happens_outside_locks(self, monkeypatch):
        import threading

        import ui.monitor._service as svc

        class _FakeGui:
            def __init__(self):
                self._data_lock = threading.Lock()
                self._viewers_lock = threading.Lock()
                self.video_dbs = {}

        gui = _FakeGui()
        observed = {}

        def _fake_get_info(g, bvid):
            observed["data_locked"] = g._data_lock.locked()
            observed["viewers_locked"] = g._viewers_lock.locked()
            return None

        monkeypatch.setattr(svc, "_get_video_info", _fake_get_info)
        monkeypatch.setattr(svc, "_log_fetch_route", lambda *a, **k: None)
        monkeypatch.setattr(svc, "_start_danmaku_fetch", lambda *a, **k: None)
        monkeypatch.setattr(svc, "invoke", lambda *a, **k: None)
        monkeypatch.setattr(svc, "_on_fetch_done", lambda *a, **k: None)

        svc._fetch_one_video(gui, BVID, {"view_count": 1})

        assert observed, "网络路径未被调用（测试替身失效）"
        assert observed["data_locked"] is False, "_data_lock 不得在网络 I/O 期间持有"
        assert observed["viewers_locked"] is False, "_viewers_lock 不得在网络 I/O 期间持有"
