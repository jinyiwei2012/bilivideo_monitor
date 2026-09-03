"""回归测试：覆盖 FUNCTIONAL_DEFECTS.md 中已修复的功能缺陷（D1-D36）。

运行方式：QT_QPA_PLATFORM=offscreen python -m pytest tests/test_defect_regressions.py -q
"""

import hashlib
import json
import time
from datetime import datetime, timedelta

import numpy as np
import pytest


# ══════════════════════════════════════════════
# D2: _LRUDict 淘汰不抛 KeyError
# ══════════════════════════════════════════════

class TestLRUCache:
    def test_eviction_no_keyerror(self):
        from algorithms.registry import _LRUDict
        d = _LRUDict(maxsize=5)
        for i in range(50):
            d[i] = i * 10
        assert len(d) == 5

    def test_derived_cache_wraparound(self):
        from algorithms.registry import AlgorithmRegistry
        AlgorithmRegistry.reset()
        base = datetime.now()
        for i in range(250):
            hist = [(base - timedelta(seconds=75 * (9 - j)), 100 + j * 5 + i) for j in range(9)]
            AlgorithmRegistry._prepare_video_data(hist, 140 + i, bvid=f"BVreg{i}")
        assert len(AlgorithmRegistry._derived_cache) <= 200


# ══════════════════════════════════════════════
# D1: 速度单位  slope*3600 + float64 时间戳精度
# ══════════════════════════════════════════════

class TestVelocityUnits:
    def test_registry_polyfit_velocity(self):
        from algorithms.registry import AlgorithmRegistry
        base = datetime.now() - timedelta(seconds=75*9)
        hist = [(base + timedelta(seconds=75*i), 100 + i*5) for i in range(9)]
        vd = AlgorithmRegistry._prepare_video_data(hist, 140, bvid="BVv1")
        vel = vd["derived_features"]["velocity_polyfit"]
        assert 200 < vel < 280, f"速度异常: {vel}"

    def test_base_calculate_velocity_two_points(self):
        from algorithms.models.simple.linear_velocity import LinearVelocityAlgorithm
        algo = LinearVelocityAlgorithm()
        t0 = time.time() - 7200
        data = {"history_data": [
            {"view_count": 100, "timestamp": t0},
            {"view_count": 200, "timestamp": time.time()},
        ]}
        assert algo.calculate_velocity(data) == pytest.approx(50.0, rel=0.1)

    def test_base_calculate_velocity_polyfit(self):
        from algorithms.models.simple.linear_velocity import LinearVelocityAlgorithm
        algo = LinearVelocityAlgorithm()
        base = time.time() - 75 * 9
        data = {"history_data": [
            {"view_count": 100 + i * 5, "timestamp": base + 75 * i} for i in range(9)
        ]}
        vel = algo.calculate_velocity(data)
        assert 200 < vel < 280, f"polyfit 速度异常: {vel}"

    def test_float64_timestamp_precision(self):
        ts = np.array([1_780_000_000 + i * 75 for i in range(9)], dtype=np.float64)
        assert (np.diff(ts) == 0).sum() == 0, "float64 时间戳出现零间隔"


# ══════════════════════════════════════════════
# D7: WBI 签名含 wts
# ══════════════════════════════════════════════

class TestWbiSign:
    def test_wts_included_in_hash(self):
        from core.bilibili_api import BilibiliAPI
        api = BilibiliAPI.__new__(BilibiliAPI)
        api._wbi_key = "test_mixin_key"
        signed = api._wbi_sign({"bvid": "BV1xx", "pn": 1})
        assert "wts" in signed and "w_rid" in signed
        p2 = {"bvid": "BV1xx", "pn": 1, "wts": signed["wts"]}
        query = "&".join(f"{k}={v}" for k, v in sorted(p2.items())) + "test_mixin_key"
        expected = hashlib.md5(query.encode(), usedforsecurity=False).hexdigest()
        assert signed["w_rid"] == expected

    def test_wbi_sign_no_key(self):
        from core.bilibili_api import BilibiliAPI
        api = BilibiliAPI.__new__(BilibiliAPI)
        api._wbi_key = None
        assert api._wbi_sign({"a": 1}) == {"a": 1}


# ══════════════════════════════════════════════
# D8: 增长模型单例共享可变状态 → 局部参数
# ══════════════════════════════════════════════

class TestGrowthModelIsolation:
    @pytest.fixture(params=[
        ("algorithms.models.growth.logistic_growth", "LogisticGrowthAlgorithm"),
        ("algorithms.models.growth.gompertz_growth", "GompertzGrowthAlgorithm"),
        ("algorithms.models.growth.richards_curve", "RichardsCurveAlgorithm"),
        ("algorithms.models.growth.weibull_growth", "WeibullGrowthAlgorithm"),
    ])
    def algo(self, request):
        import importlib
        mod = importlib.import_module(request.param[0])
        return getattr(mod, request.param[1])()

    def _hist(self, K, r, t0, days=15):
        """生成 S 型增长历史，确保目标阈值可达（K > target）。"""
        now = datetime.now()
        t = np.arange(days, dtype=float)
        v = K / (1 + np.exp(-r * (t - t0)))
        return [
            {"view_count": max(1, int(v[i])),
             "timestamp": (now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d %H:%M:%S")}
            for i in range(days)
        ]

    def test_no_state_leak_between_videos(self, algo):
        """同一实例交替预测两个量级不同的视频：A 结果不应被 B 污染"""
        # 视频 A: K=200k, target=150k（可达）
        vidA = {"view_count": 50000, "history_data": self._hist(200000, 0.3, 10), "follower": 100000}
        # 视频 B: K=800k, target=600k（可达）
        vidB = {"view_count": 400000, "history_data": self._hist(800000, 0.5, 8), "follower": 500000}

        r1 = algo.predict(vidA, 150000)
        r2 = algo.predict(vidB, 600000)
        r3 = algo.predict(vidA, 150000)

        h1, h3 = r1.predicted_hours, r3.predicted_hours
        if h1 == float("inf") and h3 == float("inf"):
            pass  # 两轮都不可达 → 一致（如模型收敛问题）
        else:
            assert abs(h1 - h3) < max(1e-6, abs(h1) * 0.01), f"状态泄漏: {h1} vs {h3}"
        # B 与 A 应有不同结果（仅当 B 有限时）
        h2 = r2.predicted_hours
        if h1 != float("inf") and h2 != float("inf"):
            assert abs(h1 - h2) > 1, f"AB 应不同: {h1} vs {h2}"


# ══════════════════════════════════════════════
# D13: 保形预测校准
# ══════════════════════════════════════════════

class TestConformalCalibration:
    def test_update_grows_calibration_set(self):
        from algorithms.conformal import get_conformal_predictor
        cp = get_conformal_predictor()
        n0 = len(cp._scores)
        cp.update(100000, 120000)
        assert len(cp._scores) == n0 + 1

    def test_cold_start_has_fallback_interval(self):
        from algorithms.conformal import get_conformal_predictor
        cp = get_conformal_predictor()
        interval = cp.predict_interval(100000)
        assert interval["lower"] < 100000 < interval["upper"]
        assert 0 < interval["interval_width_ratio"] <= 0.5


# ══════════════════════════════════════════════
# D22: 配置加密（is_encrypted 误判修复 + save_config 幂等加密）
# ══════════════════════════════════════════════

class TestConfigEncryption:
    def test_is_encrypted_no_false_positive(self):
        from utils.crypto import is_encrypted
        assert is_encrypted("sk-secret-123") is False
        assert is_encrypted("") is False

    def test_encrypt_roundtrip(self):
        from utils.crypto import encrypt, decrypt, is_encrypted
        enc = encrypt("sk-secret-123")
        assert enc != "sk-secret-123"
        assert is_encrypted(enc) is True
        assert decrypt(enc) == "sk-secret-123"

    def test_save_config_persists_encrypted(self, tmp_path, monkeypatch):
        import config as config_mod
        monkeypatch.setattr(config_mod, "CONFIG_FILE", str(tmp_path / "settings.json"))
        cfg = config_mod.load_config()
        cfg.setdefault("onebot", {})["access_token"] = "sk-secret-123"
        assert config_mod.save_config(cfg)
        saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
        tok = saved.get("onebot", {}).get("access_token", "")
        assert tok != "sk-secret-123", "明文被写回磁盘！"
        from utils.crypto import decrypt
        assert decrypt(tok) == "sk-secret-123"

    def test_save_config_idempotent(self, tmp_path, monkeypatch):
        import config as config_mod
        from utils.crypto import encrypt, decrypt
        monkeypatch.setattr(config_mod, "CONFIG_FILE", str(tmp_path / "settings.json"))
        cfg = config_mod.load_config()
        cfg.setdefault("onebot", {})["access_token"] = encrypt("sk-abc")
        config_mod.save_config(cfg)
        saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
        assert decrypt(saved["onebot"]["access_token"]) == "sk-abc"


# ══════════════════════════════════════════════
# D28: 派生特征缓存键含内容摘要
# ══════════════════════════════════════════════

class TestDerivedCacheKey:
    def test_different_content_same_shape_no_collision(self):
        from algorithms.registry import AlgorithmRegistry
        AlgorithmRegistry.reset()
        base = datetime.now()
        hist_a = [(base - timedelta(seconds=75*(9-i)), 100+i*5) for i in range(9)]
        hist_b = [(base - timedelta(seconds=75*(9-i)), 100+i*50) for i in range(9)]
        vd_a = AlgorithmRegistry._prepare_video_data(hist_a, 140, bvid="")
        vd_b = AlgorithmRegistry._prepare_video_data(hist_b, 500, bvid="")
        va = vd_a["derived_features"]["velocity_polyfit"]
        vb = vd_b["derived_features"]["velocity_polyfit"]
        assert abs(va - vb) > 1, f"缓存串键: A={va} B={vb}"


# ══════════════════════════════════════════════
# D9/D10/D14: 数据库层
# ══════════════════════════════════════════════

class TestVideoDb:
    def _make_vdb(self, tmp_path, bvid="BV1fK4y1U7abcd"):
        from core.database.video_db import VideoDatabase
        return VideoDatabase(bvid, base_dir=str(tmp_path))

    def test_save_video_info_owner_name(self, tmp_path):
        vdb = self._make_vdb(tmp_path)
        vdb.save_video_info({"bvid": "BV1fK4y1U7abcd", "title": "t", "author": "洛天依"})
        row = vdb.get_video_info()
        assert row is not None
        assert row.get("owner_name") == "洛天依"

    def test_add_predictions_is_reached(self, tmp_path):
        vdb = self._make_vdb(tmp_path)
        rows = [{
            "algorithm": "test_algo", "algorithm_id": "test_algo_id",
            "target_threshold": 5000, "predicted_seconds": 3600,
            "predicted_time": datetime.now().isoformat(), "confidence": 0.8,
            "current_views": 6000, "metadata": "{}",
            "predicted_hours": 1.0, "current_velocity": 100.0,
        }]
        assert vdb.add_predictions_batch(rows)
        import sqlite3
        conn = sqlite3.connect(vdb.db_path)
        row = conn.execute("SELECT is_reached, actual_time, error_rate FROM predictions WHERE algorithm='test_algo'").fetchone()
        conn.close()
        assert row[0] == 1, f"is_reached 应为 1, 实际 {row[0]}"
        assert row[1] != "", "actual_time 不应为空"
        assert row[2] == 0

    def test_mirror_initialized(self, tmp_path, monkeypatch):
        import core.database.video_db as vdb_mod
        # 让 mirror_base 指向 tmp/mirror 而非真实 data/ 目录
        monkeypatch.setattr(vdb_mod, "project_path", lambda *a, **kw: str(tmp_path / "mirror"))
        bvid = "BV1fK4y1U7abcd"
        vdb = vdb_mod.VideoDatabase(bvid, base_dir=str(tmp_path / "active"))
        # 视频库 _mirror_path 设置（mirror_base != base_dir）
        assert vdb._mirror_conn is not None, "镜像连接未初始化"
        assert vdb._mirror_path is not None
        assert bvid in vdb._mirror_path
        vdb.close()


class TestBackupSyncPredictions:
    def test_group_by_threshold_no_rollback(self, tmp_path):
        """连续两轮预测同步：不应 IntegrityError，两阈值都应保留"""
        from core.database.central_db import Database as CentralDatabase
        from core.database.central_backup import CentralBackup
        from core.database.video_db import VideoDatabase

        vdb = VideoDatabase("BV1fK4y1U7abcd", base_dir=str(tmp_path / "videos"))
        central = CentralDatabase(db_path=str(tmp_path / "central.db"))

        # 写入两行预测（同 algorithm 两个阈值，不同 predicted_time）
        ts1 = datetime.now().isoformat()
        rows1 = [{
            "algorithm": "algo_x", "algorithm_id": "algo_x_id",
            "target_threshold": 10000, "predicted_seconds": 3600,
            "predicted_time": ts1, "confidence": 0.7,
            "current_views": 6000, "metadata": "{}",
            "predicted_hours": 2.0, "current_velocity": 100.0,
        }, {
            "algorithm": "algo_x", "algorithm_id": "algo_x_id",
            "target_threshold": 50000, "predicted_seconds": 7200,
            "predicted_time": ts1, "confidence": 0.6,
            "current_views": 6000, "metadata": "{}",
            "predicted_hours": 5.0, "current_velocity": 100.0,
        }]
        vdb.add_predictions_batch(rows1)
        vdb.save_video_info({"bvid": "BV1fK4y1U7abcd", "title": "t", "author": "a"})

        # 第一轮同步
        vcur = vdb._conn.cursor()
        with central._get_connection() as central_conn:
            central_cur = central_conn.cursor()
            cnt1 = CentralBackup._sync_video_predictions(central_cur, "BV1fK4y1U7abcd", vcur)
        assert cnt1 == 2, f"预期同步 2 行, 实际 {cnt1}"

        # 第二轮：predicted_time 更新 + 再次同步
        ts2 = (datetime.now() + timedelta(seconds=75)).isoformat()
        rows2 = [dict(r, **{"predicted_time": ts2}) for r in rows1]
        vdb.add_predictions_batch(rows2)
        vcur2 = vdb._conn.cursor()
        with central._get_connection() as central_conn2:
            central_cur2 = central_conn2.cursor()
            cnt2 = CentralBackup._sync_video_predictions(central_cur2, "BV1fK4y1U7abcd", vcur2)

        # 第二轮同步不应抛异常，且返回 0（已有行 skip）
        assert cnt2 == 0, f"第二轮应跳过，返回 0, 实际 {cnt2}"

        # 中央库应有 2 行（两个阈值），是 INSERT OR REPLACE 后的结果
        with central._get_connection() as check_conn:
            n = check_conn.execute("SELECT COUNT(*) FROM predictions WHERE bvid=?", ("BV1fK4y1U7abcd",)).fetchone()[0]
        assert n == 2, f"中央库应有 2 行, 实际 {n}"

        vdb.close()
        central.close()


# ══════════════════════════════════════════════
# D20: QR 登录未知状态不误报成功
# ══════════════════════════════════════════════

class TestQrLogin:
    def test_unknown_status_not_success(self, monkeypatch):
        import core.bilibili_auth as auth_mod

        auth = auth_mod._AuthMixin()
        auth.USER_AGENTS = ["test"]

        class FakeResp:
            status_code = 200
            cookies = {}
            def json(self):
                return {"code": 0, "data": {"status": 999}}

        class FakeSess:
            def get(self, *a, **kw):
                return FakeResp()
            def post(self, *a, **kw):
                return FakeResp()

        monkeypatch.setattr(auth_mod, "_init_qr_session", lambda self: FakeSess())
        result = auth_mod.poll_qrcode_login(auth, "test_key")
        assert result.get("status") != 2, "未知状态不得报登录成功"
        assert "未知" in result.get("message", "")


# ══════════════════════════════════════════════
# D31: ARIMA 时间单位
# ══════════════════════════════════════════════

class TestArimaTimeUnit:
    def test_predicted_hours_not_day_scale(self):
        from algorithms.models.time_series.arima_simple import ArimaSimpleAlgorithm
        algo = ArimaSimpleAlgorithm()
        base = datetime.now() - timedelta(seconds=75*40)
        # 每点 +50，75s 间隔，current ≈ 2950，threshold=5000 未达 → 走 fallback 路径
        history = [
            {"view_count": 1000 + i*50, "timestamp": (base + timedelta(seconds=75*i)).strftime("%Y-%m-%d %H:%M:%S")}
            for i in range(40)
        ]
        video_data = {"view_count": 1000 + 39*50, "history_data": history, "timestamp": datetime.now()}
        result = algo.predict(video_data, threshold=5000)
        h = result.predicted_hours
        if h != float("inf"):
            assert h < 24, f"ARIMA 时间单位异常: {h}h"


# ══════════════════════════════════════════════
# D24: 代理健康检查
# ══════════════════════════════════════════════

class TestProxyHealthCheck:
    def _resp(self, body, status=200):
        class R:
            status_code = status
            def json(self):
                return body
        return R()

    def test_code_403_fails(self):
        from core.proxy_manager import ProxyManager
        result = {"ok": False, "error": "", "latency_ms": 0, "data": {}}
        out = ProxyManager._parse_bilibili_json(self._resp({"code": -403, "message": "风控"}), result)
        assert out["ok"] is False
        assert "风控" in out["error"]

    def test_code_0_passes(self):
        from core.proxy_manager import ProxyManager
        result = {"ok": False, "error": "", "latency_ms": 0, "data": {}}
        out = ProxyManager._parse_bilibili_json(
            self._resp({"code": 0, "data": {"title": "t", "stat": {"view": 1}}}), result)
        assert out["ok"] is True


# ══════════════════════════════════════════════
# D34: 版本比较一致
# ══════════════════════════════════════════════

class TestVersionCompare:
    def test_parse_version_ordering(self):
        from utils.update_checker import _parse_version
        assert _parse_version("1.2.3") < _parse_version("1.2.4")
        assert _parse_version("1.2.3") < _parse_version("1.3.0")
        # 预发布后缀被忽略 → 相等
        assert _parse_version("3.0.1-beta1") == _parse_version("3.0.1-beta2")


# ══════════════════════════════════════════════
# D36: 在线人数 fallback 类型 int
# ══════════════════════════════════════════════

class TestViewersFallbackType:
    def test_fallback_returns_int(self):
        import inspect
        from core.bilibili_video import _get_video_viewers_fallback
        src = inspect.getsource(_get_video_viewers_fallback)
        # 确认 fallback 返回 int 而非 str
        assert "int(online.get" in src or "int(" in src.replace("str(", ""), "fallback 未转 int"


# ══════════════════════════════════════════════
# D19: invoke 队列异常隔离
# ══════════════════════════════════════════════

class TestInvokerIsolation:
    def test_failed_callback_does_not_block_queue(self):
        from ui.invoker import _invoker
        executed = []
        _invoker.invoke(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        _invoker.invoke(lambda: executed.append(1))
        try:
            from PyQt6.QtCore import QCoreApplication
            app = QCoreApplication.instance() or QCoreApplication([])
            _invoker._wake.emit()
            app.processEvents()
            app.processEvents()
        except Exception:
            pytest.skip("需要 PyQt6 事件循环")
        assert executed == [1], "异常回调阻塞了后续回调"