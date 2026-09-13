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
