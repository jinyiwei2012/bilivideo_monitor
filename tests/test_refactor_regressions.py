"""重构回归测试。

覆盖 M1.8 修复的 3 处 NameError / 闭包失效：
1. algorithms/models/ensemble/bagging_simple.py — `Optional` 未导入
2. algorithms/models/time_series/tbats_simple.py — 未定义 `forecast`（被 except 静默吞掉）
3. ui/settings_notification.py — 闭包在 `except ... as e` 作用域外引用 `e`

这些测试同时作为后续 P0 改动的行为安全网。
"""

import numpy as np
import pytest


def _make_history(n=20):
    """生成 n 个历史点，间隔 1 小时，播放量线性递增。"""
    from datetime import datetime as dt

    base = dt(2026, 1, 1, 0, 0, 0).timestamp()
    return [(base + i * 3600, 1000 + i * 1000) for i in range(n)]


def _make_video_data(history, current_views=20000):
    from datetime import datetime as dt

    history_list = [
        {
            "view_count": v,
            "timestamp": ts,
            "timestamp_str": dt.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
            "datetime": dt.fromtimestamp(ts),
        }
        for ts, v in history
    ]
    return {
        "view_count": current_views,
        "history_data": history_list,
        "timestamp": dt.now(),
        "like_count": current_views // 10,
        "coin_count": current_views // 50,
        "favorite_count": current_views // 20,
        "share_count": current_views // 100,
        "danmaku_count": current_views // 200,
    }


class TestBaggingOptionalNameError:
    """`_RegTree.__init__` 的 `self.tree: Optional[dict] = None` 注解在运行时求值，
    修复前 `Optional` 未导入 → 实例化即 NameError。"""

    def test_regtree_instantiates_and_fits(self):
        from algorithms.models.ensemble.bagging_simple import BaggingSimpleAlgorithm

        algo = BaggingSimpleAlgorithm()
        tree = algo._RegTree(max_depth=3, min_samples=1)  # 修复前：NameError
        X = np.array([[1.0, 2.0], [2.0, 1.0], [3.0, 5.0], [4.0, 3.0]])
        y = np.array([1.0, 2.0, 3.0, 4.0])
        tree.fit(X, y)
        assert tree.tree is not None


class TestTbatsForecastNameError:
    """`_tbats_predict` 中 `np.array(forecast)` 引用未定义名，异常被 `except` 吞掉后
    永远回退 numpy。修复为 `fitted.forecast(steps=14)`。"""

    def test_tbats_lib_branch_returns_result(self, monkeypatch):
        import algorithms.models.time_series.tbats_simple as mod
        from algorithms.base import PredictionResult

        class _Fitted:
            def forecast(self, steps=14):
                return np.linspace(1000.0, 500000.0, steps)

        class _FakeTBATS:
            def __init__(self, seasonal_periods=None, use_box_cox=False):
                self.seasonal_periods = seasonal_periods

            def fit(self, views):
                return _Fitted()

        monkeypatch.setattr(mod, "_TBATS", _FakeTBATS, raising=False)
        monkeypatch.setattr(mod, "_HAS_TBATS", True, raising=True)

        algo = mod.TbatsSimpleAlgorithm()
        video_data = _make_video_data(_make_history(20), current_views=20000)
        result = algo._tbats_predict(video_data, 100000)  # 修复前：forecast 未定义 → None
        assert isinstance(result, PredictionResult)
        assert result.target_threshold == 100000


class TestSettingsNotificationErrorClosure:
    """`_test_connection` 的异常分支里，lambda 闭包引用 `except ... as e` 的 `e`；
    `e` 在 except 块结束时被删除，回调（真实 QTimer 延迟触发）会 NameError。
    修复：先 `err = str(e)` 再在闭包中使用。"""

    def test_error_callback_runs_after_except_scope(self, monkeypatch):
        import threading
        import PyQt6.QtCore as qtc
        from core.notification import notification_manager
        from ui.settings_notification import SettingsNotificationMixin

        def _boom(**kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(notification_manager, "test_connection", _boom)

        class _Text:
            def __init__(self, s):
                self._s = s

            def text(self):
                return self._s

        class _FakeSelf:
            def __init__(self):
                self.dlg = None
                self.onebot_http = _Text("http://127.0.0.1:3000")
                self.onebot_ws = _Text("")
                self.onebot_token = _Text("")
                self.result = None

            def _show_test_result(self, r):
                self.result = r

        captured = []
        monkeypatch.setattr(qtc.QTimer, "singleShot", staticmethod(lambda ms, cb: captured.append(cb)))

        class _SyncThread:
            def __init__(self, target=None, daemon=None, **kw):
                self._target = target

            def start(self):
                self._target()

        monkeypatch.setattr(threading, "Thread", _SyncThread)

        fake = _FakeSelf()
        SettingsNotificationMixin._test_connection(fake)

        # 关键：回调在 _test_connection 返回（except 作用域已结束）之后才执行，
        # 复现真实 QTimer 的延迟触发时序。
        assert captured, "未捕获到 QTimer.singleShot 回调"
        for cb in captured:
            cb()
        assert fake.result is not None
        assert fake.result.get("ok") is False
        assert fake.result.get("error") == "boom"


class TestCryptoRoundTrip:
    """M0.2: 加解密往返（覆盖 cryptography 存在/缺失两条后端路径）。"""

    def test_encrypt_decrypt_roundtrip(self):
        from utils import crypto

        for plain in ("sk-secret-123", "中文密码♪", "a" * 500, "user:pass@host"):
            ct = crypto.encrypt(plain)
            assert ct and ct != plain
            assert crypto.decrypt(ct) == plain

    def test_empty_values(self):
        from utils import crypto

        assert crypto.encrypt("") == ""
        assert crypto.decrypt("") == ""

    def test_is_encrypted_recognizes_ciphertext(self):
        from utils import crypto

        ct = crypto.encrypt("sk-secret-123")
        assert crypto.is_encrypted(ct) is True
        assert crypto.is_encrypted("") is False


class TestRegistryAlgorithmIdUnique:
    """M0.2: 注册表 algorithm_id 唯一性。

    当前已知重复：`advanced/bass_diffusion.py` 与 `growth/bass_diffusion.py`
    同用 `algorithm_id="bass_diffusion"`（计划 M3.5 合并或改 id）。修复前标记 xfail。
    """

    @pytest.mark.xfail(
        reason="已知重复 algorithm_id=bass_diffusion（advanced 与 growth 各一份，M3.5 待处理）",
        strict=False,
    )
    def test_algorithm_ids_unique(self):
        from algorithms.registry import AlgorithmRegistry

        AlgorithmRegistry.initialize()
        algos = AlgorithmRegistry.get_all_algorithms()
        ids = [getattr(a, "algorithm_id", None) for a in algos]
        dupes = sorted({i for i in ids if i and ids.count(i) > 1})
        assert not dupes, f"重复 algorithm_id: {dupes}"


class TestTorchPredictCacheFirst:
    """M1.1: 已缓存模型 + checkpoint 签名未变时，`try_torch_predict` 不再调用
    `load_best_checkpoint`（避免每次预测都做 torch.load 磁盘读取）。

    注意：`try_torch_predict` 内部使用局部 `from ... import`，因此必须 patch
    **源模块** `algorithms.training.checkpoint_manager` / `algorithms.training.device`。
    """

    _BVID = "BV1xx411c7mD"

    def _fake_algo(self, sig):
        class _FakeAlgo:
            algorithm_id = "unit_fake_algo"
            name = "unit_fake"

        a = _FakeAlgo()
        a._ckpt = object()
        a._device = object()
        a._cached_torch_model = object()
        a._cached_bvid = self._BVID
        a._cached_ckpt_sig = sig
        a._cached_model_source = "video"
        return a

    def _video_data(self):
        return {"bvid": self._BVID, "view_count": 1000, "history_data": []}

    def test_cache_hit_skips_checkpoint_load(self, monkeypatch):
        import algorithms.models.deep_learning._torch_upgrade as u
        import algorithms.training.checkpoint_manager as ckpt_mod
        import algorithms.training.device as dev

        monkeypatch.setattr(u, "_torch_available", True)
        monkeypatch.setattr(u, "_build_torch_input", lambda *a, **k: (None, 0.0, 1.0))
        monkeypatch.setattr(dev, "get_preferred_device", lambda: "cpu")
        monkeypatch.setattr(ckpt_mod, "checkpoint_signature", lambda *a, **k: ("sig",))

        calls = []

        def _load(*a, **k):
            calls.append(1)
            return None, None

        monkeypatch.setattr(ckpt_mod, "load_best_checkpoint", _load)

        algo = self._fake_algo(("sig",))
        result = u.try_torch_predict(algo, self._video_data(), 100000, model_cls=object, fallback_fn=lambda vd, th: "FB")
        assert calls == [], "缓存命中（签名未变）时不应调用 load_best_checkpoint"
        assert result == "FB"

    def test_signature_change_triggers_reload(self, monkeypatch):
        import algorithms.models.deep_learning._torch_upgrade as u
        import algorithms.training.checkpoint_manager as ckpt_mod
        import algorithms.training.device as dev

        monkeypatch.setattr(u, "_torch_available", True)
        monkeypatch.setattr(u, "_build_torch_input", lambda *a, **k: (None, 0.0, 1.0))
        monkeypatch.setattr(dev, "get_preferred_device", lambda: "cpu")
        monkeypatch.setattr(ckpt_mod, "checkpoint_signature", lambda *a, **k: ("changed",))

        calls = []

        def _load(*a, **k):
            calls.append(1)
            return None, None

        monkeypatch.setattr(ckpt_mod, "load_best_checkpoint", _load)

        algo = self._fake_algo(("old",))  # 缓存签名与当前不一致
        result = u.try_torch_predict(algo, self._video_data(), 100000, model_cls=object, fallback_fn=lambda vd, th: "FB")
        assert calls, "checkpoint 签名变化时应重新调用 load_best_checkpoint"
        assert result == "FB"


class TestReleaseCachedModelsKeepActive:
    """M1.2: release_cached_models 保留当前活跃 bvid 的模型，释放其余并返回数量。"""

    def test_keeps_active_bvid(self):
        import algorithms.models.deep_learning._torch_upgrade as u

        class _Model:
            def cpu(self):
                return self

        class _Algo:
            def __init__(self, bvid):
                self._cached_torch_model = _Model()
                self._cached_bvid = bvid
                self._cached_ckpt_sig = ("s",)
                self._cached_model_source = "video"

        keep = _Algo("BV1")
        drop = _Algo("BV2")
        n = u.release_cached_models({"keep": keep, "drop": drop}, keep_bvid="BV1")
        assert n == 1
        assert keep._cached_torch_model is not None  # 活跃视频模型保留
        assert keep._cached_bvid == "BV1"
        assert drop._cached_torch_model is None  # 其余释放
        assert drop._cached_bvid == ""
        assert drop._cached_ckpt_sig is None

    def test_release_all_without_keep(self):
        import algorithms.models.deep_learning._torch_upgrade as u

        class _Model:
            def cpu(self):
                return self

        class _Algo:
            def __init__(self):
                self._cached_torch_model = _Model()
                self._cached_bvid = "BV1"

        a = _Algo()
        n = u.release_cached_models({"x": a})
        assert n == 1
        assert a._cached_torch_model is None


class TestMaybeReleaseMemoryPressure:
    """M1.2: _maybe_release_memory 仅在内存压力时释放，内存充足时不动。"""

    def test_only_under_pressure(self, monkeypatch):
        import ui.monitor._prediction as pred
        import utils.memory_guard as mg
        import algorithms.models.deep_learning._torch_upgrade as u

        called = []

        def _release(*a, **k):
            called.append(k.get("keep_bvid"))
            return 0

        monkeypatch.setattr(u, "release_cached_models", _release)

        monkeypatch.setattr(mg, "is_memory_pressure", lambda *a, **k: False)
        pred._maybe_release_memory(None)
        assert called == [], "内存充足时不应释放模型缓存"

        monkeypatch.setattr(mg, "is_memory_pressure", lambda *a, **k: True)
        pred._maybe_release_memory(None)
        assert called, "内存压力时应调用 release_cached_models"


class TestWeightManagerBatch:
    """M1.3: 批量更新准确率 —— 整批只重算/落盘一次，且与逐条结果数值一致。"""

    def test_batch_recalcs_once_and_matches_single(self, tmp_path, monkeypatch):
        from algorithms.weight_manager import WeightManager

        names = [f"algo_{i}" for i in range(120)]
        accs = [0.1 + (i % 9) * 0.1 for i in range(120)]

        wm_batch = WeightManager(save_dir=str(tmp_path / "batch"))
        calls = {"recalc": 0, "save": 0}
        orig_recalc = wm_batch._recalculate_ml_weights
        orig_save = wm_batch._save_weights_sync

        def _recalc():
            calls["recalc"] += 1
            orig_recalc()

        def _save():
            calls["save"] += 1
            orig_save()

        monkeypatch.setattr(wm_batch, "_recalculate_ml_weights", _recalc)
        monkeypatch.setattr(wm_batch, "_save_weights_sync", _save)

        wm_batch.update_accuracy_batch(list(zip(names, accs)))
        assert calls["recalc"] == 1, "批量更新应只重算一次"
        assert calls["save"] == 1, "批量更新应只落盘一次"

        wm_single = WeightManager(save_dir=str(tmp_path / "single"))
        for n, a in zip(names, accs):
            wm_single.update_accuracy(n, a)

        assert wm_batch.ml_weights == pytest.approx(wm_single.ml_weights)
        assert wm_batch.accuracy_records == wm_single.accuracy_records


class TestRegistryAccuracyBatch:
    """M1.3: AlgorithmRegistry.update_accuracy_batch 把整批交给 WeightManager 一次。"""

    def test_delegates_batch_once(self, monkeypatch):
        import algorithms.registry as reg

        captured = []

        class _WM:
            def update_accuracy_batch(self, records):
                captured.append(list(records))

        monkeypatch.setattr(reg, "get_weight_manager", lambda: _WM())
        # 避免触发 registry 初始化（get_registry_key 内部会 initialize 137 个算法）
        monkeypatch.setattr(reg.AlgorithmRegistry, "get_registry_key", classmethod(lambda cls, x: x))

        reg.AlgorithmRegistry.update_accuracy_batch([("algo_a", 100, 120), ("algo_b", 50, 0)])

        assert len(captured) == 1, "应只调用一次 WeightManager.update_accuracy_batch"
        accs = dict(captured[0])
        assert list(accs.keys()) == ["algo_a", "algo_b"]
        assert accs["algo_a"] == pytest.approx(1.0 - 20 / 120, abs=1e-6)
        assert accs["algo_b"] == pytest.approx(0.5)


class TestOnlineLearnerStatsLinear:
    """M1.4: get_algorithm_stats 一次性计算权重，避免 O(T²)（每个 tracker 各算一次）。"""

    def test_get_weights_called_once(self, monkeypatch):
        from algorithms.online_learner import OnlineLearner

        learner = OnlineLearner()
        n = 2000
        for i in range(n):
            learner.register(f"algo_{i}")

        orig = learner.get_weights
        calls = {"n": 0}

        def _gw():
            calls["n"] += 1
            return orig()

        monkeypatch.setattr(learner, "get_weights", _gw)

        stats = learner.get_algorithm_stats()
        assert len(stats) == n
        assert calls["n"] == 1, f"get_weights 应只调用一次，实际 {calls['n']}（O(T²) 回归）"

        w = orig()
        for name, info in stats.items():
            assert info["weight"] == round(w.get(name, 1.0), 4)


class TestOnlineLearnerEtaIncremental:
    """M1.5: _recent_error_stats 增量聚合（recent_sum/recent_sumsq）与朴素全量计算一致。"""

    def test_aggregate_matches_naive(self):
        from algorithms.online_learner import OnlineLearner

        learner = OnlineLearner(warmup=0)
        names = [f"a{i}" for i in range(30)]
        for n in names:
            learner.register(n)
        # 每个 tracker 喂 >10 条，触发滑动窗口 pop，验证 sumsq 扣减路径
        for step in range(25):
            for j, n in enumerate(names):
                learner.update(n, predicted=1000, actual=1000 + (step * 7 + j * 13) % 500)

        all_errors = []
        for t in learner._trackers.values():
            all_errors.extend(t.recent_errors)
        n_naive = len(all_errors)
        mean_naive = sum(all_errors) / n_naive
        var_naive = sum((e - mean_naive) ** 2 for e in all_errors) / n_naive
        cv_naive = (var_naive ** 0.5) / mean_naive

        n, mean, cv = learner._recent_error_stats()
        assert n == n_naive
        assert mean == pytest.approx(mean_naive, rel=1e-9, abs=1e-12)
        assert cv == pytest.approx(cv_naive, rel=1e-6, abs=1e-9)

        learner._adjust_eta()
        assert 0.1 <= learner.eta <= 1.5


class TestQueryBackupClosesConnection:
    """M2.8: central_crud._query_backup 在成功/异常路径都必须关闭连接。"""

    def _crud(self, tmp_path):
        import core.database.central_crud as cc

        # 备份库文件只需存在（连接会被替换为假对象）
        (tmp_path / "bilibili_monitor.db").write_bytes(b"")

        class _DB:
            db_path = str(tmp_path / "active.db")

            def _get_backup_dir(self):
                return str(tmp_path)

        return cc, cc.CentralCRUD(_DB())

    def test_closes_on_success(self, monkeypatch, tmp_path):
        cc, crud = self._crud(tmp_path)
        created = []

        class _FakeCursor:
            def execute(self, sql, params=()):
                return self

            def fetchall(self):
                return [(1,)]

        class _FakeConn:
            def __init__(self):
                self.row_factory = None
                self.closed = False

            def cursor(self):
                return _FakeCursor()

            def close(self):
                self.closed = True

        def _connect(*a, **k):
            c = _FakeConn()
            created.append(c)
            return c

        monkeypatch.setattr(cc.sqlite3, "connect", _connect)
        rows = crud._query_backup("SELECT 1")
        assert rows == [(1,)]
        assert created and created[0].closed, "成功路径应关闭连接"

    def test_closes_on_error(self, monkeypatch, tmp_path):
        cc, crud = self._crud(tmp_path)
        created = []

        class _BadCursor:
            def execute(self, sql, params=()):
                raise RuntimeError("boom")

        class _FakeConn:
            def __init__(self):
                self.row_factory = None
                self.closed = False

            def cursor(self):
                return _BadCursor()

            def close(self):
                self.closed = True

        def _connect(*a, **k):
            c = _FakeConn()
            created.append(c)
            return c

        monkeypatch.setattr(cc.sqlite3, "connect", _connect)
        rows = crud._query_backup("SELECT 1")
        assert rows == []
        assert created and created[0].closed, "异常路径也应关闭连接"


class TestBatchFetchBounded:
    """M2.4: _batch_fetch_all 使用有界线程池，不再"每视频一个 OS 线程"。"""

    def test_bounded_concurrency_and_completes(self, monkeypatch):
        import threading
        import time
        import ui.monitor._service as svc
        import utils.memory_guard as mg

        monkeypatch.setattr(mg, "get_safe_workers", lambda: 4)

        active = []
        max_active = {"n": 0}
        completed = []
        lock = threading.Lock()

        def _fake_fetch(gui, bvid, video):
            with lock:
                active.append(bvid)
                max_active["n"] = max(max_active["n"], len(active))
            time.sleep(0.01)
            with lock:
                active.remove(bvid)
                completed.append(bvid)

        monkeypatch.setattr(svc, "_fetch_one_video", _fake_fetch)

        class _LP:
            def add_log(self, *a, **k):
                pass

        class _GUI:
            def __init__(self, n):
                self.monitored_videos = [{"bvid": f"BV{i:03d}"} for i in range(n)]
                self.log_panel = _LP()

            def _sb(self, *a, **k):
                pass

        svc._batch_fetch_all(_GUI(40))

        assert len(completed) == 40, "所有视频都应被抓取"
        assert max_active["n"] <= 4, f"并发应受限于 4，实际 {max_active['n']}"
        assert max_active["n"] >= 1


class TestCoverValidityCache:
    """M2.3: get_valid_cover 命中有效性缓存后不再重复整文件读取 + MD5。"""

    def test_repeated_calls_skip_md5(self, monkeypatch, tmp_path):
        import utils.cover_manager as cm

        monkeypatch.setattr(cm, "COVER_DIR", str(tmp_path))
        cm._cover_valid_cache.clear()

        bvid = "BV1xx411c7mD"
        data = b"fake-image-bytes"
        (tmp_path / f"{bvid}.jpg").write_bytes(data)
        (tmp_path / f"{bvid}.jpg.md5").write_text(cm._compute_md5(data))

        calls = {"n": 0}
        real_compute = cm._compute_md5

        def _counting(d):
            calls["n"] += 1
            return real_compute(d)

        monkeypatch.setattr(cm, "_compute_md5", _counting)

        p1 = cm.get_valid_cover(bvid)
        p2 = cm.get_valid_cover(bvid)
        assert p1 == p2 == str(tmp_path / f"{bvid}.jpg")
        assert calls["n"] == 1, "第二次调用应命中缓存，不再计算 MD5"


class TestMemoryHealthOffMainThread:
    """M2.10a: do_memory_health_check 必须经 fire_and_forget 后台执行，不得在主线程同步调用。"""

    def test_scheduled_via_fire_and_forget(self, monkeypatch):
        import ui.main_gui_tick as tick

        called = {"ff": [], "sync": []}
        monkeypatch.setattr(tick, "fire_and_forget", lambda fn, name=None, **k: called["ff"].append(name))
        monkeypatch.setattr(tick, "do_memory_health_check", lambda gui: called["sync"].append(1))
        monkeypatch.setattr(tick, "do_periodic_sync", lambda gui: None)
        monkeypatch.setattr(tick, "wal_checkpoint_worker", lambda gui: None)
        monkeypatch.setattr(tick, "scan_alerts_background", lambda gui: None)

        class _Badge:
            def setText(self, *a):
                pass

            def setStyleSheet(self, *a):
                pass

        class _GUI:
            auto_refresh_enabled = True
            DEFAULT_INTERVAL = 75
            FAST_INTERVAL = 10
            _global_tick_timer = None
            _last_countdown_text = ""
            _last_mode_text = ""
            _last_interval_text = ""
            _video_timers = {}
            _tick_counter = 9  # +1 = 10 → 命中 %1800==10

            def __init__(self):
                self._countdown_badge = _Badge()
                self._mode_pill = _Badge()

            def _sb(self, *a, **k):
                pass

        tick.global_tick(_GUI())
        assert called["ff"] == ["mem-health"], f"应经 fire_and_forget 调度，实际 {called['ff']}"
        assert called["sync"] == [], "不应在主线程同步调用 do_memory_health_check"


class TestNoGlobalRandomSeedPollution:
    """M2.10b: 算法模块不得用 np.random.seed() 污染全局 RNG（应使用局部 RandomState/default_rng）。"""

    def test_no_np_random_seed_in_models(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1] / "algorithms" / "models"
        offenders = [
            str(p.relative_to(root))
            for p in root.rglob("*.py")
            if "np.random.seed(" in p.read_text(encoding="utf-8")
        ]
        assert not offenders, f"仍存在污染全局 RNG 的 np.random.seed: {offenders}"


@pytest.fixture(scope="module")
def qapp():
    """模块级 QApplication（offscreen）；模块内保持引用，避免被 GC 后重建。"""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class TestLogPanelEmptyStateCounter:
    """M2.10c: _sync_empty_state 用计数判断（不再全量 toPlainText）；add_log 并发不丢。"""

    def test_empty_state_uses_counter(self, qapp):
        from ui.log_panel import LogPanel

        panel = LogPanel(None, None)
        panel._displayed_lines = 0
        panel._sync_empty_state()
        assert panel._stack.currentWidget() is panel._empty_state
        panel._displayed_lines = 1
        panel._sync_empty_state()
        assert panel._stack.currentWidget() is panel._text

    def test_concurrent_add_log_no_lost(self, qapp, monkeypatch):
        import threading

        import ui.log_panel as lp

        # 隔离跨线程调度（无事件循环时 invoke 会抛异常），仅验证加锁追加不丢日志
        monkeypatch.setattr(lp, "invoke", lambda fn: None)

        panel = lp.LogPanel(None, None)
        n_threads, per = 8, 200

        def _worker():
            for i in range(per):
                panel.add_log("INFO", f"m{i}")

        ts = [threading.Thread(target=_worker) for _ in range(n_threads)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        # flush 未执行 → pending 应恰好保留全部追加（无丢失）
        assert len(panel._pending_logs) == n_threads * per


class TestCollectHealthAlerts:
    """M2.2a: 预警收集抽为可在后台线程执行的独立函数。"""

    def test_collects_from_all_videos(self, monkeypatch):
        import core.smart_alert as sa
        import ui.dashboard_mode as dm

        monkeypatch.setattr(
            sa.AnomalyDetector,
            "detect_all",
            staticmethod(lambda records, bvid="", **k: [f"alert-{bvid}"]),
        )

        class _DB:
            def get_all_records(self, limit=10):
                return [{"x": 1}]

        class _GUI:
            monitored_videos = [{"bvid": "BV1", "title": "t1"}, {"bvid": "BV2", "title": "t2"}]
            video_dbs = {"BV1": _DB(), "BV2": _DB()}

        items = dm._collect_health_alerts(_GUI())
        assert ("t1", "alert-BV1") in items
        assert ("t2", "alert-BV2") in items


class TestRetentionCutoffSql:
    """M2.9a: 保留清理 SQL 对两种时间戳格式都正确（空格与 ISO 'T'）。"""

    def test_sql_matches_both_formats(self, tmp_path):
        import sqlite3

        conn = sqlite3.connect(str(tmp_path / "t.db"))
        conn.execute("CREATE TABLE monitor_records (timestamp TEXT, view_count INTEGER)")
        conn.executemany(
            "INSERT INTO monitor_records (timestamp, view_count) VALUES (?, ?)",
            [
                ("2020-01-01 00:00:00", 1),
                ("2099-01-01T00:00:00", 2),
                ("2099-01-01 00:00:00", 3),
            ],
        )
        conn.commit()
        cur = conn.execute(
            "DELETE FROM monitor_records WHERE datetime(replace(timestamp,'T',' ')) < datetime(?)",
            ("2050-01-01 00:00:00",),
        )
        assert cur.rowcount == 1
        remaining = sorted(r[0] for r in conn.execute("SELECT view_count FROM monitor_records"))
        assert remaining == [2, 3]
        conn.close()

    def test_methods_exist(self):
        from core.database.video_db import VideoDatabase
        from core.database.central_crud import CentralCRUD

        assert hasattr(VideoDatabase, "delete_monitor_records_before")
        assert hasattr(CentralCRUD, "delete_monitor_records_before")


class TestMaybeCleanupOldRecords:
    """M2.9a: _maybe_cleanup_old_records 按 history_days 配置执行/跳过。"""

    def _run(self, monkeypatch, days, video_dbs):
        import ui.main_gui_tick as tick
        import config as cfgmod
        import core as coremod

        monkeypatch.setattr(cfgmod, "load_config", lambda: {"monitor": {"history_days": days}})

        class _DB:
            def delete_monitor_records_before(self, cutoff):
                return 2

        monkeypatch.setattr(coremod, "db", _DB())

        class _GUI:
            _last_record_cleanup = 0

            def __init__(self):
                self.video_dbs = video_dbs

        tick._maybe_cleanup_old_records(_GUI())

    def test_deletes_when_enabled(self, monkeypatch):
        calls = []

        class _VDB:
            def delete_monitor_records_before(self, cutoff):
                calls.append(cutoff)
                return 3

        self._run(monkeypatch, 30, {"BV1": _VDB()})
        assert calls, "history_days>0 时应清理视频库"

    def test_skips_when_disabled(self, monkeypatch):
        calls = []

        class _VDB:
            def delete_monitor_records_before(self, cutoff):
                calls.append(cutoff)
                return 3

        self._run(monkeypatch, 0, {"BV1": _VDB()})
        assert not calls, "history_days<=0 时应跳过"


class TestIndexesAdded:
    """M2.9b: 新增覆盖索引已注册/创建。"""

    def test_video_db_index_statements_present(self):
        from core.database.video_db import VideoDatabase

        sqls = " ".join(s for s, _ in VideoDatabase.SCHEMA_STATEMENTS)
        assert "idx_predict_created_at" in sqls
        assert "idx_danmaku_video_ts" in sqls

    def test_central_indexes_created(self, tmp_path):
        from core.database.central_db import Database

        d = Database(db_path=str(tmp_path / "central.db"))
        try:
            names = {r[0] for r in d._conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        finally:
            d._conn.close()
        assert "idx_videos_owner_id" in names
        assert "idx_predictions_created_at" in names


class TestOnlineViewersBackgroundCache:
    """M2.2d: 在线人数缓存由后台读取并传入 _populate，主线程不查库。"""

    def test_populate_with_cached_skips_read(self, monkeypatch):
        import ui.online_viewers_panel as ovp

        calls = {"n": 0}

        def _read():
            calls["n"] += 1
            return {}

        monkeypatch.setattr(ovp, "_read_viewers", _read)

        class _Fake:
            gui = None

        ovp.OnlineViewersPanel._populate(_Fake(), cached={"BV1": {"total": 1}})
        assert calls["n"] == 0, "传入 cached 时不应再查库"

        ovp.OnlineViewersPanel._populate(_Fake())
        assert calls["n"] == 1, "未传 cached 时回退同步读取"

    def test_update_ui_passes_cached(self):
        import ui.online_viewers_panel as ovp

        seen = {}

        class _Lbl:
            def setText(self, s):
                pass

        class _Fake:
            _time_lbl = _Lbl()

            def _populate(self, cached=None):
                seen["cached"] = cached

        ovp.OnlineViewersPanel._update_ui_after_fetch(_Fake(), cached={"x": 1})
        assert seen["cached"] == {"x": 1}


class TestDetailScoreHistoryCache:
    """M2.2b: 历史分数走后台缓存，主线程不查库。"""

    @staticmethod
    def _make_panel(cache, pending):
        from ui.detail_panel import DetailPanel

        panel = DetailPanel.__new__(DetailPanel)
        panel._score_history_cache = cache
        panel._score_history_pending = pending
        panel._current_tab_name = "☰ 详细数据"
        panel._detail_text_fp = None
        return panel

    @staticmethod
    def _make_db():
        class _DB:
            def __init__(self):
                self.calls = 0

            def get_weekly_scores(self, limit=5):
                self.calls += 1
                return [
                    {"timestamp": "2026-01-01T00:00", "total_score": 1.0},
                    {"timestamp": "2026-01-02T00:00", "total_score": 2.0},
                ]

            def get_yearly_scores(self, limit=5):
                self.calls += 1
                return []

        return _DB()

    @staticmethod
    def _make_gui(db):
        class _Gui:
            video_dbs = {"BV1": db}
            selected_bvid = "OTHER"

        return _Gui()

    def test_main_thread_does_not_touch_db(self, monkeypatch):
        import ui.detail_panel as dp

        monkeypatch.setattr(dp, "fire_and_forget", lambda fn, *a, **k: None)
        monkeypatch.setattr(dp, "invoke", lambda fn: fn())

        db = self._make_db()
        panel = self._make_panel({}, set())
        panel.gui = self._make_gui(db)

        weekly, yearly = panel._get_score_history("BV1")
        assert weekly == [] and yearly == []
        assert db.calls == 0, "主线程不应查库"

    def test_background_load_populates_cache(self, monkeypatch):
        import ui.detail_panel as dp

        monkeypatch.setattr(dp, "fire_and_forget", lambda fn, *a, **k: fn())
        monkeypatch.setattr(dp, "invoke", lambda fn: fn())

        db = self._make_db()
        panel = self._make_panel({}, set())
        panel.gui = self._make_gui(db)

        panel._get_score_history("BV1")
        assert db.calls == 2
        assert len(panel._score_history_cache["BV1"][0]) == 2
        assert panel._score_history_cache["BV1"][1] == []

    def test_pending_dedup(self, monkeypatch):
        import ui.detail_panel as dp

        sched = {"n": 0}
        monkeypatch.setattr(dp, "fire_and_forget", lambda fn, *a, **k: sched.__setitem__("n", sched["n"] + 1))
        monkeypatch.setattr(dp, "invoke", lambda fn: fn())

        db = self._make_db()
        panel = self._make_panel({}, set())
        panel.gui = self._make_gui(db)

        panel._get_score_history("BV1")
        panel._get_score_history("BV1")
        assert sched["n"] == 1, "同一 bvid 只应调度一次后台读取"
        assert "BV1" in panel._score_history_pending

    def test_background_load_materializes_before_read(self, monkeypatch):
        import ui.detail_panel as dp

        order = []
        monkeypatch.setattr(dp, "fire_and_forget", lambda fn, *a, **k: fn())
        monkeypatch.setattr(dp, "invoke", lambda fn: fn())
        monkeypatch.setattr(dp, "ensure_scores", lambda db: order.append("ensure"))

        class _DB:
            def get_weekly_scores(self, limit=5):
                order.append("weekly")
                return []

            def get_yearly_scores(self, limit=5):
                order.append("yearly")
                return []

        class _Gui:
            video_dbs = {"BV1": _DB()}
            selected_bvid = "OTHER"

        panel = self._make_panel({}, set())
        panel.gui = _Gui()

        panel._get_score_history("BV1")
        assert order == ["ensure", "weekly", "yearly"], "后台应先物化归档再读最近 5 点"


class TestDanmakuBackgroundLoad:
    """M2.2c: 弹幕后台读取，计数变化才重渲。"""

    @staticmethod
    def _panel():
        from ui.detail_panel import DetailPanel

        panel = DetailPanel.__new__(DetailPanel)
        panel._dm_cache = {}
        panel._dm_pending = set()
        panel._current_tab_name = "♬ 弹幕"
        return panel

    def test_schedule_does_not_query_and_only_rerenders_on_count_change(self, monkeypatch):
        import ui.detail_tabs as dt

        monkeypatch.setattr(dt, "invoke", lambda fn: fn())

        state = {"records": [{"video_ts": 1, "content": "a"}], "count": 1}

        class _DB:
            def __init__(self):
                self.calls = 0

            def get_danmaku_records(self, limit=200):
                self.calls += 1
                return state["records"]

            def count_danmaku(self):
                return state["count"]

        db = _DB()
        holds = {"fn": None}
        monkeypatch.setattr(dt, "fire_and_forget", lambda fn, *a, **k: holds.__setitem__("fn", fn))

        class _Gui:
            selected_bvid = "BV1"
            video_dbs = {"BV1": db}

        panel = self._panel()
        panel.gui = _Gui()
        rendered = []
        panel._render_danmaku = lambda records, count: rendered.append(count)

        panel._schedule_danmaku_load("BV1", db)
        assert db.calls == 0, "调度时不得查库"
        assert "BV1" in panel._dm_pending

        holds["fn"]()
        assert db.calls == 1
        assert rendered == [1]

        # 计数未变 → 不重渲
        panel._schedule_danmaku_load("BV1", db)
        holds["fn"]()
        assert rendered == [1], "计数未变不应重渲"

        # 计数变化 → 重渲
        state["count"] = 2
        state["records"] = state["records"] + [{"video_ts": 2, "content": "b"}]
        panel._schedule_danmaku_load("BV1", db)
        holds["fn"]()
        assert rendered == [1, 2]

    def test_pending_dedup(self, monkeypatch):
        import ui.detail_tabs as dt

        monkeypatch.setattr(dt, "invoke", lambda fn: fn())
        sched = {"n": 0}
        monkeypatch.setattr(dt, "fire_and_forget", lambda fn, *a, **k: sched.__setitem__("n", sched["n"] + 1))

        class _DB:
            def get_danmaku_records(self, limit=200):
                return []

            def count_danmaku(self):
                return 0

        panel = self._panel()
        panel._schedule_danmaku_load("BV1", _DB())
        panel._schedule_danmaku_load("BV1", _DB())
        assert sched["n"] == 1, "同一 bvid 只应调度一次后台读取"


class TestInvokerKeyedCoalescing:
    """M2.10: invoker 按 key 合并 + 背压 + 异常走 logger。"""

    @staticmethod
    def _make():
        from ui.invoker import _MainInvoker

        inv = _MainInvoker()
        inv._wake.disconnect()  # 模拟跨线程排队，避免同线程直连时同步执行
        return inv

    def test_key_coalescing_keeps_latest(self):
        inv = self._make()
        ran = []
        inv.invoke(lambda: ran.append("a1"), key="k")
        inv.invoke(lambda: ran.append("a2"), key="k")
        inv.invoke(lambda: ran.append("a3"), key="k")
        assert ran == [], "未 drain 前不应执行"
        inv._drain()
        assert ran == ["a3"], "同一 key 只执行最新回调"

    def test_unkeyed_fifo_all_run(self):
        inv = self._make()
        ran = []
        inv.invoke(lambda: ran.append(1))
        inv.invoke(lambda: ran.append(2))
        inv._drain()
        assert ran == [1, 2]

    def test_backpressure_drops_new(self, monkeypatch):
        import ui.invoker as iv

        monkeypatch.setattr(iv, "_MAX_QUEUE", 2)
        inv = self._make()
        ran = []
        inv.invoke(lambda: ran.append(1))
        inv.invoke(lambda: ran.append(2))
        inv.invoke(lambda: ran.append(3))  # 超限 → 丢弃
        inv._drain()
        assert ran == [1, 2]

    def test_exception_logged_and_isolated(self):
        inv = self._make()
        ran = []

        def _boom():
            raise RuntimeError("boom")

        inv.invoke(_boom)
        inv.invoke(lambda: ran.append("after"))
        inv._drain()
        assert ran == ["after"], "单回调异常不应阻断后续"


class TestCoverLoaderThreading:
    """M2.10f: 封面 worker 只产出 QImage + 有界线程池。"""

    def test_fetch_uses_qimage_not_qpixmap(self, monkeypatch):
        import ui.video_list_panel as vlp

        class _Resp:
            status_code = 200
            content = b"fake-bytes"

        class _Session:
            def get(self, url, timeout=10):
                return _Resp()

        class _FakeImage:
            def __init__(self):
                self.loaded = None

            def loadFromData(self, data):
                self.loaded = data
                return True

            def isNull(self):
                return False

        def _no_pixmap(*a, **k):
            raise AssertionError("worker 不应构造 QPixmap")

        monkeypatch.setattr(vlp, "_cover_session", _Session())
        monkeypatch.setattr(vlp, "save_cover", lambda b, c: None)
        monkeypatch.setattr(vlp, "QImage", _FakeImage)
        monkeypatch.setattr(vlp, "QPixmap", _no_pixmap)

        got = []
        loader = vlp.CoverLoader()
        try:
            loader.cover_loaded.connect(lambda bvid, obj: got.append((bvid, obj)))
            loader._fetch("BV1", "http://x/y.png")
        finally:
            loader.shutdown()

        assert got and got[0][0] == "BV1"
        assert isinstance(got[0][1], _FakeImage)
        assert got[0][1].loaded == b"fake-bytes"

    def test_on_cover_loaded_converts_image_to_pixmap(self, monkeypatch):
        import ui.video_list_panel as vlp
        from PyQt6.QtGui import QImage

        converted = []

        class _FakePixmap:
            @staticmethod
            def fromImage(img):
                converted.append(img)
                return "pixmap"

        monkeypatch.setattr(vlp, "QPixmap", _FakePixmap)

        class _List:
            def itemDelegate(self):
                return None

        class _Panel:
            _card_widgets = {}

            def __init__(self):
                self._list = _List()

        image = QImage()
        vlp.VideoListPanel._on_cover_loaded(_Panel(), "BV1", image)
        assert converted == [image], "主线程应把 QImage 转成 QPixmap"

    def test_bounded_pool_wiring(self, monkeypatch):
        import ui.video_list_panel as vlp

        loader = vlp.CoverLoader()
        try:
            assert loader._pool._max_workers == vlp.CoverLoader.MAX_WORKERS
            monkeypatch.setattr(loader, "_fetch", lambda b, u: None)
            loader.load_cover("BV1", "u")
        finally:
            loader.shutdown()
        # 关闭后不再提交（不抛异常）
        loader.load_cover("BV2", "u")


class TestSearchDebounce:
    """M2.10g: 搜索输入去抖后过滤。"""

    def test_on_search_starts_timer_and_apply_filters(self):
        import ui.video_list_panel as vlp

        class _Timer:
            def __init__(self):
                self.starts = 0

            def start(self):
                self.starts += 1

        class _Item:
            def __init__(self, data):
                self._data = data
                self.hidden = None

            def data(self, role):
                return self._data

            def setHidden(self, flag):
                self.hidden = flag

        class _List:
            def __init__(self, items):
                self._items = items

            def count(self):
                return len(self._items)

            def item(self, i):
                return self._items[i]

        class _Panel:
            _search_text = ""

        panel = _Panel()
        panel._search_timer = _Timer()

        vlp.VideoListPanel._on_search(panel, "  ABC ")
        assert panel._search_text == "abc"
        assert panel._search_timer.starts == 1, "输入变化应触发一次去抖计时"

        items = [
            _Item({"bvid": "BV1abc", "title": "hello"}),
            _Item({"bvid": "BV2", "title": "world"}),
            _Item(None),
        ]
        panel._list = _List(items)

        vlp.VideoListPanel._apply_search(panel)
        assert items[0].hidden is False
        assert items[1].hidden is True
        assert items[2].hidden is None, "无 data 的项不应改动"


class TestDiffusionSchedule:
    """M2.10h: 反向扩散少步采样时间步序列。"""

    def test_full_steps_when_none_or_ge(self):
        from algorithms.models.deep_learning.diffusion_ts import _diffusion_schedule

        assert _diffusion_schedule(5) == [4, 3, 2, 1, 0]
        assert _diffusion_schedule(5, 5) == [4, 3, 2, 1, 0]
        assert _diffusion_schedule(5, 10) == [4, 3, 2, 1, 0]

    def test_reduced_steps_descending_and_includes_zero(self):
        from algorithms.models.deep_learning.diffusion_ts import _diffusion_schedule

        sched = _diffusion_schedule(100, 20)
        assert sched[0] == 99
        assert sched[-1] == 0
        assert len(sched) == 20
        assert sched == sorted(set(sched), reverse=True)
        assert all(0 <= t < 100 for t in sched)


class TestAgeHoursMemo:
    """M2.7a: get_video_age_hours 排序结果按轮缓存（只排一次）。"""

    @staticmethod
    def _algo():
        from algorithms.base import BaseAlgorithm

        class _Algo:
            _timestamp_sort_key = staticmethod(BaseAlgorithm._timestamp_sort_key)
            _oldest_history_epoch = BaseAlgorithm._oldest_history_epoch

        return _Algo()

    def test_sorted_once_per_round(self, monkeypatch):
        import algorithms.base as bmod
        from algorithms.base import BaseAlgorithm

        algo = self._algo()
        video = {"history_data": [{"timestamp": f"2026-01-0{i + 1} 00:00:00"} for i in range(3)]}

        real_sorted = sorted
        calls = {"n": 0}

        def _spy(*a, **k):
            calls["n"] += 1
            return real_sorted(*a, **k)

        monkeypatch.setattr(bmod, "sorted", _spy, raising=False)

        a1 = BaseAlgorithm.get_video_age_hours(algo, video)
        a2 = BaseAlgorithm.get_video_age_hours(algo, video)
        assert calls["n"] == 1, "同一 video_data 只应排序一次"
        assert abs(a1 - a2) < 1e-6

        video["history_data"].append({"timestamp": "2026-01-04 00:00:00"})
        BaseAlgorithm.get_video_age_hours(algo, video)
        assert calls["n"] == 2, "历史变化后应重新排序"

    def test_fallback_timestamp_path(self):
        import time

        from algorithms.base import BaseAlgorithm

        video = {"history_data": [], "timestamp": time.time() - 3600}
        age = BaseAlgorithm.get_video_age_hours(self._algo(), video)
        assert 0.9 < age < 1.1


class TestLightVideoInfoRead:
    """M2.5: 同步路径轻量只读 video_info（不建表/不迁移）。"""

    def test_reads_existing_row_and_skips_missing(self, tmp_path):
        import sqlite3

        from core.database.central_crud import CentralCRUD

        bvid = "BV1"
        d = tmp_path / bvid
        d.mkdir()
        db = sqlite3.connect(str(d / f"{bvid}.db"))
        db.execute("CREATE TABLE video_info (id INTEGER PRIMARY KEY, title TEXT, view_count INTEGER)")
        db.execute("INSERT INTO video_info (id, title, view_count) VALUES (1, 't', 5)")
        db.commit()
        db.close()

        # 不存在的视频 → None，且不应创建任何文件
        assert CentralCRUD._read_video_info_light("nosuch", str(tmp_path)) is None
        assert not (tmp_path / "nosuch").exists()

        row = CentralCRUD._read_video_info_light(bvid, str(tmp_path))
        assert row and row["title"] == "t" and row["view_count"] == 5

    def test_missing_table_returns_none(self, tmp_path):
        import sqlite3

        from core.database.central_crud import CentralCRUD

        bvid = "BV2"
        d = tmp_path / bvid
        d.mkdir()
        sqlite3.connect(str(d / f"{bvid}.db")).close()  # 空库，无表

        assert CentralCRUD._read_video_info_light(bvid, str(tmp_path)) is None


class TestTimeUtilsCanonicalFormat:
    """M2.9c: 统一时间戳格式（空格分隔、秒精度、可字典序比较）。"""

    def test_format_and_now_use_canonical_fmt(self):
        from datetime import datetime

        from utils.time_utils import TS_FMT, format_ts, now_ts

        assert TS_FMT == "%Y-%m-%d %H:%M:%S"
        s = format_ts(datetime(2026, 1, 2, 3, 4, 5, 123456))
        assert s == "2026-01-02 03:04:05", "不应含微秒或 T"
        assert "T" not in s and "." not in s
        assert len(now_ts()) == 19

    def test_mixed_format_breaks_range_comparison(self):
        from datetime import datetime

        from utils.time_utils import format_ts

        same_day_later = format_ts(datetime(2026, 1, 2, 12, 0, 0))
        iso_cutoff = datetime(2026, 1, 2, 3, 0, 0).isoformat()
        # 修复前的缺陷：同一天、晚于 cutoff 的行会被 isoformat 误判为小于 cutoff
        assert (same_day_later >= iso_cutoff) is False
        assert (same_day_later >= format_ts(datetime(2026, 1, 2, 3, 0, 0))) is True

    def test_normalize_timestamp_outputs_canonical(self):
        from utils.time_utils import normalize_timestamp

        _, _, s = normalize_timestamp("2026-01-02T03:04:05.123456")
        assert s == "2026-01-02 03:04:05", "解析 ISO 输入后应输出规范格式"


class TestCleanupUsesPlainComparison:
    """M2.9c: 统一格式后清理用纯字典序比较（可命中索引）。"""

    def test_central_delete_by_canonical_cutoff(self, tmp_path):
        from core.database.central_db import Database

        d = Database(db_path=str(tmp_path / "central.db"))
        try:
            conn = d._conn
            conn.executemany(
                "INSERT INTO monitor_records (bvid, timestamp) VALUES (?, ?)",
                [
                    ("BV1", "2026-01-01 10:00:00"),
                    ("BV1", "2026-01-02 10:00:00"),
                    ("BV1", "2026-01-03 10:00:00"),
                ],
            )
            conn.commit()

            deleted = d.delete_monitor_records_before("2026-01-02 10:00:00")
            assert deleted == 1

            remaining = [r[0] for r in conn.execute("SELECT timestamp FROM monitor_records ORDER BY timestamp")]
            assert remaining == ["2026-01-02 10:00:00", "2026-01-03 10:00:00"]
        finally:
            d._conn.close()


class TestScoresUniqueTimestamp:
    """M2.11a: 分数表 timestamp 唯一 → upsert 幂等。"""

    @staticmethod
    def _isolate(monkeypatch, tmp_path):
        import core.database.video_db as vdb

        # 让 mirror_base == base_dir，避免写入仓库 data/ 目录
        monkeypatch.setattr(vdb, "project_path", lambda *parts: str(tmp_path))
        return vdb

    def test_same_timestamp_upsert_keeps_one_row(self, tmp_path, monkeypatch):
        vdb = self._isolate(monkeypatch, tmp_path)
        db = vdb.VideoDatabase("BV1xx411c7mD", base_dir=str(tmp_path))
        try:
            assert db.add_weekly_score("2026-01-01 10:00:00", {"total_score": 1.0})
            assert db.add_weekly_score("2026-01-01 10:00:00", {"total_score": 2.0})
            rows = db.get_weekly_scores()
            assert len(rows) == 1, "同一 timestamp 只应保留一行"
            assert rows[0]["total_score"] == 2.0

            assert db.add_yearly_score("2026-01-01 10:00:00", {"total_score": 5.0})
            assert db.add_yearly_score("2026-01-01 10:00:00", {"total_score": 6.0})
            yrows = db.get_yearly_scores()
            assert len(yrows) == 1 and yrows[0]["total_score"] == 6.0
        finally:
            db.close()

    def test_v4_migration_dedupes_and_builds_unique_index(self, tmp_path, monkeypatch):
        import sqlite3

        vdb = self._isolate(monkeypatch, tmp_path)

        # 造一个 v3 旧库：重复 timestamp + 旧普通索引
        d = tmp_path / "BV1xx411c7mD"
        d.mkdir()
        con = sqlite3.connect(str(d / "BV1xx411c7mD.db"))
        con.execute(
            "CREATE TABLE weekly_scores (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TIMESTAMP, total_score REAL)"
        )
        con.execute("CREATE INDEX idx_weekly_timestamp ON weekly_scores(timestamp)")
        con.execute("INSERT INTO weekly_scores (timestamp, total_score) VALUES ('2026-01-01 10:00:00', 1.0)")
        con.execute("INSERT INTO weekly_scores (timestamp, total_score) VALUES ('2026-01-01 10:00:00', 2.0)")
        con.execute("PRAGMA user_version = 3")
        con.commit()
        con.close()

        db = vdb.VideoDatabase("BV1xx411c7mD", base_dir=str(tmp_path))
        try:
            rows = db.get_weekly_scores()
            assert len(rows) == 1 and rows[0]["total_score"] == 2.0

            names = {r[0] for r in db._conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            assert "idx_weekly_ts" in names, "应创建唯一索引"
            assert "idx_weekly_timestamp" not in names, "旧普通索引应被删除"
            assert db._conn.execute("PRAGMA user_version").fetchone()[0] == 4
        finally:
            db.close()


class TestScoreMaterializer:
    """M2.11b: 分数按整点桶惰性物化（水位线增量 + 幂等）。"""

    @staticmethod
    def _mkdb(tmp_path, monkeypatch):
        import core.database.video_db as vdb

        monkeypatch.setattr(vdb, "project_path", lambda *parts: str(tmp_path))
        return vdb.VideoDatabase("BV1xx411c7mD", base_dir=str(tmp_path))

    @staticmethod
    def _rec(db, ts, views):
        from core.database.models import MonitorRecord

        return MonitorRecord(
            bvid=db.bvid,
            timestamp=ts,
            view_count=views,
            like_count=10,
            coin_count=1,
            share_count=0,
            favorite_count=2,
            danmaku_count=0,
            reply_count=0,
        )

    def test_hourly_buckets_watermark_and_idempotency(self, tmp_path, monkeypatch):
        from utils.score_materializer import ensure_scores

        db = self._mkdb(tmp_path, monkeypatch)
        try:
            for ts, v in [
                ("2026-01-01 10:05:00", 1000),
                ("2026-01-01 10:45:00", 2000),
                ("2026-01-01 11:10:00", 3000),
            ]:
                db.add_monitor_record(self._rec(db, ts, v))

            r1 = ensure_scores(db)
            assert r1["computed"] == 2, "10 点与 11 点两个桶"
            rows = db.get_weekly_scores()
            assert [r["timestamp"] for r in rows] == ["2026-01-01 11:00:00", "2026-01-01 10:00:00"]

            from dataclasses import asdict

            from utils.weekly_score import calculate_from_dict as calc_weekly

            def _expect(views):
                return asdict(
                    calc_weekly(
                        {
                            "view_count": views,
                            "like_count": 10,
                            "coin_count": 1,
                            "favorite_count": 2,
                            "danmaku_count": 0,
                            "reply_count": 0,
                        }
                    )
                )["total_score"]

            ten = next(r for r in rows if r["timestamp"].startswith("2026-01-01 10"))
            eleven = next(r for r in rows if r["timestamp"].startswith("2026-01-01 11"))
            assert ten["total_score"] == _expect(2000), "10 点桶应取 10:45 那条"
            assert eleven["total_score"] == _expect(3000), "11 点桶应取 11:10 那条"

            # 当前小时桶刷新：同一桶内新记录 → 仍只一行、分数更新
            db.add_monitor_record(self._rec(db, "2026-01-01 11:50:00", 9000))
            r2 = ensure_scores(db)
            assert r2["computed"] == 1, "只刷新 11 点桶"
            rows2 = db.get_weekly_scores()
            assert len(rows2) == 2, "幂等：不新增行"
            eleven2 = next(r for r in rows2 if r["timestamp"].startswith("2026-01-01 11"))
            assert eleven2["total_score"] == _expect(9000)
            assert eleven2["total_score"] != eleven["total_score"]

            # 新整点 → 新桶（同时会刷新当前 11 点桶：水位线是桶时刻，早于桶内记录）
            db.add_monitor_record(self._rec(db, "2026-01-01 12:05:00", 10000))
            r3 = ensure_scores(db)
            assert r3["computed"] == 2, "刷新 11 点桶 + 新增 12 点桶"
            assert len(db.get_weekly_scores()) == 3
            assert len(db.get_yearly_scores()) == 3
        finally:
            db.close()

    def test_current_scores_computes_without_writing(self, tmp_path, monkeypatch):
        from utils.score_materializer import current_scores

        db = self._mkdb(tmp_path, monkeypatch)
        try:
            assert current_scores(db) is None, "无记录时返回 None"
            db.add_monitor_record(self._rec(db, "2026-01-01 10:00:00", 5000))
            weekly, yearly = current_scores(db)
            assert weekly["total_score"] > 0 and yearly["total_score"] > 0
            assert db.get_weekly_scores() == [], "现算不应落库"
        finally:
            db.close()


class TestCentralIncrementalSync:
    """M2.5b: 中央同步按高水位线只处理增量。"""

    _COLS = (
        "bvid TEXT, timestamp TEXT, view_count INTEGER, like_count INTEGER, coin_count INTEGER,"
        " share_count INTEGER, favorite_count INTEGER, danmaku_count INTEGER, reply_count INTEGER,"
        " viewers_app INTEGER, viewers_web INTEGER, viewers_total INTEGER, like_view_ratio REAL"
    )

    @staticmethod
    def _mk_pair():
        import sqlite3

        a = sqlite3.connect(":memory:")
        c = sqlite3.connect(":memory:")
        a.row_factory = sqlite3.Row
        c.row_factory = sqlite3.Row
        a.execute(f"CREATE TABLE monitor_records ({TestCentralIncrementalSync._COLS})")
        c.execute(f"CREATE TABLE monitor_records ({TestCentralIncrementalSync._COLS})")
        return a, c

    def test_only_incremental_rows_copied(self):
        from core.database.central_backup import CentralBackup

        a, c = self._mk_pair()
        try:
            a.executemany(
                "INSERT INTO monitor_records (bvid, timestamp, view_count) VALUES (?,?,?)",
                [
                    ("BV1", "2026-01-01 10:00:00", 100),
                    ("BV1", "2026-01-01 11:00:00", 200),
                    ("BV1", "2026-01-01 12:00:00", 300),
                ],
            )
            c.execute(
                "INSERT INTO monitor_records (bvid, timestamp, view_count) VALUES ('BV1','2026-01-01 10:00:00',100)"
            )
            a.commit()
            c.commit()

            result = {"synced_records": 0}
            active_bvids, central_bvids = CentralBackup(None)._sync_monitor_records_to_central(
                a.cursor(), c.cursor(), result
            )
            assert active_bvids == {"BV1"}
            assert central_bvids == {"BV1"}
            assert result["synced_records"] == 2, "只补 11:00 与 12:00"
            got = [r[0] for r in c.execute("SELECT timestamp FROM monitor_records ORDER BY timestamp")]
            assert got == ["2026-01-01 10:00:00", "2026-01-01 11:00:00", "2026-01-01 12:00:00"]
        finally:
            a.close()
            c.close()

    def test_new_bvid_full_copy_and_lvr_filled(self):
        from core.database.central_backup import CentralBackup

        a, c = self._mk_pair()
        try:
            a.execute(
                "INSERT INTO monitor_records (bvid, timestamp, view_count, like_count) VALUES ('BV2','2026-02-01 08:00:00',1000,50)"
            )
            a.commit()

            result = {"synced_records": 0}
            _, central_bvids = CentralBackup(None)._sync_monitor_records_to_central(a.cursor(), c.cursor(), result)
            assert central_bvids == set(), "中央库此前无该 bvid"
            assert result["synced_records"] == 1
            row = c.execute("SELECT timestamp, like_view_ratio FROM monitor_records").fetchone()
            assert row[0] == "2026-02-01 08:00:00"
            assert abs(row[1] - 0.05) < 1e-9, "缺失的播赞比应被补算"
        finally:
            a.close()
            c.close()


class TestScoreCenterLogic:
    """M2.11d: 分数中心纯逻辑（范围 / 过滤 / 格式化 / 先物化再读）。"""

    def test_range_cutoff_mapping(self):
        from datetime import datetime, timedelta

        from ui.score_center import range_cutoff
        from utils.time_utils import format_ts

        assert range_cutoff("全部") is None
        assert range_cutoff("未知范围") is None
        for label, days in (("最近7天", 7), ("最近30天", 30), ("最近90天", 90)):
            assert range_cutoff(label) == format_ts(datetime.now() - timedelta(days=days))

    def test_filter_rows_by_cutoff(self):
        from ui.score_center import filter_rows

        rows = [{"timestamp": "2026-01-01 10:00:00"}, {"timestamp": "2026-01-03 10:00:00"}]
        assert filter_rows(rows, None) == rows
        assert filter_rows(rows, "2026-01-02 00:00:00") == [{"timestamp": "2026-01-03 10:00:00"}]

    def test_format_score_row_columns_and_none(self):
        from ui.score_center import WEEKLY_COLUMNS, YEARLY_COLUMNS, format_score_row

        row = {"timestamp": "2026-01-01 10:00:00", "total_score": 1234.5, "correction_a": None}
        weekly = format_score_row(row, "weekly")
        yearly = format_score_row(row, "yearly")
        assert len(weekly) == len(WEEKLY_COLUMNS)
        assert len(yearly) == len(YEARLY_COLUMNS)
        assert weekly[0] == "2026-01-01 10:00:00"
        assert weekly[1] == "1,234.50"
        assert weekly[7] == "", "None 应渲染为空串"

    def test_sort_rows_ascending(self):
        from ui.score_center import sort_rows_ascending

        rows = [{"timestamp": "2026-01-02 10:00:00"}, {"timestamp": "2026-01-01 10:00:00"}]
        assert [r["timestamp"] for r in sort_rows_ascending(rows)] == [
            "2026-01-01 10:00:00",
            "2026-01-02 10:00:00",
        ]

    def test_load_scores_materializes_before_read(self, monkeypatch):
        import ui.score_center as sc

        order = []
        monkeypatch.setattr(sc, "ensure_scores", lambda db: order.append("ensure"))

        class _DB:
            def get_weekly_scores(self, limit=0):
                order.append("weekly")
                return [{"timestamp": "x"}]

            def get_yearly_scores(self, limit=0):
                order.append("yearly")
                return []

        db = _DB()
        assert sc.load_scores(db, "weekly") == [{"timestamp": "x"}]
        assert order == ["ensure", "weekly"], "必须先物化再读"
        order.clear()
        sc.load_scores(db, "yearly")
        assert order == ["ensure", "yearly"]


class TestCurveFitCache:
    """M2.6: curve_fit 结果按内容缓存（历史未变不重复拟合）。"""

    @staticmethod
    def _algo():
        from algorithms.base import BaseAlgorithm

        class _Algo:
            _safe_curve_fit = BaseAlgorithm._safe_curve_fit

            def _model(self, t, a, b):
                return a * t + b

        return _Algo()

    def test_same_input_fits_once(self, monkeypatch):
        import numpy as np

        from algorithms.base import BaseAlgorithm, clear_curve_fit_cache

        clear_curve_fit_cache()
        calls = {"n": 0}

        def _fake(func, x, y, p0=None, bounds=None, maxfev=None):
            calls["n"] += 1
            return np.array([1.0, 2.0]), None

        monkeypatch.setattr("scipy.optimize.curve_fit", _fake)

        algo = self._algo()
        times = np.array([1.0, 2.0, 3.0])
        views = np.array([10.0, 20.0, 30.0])
        args = (algo._model, times, views, [1.0, 1.0], (0, np.inf))

        r1 = BaseAlgorithm._safe_curve_fit(algo, *args)
        r2 = BaseAlgorithm._safe_curve_fit(algo, *args)
        assert calls["n"] == 1, "相同输入只应拟合一次"
        assert r1[1] is True and r2[1] is True

        # 数据变化 → 缓存自然失效
        BaseAlgorithm._safe_curve_fit(algo, algo._model, times, views * 2, [1.0, 1.0], (0, np.inf))
        assert calls["n"] == 2, "输入变化后应重新拟合"

    def test_failure_cached_and_falls_back(self, monkeypatch):
        import numpy as np

        from algorithms.base import BaseAlgorithm, clear_curve_fit_cache

        clear_curve_fit_cache()
        calls = {"n": 0}

        def _boom(*a, **k):
            calls["n"] += 1
            raise RuntimeError("no convergence")

        monkeypatch.setattr("scipy.optimize.curve_fit", _boom)

        algo = self._algo()
        times = np.array([1.0, 2.0])
        views = np.array([1.0, 2.0])
        r1 = BaseAlgorithm._safe_curve_fit(algo, algo._model, times, views, [1.0, 1.0], (0, np.inf))
        r2 = BaseAlgorithm._safe_curve_fit(algo, algo._model, times, views, [1.0, 1.0], (0, np.inf))
        assert calls["n"] == 1, "失败结果也应缓存，避免重复尝试"
        assert r1[1] is False and r2[1] is False
        assert list(r1[0]) == [1.0, 1.0], "失败时回退初始参数"

    def test_different_bounds_not_shared(self, monkeypatch):
        import numpy as np

        from algorithms.base import BaseAlgorithm, clear_curve_fit_cache

        clear_curve_fit_cache()
        calls = {"n": 0}

        def _fake(func, x, y, p0=None, bounds=None, maxfev=None):
            calls["n"] += 1
            return np.array([1.0]), None

        monkeypatch.setattr("scipy.optimize.curve_fit", _fake)

        algo = self._algo()
        times = np.array([1.0, 2.0])
        views = np.array([1.0, 2.0])
        BaseAlgorithm._safe_curve_fit(algo, algo._model, times, views, [1.0], (0, np.inf))
        BaseAlgorithm._safe_curve_fit(algo, algo._model, times, views, [1.0], (0, 10))
        assert calls["n"] == 2, "不同 bounds 不应共用缓存"


class TestTorchInputMemo:
    """M2.7b: _build_torch_input 结果按历史内容缓存在 video_data。"""

    @staticmethod
    def _entry(i):
        return {
            "timestamp": 1767225600.0 + i * 3600,  # 数值时间戳（_velocity_series 要求）
            "view_count": 100 * (i + 1),
            "like_count": i,
            "coin_count": 0,
            "favorite_count": 0,
            "danmaku_count": 0,
            "reply_count": 0,
        }

    def test_memoized_and_recomputed_on_history_change(self):
        import numpy as np

        from algorithms.models.deep_learning._torch_upgrade import _build_torch_input

        hist = [self._entry(i) for i in range(6)]
        video = {"history_data": hist}
        feats = ("view_count", "like_count")

        arr1, m1, s1 = _build_torch_input(video, feats, 5)
        assert arr1 is not None and arr1.shape == (5, 7)
        assert "_torch_input_memo" in video, "首次构建应写入缓存"

        arr2, m2, s2 = _build_torch_input(video, feats, 5)
        assert np.array_equal(arr1, arr2)
        assert (m1, s1) == (m2, s2)
        assert arr2 is not arr1, "命中缓存应返回副本"

        # 改写副本不应污染缓存
        arr2[0, 0] = 999.0
        arr3, _, _ = _build_torch_input(video, feats, 5)
        assert arr3[0, 0] != 999.0

        # 历史变化 → 缓存失效并重建
        video["history_data"] = hist + [self._entry(6)]
        arr4, _, _ = _build_torch_input(video, feats, 5)
        assert not np.array_equal(arr4, arr1)

    def test_insufficient_history_short_circuits(self):
        from algorithms.models.deep_learning._torch_upgrade import _build_torch_input

        video = {"history_data": [self._entry(0)]}
        assert _build_torch_input(video, ("view_count",), 5) == (None, 0.0, 1.0)
        assert "_torch_input_memo" not in video, "历史不足时不应写缓存"


class TestModelCache:
    """M2.6b: 已拟合估计器按内容缓存（内容变化即重训，LRU 有界）。"""

    def test_same_content_reuses_and_changes_refits(self):
        import numpy as np

        from algorithms.model_cache import cache_size, clear_model_cache, get_or_fit

        clear_model_cache()
        fits = {"n": 0}

        class _Est:
            def fit(self, X, y):
                fits["n"] += 1
                return self

            def predict(self, X):
                return np.zeros(len(X))

        X = np.array([[1.0], [2.0], [3.0]])
        y = np.array([1.0, 2.0, 3.0])

        m1 = get_or_fit("t_algo", _Est, X, y)
        m2 = get_or_fit("t_algo", _Est, X, y)
        assert fits["n"] == 1, "相同内容只应拟合一次"
        assert m1 is m2, "命中缓存应返回同一实例"
        assert cache_size() == 1

        y2 = np.array([2.0, 4.0, 6.0])
        m3 = get_or_fit("t_algo", _Est, X, y2)
        assert fits["n"] == 2, "内容变化后应重新拟合"
        assert m3 is not m1

        get_or_fit("t_other", _Est, X, y)
        assert fits["n"] == 3, "不同算法命名空间互不干扰"

    def test_lru_bound_and_clear(self):
        import numpy as np

        import algorithms.model_cache as mc

        mc.clear_model_cache()

        class _Est:
            def fit(self, X, y):
                return self

        old = mc._MAXSIZE
        mc._MAXSIZE = 3
        try:
            for i in range(5):
                mc.get_or_fit("k", _Est, np.array([[float(i)]]), np.array([float(i)]))
            assert mc.cache_size() == 3, "应受 LRU 上限约束"
        finally:
            mc._MAXSIZE = old
        assert mc.clear_model_cache() >= 1
        assert mc.cache_size() == 0

    def test_unhashable_input_falls_back_without_caching(self):
        from algorithms.model_cache import cache_size, clear_model_cache, get_or_fit

        clear_model_cache()
        fits = {"n": 0}

        class _Est:
            def fit(self, obj):
                fits["n"] += 1
                return self

        class _Weird:
            def __len__(self):
                raise TypeError("not an array")

        get_or_fit("w", _Est, _Weird())
        get_or_fit("w", _Est, _Weird())
        assert fits["n"] == 2, "无法摘要时回退为每次拟合"
        assert cache_size() == 0


class TestAlgorithmSourcesCompile:
    """安全网: algorithms/ 下所有源码必须语法有效（防静默丢失算法）。"""

    def test_all_algorithm_modules_compile(self):
        import py_compile
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "algorithms"
        failures = []
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                py_compile.compile(str(path), doraise=True)
            except Exception as e:
                failures.append(f"{path.name}: {e}")
        assert not failures, "算法源码存在语法错误:\n" + "\n".join(failures)
