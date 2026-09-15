# -*- coding: utf-8 -*-
"""风控观测消费端 + Cookie 续期定时（risk_control_playbook §10 / §13-1、§13-2）。

只测纯逻辑与调度：**不发网络请求、不起 Qt、不碰真实 data/**。
"""

import time
from typing import Any, Callable

from ui import main_gui_tick as tick


class _StubLogPanel:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str]] = []

    def add_log(self, level: str, message: str) -> None:
        self.entries.append((level, message))


class _StubGui:
    def __init__(self) -> None:
        self.status: dict[str, tuple[str, str]] = {}
        self.log_panel = _StubLogPanel()

    def _sb(self, key: str, text: str, color: str | None = None) -> None:
        self.status[key] = (text, color or "")


class _StubCookies:
    def __init__(self, sessdata: str = "") -> None:
        self._sessdata = sessdata

    def get(self, name: str, domain: str | None = None) -> str:
        return self._sessdata if name == "SESSDATA" else ""


class _StubSession:
    def __init__(self, sessdata: str = "") -> None:
        self.cookies = _StubCookies(sessdata)


class _StubApi:
    """最小 API 替身：记录请求次数，用于断言「未登录零请求」。"""

    def __init__(self, *, sessdata: str = "", logged_out: bool = False, cooldown: float = 0.0) -> None:
        self.session = _StubSession(sessdata)
        self._cookies: dict[str, str] = {"SESSDATA": sessdata} if sessdata else {}
        self._logged_out = logged_out
        self._risk_cooldown_until = time.time() + cooldown
        self._voucher_streak = 0
        self._risk_scope = ""
        self._risk_last_kind = ""
        self._risk_last_voucher = ""
        self._consecutive_412_errors = 0
        self.requests: list[str] = []

    def risk_state(self) -> dict:
        from core.bilibili_request import risk_state

        return risk_state(self)

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        self.requests.append(url)
        return None


def _sync_runner(fn: Callable[[], None], name: str | None = None) -> None:
    fn()


# ═══════════════ 状态栏文本/颜色 ═══════════════


def test_risk_badge_text_states() -> None:
    assert tick._risk_badge_text({"logged_out": True, "cooldown_remaining": 0}) == "⚠ 登录已失效"
    assert "风控冷却" in tick._risk_badge_text({"logged_out": False, "cooldown_remaining": 42.7})
    assert tick._risk_badge_text({"logged_out": False, "cooldown_remaining": 0}) == ""


def test_risk_badge_color_priority() -> None:
    from ui.theme import C

    assert tick._risk_badge_color({"logged_out": True, "cooldown_remaining": 99}) == C["danger"]
    assert tick._risk_badge_color({"logged_out": False, "cooldown_remaining": 1}) == C["warning"]
    assert tick._risk_badge_color({"logged_out": False, "cooldown_remaining": 0}) == C["text_3"]


def test_report_risk_updates_status_bar_without_noise() -> None:
    """冷却中：写入状态栏，但不写日志、不通知（未掉登录）。"""
    gui = _StubGui()
    tick._maybe_report_risk(gui, api=_StubApi(sessdata="x", cooldown=30))
    text, color = gui.status["risk"]
    assert "风控冷却" in text
    assert color
    assert gui.log_panel.entries == []


def test_logged_out_notified_once_per_transition(monkeypatch) -> None:
    """掉登录：通知+续期各一次；持续掉登录不重复打扰；恢复后再掉可再次通知。"""
    gui = _StubGui()
    calls = {"notify": 0, "renew": 0}
    monkeypatch.setattr(tick, "_notify_logged_out", lambda: calls.__setitem__("notify", calls["notify"] + 1))
    monkeypatch.setattr(tick, "_renew_now_async", lambda api: calls.__setitem__("renew", calls["renew"] + 1))

    api = _StubApi(sessdata="x", logged_out=True)
    tick._maybe_report_risk(gui, api=api)
    tick._maybe_report_risk(gui, api=api)
    assert calls == {"notify": 1, "renew": 1}
    assert gui.status["risk"][0] == "⚠ 登录已失效"
    assert [level for level, _ in gui.log_panel.entries] == ["WARNING"]

    tick._maybe_report_risk(gui, api=_StubApi(sessdata="x", logged_out=False))
    assert gui.status["risk"][0] == ""
    tick._maybe_report_risk(gui, api=api)
    assert calls["notify"] == 2
    assert calls["renew"] == 2


def test_report_risk_survives_broken_api() -> None:
    """API 读取异常时不得抛出（tick 每秒调用）。"""

    class _Bad:
        def risk_state(self) -> dict:
            raise RuntimeError("boom")

    gui = _StubGui()
    tick._maybe_report_risk(gui, api=_Bad())
    assert gui.status == {}


# ═══════════════ Cookie 续期定时 ═══════════════


def test_has_login_cookies_variants() -> None:
    assert tick._has_login_cookies(_StubApi(sessdata="a")) is True
    assert tick._has_login_cookies(_StubApi()) is False

    class _NoSession:
        _cookies: dict[str, str] = {"SESSDATA": "b"}

    assert tick._has_login_cookies(_NoSession()) is True


def test_renew_skipped_entirely_when_not_logged_in() -> None:
    """未登录：零请求、零调度、不写节流时间戳。"""
    gui = _StubGui()
    scheduled: list[str] = []

    def _runner(fn: Callable[[], None], name: str | None = None) -> None:
        scheduled.append(str(name))
        fn()

    api = _StubApi()
    tick._maybe_renew_cookies(gui, api=api, runner=_runner)
    assert api.requests == []
    assert scheduled == []
    assert not hasattr(gui, "_last_cookie_renew")


def test_renew_runs_once_then_throttled(monkeypatch) -> None:
    """已登录：启动后立即一次，12h 内不再重复（节流）。"""
    gui = _StubGui()
    calls: list[str] = []
    monkeypatch.setattr(tick, "_renew_worker", lambda api: calls.append("renew"))

    api = _StubApi(sessdata="SESSDATA-value")
    tick._maybe_renew_cookies(gui, api=api, runner=_sync_runner)
    tick._maybe_renew_cookies(gui, api=api, runner=_sync_runner)
    assert calls == ["renew"]
    assert api.requests == []  # 调度本身不发请求
    assert gui._last_cookie_renew > 0

    gui._last_cookie_renew = time.time() - tick._COOKIE_RENEW_INTERVAL - 1
    tick._maybe_renew_cookies(gui, api=api, runner=_sync_runner)
    assert calls == ["renew", "renew"]


def test_renew_worker_uses_12h_interval(monkeypatch) -> None:
    """_renew_worker 用 12h 间隔调用核心节流函数（非 force）。"""
    seen: list[tuple[float, bool]] = []

    def _fake_maybe(api: Any, *, interval_hours: float = 12.0, force: bool = False) -> None:
        seen.append((interval_hours, force))
        return None

    monkeypatch.setattr("core.bilibili_cookie_refresh.maybe_refresh", _fake_maybe)
    tick._renew_worker(_StubApi(sessdata="x"))
    assert seen == [(12.0, False)]
    assert tick._COOKIE_RENEW_INTERVAL == 12 * 3600


def test_renew_worker_swallows_errors(monkeypatch) -> None:
    """续期异常不得冒泡到后台任务层。"""

    def _boom(api: Any, *, interval_hours: float = 12.0, force: bool = False) -> None:
        raise RuntimeError("network down")

    monkeypatch.setattr("core.bilibili_cookie_refresh.maybe_refresh", _boom)
    tick._renew_worker(_StubApi(sessdata="x"))  # 不抛异常即通过
